"""Tests for scripts/summarize_previous_session.py's Jev-compaction wiring.

TRDD-RAEGS1D5 card 3 part C, commit C1 ("wire the compaction lane to jev_compact"). Covers:
the exact subprocess invocation (path + argv + timeout=120), the exit-code -> findings_ledger
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


# --- the subprocess invocation form itself -------------------------------------------------


def test_compact_invocation_form_and_timeout(tmp_path, monkeypatch, _isolated_env):
    """Exec by PATH (`PLUGIN_ROOT/scripts/jev_compact.py`), argv carries `compact --transcript
    <prev> --out <path> --session-key <key>` with no `--state-heads` flag when trddgrep is
    absent, and the call is made with `timeout=120`."""
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
    assert captured_kwargs.get("timeout") == 120
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


# --- exit 5/6/7 -> the findings ledger, and the hold is LEFT to expire ---------------------


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

    rc = sps.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "SUMMARY_FAILED" in out

    entries = _ledger_entries()
    assert any(e["code"] == expect_code and e["sev"] == expect_sev
               and expect_substr in e["msg"] for e in entries), entries

    # The hold is NEVER released on a non-zero exit -- it is left to expire onto the
    # mechanical fact-only template, today's (unchanged) degrade path.
    from external_handoff_clear import _PENDING_FILE  # noqa: PLC0415
    assert (state.state_dir() / _PENDING_FILE).is_file()


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

    assert sps.main() == 0
    entries = _ledger_entries()
    assert any(e["code"] == "JEV-COMPACT-FAILED" and "timeout" in e["msg"] for e in entries)


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


def test_consumed_pane_sidecar_skips_composing_regardless_of_age(tmp_path, monkeypatch,
                                                                   _isolated_env):
    """A `.consumed-*` sidecar means the dedicated hook already ran (or declined to a
    template) for this pane's clear -- skip even when the consumption is old, since the
    invariant is "one composer per transcript", not a time window."""
    monkeypatch.setenv("TMUX_PANE", "%9")
    pane_key = state.terminal_pane_key({"TMUX_PANE": "%9"})
    assert pane_key
    sd = state.state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    old_epoch = int(time.time()) - 10_000
    (sd / f"resume-after-clear.{pane_key}.transcript.consumed-{old_epoch}").write_text(
        f"/tmp/some-transcript.jsonl\n{old_epoch}\n", encoding="utf-8"
    )

    def _boom(*_a, **_kw):
        raise AssertionError("must not run jev_compact.py when this pane's sidecar is consumed")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(jcl, "previous_transcript", _boom)

    assert sps.main() == 0


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
