"""SessionStart must record the ONE unambiguous observation that a `/clear` happened.

`/clear` has no hook of its own, but it re-enters SessionStart with `source=clear`.
`dispatch.py::_phase_clear_resume` gates on the `clear-observed.ts` stamp written here
instead of the mere presence of `resume-after-clear.flag`, because that flag is a
PRE-marker: `clear_trigger.py` writes it BEFORE firing `/clear`. Without this stamp the
phase cannot tell "the clear happened" from "the clear is still pending", and every
other resume phase used to eat the flag in that gap — stranding the fresh session with
no cue at all.

Isolation matches `test_session_start_rearm_guard.py`: $CLAUDE_PROJECT_DIR +
$JANITOR_GLOBAL_STATE_DIR + $HOME under tmp, and the two heavy best-effort filesystem
steps (rules install, lean-ctx allowlist) neutralized. The hook's real `main()` runs.
"""

from __future__ import annotations

import importlib.util as _u
import json
import sys
import time
from io import StringIO
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))


def _run_session_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, source: str
) -> Path:
    """Run the real SessionStart main() with a `source` payload; return the state dir."""
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_PROJECT_ROOT))

    for mod in ("global_state", "state"):
        sys.modules.pop(mod, None)
    import global_state as gs
    import state

    gs.init_global_state()

    monkeypatch.setattr("lib.rules_installer.install_rules", lambda _root: [])
    monkeypatch.setattr("lib.leanctx_allowlist.ensure_janitor_allowed", lambda: [])

    spec = _u.spec_from_file_location(
        "janitor_on_session_start_clear_observed",
        str(_PROJECT_ROOT / "scripts" / "hooks" / "on-session-start.py"),
    )
    assert spec is not None and spec.loader is not None
    hook = _u.module_from_spec(spec)
    spec.loader.exec_module(hook)

    payload = json.dumps({"source": source, "session_id": "sid-1", "transcript_path": ""})
    old_in, old_out = sys.stdin, sys.stdout
    sys.stdin = StringIO(payload)
    sys.stdout = StringIO()
    try:
        hook.main()
    finally:
        sys.stdin, sys.stdout = old_in, old_out
    return state.state_dir()


def test_a_clear_is_recorded_with_a_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """source=clear → `clear-observed.ts` holds a fresh epoch. This stamp is the ONLY
    thing that lets the post-clear resume fire, so its absence is a silent stall."""
    before = int(time.time())
    sd = _run_session_start(monkeypatch, tmp_path, source="clear")
    stamp = sd / "clear-observed.ts"
    assert stamp.is_file(), "SessionStart(source=clear) must record the observation"
    observed = int(stamp.read_text(encoding="utf-8").strip())
    assert before <= observed <= int(time.time()) + 1, f"stale/garbage epoch: {observed}"


@pytest.mark.parametrize("source", ["startup", "resume", "compact", "unknown-source", ""])
def test_no_other_source_is_mistaken_for_a_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    """Only a real `/clear` may arm the flag. A `compact` in particular restarts the
    hook in the SAME session, so treating it as a clear would consume the PRE-marker
    early — the exact bug this stamp exists to prevent, via a different door."""
    sd = _run_session_start(monkeypatch, tmp_path, source=source)
    assert not (sd / "clear-observed.ts").exists(), f"source={source!r} is not a /clear"
