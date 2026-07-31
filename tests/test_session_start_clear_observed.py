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

    # `state.state_dir()` and friends are @lru_cache'd for the PROCESS lifetime — correct
    # in production (one project per process), lethal here. The hook resolves its helpers
    # as `from lib import state`, which is a DIFFERENT module object from the bare `state`
    # this file re-imports, with its OWN caches: popping only the bare name leaves the
    # hook pinned to whichever project ran FIRST in this process. Symptom: every test after
    # the first writes into the first one's tmp dir, so a per-test assertion on a file both
    # fails and looks like the hook is broken. Clear BOTH modules' caches after the env is
    # set, so each test resolves its own dirs.
    # `lib.state` is looked up rather than imported: on the first test the hook has not
    # created it yet, and there is no stale cache to clear then anyway.
    for mod_obj in (state, sys.modules.get("lib.state")):
        for fn in ("project_root", "janitor_root", "state_dir", "log_dir"):
            clear = getattr(getattr(mod_obj, fn, None), "cache_clear", None)
            if clear is not None:
                clear()

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


def _diagnosis(sd: Path) -> str:
    """Why the stamp is missing, from the hook's own log — a wrong `source` and a failed
    write both leave no file, and the hook logs BOTH, so a full-suite-only failure is
    readable from the report instead of costing another 5-minute reproduce."""
    log = sd.parent / "logs" / "session-start.log"
    return (
        f"\n  state dir contents: {sorted(p.name for p in sd.glob('*')) if sd.is_dir() else 'MISSING'}"
        f"\n  session-start.log tail: {log.read_text(encoding='utf-8')[-600:] if log.is_file() else 'no log'}"
    )


def test_a_clear_is_recorded_with_a_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """source=clear → `clear-observed.ts` holds a fresh epoch. This stamp is the ONLY
    thing that lets the post-clear resume fire, so its absence is a silent stall."""
    before = int(time.time())
    sd = _run_session_start(monkeypatch, tmp_path, source="clear")
    stamp = sd / "clear-observed.ts"
    assert stamp.is_file(), (
        "SessionStart(source=clear) must record the observation" + _diagnosis(sd)
    )
    observed = int(stamp.read_text(encoding="utf-8").strip())
    assert before <= observed <= int(time.time()) + 1, f"stale/garbage epoch: {observed}"


@pytest.mark.parametrize("source", ["startup", "resume", "compact", "unknown-source", ""])
def test_no_other_source_is_mistaken_for_a_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    """Only a real `/clear` may arm the flag. A `compact` in particular restarts the
    hook in the SAME session, so treating it as a clear would consume the PRE-marker
    early — the exact bug this stamp exists to prevent, via a different door.

    The absence assertion alone would pass vacuously if `main()` never reached the branch,
    so it is paired with positive proof from the hook's own log that it parsed exactly this
    source — otherwise a hook that crashed on import would look like five passing tests."""
    sd = _run_session_start(monkeypatch, tmp_path, source=source)
    log = (sd.parent / "logs" / "session-start.log").read_text(encoding="utf-8")
    # The hook keeps whatever the payload carried, VERBATIM — only a MISSING `source` key
    # falls back to "startup", so an explicitly-empty one stays empty. Either way it is not
    # "clear", which is all this test needs.
    assert f"source={source}" in log, f"the hook did not reach the source branch{_diagnosis(sd)}"
    assert not (sd / "clear-observed.ts").exists(), f"source={source!r} is not a /clear"
