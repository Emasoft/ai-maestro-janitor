"""Tests for scripts/summarize_previous_session.py's Jev-compaction wiring.

TRDD-RAEGS1D5 card 3 part C, commit C1 ("wire the compaction lane to jev_compact"). Covers:
the exact subprocess invocation (path + argv + a timeout spanning the WHOLE remaining retry
budget -- orchestrator correction 2026-09-23, see `test_compact_invocation_form_and_timeout`),
the exit-code -> findings_ledger
mapping table (5/6/7, including the coordinator's `kind=unreachable`/`kind=rate_limited`
amendments and the `kind=auth` dedupe), and the STATE-heads discovery via a stub `trddgrep`
on PATH plus its absence. `jev_compact.py` itself is never invoked for real here — every test
uses a stub script or a monkeypatched `subprocess.run`, so no network call, no httpx/jevctx
import, ever happens in this file (mirrors tests/test_jev_boundary.py's own constraint).
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

import external_clear as ec  # noqa: E402
import external_handoff_clear as ehc  # noqa: E402
import findings_ledger  # noqa: E402
import global_state  # noqa: E402
import handoff_files  # noqa: E402
import jev_compaction_lane as jcl  # noqa: E402
import state  # noqa: E402
import summarize_previous_session as sps  # noqa: E402


def _ledger_entries() -> list[dict]:
    path = findings_ledger.ledger_path()
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Every test gets its own project root, HOME, and janitor control dir — never the real
    machine's. Every lru_cache'd state.* accessor is cleared before and after, since each
    caches with no args (a process-lifetime singleton otherwise leaking one test's paths into
    the next) — the same pattern tests/test_external_clear.py already uses for `log_dir`."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "control"))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    for fn in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        fn.cache_clear()
    yield project_dir
    for fn in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        fn.cache_clear()


def _make_prev_transcript(tmp_path: Path, name: str = "prevsess.jsonl") -> Path:
    p = tmp_path / name
    lines = [
        {"message": {"role": "user", "content": [{"type": "text", "text": "do the thing"}]}},
        {"message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}},
    ]
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return p


_STUB_JEV_COMPACT = """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

argv = sys.argv
Path({argv_log!r}).write_text(json.dumps(argv), encoding="utf-8")
out_text = {out_text!r}
if out_text and "--out" in argv:
    Path(argv[argv.index("--out") + 1]).write_text(out_text, encoding="utf-8")
sys.stdout.write({stdout!r})
sys.stderr.write({stderr!r})
sys.exit({exit_code})
"""


def _stub_jev_compact(plugin_root: Path, argv_log: Path, *, exit_code: int, out_text: str = "",
                       stderr: str = "", stdout: str = "") -> None:
    """A fake `scripts/jev_compact.py` — records its own argv to `argv_log` and exits with a
    fixed code, standing in for the real (httpx/jevctx-dependent, network-touching) CLI. Runs
    as a REAL subprocess (git-tracked 100755 in production; chmod'd here the same way) so the
    exec-by-path invocation form itself is exercised, not just the Python call that builds it.

    `stdout` (TRDD-1ETALGDG followup): the real CLI's own `compacted items=...` success line
    (carrying `blocked=N blocked_digest=<hex>`) -- unset (the default) reproduces the OLD
    stub behaviour (no stdout at all), so every existing caller is unaffected.
    """
    script = plugin_root / "scripts" / "jev_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        _STUB_JEV_COMPACT.format(argv_log=str(argv_log), out_text=out_text, exit_code=exit_code,
                                  stderr=stderr, stdout=stdout),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


_COMPACTED_DOC = (
    "# Compacted context (Jev compaction)\ntranscript: /tmp/x\n\n## Kept items\nsome text\n\n"
    '## Elided\n[[elided id=a:0 tokens=5 "x"]]\n\n'
    'pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" '
    "expand --transcript /tmp/x <id>"
)


def _write_probe_stamp(**fields) -> None:
    path = global_state.control_dir() / "jev-probe.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields), encoding="utf-8")


class _FakeClock:
    """A simulated clock passed as `sps.main`'s own `now_fn`/`sleep_fn` keyword arguments
    (TRDD-RAEGS1D5 owner review finding #5 -- EXPLICIT parameters now, never the module-level
    mutable `_now_fn`/`_sleep_fn` hooks this used to be): `sleep()` just advances `now` by the
    requested duration instead of actually blocking, so a retry loop that would otherwise burn
    real minutes of wall-clock time (the owner's 5-minute Jev retry budget,
    `_TRANSIENT_RETRY_SLEEP_S` backoff) converges in milliseconds while still exercising the
    REAL number of loop iterations the production code would make. `jev_deadline` in
    `summarize_previous_session._main` is computed from the passed-in `now_fn()`, never a bare
    `time.time()` call, specifically so a faked clock and the retry loop's own budget check
    always agree."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _fake_clock() -> _FakeClock:
    """A fresh `_FakeClock` -- pass `now_fn=clock.time, sleep_fn=clock.sleep` to `sps.main(...)`
    at each call site (no monkeypatching needed: the clock is an ordinary argument now)."""
    return _FakeClock()


_STUB_JEV_COMPACT_APPENDING = """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

argv = sys.argv
log = Path({argv_log!r})
with log.open("a", encoding="utf-8") as f:
    f.write(json.dumps(argv) + "\\n")
sys.exit({exit_code})
"""


def _stub_jev_compact_appending(plugin_root: Path, argv_log: Path, *, exit_code: int) -> None:
    """Like `_stub_jev_compact`, but APPENDS one JSON line per invocation instead of writing
    once -- lets a test count how many times the retry loop actually re-invoked the CLI."""
    script = plugin_root / "scripts" / "jev_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        _STUB_JEV_COMPACT_APPENDING.format(argv_log=str(argv_log), exit_code=exit_code),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


_STUB_LLM_EXT_COMPACT = """#!/usr/bin/env python3
import sys
sys.stdout.write({text!r})
sys.exit({exit_code})
"""


def _stub_llm_ext_compact(plugin_root: Path, *, exit_code: int = 0, text: str = "llm-ext summary text") -> None:
    """A fake `scripts/llm_ext_compact.py` -- standing in for the real (llm-ext-binary-
    touching) fallback CLI, the same way `_stub_jev_compact` stands in for `jev_compact.py`."""
    script = plugin_root / "scripts" / "llm_ext_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(_STUB_LLM_EXT_COMPACT.format(text=text, exit_code=exit_code), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


_STUB_JEV_COMPACT_DECLINE_GATE = """#!/usr/bin/env python3
import json
import sys
import time
from pathlib import Path

argv = sys.argv[1:]
log = Path({argv_log!r})
with log.open("a", encoding="utf-8") as f:
    f.write(json.dumps(argv) + "\\n")

stamp_path = Path({stamp_path!r})
no_decline = "--no-decline" in argv

if not no_decline and stamp_path.is_file():
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except Exception:
        stamp = {{}}
    if stamp.get("kind") == "unavailable" and (time.time() - float(stamp.get("ts", 0) or 0)) < 300:
        sys.exit(5)  # mirrors jev_compact.py compact's own EXIT_DECLINED_UNAVAILABLE

# --no-decline was given, or no fresh decline-worthy stamp exists -- a REAL (simulated)
# attempt that fails transiently, the same way an outage would, re-stamping "unavailable" so
# a caller that forgot --no-decline would fast-decline on its NEXT invocation.
stamp_path.write_text(
    json.dumps({{"ok": False, "kind": "unavailable", "reason": "simulated outage",
                 "ts": time.time()}}),
    encoding="utf-8",
)
sys.exit(7)  # EXIT_JEV_ERROR
"""


def _stub_jev_compact_decline_gate(plugin_root: Path, argv_log: Path, stamp_path: Path) -> None:
    """A `jev_compact.py` stand-in that MIMICS the real CLI's own decline gate (owner review
    finding #6(b), TRDD-RAEGS1D5): unlike `_stub_jev_compact_appending` (which always returns
    the same fixed exit code regardless of `--no-decline`), this stub actually DECLINES (exit
    5) when `--no-decline` is missing and a fresh `kind="unavailable"` stamp is on disk --
    proving the lane's retries are genuine only when `--no-decline` is truly threaded through,
    not merely present in argv."""
    script = plugin_root / "scripts" / "jev_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        _STUB_JEV_COMPACT_DECLINE_GATE.format(argv_log=str(argv_log), stamp_path=str(stamp_path)),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


# --- the subprocess invocation form itself -------------------------------------------------


def test_compact_invocation_form_and_timeout(tmp_path, monkeypatch, _isolated_env):
    """Exec by PATH (`PLUGIN_ROOT/scripts/jev_compact.py`), argv carries `compact --transcript
    <prev> --out <path> --session-key <key>` with no `--state-heads` flag when trddgrep is
    absent, and the FIRST attempt's `timeout` spans the WHOLE remaining retry budget (~300s,
    the `_DEFAULT_JEV_RETRY_BUDGET_S` default) -- orchestrator correction 2026-09-23, from a
    real measurement (a 49MB transcript took 168s for ONE `jev_compact.py compact` run): a
    fixed 120s sub-budget would have killed a genuinely slow-but-healthy attempt before it
    could finish, when the whole point of the retry budget is to give Jev room to actually work."""
    # trddgrep must be genuinely absent, but `/usr/bin/env python3` (the stub's own shebang)
    # still needs to resolve -- keep the real interpreter's directory on PATH, nothing else.
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent))
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    argv_log = tmp_path / "argv.json"
    _stub_jev_compact(plugin_root, argv_log, exit_code=0, out_text=_COMPACTED_DOC)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)

    real_run = subprocess.run
    captured_kwargs: dict = {}

    def _spy_run(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return real_run(cmd, **kwargs)

    # `subprocess.run` is called inside `jev_compaction_lane.run_compact` now, not in `sps`
    # itself (card 3 C2 thinned the entry script) — but `subprocess` is ONE module object
    # shared by every importer, so patching it here via this file's own import still
    # intercepts the call made from inside the lib module.
    monkeypatch.setattr(subprocess, "run", _spy_run)

    rc = sps.main()
    assert rc == 0
    # ~300s (the default retry budget), not a fixed sub-cap -- a few seconds of slack for the
    # test's own real wall-clock time between computing the deadline and the subprocess call.
    timeout = captured_kwargs.get("timeout")
    assert timeout is not None and 290 <= timeout <= sps._DEFAULT_JEV_RETRY_BUDGET_S, timeout
    assert captured_kwargs.get("capture_output") is True
    assert captured_kwargs.get("text") is True

    argv = json.loads(argv_log.read_text(encoding="utf-8"))
    assert argv[0] == str(plugin_root / "scripts" / "jev_compact.py")
    assert argv[1] == "compact"
    assert "--transcript" in argv and str(prev) in argv
    assert "--out" in argv
    assert "--session-key" in argv
    assert "--state-heads" not in argv  # trddgrep absent -> no heads flag at all


# --- exit 0: success writes the compacted context through compose_handoff ------------------


def test_exit_0_writes_a_composed_handoff_and_releases_the_hold(tmp_path, monkeypatch,
                                                                  _isolated_env):
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    _stub_jev_compact(plugin_root, tmp_path / "argv.json", exit_code=0, out_text=_COMPACTED_DOC)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    rc = sps.main()
    assert rc == 0

    sd = state.state_dir()
    group = handoff_files.newest_group(sd)
    assert group, "a handoff must have been written"
    text = group[0].read_text(encoding="utf-8")
    assert "pointers expand with:" in text
    assert "Jev compaction" in text
    # The hold must release on ARTIFACT PRESENCE, not merely at some later TTL expiry
    # (TRDD-RAEGS1D5 card 3 C2): the ten-minute-to-seconds win is exactly this — the moment
    # the compacted context is written, `summary_hold_active` must already read False.
    from external_handoff_clear import _PENDING_FILE, summary_hold_active  # noqa: PLC0415
    assert not (sd / _PENDING_FILE).is_file(), "the hold must be released on success"
    assert not summary_hold_active(sd, int(time.time())), (
        "summary_hold_active must be False the same second the artifact lands"
    )


_STUB_JEV_COMPACT_TWO_DOCS = """#!/usr/bin/env python3
import sys
from pathlib import Path
argv = sys.argv
if "--out" in argv:
    Path(argv[argv.index("--out") + 1]).write_text({full_text!r}, encoding="utf-8")
if "--inject-out" in argv:
    Path(argv[argv.index("--inject-out") + 1]).write_text({inject_text!r}, encoding="utf-8")
sys.exit(0)
"""


def _stub_jev_compact_two_docs(plugin_root: Path, *, full_text: str, inject_text: str) -> None:
    """Writes DIFFERENT text to `--out` and `--inject-out` -- lets a test prove
    `jev_compaction_lane.run_compact_with_fallback` actually PREFERS the capped companion when
    it exists, rather than only ever exercising the fallback-to-full-document branch every other
    stub in this file exercises (they never create `--inject-out` at all). Mirrors the hook's
    own `_STUB_JEV_COMPACT_TWO_DOCS` fixture in
    tests/test_on_session_start_post_clear_compact.py."""
    script = plugin_root / "scripts" / "jev_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        _STUB_JEV_COMPACT_TWO_DOCS.format(full_text=full_text, inject_text=inject_text),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def test_exit_0_prefers_the_capped_inject_out_companion_over_the_full_document(
    tmp_path, monkeypatch, _isolated_env,
):
    """Adversarial review finding (TRDD-RAEGS1D5 retune follow-up): `run_compact_with_fallback`'s
    new "prefer `inject_out_path` when readable" branch -- the riskiest line in that diff, since
    it changes what `text` MEANS for this detached lane -- had zero coverage anywhere: every
    other stub in this file never creates `--inject-out`, so only the fallback-to-full-document
    path was ever exercised. This proves the OTHER branch: when jev_compact.py writes a
    DIFFERENT, smaller document to `--inject-out`, THAT is what lands in the written handoff,
    not the full `--out` document."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    full_only = "FULL-ONLY-KEPT-ITEM-MARKER"
    inject_only = "INJECT-ONLY-KEPT-ITEM-MARKER"
    full_text = (
        f"# Compacted context (Jev compaction)\ntranscript: /tmp/x\n\n## Kept items\n{full_only}\n\n"
        'pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" '
        "expand --transcript /tmp/x <id>"
    )
    inject_text = (
        f"# Compacted context (Jev compaction)\ntranscript: /tmp/x\n\n## Kept items\n{inject_only}\n\n"
        'pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" '
        "expand --transcript /tmp/x <id>"
    )
    _stub_jev_compact_two_docs(plugin_root, full_text=full_text, inject_text=inject_text)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    rc = sps.main()
    assert rc == 0

    sd = state.state_dir()
    group = handoff_files.newest_group(sd)
    assert group, "a handoff must have been written"
    text = group[0].read_text(encoding="utf-8")
    assert inject_only in text, "the CAPPED companion must be what lands in the handoff"
    assert full_only not in text, "the full document must NOT leak in when a companion exists"


_STUB_JEV_COMPACT_CAPTURE_ARGV_TWO_DOCS = """#!/usr/bin/env python3
import json
import sys
from pathlib import Path
argv = sys.argv
Path({argv_log!r}).write_text(json.dumps(argv), encoding="utf-8")
out_text = {out_text!r}
if out_text and "--out" in argv:
    Path(argv[argv.index("--out") + 1]).write_text(out_text, encoding="utf-8")
if out_text and "--inject-out" in argv:
    Path(argv[argv.index("--inject-out") + 1]).write_text(out_text, encoding="utf-8")
sys.exit(0)
"""


def _stub_jev_compact_capture_argv_and_inject_out(
    plugin_root: Path, argv_log: Path, *, out_text: str,
) -> None:
    """Like `_stub_jev_compact` above (records its own argv) but ALSO writes `out_text` to
    `--inject-out` when given -- needed to both assert on the EXACT `--inject-max-bytes` argv
    (TRDD-RAEGS1D5 room-floor follow-up) and exercise `run_compact_with_fallback`'s "prefer the
    capped companion" branch (`_stub_jev_compact` above never creates `--inject-out` at all)."""
    script = plugin_root / "scripts" / "jev_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        _STUB_JEV_COMPACT_CAPTURE_ARGV_TWO_DOCS.format(argv_log=str(argv_log), out_text=out_text),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def test_card_heavy_facts_section_keeps_every_id_and_shortens_titles_first(
    tmp_path, monkeypatch, _isolated_env,
):
    """TRDD-RAEGS1D5 room-floor follow-up, round 2 (detached lane). Same defect and fix as the
    SessionStart hook's own test of the same name in
    tests/test_on_session_start_post_clear_compact.py: `jcl.trim_cards_for_room` must never drop
    a card's id (the card list is how a resumed session finds its in-flight TRDDs, and a
    card-heavy facts section is exactly the situation a BUSY session is in) -- it shortens TITLES
    toward "" instead, and the returned `--inject-max-bytes` is never inflated above what
    `compose_handoff` actually has room for (round 1's `max(LANE_MIN_INJECT_BYTES, ...)` could
    exceed the real room and get sliced -- see the hook's own companion fixture, `test_natural_
    value_never_inflated_past_real_room_even_when_titles_are_fully_emptied`, which reproduces
    that danger precisely and is not duplicated here)."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"

    # 10 in-flight cards, (id, column, title) -- same fixture shape and title length as the
    # hook's own test of this name, measured directly (not guessed) to starve the RAW, full-title
    # room below the target -- see the assertion right below that proves it for THIS file's own
    # inputs (a different `prev` transcript/tail than the hook's fixture uses).
    long_title = ("a very long TRDD title describing exactly what this card is about " * 20)[:750]
    cards = [(f"CARD{i:04d}", "dev", long_title) for i in range(10)]
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, cards, ""))

    small_doc = (
        "# Compacted context (Jev compaction)\ntranscript: /tmp/x\n\n## Kept items\n"
        "-- user newest-owner-item --\nTHE NEWEST OWNER MESSAGE survives verbatim\n\n"
        "another modest kept item\n\n"
        'pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py"'
        " expand --transcript /tmp/x <id>"
    )
    argv_log = tmp_path / "argv.json"
    _stub_jev_compact_capture_argv_and_inject_out(plugin_root, argv_log, out_text=small_doc)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)

    # Independently compute the EXACT (trimmed-inputs, inject_max_bytes) `jcl.trim_cards_for_room`
    # must produce for this fixture -- exact equality against an independently-computed value, not
    # just a bound.
    now_iso_probe = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    tail_probe = ec.recent_messages(str(prev))
    raw_room = ec.compose_handoff_room(
        ec.HandoffInputs(trigger="jev-compaction", findings=[], cards=cards),
        now_iso=now_iso_probe, tail=tail_probe,
        max_bytes=jcl.LANE_INJECTION_MAX_BYTES, source=jcl.SOURCE_JEV,
    )
    assert jcl.inject_max_bytes_for(raw_room, str(prev)) < jcl.LANE_MIN_INJECT_BYTES, (
        "fixture must starve the RAW, full-title room below the target, or it proves nothing new"
    )
    expected_inputs, expected_inject_max_bytes = jcl.trim_cards_for_room(
        ec.HandoffInputs(trigger="jev-compaction", findings=[], cards=cards),
        now_iso=now_iso_probe, tail=tail_probe, transcript_path=str(prev),
        max_bytes=jcl.LANE_INJECTION_MAX_BYTES, source=jcl.SOURCE_JEV,
    )
    # Every id AND column present, unchanged, none dropped -- only titles may have shrunk
    # (adversarial review, round 2 self-review: id-only checks would miss a mutation that
    # corrupted `col` while leaving `cid` intact).
    assert len(expected_inputs.cards) == 10
    assert [(cid, col) for cid, col, _title in expected_inputs.cards] == [
        (f"CARD{i:04d}", "dev") for i in range(10)
    ]
    assert any(len(title) < len(long_title) for _cid, _col, title in expected_inputs.cards), (
        "fixture must actually shorten at least one title, or this test proves nothing new"
    )

    rc = sps.main()
    assert rc == 0

    argv = json.loads(argv_log.read_text(encoding="utf-8"))
    assert "--inject-max-bytes" in argv
    passed = int(argv[argv.index("--inject-max-bytes") + 1])
    # Exact equality (never just "never 0/negative") -- sized exactly as `jcl.trim_cards_for_room`
    # computed above, never inflated above it.
    assert passed == expected_inject_max_bytes, (passed, expected_inject_max_bytes)
    assert passed > 0

    sd = state.state_dir()
    group = handoff_files.newest_group(sd)
    assert group, "a handoff must have been written"
    text = group[0].read_text(encoding="utf-8")
    # Unsliced: the whole stub summary -- including its "newest owner" line -- survives verbatim.
    assert small_doc in text
    assert "THE NEWEST OWNER MESSAGE survives verbatim" in text
    assert "summary truncated" not in text
    # Every one of the 10 ids is still present in the written handoff -- the round-2 invariant
    # this test exists to pin.
    for i in range(10):
        assert f"TRDD-CARD{i:04d}" in text, f"card {i} lost its id"


# --- exit 5/6/7 -> the findings ledger, then (TRDD-RAEGS1D5) Jev exhausts and the llm-ext
# fallback is attempted; with no `llm_ext_compact.py` stub present it fails too (spawn error),
# so the FINAL outcome is the advisor's "on final failure: ensure a template exists, release
# the hold" recommendation -- superseding the old "left to expire" degrade path this test used
# to assert. -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exit_code,stamp,expect_code,expect_sev,expect_substr",
    [
        (5, {"kind": "unavailable", "reason": "HTTP 503", "ts": 0.0},
         "JEV-COMPACT-DECLINED", "LOW", "endpoint unavailable"),
        (6, None, "JEV-COMPACT-NO-DIGEST", "LOW", "nothing to digest"),
        (7, {"kind": "unavailable", "reason": "HTTP 503"},
         "JEV-SCORER-UNAVAILABLE", "MEDIUM", "scorer unavailable"),
        (7, {"kind": "auth", "reason": "401 invalid key"},
         "JEV-AUTH-REJECTED", "HIGH", "provider key rejected"),
        (7, {"kind": "unreachable", "reason": "DNS resolution failed"},
         "JEV-SCORER-UNREACHABLE", "HIGH", "scorer unreachable from this lane"),
        (7, {"kind": "budget", "reason": "422 request too large"},
         "JEV-COMPACT-FAILED", "HIGH", "jev_compact failed"),
        (7, {},  # no `kind` at all -- defensive fallback to unavailable's text
         "JEV-SCORER-UNAVAILABLE", "MEDIUM", "scorer unavailable"),
    ],
)
def test_nonzero_exit_maps_to_the_right_finding(
    tmp_path, monkeypatch, _isolated_env, exit_code, stamp, expect_code, expect_sev,
    expect_substr, capsys,
):
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    _stub_jev_compact(plugin_root, tmp_path / "argv.json", exit_code=exit_code)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))
    if stamp is not None:
        _write_probe_stamp(**stamp)
    # A transient/rate-limited kind retries inside the 5-minute budget -- the fake clock makes
    # those retries converge without any real sleeping (see `_FakeClock`'s own docstring).
    clock = _fake_clock()

    rc = sps.main(now_fn=clock.time, sleep_fn=clock.sleep)
    assert rc == 0
    out = capsys.readouterr().out
    assert "SUMMARY_FAILED" in out

    entries = _ledger_entries()
    assert any(e["code"] == expect_code and e["sev"] == expect_sev
               and expect_substr in e["msg"] for e in entries), entries

    # TRDD-RAEGS1D5 advisor recommendation (supersedes the old "left to expire" behaviour this
    # test used to assert): once Jev is exhausted AND the llm-ext fallback ALSO fails (no
    # `llm_ext_compact.py` stub exists under this fake plugin_root, so the fallback's own
    # subprocess spawn fails), a TEMPLATE handoff is written and the hold is released
    # immediately -- there is nothing left to wait for.
    from external_handoff_clear import _PENDING_FILE  # noqa: PLC0415
    assert not (state.state_dir() / _PENDING_FILE).is_file()
    group = handoff_files.newest_group(state.state_dir())
    assert group and group[0].read_text(encoding="utf-8").lstrip().startswith(
        handoff_files.TEMPLATE_MARKER
    )


def test_kind_rate_limited_with_retry_after_is_medium(tmp_path, monkeypatch, _isolated_env):
    """Coordinator amendment: `kind=rate_limited` + a present `retry_after_s` is its own
    MEDIUM finding, distinct from the generic `unavailable` text."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    _stub_jev_compact(plugin_root, tmp_path / "argv.json", exit_code=7)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))
    _write_probe_stamp(kind="rate_limited", reason="429", retry_after_s=42)
    clock = _fake_clock()

    assert sps.main(now_fn=clock.time, sleep_fn=clock.sleep) == 0
    entries = _ledger_entries()
    hit = [e for e in entries if e["code"] == "JEV-RATE-LIMITED"]
    assert hit and hit[0]["sev"] == "MEDIUM"
    assert "retry after 42s" in hit[0]["msg"]


def test_kind_rate_limited_without_retry_after_falls_back_to_unavailable(
    tmp_path, monkeypatch, _isolated_env,
):
    """Defensive read (coordinator amendment): a `rate_limited` stamp missing its own
    `retry_after_s` degrades to the `unavailable` wording rather than printing a missing
    number or crashing."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    _stub_jev_compact(plugin_root, tmp_path / "argv.json", exit_code=7)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))
    _write_probe_stamp(kind="rate_limited", reason="429 no window given")
    clock = _fake_clock()

    assert sps.main(now_fn=clock.time, sleep_fn=clock.sleep) == 0
    entries = _ledger_entries()
    assert any(e["code"] == "JEV-SCORER-UNAVAILABLE" for e in entries)
    assert not any(e["code"] == "JEV-RATE-LIMITED" for e in entries)


def test_auth_finding_deduped_on_the_same_reason(tmp_path, monkeypatch, _isolated_env):
    """`kind=auth` findings are surfaced ONCE per distinct reason text — a standing config
    problem re-surfaced every SessionStart would be noise, not new information."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    _stub_jev_compact(plugin_root, tmp_path / "argv.json", exit_code=7)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))
    _write_probe_stamp(kind="auth", reason="401 invalid key")

    from external_handoff_clear import _release_summary_hold  # noqa: PLC0415

    key = handoff_files.session_key(str(prev))
    assert sps.main() == 0
    sd = state.state_dir()
    # `_main`'s own SOURCE_FAILED branch already released this lane's hold (no
    # `llm_ext_compact.py` stub exists under this fake plugin_root, so the fallback fails too,
    # and the final-failure path writes a template + releases -- see `run_compact_with_fallback`'s
    # docstring). This call is therefore a no-op in practice; it stays as a defensive belt-and-
    # braces cleanup between the two simulated "starts" below, and R4 (owner review finding #1)
    # now REQUIRES `key=` explicitly -- there is no unconditional release left to fall back to.
    _release_summary_hold(sd, key=key)
    assert sps.main() == 0

    entries = _ledger_entries()
    auth_hits = [e for e in entries if e["code"] == "JEV-AUTH-REJECTED"]
    assert len(auth_hits) == 1, f"expected exactly one dedup'd auth finding, got {auth_hits}"


# --- TRDD-1ETALGDG followup item 2(b): blocked=N visibility on an exit-0 compaction -------


def test_parse_blocked_summary_extracts_count_and_digest() -> None:
    """`jcl.parse_blocked_summary` pulls `(count, digest)` off `jev_compact.py`'s own
    `compacted items=...` stdout line, and degrades to `(0, "")` -- never an exception --
    when the line is missing (an older `jev_compact.py`, or stdout captured mid-write)."""
    line = "compacted items=5/8 tokens=100 cost=0.01 ms=50 blocked=3 blocked_digest=" + "ab" * 32
    assert jcl.parse_blocked_summary(line) == (3, "ab" * 32)
    assert jcl.parse_blocked_summary(
        "compacted items=8/8 tokens=100 cost=0.01 ms=50 blocked=0 blocked_digest="
    ) == (0, "")
    assert jcl.parse_blocked_summary("") == (0, "")
    assert jcl.parse_blocked_summary("compacted items=8/8 tokens=100\n") == (0, "")


def test_blocked_finding_deduped_by_content_across_two_sessions(tmp_path, monkeypatch, _isolated_env):
    """Coordinator amendment (2026-09-23): the `blocked=N` finding must NOT be deduped only
    per session key -- the SAME poisoning content recurs in EVERY new session of this repo,
    each against a DIFFERENT transcript (so a session-keyed dedupe would never suppress the
    repeat). Two separate `sps.main()` runs, each against its OWN transcript (so neither hits
    the "already summarized" early-skip) but reporting the SAME `blocked_digest` on their
    exit-0 summary line, must still produce exactly ONE `JEV-COMPACT-BLOCKED` finding."""
    project_dir = _isolated_env
    plugin_root = tmp_path / "plugin"
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))
    same_digest = "cd" * 32
    _stub_jev_compact(
        plugin_root, tmp_path / "argv.json", exit_code=0, out_text=_COMPACTED_DOC,
        stdout=f"compacted items=5/8 tokens=100 cost=0.01 ms=50 blocked=3 "
               f"blocked_digest={same_digest}\n",
    )

    from external_handoff_clear import _release_summary_hold  # noqa: PLC0415

    sd = state.state_dir()

    prev1 = _make_prev_transcript(project_dir, name="prevsess1.jsonl")
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev1)
    assert sps.main() == 0
    _release_summary_hold(sd, key=handoff_files.session_key(str(prev1)))

    # A DIFFERENT transcript (a different session_key, so run 2 is a genuine new attempt, not
    # the "already summarized" early-skip) reporting the IDENTICAL content digest.
    prev2 = _make_prev_transcript(project_dir, name="prevsess2.jsonl")
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev2)
    assert sps.main() == 0
    _release_summary_hold(sd, key=handoff_files.session_key(str(prev2)))

    entries = _ledger_entries()
    blocked_hits = [e for e in entries if e["code"] == "JEV-COMPACT-BLOCKED"]
    assert len(blocked_hits) == 1, f"expected exactly one dedup'd finding, got {blocked_hits}"
    assert blocked_hits[0]["sev"] == "LOW"


def test_blocked_finding_day_cap_suppresses_a_second_distinct_digest_same_day(tmp_path):
    """The content-digest dedupe alone would let a DIFFERENT poison digest fire a second
    finding the same day -- the separate one-per-day cap on the CODE itself must suppress
    that too, regardless of digest."""
    sd = tmp_path / "state"
    jcl.record_blocked_finding(sd, blocked=2, blocked_digest="aa" * 32)
    jcl.record_blocked_finding(sd, blocked=5, blocked_digest="bb" * 32)  # a different digest!
    entries = _ledger_entries()
    blocked_hits = [e for e in entries if e["code"] == "JEV-COMPACT-BLOCKED"]
    assert len(blocked_hits) == 1, f"expected the day cap to suppress the second one, got {blocked_hits}"


def test_timeout_expired_is_a_high_bug_finding(tmp_path, monkeypatch, _isolated_env):
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))
    # No `llm_ext_compact.py` under this empty plugin root: the llm-ext fallback (owner review
    # finding #4) now runs via `subprocess.Popen`, not `subprocess.run` -- it is no longer
    # covered by the `subprocess.run` monkeypatch below, so it must be neutralized separately
    # (a missing script -> a clean FileNotFoundError/OSError -> "spawn failed", never a real
    # attempt to launch the production `scripts/llm_ext_compact.py` against a real transcript).
    monkeypatch.setattr(sps, "PLUGIN_ROOT", tmp_path / "plugin")

    def _raise_timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 120))

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    # Every `subprocess.run` call (the Jev side) times out; the fake clock keeps the retry
    # loop's real sleeps from actually happening.
    clock = _fake_clock()

    assert sps.main(now_fn=clock.time, sleep_fn=clock.sleep) == 0
    entries = _ledger_entries()
    assert any(e["code"] == "JEV-COMPACT-FAILED" and "timeout" in e["msg"] for e in entries)


# --- TRDD-RAEGS1D5 owner decision 2026-09-23: retry-then-llm-ext-fallback -------------------


def test_transient_failure_retries_more_than_once_then_llm_ext_fallback_succeeds(
    tmp_path, monkeypatch, _isolated_env,
):
    """The critical assertion the advisor review names as the most likely way this design is
    wrong if unverified: a TRANSIENT Jev failure (`kind="unreachable"`) must make MORE THAN
    ONE real `jev_compact.py` attempt inside the retry budget, not just "eventually fall back"
    -- a `--no-decline` bug that fast-declines every retry after the first would still make the
    fallback fire, but with only ONE real attempt, defeating "retry for 5 minutes"."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    argv_log = tmp_path / "argv.jsonl"
    _stub_jev_compact_appending(plugin_root, argv_log, exit_code=jcl.EXIT_JEV_ERROR)
    _stub_llm_ext_compact(plugin_root, text="llm-ext fallback summary")
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))
    _write_probe_stamp(kind="unreachable", reason="DNS resolution failed")
    clock = _fake_clock()

    rc = sps.main(now_fn=clock.time, sleep_fn=clock.sleep)
    assert rc == 0

    attempts = [ln for ln in argv_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(attempts) > 1, f"expected more than one real jev_compact attempt, got {attempts}"
    for argv in (json.loads(ln) for ln in attempts):
        # Owner review finding #6(a): count ONLY jev_compact.py invocations -- `argv_log` is
        # written exclusively by the `_stub_jev_compact_appending` script (a SEPARATE file from
        # `_stub_llm_ext_compact`'s own, which never touches this log), but assert it here too
        # so a future stub that merges the two logs cannot silently make this count vacuous.
        assert "jev_compact.py" in argv[0], argv
        assert "--no-decline" in argv, argv  # R1: every retry bypasses the stale-outage gate

    sd = state.state_dir()
    group = handoff_files.newest_group(sd)
    assert group, "expected the llm-ext fallback's summary to have been written as a handoff"
    text = group[0].read_text(encoding="utf-8")
    assert "llm-ext fallback summary" in text
    assert "jev-compaction-llm-ext-fallback" in text  # the header line names the source

    from external_handoff_clear import _PENDING_FILE  # noqa: PLC0415
    assert not (sd / _PENDING_FILE).is_file(), "the hold must release once the fallback succeeds"


def test_auth_failure_falls_back_to_llm_ext_without_waiting(tmp_path, monkeypatch, _isolated_env):
    """`kind="auth"` (a rejected provider key) can never succeed on retry -- the loop must stop
    and fall back to llm-ext on the FIRST failure, spending zero seconds of the retry budget."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    argv_log = tmp_path / "argv.jsonl"
    _stub_jev_compact_appending(plugin_root, argv_log, exit_code=jcl.EXIT_JEV_ERROR)
    _stub_llm_ext_compact(plugin_root, text="llm-ext fallback summary")
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))
    _write_probe_stamp(kind="auth", reason="401 invalid key")
    clock = _fake_clock()
    start = clock.now

    assert sps.main(now_fn=clock.time, sleep_fn=clock.sleep) == 0

    attempts = [ln for ln in argv_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(attempts) == 1, f"an auth failure must not retry, got {attempts}"
    assert clock.now == start, "an auth failure must fall back WITHOUT sleeping first"
    sd = state.state_dir()
    text = handoff_files.newest_group(sd)[0].read_text(encoding="utf-8")
    assert "llm-ext fallback summary" in text


def test_rate_limited_retry_after_exceeding_the_budget_falls_back_immediately(
    tmp_path, monkeypatch, _isolated_env,
):
    """R3 (advisor review): when the stamp's own `retry_after_s` already exceeds what remains
    of the retry budget, sleeping to find out is pure waste -- the loop must fall back to
    llm-ext at once instead of sleeping (capped) to the deadline first."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    argv_log = tmp_path / "argv.jsonl"
    _stub_jev_compact_appending(plugin_root, argv_log, exit_code=jcl.EXIT_JEV_ERROR)
    _stub_llm_ext_compact(plugin_root, text="llm-ext fallback summary")
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))
    # retry_after_s (1000s) comfortably exceeds the whole default 300s retry budget.
    _write_probe_stamp(kind="rate_limited", reason="429", retry_after_s=1000)
    clock = _fake_clock()
    start = clock.now

    assert sps.main(now_fn=clock.time, sleep_fn=clock.sleep) == 0

    attempts = [ln for ln in argv_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(attempts) == 1, f"a retry_after past the budget must not retry, got {attempts}"
    assert clock.now == start, "must fall back WITHOUT sleeping out a wait it can't afford"
    sd = state.state_dir()
    text = handoff_files.newest_group(sd)[0].read_text(encoding="utf-8")
    assert "llm-ext fallback summary" in text


def test_jev_timeout_is_never_retried_falls_straight_to_llm_ext(tmp_path, monkeypatch, _isolated_env):
    """Orchestrator correction 2026-09-23, from a real measurement (a 49MB transcript took
    168s for ONE `jev_compact.py compact` run, so a single attempt may legitimately span the
    WHOLE remaining budget): a `run_compact` subprocess TIMEOUT must NEVER be retried -- it is
    deterministic work (same transcript, same digest, same items), so a second attempt would
    reproduce the identical timeout and only burn more of an already-exhausted budget. Exactly
    ONE `jev_compact.py` invocation is made; the lane falls straight to the llm-ext fallback."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    _stub_llm_ext_compact(plugin_root, text="llm-ext fallback summary")
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    real_run = subprocess.run
    jev_calls = {"n": 0}

    def _spy_run(cmd, **kwargs):
        if isinstance(cmd, (list, tuple)) and cmd and "jev_compact.py" in str(cmd[0]):
            jev_calls["n"] += 1
            if jev_calls["n"] > 1:
                raise AssertionError(
                    "jev_compact.py must be invoked at most once -- a timeout must not retry"
                )
            # Owner review finding #6(c): raise the TimeoutExpired WITHOUT touching the fake
            # clock -- only `run_compact_with_fallback`'s own `sleep_fn` calls may advance
            # simulated time; a subprocess timeout itself must never appear to have "waited".
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", _spy_run)
    clock = _fake_clock()
    start = clock.now

    rc = sps.main(now_fn=clock.time, sleep_fn=clock.sleep)

    assert rc == 0
    assert jev_calls["n"] == 1, "expected exactly one jev_compact attempt after a timeout"
    assert clock.now == start, (
        "a timeout must not sleep/advance the clock before falling back -- only an explicit "
        "sleep_fn() call may, and a timeout takes the straight-to-fallback break instead"
    )
    sd = state.state_dir()
    text = handoff_files.newest_group(sd)[0].read_text(encoding="utf-8")
    assert "llm-ext fallback summary" in text


# --- STATE heads: a stub trddgrep on PATH, and its absence ---------------------------------

_TRDDGREP_STUB = """#!/usr/bin/env python3
import sys

argv = sys.argv[1:]
if "show" in argv:
    card_id = argv[argv.index("show") + 1]
    print("\\x1b[1m" + card_id + "\\x1b[0m P? dev fake card")
    print("  design/tasks/fake.md")
    print()
    print("  \\u23f5 STATE (authoritative)")
    print()
    print("  - fake state line for " + card_id)
else:
    print("\\x1b[1m")
    print("1 open cards (design/tasks)")
    print("\\x1b[0m")
    print("\\u2550\\u2550\\u2550 \\x1b[1mDEV\\x1b[0m (1)")
    print("  ABCDEF12 \\x1b[2mP?\\x1b[0m dev           A fake in-flight card")
    print("\\u2550\\u2550\\u2550 \\x1b[1mBACKBURNER\\x1b[0m (1)")
    print("  ZZZZZZZZ \\x1b[2mP?\\x1b[0m backburner    Not in-flight, must be excluded")
sys.exit(0)
"""


def _install_stub_trddgrep(bin_dir: Path, monkeypatch) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "trddgrep"
    stub.write_text(_TRDDGREP_STUB, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{sys.exec_prefix}/bin")


def test_state_heads_written_for_unmentioned_in_flight_fill_only(tmp_path, monkeypatch, _isolated_env):
    """TRDD-O2FNJ4KW: with no transcript passed (no mentions at all), the top set falls back to
    the old deterministic in-flight-columns fill -- the DEV card qualifies, the BACKBURNER one
    doesn't (not an in-flight column) but is still named on the "other open cards" line, never
    silently dropped."""
    project_dir = _isolated_env
    (project_dir / "design" / "tasks").mkdir(parents=True)
    _install_stub_trddgrep(tmp_path / "bin", monkeypatch)

    sd = state.state_dir()
    paths, unavailable, cards, other_line = jcl.state_head_paths(project_dir, sd)

    assert unavailable is False
    assert len(paths) == 1  # only the DEV card, never the BACKBURNER one
    text = Path(paths[0]).read_text(encoding="utf-8")
    assert "ABCDEF12" in Path(paths[0]).name
    assert "STATE" in text
    assert "fake state line for ABCDEF12" in text

    # `cards` reuses the SAME board dump -- (id, column, title) -- so `HandoffInputs.cards` is
    # never silently empty when real cards exist (review finding on TRDD-RAEGS1D5 C1).
    assert cards == [("ABCDEF12", "dev", "A fake in-flight card")]
    # BACKBURNER never earns a title/STATE head here, but it is still SURFACED -- TRDD-O2FNJ4KW's
    # whole point is that an unmentioned open card is named, not dropped.
    assert "ZZZZZZZZ" in other_line


def test_state_heads_unavailable_when_trddgrep_absent(tmp_path, monkeypatch, _isolated_env):
    monkeypatch.setenv("PATH", "/nonexistent-bin-only")
    sd = state.state_dir()
    paths, unavailable, cards, other_line = jcl.state_head_paths(_isolated_env, sd)
    assert paths == []
    assert unavailable is True
    assert cards == []
    assert other_line == ""


# --- TRDD-O2FNJ4KW: ranking the top cards by the session's OWN transcript mentions ----------


_RANK_TRDDGREP_STUB = """#!/usr/bin/env python3
import sys

argv = sys.argv[1:]
if "show" in argv:
    card_id = argv[argv.index("show") + 1]
    print(card_id + " P? fake card")
    print("  design/tasks/fake.md")
    print()
    print("  \\u23f5 STATE (authoritative)")
    print()
    print("  - fake state line for " + card_id)
else:
    print("1 open cards (design/tasks)")
    print("\\u2550\\u2550\\u2550 TODO (1)")
    print("  K0PMVRN6 P? todo          Mentioned only in assistant text")
    print("\\u2550\\u2550\\u2550 LIVE_AUDITING (1)")
    print("  WZKFSQ2N P? live_auditing Mentioned only in a tool_use input")
    print("\\u2550\\u2550\\u2550 DEV (1)")
    print("  ABCDEF12 P? dev           Never mentioned, in-flight fallback")
    print("\\u2550\\u2550\\u2550 TESTING (1)")
    print("  STALE001 P? testing       Never mentioned, stale in-flight fallback")
sys.exit(0)
"""


def _install_rank_stub_trddgrep(bin_dir: Path, monkeypatch) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "trddgrep"
    stub.write_text(_RANK_TRDDGREP_STUB, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{sys.exec_prefix}/bin")


def _write_transcript(tmp_path: Path, lines: list[dict]) -> Path:
    p = tmp_path / "rank-transcript.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return p


def test_mention_in_assistant_text_ranks_above_unmentioned_in_flight_card(
    tmp_path, monkeypatch, _isolated_env,
):
    project_dir = _isolated_env
    (project_dir / "design" / "tasks").mkdir(parents=True)
    _install_rank_stub_trddgrep(tmp_path / "bin", monkeypatch)
    transcript = _write_transcript(tmp_path, [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Working TRDD-K0PMVRN6 now."},
        ]}},
    ])

    sd = state.state_dir()
    _paths, _unavailable, cards, other_line = jcl.state_head_paths(
        project_dir, sd, str(transcript),
    )

    # The mentioned card leads the list; the never-mentioned in-flight fallback cards follow.
    assert cards[0][0] == "K0PMVRN6"
    ids = [c[0] for c in cards]
    assert ids.index("K0PMVRN6") < ids.index("ABCDEF12")
    assert "WZKFSQ2N" in other_line  # not mentioned, not an in-flight column -- named, not lost


def test_mention_only_in_tool_result_or_hook_record_does_not_count(
    tmp_path, monkeypatch, _isolated_env,
):
    project_dir = _isolated_env
    (project_dir / "design" / "tasks").mkdir(parents=True)
    _install_rank_stub_trddgrep(tmp_path / "bin", monkeypatch)
    transcript = _write_transcript(tmp_path, [
        # A tool_result (e.g. a board dump) mentioning WZKFSQ2N must NOT count as a mention.
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "board dump: TRDD-WZKFSQ2N in live_auditing"},
        ]}},
        # A janitor-typed automation command mentioning K0PMVRN6 must NOT count either --
        # `origin.kind` "system"/automation, never the owner's own words.
        {"type": "user", "origin": {"kind": "auto-continuation"},
         "message": {"role": "user", "content": "see TRDD-K0PMVRN6"}},
    ])

    sd = state.state_dir()
    _paths, _unavailable, cards, other_line = jcl.state_head_paths(
        project_dir, sd, str(transcript),
    )

    ids = {c[0] for c in cards}
    assert "WZKFSQ2N" not in ids
    assert "K0PMVRN6" not in ids
    # Both fall back to the deterministic in-flight fill/other-line path, same as no mentions.
    assert "WZKFSQ2N" in other_line


def test_state_head_ranking_order_is_deterministic_across_two_runs(
    tmp_path, monkeypatch, _isolated_env,
):
    project_dir = _isolated_env
    (project_dir / "design" / "tasks").mkdir(parents=True)
    _install_rank_stub_trddgrep(tmp_path / "bin", monkeypatch)
    transcript = _write_transcript(tmp_path, [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "TRDD-K0PMVRN6 and TRDD-WZKFSQ2N both open."},
        ]}},
    ])

    sd = state.state_dir()
    first = jcl.state_head_paths(project_dir, sd, str(transcript))
    second = jcl.state_head_paths(project_dir, sd, str(transcript))
    assert [c[0] for c in first[2]] == [c[0] for c in second[2]]
    assert first[3] == second[3]


def test_bare_id_without_trdd_prefix_still_counts_as_a_mention(
    tmp_path, monkeypatch, _isolated_env,
):
    """TRDD-O2FNJ4KW follow-up (review correction 2): real assistant prose overwhelmingly drops
    the `TRDD-` prefix ("K0PMVRN6 is committed") -- the bare id alone must still rank the card."""
    project_dir = _isolated_env
    (project_dir / "design" / "tasks").mkdir(parents=True)
    _install_rank_stub_trddgrep(tmp_path / "bin", monkeypatch)
    transcript = _write_transcript(tmp_path, [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "K0PMVRN6 is committed."},
        ]}},
    ])

    sd = state.state_dir()
    _paths, _unavailable, cards, _other_line = jcl.state_head_paths(
        project_dir, sd, str(transcript),
    )
    assert cards[0][0] == "K0PMVRN6"


def test_hash_prefixed_id_counts_as_a_mention(tmp_path, monkeypatch, _isolated_env):
    """TRDD-O2FNJ4KW follow-up (review correction 2): `#<id>` is also a valid mention form."""
    project_dir = _isolated_env
    (project_dir / "design" / "tasks").mkdir(parents=True)
    _install_rank_stub_trddgrep(tmp_path / "bin", monkeypatch)
    transcript = _write_transcript(tmp_path, [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "See #K0PMVRN6 for the fix."},
        ]}},
    ])

    sd = state.state_dir()
    _paths, _unavailable, cards, _other_line = jcl.state_head_paths(
        project_dir, sd, str(transcript),
    )
    assert cards[0][0] == "K0PMVRN6"


def test_random_uppercase_word_that_is_not_an_open_id_never_counts(
    tmp_path, monkeypatch, _isolated_env,
):
    """TRDD-O2FNJ4KW follow-up (review correction 2): mentions are matched against the SET of
    open-card ids the board already named, so an unrelated 8-char uppercase token can never
    false-positive into a mention -- the ranking is identical to the no-transcript fallback."""
    project_dir = _isolated_env
    (project_dir / "design" / "tasks").mkdir(parents=True)
    _install_rank_stub_trddgrep(tmp_path / "bin", monkeypatch)
    transcript = _write_transcript(tmp_path, [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "RANDOM99 is not a real card on this board."},
        ]}},
    ])

    sd = state.state_dir()
    with_transcript = jcl.state_head_paths(project_dir, sd, str(transcript))
    without_transcript = jcl.state_head_paths(project_dir, sd)
    assert [c[0] for c in with_transcript[2]] == [c[0] for c in without_transcript[2]]
    assert with_transcript[3] == without_transcript[3]


def test_bulk_tool_use_mention_does_not_change_the_ranking(tmp_path, monkeypatch, _isolated_env):
    """TRDD-O2FNJ4KW follow-up (review correction 1): a SINGLE `tool_use` input block naming
    more than `jcl._TOOL_USE_MENTION_CAP` distinct open-card ids (a worker prompt, a card batch,
    a `grep -E 'A|B|C|D|E'`) must contribute NONE of them -- letting it count would put every
    named id at the same "most recent" rank, which is exactly the skew the review flagged."""
    project_dir = _isolated_env
    (project_dir / "design" / "tasks").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    stub = bin_dir / "trddgrep"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "argv = sys.argv[1:]\n"
        "if 'show' in argv:\n"
        "    card_id = argv[argv.index('show') + 1]\n"
        "    print(card_id + ' P? fake card')\n"
        "    print('  design/tasks/fake.md')\n"
        "    print()\n"
        "    print('  \\u23f5 STATE (authoritative)')\n"
        "    print()\n"
        "    print('  - fake state line for ' + card_id)\n"
        "else:\n"
        "    print('5 open cards (design/tasks)')\n"
        "    print('\\u2550\\u2550\\u2550 TODO (5)')\n"
        "    print('  AAAAAAA1 P? todo          card one')\n"
        "    print('  AAAAAAA2 P? todo          card two')\n"
        "    print('  AAAAAAA3 P? todo          card three')\n"
        "    print('  AAAAAAA4 P? todo          card four')\n"
        "    print('  AAAAAAA5 P? todo          card five')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{sys.exec_prefix}/bin")

    transcript = _write_transcript(tmp_path, [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "input": {
                "command": "grep -E 'AAAAAAA1|AAAAAAA2|AAAAAAA3|AAAAAAA4|AAAAAAA5'",
            }},
        ]}},
    ])

    sd = state.state_dir()
    _paths, _unavailable, cards, other_line = jcl.state_head_paths(
        project_dir, sd, str(transcript),
    )
    # `todo` is not a `STATE_HEAD_COLUMNS` fill column, so a real mention of any of these ids
    # would have put it in `cards` -- none of them made it there, proving the whole bulk mention
    # was dropped rather than merely de-prioritized.
    assert cards == []
    for i in range(1, 6):
        assert f"AAAAAAA{i}" in other_line


def test_bulk_assistant_text_mention_does_not_change_the_ranking(
    tmp_path, monkeypatch, _isolated_env,
):
    """6471f448 review of TRDD-O2FNJ4KW: the `tool_use` cap alone missed an assistant TEXT block
    (a status update naming many new cards) -- that block must be dropped exactly like a bulk
    `tool_use` input, since it is the identical skew in prose form."""
    project_dir = _isolated_env
    (project_dir / "design" / "tasks").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    stub = bin_dir / "trddgrep"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "argv = sys.argv[1:]\n"
        "if 'show' in argv:\n"
        "    card_id = argv[argv.index('show') + 1]\n"
        "    print(card_id + ' P? fake card')\n"
        "    print('  design/tasks/fake.md')\n"
        "    print()\n"
        "    print('  \\u23f5 STATE (authoritative)')\n"
        "    print()\n"
        "    print('  - fake state line for ' + card_id)\n"
        "else:\n"
        "    print('5 open cards (design/tasks)')\n"
        "    print('\\u2550\\u2550\\u2550 TODO (5)')\n"
        "    print('  AAAAAAA1 P? todo          card one')\n"
        "    print('  AAAAAAA2 P? todo          card two')\n"
        "    print('  AAAAAAA3 P? todo          card three')\n"
        "    print('  AAAAAAA4 P? todo          card four')\n"
        "    print('  AAAAAAA5 P? todo          card five')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{sys.exec_prefix}/bin")

    transcript = _write_transcript(tmp_path, [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": (
                "Opened TRDD-AAAAAAA1, TRDD-AAAAAAA2, TRDD-AAAAAAA3, TRDD-AAAAAAA4 and "
                "TRDD-AAAAAAA5 for the fan-out."
            )},
        ]}},
    ])

    sd = state.state_dir()
    _paths, _unavailable, cards, other_line = jcl.state_head_paths(
        project_dir, sd, str(transcript),
    )
    # `todo` is not a `STATE_HEAD_COLUMNS` fill column, so a real mention of any of these ids
    # would have put it in `cards` -- none of them made it there, proving the whole bulk mention
    # was dropped rather than merely de-prioritized.
    assert cards == []
    for i in range(1, 6):
        assert f"AAAAAAA{i}" in other_line


def test_assistant_text_mentioning_two_ids_still_counts(tmp_path, monkeypatch, _isolated_env):
    """The 6471f448 text-block cap only drops a block past `_TOOL_USE_MENTION_CAP` (3) distinct
    ids -- an ordinary assistant status update naming two cards is not a bulk listing and must
    still rank both of them."""
    project_dir = _isolated_env
    (project_dir / "design" / "tasks").mkdir(parents=True)
    _install_rank_stub_trddgrep(tmp_path / "bin", monkeypatch)
    transcript = _write_transcript(tmp_path, [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "TRDD-K0PMVRN6 and TRDD-WZKFSQ2N are both done now."},
        ]}},
    ])

    sd = state.state_dir()
    _paths, _unavailable, cards, _other_line = jcl.state_head_paths(
        project_dir, sd, str(transcript),
    )
    ids = {c[0] for c in cards}
    assert {"K0PMVRN6", "WZKFSQ2N"} <= ids


def test_other_ids_line_caps_and_names_the_remainder():
    many_ids = [f"ID{i:06d}" for i in range(50)]
    line = jcl._format_other_ids_line(many_ids, cap=40)
    assert line.startswith("other open cards: ")
    assert "and " in line and "more (trddgrep)" in line
    assert len(line.split("other open cards: ", 1)[1].rsplit(", and", 1)[0].encode("utf-8")) <= 40 + 2

    short_line = jcl._format_other_ids_line(["ONLYONE1"], cap=300)
    assert short_line == "other open cards: ONLYONE1"
    assert jcl._format_other_ids_line([]) == ""


def test_heads_unavailable_note_lands_in_the_written_handoff(tmp_path, monkeypatch,
                                                               _isolated_env):
    """The brief's C1 requirement: trddgrep absent/failing must add a visible note to the
    injected header, not just silently inject zero heads (which reads identically to "no
    in-flight work" — a materially different claim)."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    # trddgrep absent, but the stub's own `/usr/bin/env python3` shebang still needs to resolve.
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent))
    plugin_root = tmp_path / "plugin"
    _stub_jev_compact(plugin_root, tmp_path / "argv.json", exit_code=0, out_text=_COMPACTED_DOC)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)

    assert sps.main() == 0
    sd = state.state_dir()
    text = handoff_files.newest_group(sd)[0].read_text(encoding="utf-8")
    assert "heads: none (trddgrep unavailable)" in text


def test_in_flight_cards_land_in_the_written_handoff(tmp_path, monkeypatch, _isolated_env):
    """Review finding on TRDD-RAEGS1D5 C1: `HandoffInputs.cards` must carry the REAL in-flight
    board cards (reused from the same trddgrep board dump the STATE heads come from), not an
    always-empty list — an empty `cards=[]` leaves `compose_template_handoff`'s fixed "read the
    STATE block of the first in-flight card below" NEXT ACTION line pointing at nothing."""
    project_dir = _isolated_env
    (project_dir / "design" / "tasks").mkdir(parents=True)
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    _install_stub_trddgrep(tmp_path / "bin", monkeypatch)
    plugin_root = tmp_path / "plugin"
    _stub_jev_compact(plugin_root, tmp_path / "argv.json", exit_code=0, out_text=_COMPACTED_DOC)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)

    assert sps.main() == 0
    sd = state.state_dir()
    text = handoff_files.newest_group(sd)[0].read_text(encoding="utf-8")
    assert "ABCDEF12" in text
    assert "A fake in-flight card" in text
    assert "heads: none (trddgrep unavailable)" not in text



# --- TRDD-RAEGS1D5 owner decision 2026-09-23 R2: `--transcript` names the source explicitly --


def test_transcript_flag_skips_the_pane_claim_check_and_the_guess(tmp_path, monkeypatch, _isolated_env):
    """R2: a caller passing `--transcript PATH` (the sync hook, on its own failure) must skip
    BOTH the pane-claim check (a FRESH sidecar for this pane exists here, which would
    otherwise make this run defer entirely) and the `previous_transcript()` guess -- proven by
    setting up a fresh sidecar that would normally cause an immediate no-op return, then
    passing an EXPLICIT, different transcript and confirming it gets composed anyway."""
    monkeypatch.setenv("TMUX_PANE", "%42")
    project_dir = _isolated_env
    sd = state.state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    pane_key = state.terminal_pane_key({"TMUX_PANE": "%42"})
    assert pane_key
    # A FRESH sidecar for THIS pane -- without --transcript, main() would return 0 immediately.
    (sd / f"resume-after-clear.{pane_key}.transcript").write_text(
        f"/tmp/some-other-transcript.jsonl\n{int(time.time())}\n", encoding="utf-8"
    )

    explicit = _make_prev_transcript(project_dir, name="explicit.jsonl")

    def _boom(*_a, **_kw):
        raise AssertionError("--transcript must skip previous_transcript() entirely")

    monkeypatch.setattr(jcl, "previous_transcript", _boom)
    plugin_root = tmp_path / "plugin"
    _stub_jev_compact(plugin_root, tmp_path / "argv.json", exit_code=0, out_text=_COMPACTED_DOC)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    rc = sps.main(["--transcript", str(explicit)])

    assert rc == 0
    group = handoff_files.newest_group(sd)
    assert group and "pointers expand with:" in group[0].read_text(encoding="utf-8"), (
        "the explicitly-named transcript must have been composed despite the fresh sidecar"
    )


def test_transcript_flag_for_a_missing_file_is_a_clean_noop(tmp_path, monkeypatch, _isolated_env):
    """A caller-named transcript that does not exist on disk must degrade to "nothing to do",
    never a crash or an attempt to compact a nonexistent file."""
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.delenv("ITERM_SESSION_ID", raising=False)

    def _boom(*_a, **_kw):
        raise AssertionError("must not fall back to previous_transcript() when --transcript "
                              "is given, even if the named file is missing")

    monkeypatch.setattr(jcl, "previous_transcript", _boom)

    rc = sps.main(["--transcript", str(tmp_path / "does-not-exist.jsonl")])

    assert rc == 0
    assert not handoff_files.newest_group(state.state_dir())


# --- TRDD-RAEGS1D5 card 5: pane-sidecar deference (the dedicated post-clear-compact hook
# owns a transcript this summarizer would otherwise race it to compose) ---------------------


def test_fresh_pane_sidecar_skips_composing_entirely(tmp_path, monkeypatch, _isolated_env):
    """A fresh (<=300s) sidecar for THIS pane means the dedicated hook is (about to be)
    handling this exact clear -- the summarizer must exit before even looking for a
    previous transcript, let alone spend a subprocess call on it."""
    monkeypatch.setenv("TMUX_PANE", "%7")
    pane_key = state.terminal_pane_key({"TMUX_PANE": "%7"})
    assert pane_key
    sd = state.state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    (sd / f"resume-after-clear.{pane_key}.transcript").write_text(
        f"/tmp/some-transcript.jsonl\n{int(time.time())}\n", encoding="utf-8"
    )

    def _boom(*_a, **_kw):
        raise AssertionError("must not run jev_compact.py when this pane's sidecar is fresh")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(jcl, "previous_transcript", _boom)

    assert sps.main() == 0
    assert not handoff_files.newest_group(sd)


def test_fresh_consumed_pane_sidecar_skips_composing(tmp_path, monkeypatch, _isolated_env):
    """A `.consumed-*` sidecar WRITTEN in the last 300s means the dedicated hook just ran (or
    declined to a template) for this pane's clear moments ago -- skip."""
    monkeypatch.setenv("TMUX_PANE", "%9")
    pane_key = state.terminal_pane_key({"TMUX_PANE": "%9"})
    assert pane_key
    sd = state.state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    recent_epoch = int(time.time()) - 10
    (sd / f"resume-after-clear.{pane_key}.transcript.consumed-{recent_epoch}").write_text(
        f"/tmp/some-transcript.jsonl\n{recent_epoch}\n", encoding="utf-8"
    )

    def _boom(*_a, **_kw):
        raise AssertionError("must not run jev_compact.py when this pane's sidecar is consumed")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(jcl, "previous_transcript", _boom)

    assert sps.main() == 0


def test_stale_consumed_pane_sidecar_does_not_block_composing_forever(
    tmp_path, monkeypatch, _isolated_env,
):
    """Review finding, 2026-09-23: a `.consumed-*` marker OLDER than 300s must NOT skip this
    summarizer -- the marker is written the instant the dedicated hook STARTS handling a clear
    and is never cleaned up afterwards, so treating any age as "handled there" would block this
    summarizer from composing a real handoff for that pane EVER AGAIN, no matter how many later
    sessions and clears happen. Only a fresh marker is still-in-flight evidence."""
    monkeypatch.setenv("TMUX_PANE", "%9")
    pane_key = state.terminal_pane_key({"TMUX_PANE": "%9"})
    assert pane_key
    sd = state.state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    old_epoch = int(time.time()) - 10_000
    (sd / f"resume-after-clear.{pane_key}.transcript.consumed-{old_epoch}").write_text(
        f"/tmp/some-transcript.jsonl\n{old_epoch}\n", encoding="utf-8"
    )

    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    _stub_jev_compact(plugin_root, tmp_path / "argv.json", exit_code=0, out_text=_COMPACTED_DOC)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    assert sps.main() == 0
    assert handoff_files.newest_group(sd), "a stale consumed marker must not block a real compose"


def test_a_stale_pane_sidecar_for_a_DIFFERENT_pane_does_not_block_composing(
    tmp_path, monkeypatch, _isolated_env,
):
    """Two panes' sidecars do not cross: a sidecar belonging to another pane must never make
    THIS pane's summarizer skip its own, unrelated previous transcript."""
    monkeypatch.setenv("TMUX_PANE", "%1")
    other_key = state.terminal_pane_key({"TMUX_PANE": "%2"})
    assert other_key
    sd = state.state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    (sd / f"resume-after-clear.{other_key}.transcript").write_text(
        f"/tmp/other-pane-transcript.jsonl\n{int(time.time())}\n", encoding="utf-8"
    )
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    _stub_jev_compact(plugin_root, tmp_path / "argv.json", exit_code=0, out_text=_COMPACTED_DOC)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    assert sps.main() == 0
    assert handoff_files.newest_group(sd), "this pane's own transcript must still compose"


def test_template_marked_handoff_does_not_count_as_already_summarized(
    tmp_path, monkeypatch, _isolated_env,
):
    """A handoff whose first line is `handoff_files.TEMPLATE_MARKER` is the dedicated hook's
    OWN failure fallback, never a real Jev compose -- the "already summarized" skip must
    ignore it so a real compose is retried on the next SessionStart (TRDD-RAEGS1D5 card 5)."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    key = handoff_files.session_key(str(prev))
    sd = state.state_dir()
    handoff_files.write(
        sd, key, f"{handoff_files.TEMPLATE_MARKER}\nfact-only, no real compaction\n",
    )
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    _stub_jev_compact(plugin_root, tmp_path / "argv.json", exit_code=0, out_text=_COMPACTED_DOC)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    assert sps.main() == 0
    texts = [p.read_text(encoding="utf-8") for p in handoff_files.newest_group(sd)]
    assert any("pointers expand with:" in t for t in texts), (
        "a real Jev compose must have been retried, not skipped as already-summarized"
    )


def test_a_real_non_template_handoff_still_skips(tmp_path, monkeypatch, _isolated_env):
    """Regression: the template-marker carve-out must not un-skip a GENUINE prior compose --
    only a template-marked one is retried."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    key = handoff_files.session_key(str(prev))
    sd = state.state_dir()
    handoff_files.write(sd, key, "# Compacted context (Jev compaction)\nreal content\n")

    def _boom(*_a, **_kw):
        raise AssertionError("a real prior compose must still be skipped, not re-run")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)

    assert sps.main() == 0


# --- TRDD-RAEGS1D5 adversarial-review follow-up fixes (2026-09-23) -------------------------


def test_overlapping_lanes_release_only_the_matching_key(tmp_path, monkeypatch, _isolated_env):
    """R4, LANE level (owner review finding #1): while lane A is still compacting, lane B's
    own capture overwrites the SAME shared `summary-pending.json` with ITS key -- lane A's
    later success must still release only ITS OWN hold record. Here that means a no-op: the
    CURRENT record on disk belongs to B by the time A finishes, so A's release must leave it
    fully intact rather than dropping B's still-active hold out from under it."""
    project_dir = _isolated_env
    prev_a = _make_prev_transcript(project_dir, name="a.jsonl")
    prev_b = _make_prev_transcript(project_dir, name="b.jsonl")
    key_a = handoff_files.session_key(str(prev_a))
    key_b = handoff_files.session_key(str(prev_b))
    assert key_a != key_b

    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev_a)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))
    plugin_root = tmp_path / "plugin"
    _stub_jev_compact(plugin_root, tmp_path / "argv.json", exit_code=0, out_text=_COMPACTED_DOC)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)

    sd = state.state_dir()
    real_run_with_fallback = jcl.run_compact_with_fallback

    def _racing_run_with_fallback(*args, **kwargs):
        # Simulate lane B's own `_capture_summary_source` landing WHILE lane A is still
        # compacting -- overwrites the ONE shared summary-pending.json with a DIFFERENT key.
        ehc._capture_summary_source(sd, {"transcript": str(prev_b)}, int(time.time()))
        return real_run_with_fallback(*args, **kwargs)

    monkeypatch.setattr(jcl, "run_compact_with_fallback", _racing_run_with_fallback)

    assert sps.main() == 0  # lane A's own run, composing prev_a

    # Lane A wrote ITS OWN handoff and finished successfully...
    assert handoff_files.newest_group(sd), "lane A's own compose must still have landed"
    # ...but the CURRENT pending record on disk still belongs to lane B: A's release call
    # (key=key_a) must have been a no-op against B's record (key=key_b).
    rec = json.loads((sd / ehc._PENDING_FILE).read_text(encoding="utf-8"))
    assert rec["key"] == key_b, "lane A's release must not have dropped lane B's own hold"
    assert ehc.summary_hold_active(sd, int(time.time())), "lane B's hold must still be armed"


def test_exit_6_no_digest_never_tries_llm_ext_fallback(tmp_path, monkeypatch, _isolated_env):
    """Owner review finding #2: exit 6 (`jev_compaction.NoDigest` -- neither a human message
    nor a TRDD STATE head exists) means there is nothing in the transcript worth summarizing
    either way. The lane must skip the llm-ext fallback entirely and write the template
    straight away, rather than spend the rest of the hold re-discovering the same "nothing to
    summarize" conclusion through a second, slower path."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    _stub_jev_compact(plugin_root, tmp_path / "argv.json", exit_code=jcl.EXIT_DECLINED_NO_DIGEST)
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    def _boom(*_a, **_kw):
        raise AssertionError("exit 6 (no digest) must never try the llm-ext fallback")

    monkeypatch.setattr(jcl, "_run_llm_ext_fallback", _boom)

    assert sps.main() == 0
    entries = _ledger_entries()
    assert any(e["code"] == "JEV-COMPACT-NO-DIGEST" for e in entries)
    sd = state.state_dir()
    text = handoff_files.newest_group(sd)[0].read_text(encoding="utf-8")
    assert text.lstrip().startswith(handoff_files.TEMPLATE_MARKER)
    assert not (sd / ehc._PENDING_FILE).is_file()


def test_exit_127_command_not_found_never_tries_llm_ext_fallback(
    tmp_path, monkeypatch, _isolated_env,
):
    """Owner review finding #2: exit 127 means `uv` is not on this session's PATH. Since
    `llm_ext_compact.py` is exec'd BY PATH with the IDENTICAL `uv run --script` shebang,
    trying the fallback would fail the same way for the same reason -- skip it and go
    straight to the template instead of burning the rest of the hold proving that twice."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    real_run = subprocess.run

    def _spy_run(cmd, **kwargs):
        if isinstance(cmd, (list, tuple)) and cmd and "jev_compact.py" in str(cmd[0]):
            return subprocess.CompletedProcess(cmd, 127, stdout="", stderr="uv: command not found")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", _spy_run)

    def _boom(*_a, **_kw):
        raise AssertionError("exit 127 (uv missing) must never try the llm-ext fallback")

    monkeypatch.setattr(jcl, "_run_llm_ext_fallback", _boom)

    assert sps.main() == 0
    entries = _ledger_entries()
    assert any(
        e["code"] == "JEV-COMPACT-FAILED" and "uv not on PATH" in e["msg"] for e in entries
    ), entries
    sd = state.state_dir()
    text = handoff_files.newest_group(sd)[0].read_text(encoding="utf-8")
    assert text.lstrip().startswith(handoff_files.TEMPLATE_MARKER)
    assert not (sd / ehc._PENDING_FILE).is_file()


def test_llm_ext_fallback_handoff_declares_itself_not_verbatim_jev_output(
    tmp_path, monkeypatch, _isolated_env,
):
    """Owner review finding #3: the llm-ext fallback's compacted-context block must say,
    before the model reads it as fact, that this is LLM-EXTERNALIZER-GENERATED PROSE -- not
    the real Jev-selected verbatim transcript items `ec.compose_handoff`'s own fixed header
    ("Jev compaction" / "chosen by Jev scoring") otherwise implies for every summary it
    renders, real Jev compose or not.

    TRDD-1ETALGDG followup: `summarize_previous_session.py` no longer prepends its OWN
    disclaimer text -- `ec.compose_handoff` now takes `source` and renders the TRUE header
    itself from `external_clear._COMPACTED_CONTEXT_HEADS` (owner review finding #3, fixed at
    the source instead of at every caller). This asserts THAT header's own wording survives
    into the written handoff, not the removed prepend."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    argv_log = tmp_path / "argv.jsonl"
    _stub_jev_compact_appending(plugin_root, argv_log, exit_code=jcl.EXIT_JEV_ERROR)
    _stub_llm_ext_compact(plugin_root, text="the fallback prose")
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))
    _write_probe_stamp(kind="auth", reason="401 invalid key")  # non-retryable -> fast fallback

    assert sps.main() == 0
    sd = state.state_dir()
    text = handoff_files.newest_group(sd)[0].read_text(encoding="utf-8")
    assert "llm-ext fallback: generated prose summary" in text
    assert "not jev-selected verbatim text" in text.lower()
    # The TRUE header must land BEFORE the real llm-ext text, not after -- it is meant to be
    # read first, functionally the block's header.
    assert text.index("llm-ext fallback: generated prose summary") < text.index("the fallback prose")


def test_lane_actually_retries_through_a_decline_gate_mimicking_stub(
    tmp_path, monkeypatch, _isolated_env,
):
    """Owner review finding #6(b): the OTHER attempt-count test's stub ignores `--no-decline`
    entirely, so counting invocations there cannot tell "the flag genuinely bypasses the real
    gate" apart from "the flag is present in argv but does nothing" -- both would produce the
    identical log. This stub mimics `jev_compact.py compact`'s OWN decline gate (exit 5 on a
    fresh `kind="unavailable"` stamp UNLESS `--no-decline` is given): more than one REAL
    attempt is only possible here if `--no-decline` genuinely reaches every retry, because a
    regression that dropped it would make every attempt after the first fast-decline (exit 5)
    against the very stamp the first attempt itself wrote."""
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    plugin_root = tmp_path / "plugin"
    argv_log = tmp_path / "argv.jsonl"
    stamp_path = global_state.control_dir() / "jev-probe.json"
    # A FRESH decline-worthy stamp already on disk BEFORE the first attempt: without
    # `--no-decline` threaded through, attempt 1 itself would fast-decline (exit 5) against
    # this pre-existing stamp, and `len(attempts) > 1` below would fail.
    _write_probe_stamp(ok=False, kind="unavailable", reason="pre-existing outage", ts=time.time())
    _stub_jev_compact_decline_gate(plugin_root, argv_log, stamp_path)
    _stub_llm_ext_compact(plugin_root, text="llm-ext fallback summary")
    monkeypatch.setattr(sps, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))
    clock = _fake_clock()

    rc = sps.main(now_fn=clock.time, sleep_fn=clock.sleep)
    assert rc == 0

    attempts = [
        json.loads(ln) for ln in argv_log.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    assert len(attempts) > 1, f"expected more than one real attempt, got {attempts}"

    # Every real attempt reached the "transient failure" branch (exit 7), never the decline
    # gate (exit 5) -- proven by the finding the lane recorded: a decline would have produced
    # the LOW-severity JEV-COMPACT-DECLINED code instead of the MEDIUM JEV-SCORER-UNAVAILABLE
    # one `handle_nonzero_exit` maps exit 7 + kind=unavailable to.
    entries = _ledger_entries()
    assert not any(e["code"] == "JEV-COMPACT-DECLINED" for e in entries), entries
    assert any(e["code"] == "JEV-SCORER-UNAVAILABLE" for e in entries), entries


_STUB_LLM_EXT_SPAWNS_CHILD = """#!/usr/bin/env python3
import subprocess
import sys
import time

pid_file = {pid_file!r}
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
with open(pid_file, "w") as f:
    f.write(str(child.pid))
time.sleep(120)
"""


def test_llm_ext_fallback_outer_timeout_kills_the_whole_process_group(tmp_path, monkeypatch):
    """Owner review finding #4: on the outer timeout, `_run_llm_ext_fallback` must kill the
    WHOLE process group (`os.killpg`), not just the immediate `llm_ext_compact.py` process --
    its own `uv run --script` shebang launches the real llm-ext binary as a CHILD of that
    process, and a lone `Popen.kill()` (or `subprocess.run`'s own default timeout handling)
    would leave it running past the hold's own deadline with nothing left to reap it. This
    stub stands in for that child by spawning one of its own and recording its pid, so the
    test can verify the WHOLE group -- not merely the direct child -- actually dies."""
    plugin_root = tmp_path / "plugin"
    script = plugin_root / "scripts" / "llm_ext_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    pid_file = tmp_path / "child.pid"
    script.write_text(
        _STUB_LLM_EXT_SPAWNS_CHILD.format(pid_file=str(pid_file)), encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    # Shrink both thresholds so the real outer subprocess timeout fires in ~1s instead of the
    # production 30s-attempt-floor / 15s-slack -- this test still exercises the REAL
    # `subprocess.Popen` + `communicate(timeout=...)` + `os.killpg` path, just on a fast clock.
    monkeypatch.setattr(jcl, "_MIN_JEV_ATTEMPT_S", 0.1)
    monkeypatch.setattr(jcl, "_LLM_EXT_OUTER_SLACK_S", 0.5)

    ok, detail = jcl._run_llm_ext_fallback(
        plugin_root, transcript="/tmp/x.jsonl", timeout_s=1.0,
    )
    assert ok is False
    assert "timed out" in detail

    for _ in range(50):
        if pid_file.is_file() and pid_file.read_text(encoding="utf-8").strip():
            break
        time.sleep(0.1)
    assert pid_file.is_file(), "the child never started -- the test setup itself is broken"
    child_pid = int(pid_file.read_text(encoding="utf-8").strip())

    import os

    for _ in range(30):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail(f"child pid {child_pid} still alive after the outer timeout's killpg")


def test_llm_ext_fallback_outer_timeout_reaps_the_group_leader(tmp_path, monkeypatch):
    """After the outer-timeout `os.killpg` + `proc.communicate(timeout=5)` path, the group
    leader `Popen` itself (the `llm_ext_compact.py` process, not the grandchild the previous
    test checks) must be REAPED, not left a zombie -- `killpg` only signals, it doesn't wait,
    so a fix that kills but never calls `.wait()`/`.communicate()` on the dead process leaves
    `poll()`/`returncode` unset. Wraps `subprocess.Popen` to capture the real instance
    `_run_llm_ext_fallback` creates, then asserts on it after the call returns."""
    plugin_root = tmp_path / "plugin"
    script = plugin_root / "scripts" / "llm_ext_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "#!/usr/bin/env python3\nimport time\ntime.sleep(120)\n", encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    monkeypatch.setattr(jcl, "_MIN_JEV_ATTEMPT_S", 0.1)
    monkeypatch.setattr(jcl, "_LLM_EXT_OUTER_SLACK_S", 0.5)

    captured: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def _capturing_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        captured.append(proc)
        return proc

    monkeypatch.setattr(jcl.subprocess, "Popen", _capturing_popen)

    ok, detail = jcl._run_llm_ext_fallback(
        plugin_root, transcript="/tmp/x.jsonl", timeout_s=1.0,
    )
    assert ok is False
    assert "timed out" in detail

    assert captured, "the stub Popen was never captured -- the test setup itself is broken"
    proc = captured[0]
    # Read `.returncode` directly -- NEVER call `.poll()`/`.wait()` here. Both would reap the
    # child THEMSELVES via their own `waitpid(WNOHANG)`, which would make the assertion pass
    # even if `_run_llm_ext_fallback`'s own reap were deleted entirely (review finding: a
    # `proc.poll()` call in the test is not a read, it's a second reap attempt that masks a
    # missing one inside the function under test). `.returncode` is a plain attribute Popen
    # only sets as a SIDE EFFECT of an internal `wait()`, so this only proves true when
    # `_run_llm_ext_fallback` reaped the child itself before returning.
    assert proc.returncode is not None, "group leader left a zombie: not reaped inside the fn"


def test_llm_ext_fallback_outer_timeout_on_windows_calls_proc_kill_not_killpg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """TRDD-1ETALGDG followup item 3: commit b0e94f43's `sys.platform == "win32"` branch in
    `_run_llm_ext_fallback` has never actually run on this project's (macOS/Linux) test/CI
    machines -- `os.killpg`/SIGKILL don't exist on Windows (no POSIX process groups), so that
    branch calls `proc.kill()` (`TerminateProcess`) on the direct child instead. Forces the
    branch by monkeypatching `sys.platform`, stubs `subprocess.Popen` so no real process is
    involved, and proves `proc.kill()` -- not `os.killpg` -- is what gets called."""
    monkeypatch.setattr(jcl.sys, "platform", "win32")

    calls = {"kill": 0, "killpg": 0}

    class _FakeProc:
        pid = 4242

        def __init__(self) -> None:
            self._communicate_calls = 0

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            self._communicate_calls += 1
            if self._communicate_calls == 1:
                # The OUTER `communicate(timeout=timeout_s + _LLM_EXT_OUTER_SLACK_S)` call --
                # simulates the subprocess never finishing in time. `timeout` is always given
                # a real float by the code under test; the `or 0.0` only satisfies mypy's
                # `TimeoutExpired(timeout: float)` signature for the `| None` default above.
                raise subprocess.TimeoutExpired(cmd="llm_ext_compact.py", timeout=timeout or 0.0)
            # The REAP call after the kill -- the (now-dead, in a real run) process returns
            # cleanly the second time.
            return "", ""

        def kill(self) -> None:
            calls["kill"] += 1

    def _fake_popen(*args, **kwargs):
        return _FakeProc()

    def _fake_killpg(pid, sig):
        calls["killpg"] += 1

    monkeypatch.setattr(jcl.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(jcl.os, "killpg", _fake_killpg)

    ok, detail = jcl._run_llm_ext_fallback(
        tmp_path, transcript="/tmp/x.jsonl", timeout_s=60.0,
    )

    assert calls["kill"] == 1, "expected proc.kill() (TerminateProcess) on the win32 branch"
    assert calls["killpg"] == 0, "os.killpg must never be reached on the win32 branch"
    assert ok is False
    assert "timed out" in detail
