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
sys.stderr.write({stderr!r})
sys.exit({exit_code})
"""


def _stub_jev_compact(plugin_root: Path, argv_log: Path, *, exit_code: int, out_text: str = "",
                       stderr: str = "") -> None:
    """A fake `scripts/jev_compact.py` — records its own argv to `argv_log` and exits with a
    fixed code, standing in for the real (httpx/jevctx-dependent, network-touching) CLI. Runs
    as a REAL subprocess (git-tracked 100755 in production; chmod'd here the same way) so the
    exec-by-path invocation form itself is exercised, not just the Python call that builds it.
    """
    script = plugin_root / "scripts" / "jev_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        _STUB_JEV_COMPACT.format(argv_log=str(argv_log), out_text=out_text, exit_code=exit_code,
                                  stderr=stderr),
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
    """A simulated clock for `sps._now_fn`/`sps._sleep_fn` (TRDD-RAEGS1D5): `sleep()` just
    advances `now` by the requested duration instead of actually blocking, so a retry loop
    that would otherwise burn real minutes of wall-clock time (the owner's 5-minute Jev retry
    budget, `_TRANSIENT_RETRY_SLEEP_S` backoff) converges in milliseconds while still exercising
    the REAL number of loop iterations the production code would make. `jev_deadline` in
    `summarize_previous_session._main` is computed from `_now_fn()`, never a bare `time.time()`
    call, specifically so a faked clock and the retry loop's own budget check always agree."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _install_fake_clock(monkeypatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr(sps, "_now_fn", clock.time)
    monkeypatch.setattr(sps, "_sleep_fn", clock.sleep)
    return clock


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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))
    if stamp is not None:
        _write_probe_stamp(**stamp)
    # A transient/rate-limited kind retries inside the 5-minute budget -- the fake clock makes
    # those retries converge without any real sleeping (see `_FakeClock`'s own docstring).
    _install_fake_clock(monkeypatch)

    rc = sps.main()
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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))
    _write_probe_stamp(kind="rate_limited", reason="429", retry_after_s=42)
    _install_fake_clock(monkeypatch)

    assert sps.main() == 0
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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))
    _write_probe_stamp(kind="rate_limited", reason="429 no window given")
    _install_fake_clock(monkeypatch)

    assert sps.main() == 0
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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))
    _write_probe_stamp(kind="auth", reason="401 invalid key")

    from external_handoff_clear import _release_summary_hold  # noqa: PLC0415

    assert sps.main() == 0
    sd = state.state_dir()
    # Re-arm the hold as a second SessionStart would (the first run consumed it by declining,
    # which leaves it in place -- but a fresh call still needs a fresh transcript reachable).
    _release_summary_hold(sd)  # simulate the TTL having expired, cleaning up between "starts"
    assert sps.main() == 0

    entries = _ledger_entries()
    auth_hits = [e for e in entries if e["code"] == "JEV-AUTH-REJECTED"]
    assert len(auth_hits) == 1, f"expected exactly one dedup'd auth finding, got {auth_hits}"


def test_timeout_expired_is_a_high_bug_finding(tmp_path, monkeypatch, _isolated_env):
    project_dir = _isolated_env
    prev = _make_prev_transcript(project_dir)
    monkeypatch.setattr(jcl, "previous_transcript", lambda root, sid: prev)
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

    def _raise_timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 120))

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    # Every `subprocess.run` call times out, including the llm-ext fallback's own -- the fake
    # clock keeps the retry loop's real sleeps from actually happening.
    _install_fake_clock(monkeypatch)

    assert sps.main() == 0
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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))
    _write_probe_stamp(kind="unreachable", reason="DNS resolution failed")
    _install_fake_clock(monkeypatch)

    rc = sps.main()
    assert rc == 0

    attempts = [ln for ln in argv_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(attempts) > 1, f"expected more than one real jev_compact attempt, got {attempts}"
    for argv in (json.loads(ln) for ln in attempts):
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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))
    _write_probe_stamp(kind="auth", reason="401 invalid key")
    clock = _install_fake_clock(monkeypatch)
    start = clock.now

    assert sps.main() == 0

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))
    # retry_after_s (1000s) comfortably exceeds the whole default 300s retry budget.
    _write_probe_stamp(kind="rate_limited", reason="429", retry_after_s=1000)
    clock = _install_fake_clock(monkeypatch)
    start = clock.now

    assert sps.main() == 0

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

    real_run = subprocess.run
    jev_calls = {"n": 0}

    def _spy_run(cmd, **kwargs):
        if isinstance(cmd, (list, tuple)) and cmd and "jev_compact.py" in str(cmd[0]):
            jev_calls["n"] += 1
            if jev_calls["n"] > 1:
                raise AssertionError(
                    "jev_compact.py must be invoked at most once -- a timeout must not retry"
                )
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", _spy_run)
    _install_fake_clock(monkeypatch)

    rc = sps.main()

    assert rc == 0
    assert jev_calls["n"] == 1, "expected exactly one jev_compact attempt after a timeout"
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


def test_state_heads_written_for_in_flight_columns_only(tmp_path, monkeypatch, _isolated_env):
    project_dir = _isolated_env
    (project_dir / "design" / "tasks").mkdir(parents=True)
    _install_stub_trddgrep(tmp_path / "bin", monkeypatch)

    sd = state.state_dir()
    paths, unavailable, cards = jcl.state_head_paths(project_dir, sd)

    assert unavailable is False
    assert len(paths) == 1  # only the DEV card, never the BACKBURNER one
    text = Path(paths[0]).read_text(encoding="utf-8")
    assert "ABCDEF12" in Path(paths[0]).name
    assert "STATE" in text
    assert "fake state line for ABCDEF12" in text

    # `cards` reuses the SAME board dump -- (id, column, title), restricted to the in-flight
    # columns, so `HandoffInputs.cards` is never silently empty when real cards exist (review
    # finding on TRDD-RAEGS1D5 C1).
    assert cards == [("ABCDEF12", "dev", "A fake in-flight card")]


def test_state_heads_unavailable_when_trddgrep_absent(tmp_path, monkeypatch, _isolated_env):
    monkeypatch.setenv("PATH", "/nonexistent-bin-only")
    sd = state.state_dir()
    paths, unavailable, cards = jcl.state_head_paths(_isolated_env, sd)
    assert paths == []
    assert unavailable is True
    assert cards == []


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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

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
