"""TRDD-W6DZPXLG box 1: the post-clear hook records which session succeeded the cleared one.

`on-session-start-post-clear-compact.py` is the only place that holds both ids of a clear: the
cleared transcript (from the pane sidecar) and the new session id (from the SessionStart
payload). It writes `clear-successor-<old key>.txt` so `dispatch._phase_late_summary_drift`
can hand the late-summary cue to the successor only. The hook runs in-process, as in
`tests/test_on_session_start_post_clear_compact.py`; the Jev compose script is a stub, so no
network call happens.
"""

from __future__ import annotations

import contextlib
import importlib.util as _u
import io
import stat
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "on-session-start-post-clear-compact.py"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import jev_compaction_lane as jcl  # noqa: E402
import state  # noqa: E402

_OLD_SID = "cafebabe-abcd-4ef0-8abc-abcdefabcdef"
_OLD_KEY = "cafebabe"
_NEW_SID = "fedcbafe-abcd-4ef0-8abc-abcdefabcdef"

_STUB = """#!/usr/bin/env python3
import sys
from pathlib import Path
argv = sys.argv
for flag in ("--out", "--inject-out"):
    if flag in argv:
        Path(argv[argv.index(flag) + 1]).write_text("# Compacted context\\nsome text\\n", encoding="utf-8")
"""


def _run_hook(tmp_path: Path, monkeypatch, *, sidecar_age_s: int, late_landing: bool = False, keep_env: bool = False) -> Path:
    """Run the hook once for a clear of `_OLD_SID` into `_NEW_SID`; return the state dir."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    if not keep_env:
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("TMUX_PANE", "%4")
    for fn in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        fn.cache_clear()
    script = plugin_root / "scripts" / "jev_compact.py"
    script.parent.mkdir(parents=True)
    script.write_text(_STUB, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    transcript = tmp_path / f"{_OLD_SID}.jsonl"
    transcript.write_text('{"message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    sd.mkdir(parents=True)
    pane_key = state.terminal_pane_key({"TMUX_PANE": "%4"})
    epoch = int(time.time()) - sidecar_age_s
    (sd / f"resume-after-clear.{pane_key}.transcript").write_text(f"{transcript}\n{epoch}\n", encoding="utf-8")
    if late_landing:
        # The chain's leftover flag and a `.ts` equal to the sidecar epoch: `_late_landing_allowed`.
        (sd / "resume-after-clear.flag").write_text("continue", encoding="utf-8")
        (sd / "resume-after-clear.ts").write_text(str(epoch), encoding="utf-8")

    spec = _u.spec_from_file_location("post_clear_hook_successor_under_test", str(_HOOK))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear", "session_id": _NEW_SID})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))
    with contextlib.redirect_stdout(io.StringIO()):
        assert mod.main() == 0
    return sd


def test_a_fresh_sidecar_records_the_new_session_as_the_cleared_ones_successor(tmp_path, monkeypatch) -> None:
    """A fresh sidecar writes `clear-successor-<old key>.txt` holding the payload session id."""
    sd = _run_hook(tmp_path, monkeypatch, sidecar_age_s=0)
    record = sd / f"clear-successor-{_OLD_KEY}.txt"
    assert record.is_file(), sorted(p.name for p in sd.iterdir())
    assert record.read_text(encoding="utf-8").strip() == _NEW_SID


def test_a_stale_sidecar_records_no_successor(tmp_path, monkeypatch) -> None:
    """A sidecar past the 300 s window is not this clear's: it must leave no successor record."""
    sd = _run_hook(tmp_path, monkeypatch, sidecar_age_s=10_000)
    assert list(sd.glob("clear-successor-*.txt")) == []


def test_a_late_landing_sidecar_still_records_the_successor(tmp_path, monkeypatch) -> None:
    """A 600 s-old sidecar the chain's flag and matching `.ts` vouch for is used, so it records too."""
    sd = _run_hook(tmp_path, monkeypatch, sidecar_age_s=600, late_landing=True)
    record = sd / f"clear-successor-{_OLD_KEY}.txt"
    assert record.read_text(encoding="utf-8").strip() == _NEW_SID


def test_the_hook_logs_whether_the_payload_id_matches_the_env_session_id(tmp_path, monkeypatch) -> None:
    """The hook logs the payload-vs-CLAUDE_CODE_SESSION_ID comparison (a boolean, never the ids)."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _NEW_SID)
    _run_hook(tmp_path, monkeypatch, sidecar_age_s=0, keep_env=True)
    log = (state.log_dir() / "jev-post-clear-hook.log").read_text(encoding="utf-8")
    assert "payload id matches CLAUDE_CODE_SESSION_ID: True" in log, log


def test_the_hook_record_round_trips_through_the_dispatch_phase(tmp_path, monkeypatch, capsys) -> None:
    """Round trip only: the id the hook stores, set as CLAUDE_CODE_SESSION_ID, makes the phase fire the cue.
    It does NOT show that a live SessionStart payload id equals the live env id (unproven; one measured clear)."""
    sd = _run_hook(tmp_path, monkeypatch, sidecar_age_s=0)
    (sd / f"late-summary-noted-{_OLD_KEY}.txt").write_text("\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _NEW_SID)
    spec = _u.spec_from_file_location("dispatch_successor_under_test", str(_PROJECT_ROOT / "scripts" / "dispatch.py"))
    assert spec is not None and spec.loader is not None
    dispatch = _u.module_from_spec(spec)
    spec.loader.exec_module(dispatch)
    capsys.readouterr()
    dispatch._phase_late_summary_drift()
    out = capsys.readouterr().out
    assert "[janitor-resume]" in out and "a fuller summary of the cleared session" in out, out
