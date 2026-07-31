"""SessionStart must record the ONE unambiguous observation that a `/clear` happened.

`/clear` has no hook of its own, but it re-enters SessionStart with `source=clear`.
`dispatch.py::_phase_clear_resume` gates on the `clear-observed.ts` stamp written here
instead of the mere presence of `resume-after-clear.flag`, because that flag is a
PRE-marker: `clear_trigger.py` writes it BEFORE firing `/clear`. Without this stamp the
phase cannot tell "the clear happened" from "the clear is still pending", and every
other resume phase used to eat the flag in that gap — stranding the fresh session with
no cue at all.

The hook runs as a SUBPROCESS, the way Claude Code actually runs it (the same pattern as
`test_hooks_execute.py`). That is not merely more faithful — it is load-bearing. The
first cut of this file imported the hook in-process, and `state.state_dir()` and friends
are `@lru_cache`'d for the process lifetime (correct in production: one project per
process). The hook resolves its helpers as `from lib import state`, a DIFFERENT module
object from a bare `import state`, with its own caches — so an in-process test that
clears one leaves the hook pinned to whichever project ran FIRST in the pytest process.
Every later test then wrote into the first test's tmp dir, which reads exactly like "the
stamp is broken", passes in isolation, and fails only in the full suite. A subprocess has
no such shared state by construction.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "scripts" / "hooks" / "on-session-start.py"


def _run_session_start(tmp_path: Path, *, source: str) -> Path:
    """Run the SessionStart hook as Claude Code does; return the project's state dir."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    # The plugin must look installed, or scope detection short-circuits before the hook
    # reaches the branch under test.
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"ai-maestro-janitor@ai-maestro-plugins": True}}),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()

    env = {
        **os.environ,
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(REPO),
        "CLAUDE_PROJECT_DIR": str(project),
        # Never touch the real machine: no daemon spawn, no OS keepalive, no real
        # global state.
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "global-state"),
        "CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED": "false",
        "CLAUDE_PLUGIN_OPTION_OS_KEEPALIVE_ENABLED": "false",
    }

    proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, str(HOOK)],
        input=json.dumps(
            {"source": source, "session_id": "sid-1", "transcript_path": ""}
        ),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(project),
    )
    assert "Traceback" not in proc.stderr, (
        f"the hook crashed, so any assertion below would be vacuous:\n{proc.stderr[:2000]}"
    )
    return project / ".janitor" / "state"


def _diagnosis(sd: Path) -> str:
    """Why the stamp is missing, from the hook's own log — a wrong `source` and a failed
    write both leave no file, and the hook logs BOTH, so a full-suite-only failure is
    readable from the report instead of costing another 5-minute reproduce."""
    log = sd.parent / "logs" / "session-start.log"
    return (
        f"\n  state dir contents: {sorted(p.name for p in sd.glob('*')) if sd.is_dir() else 'MISSING'}"
        f"\n  session-start.log tail: {log.read_text(encoding='utf-8')[-600:] if log.is_file() else 'no log'}"
    )


def test_a_clear_is_recorded_with_a_timestamp(tmp_path: Path) -> None:
    """source=clear → `clear-observed.ts` holds a fresh epoch. This stamp is the ONLY
    thing that lets the post-clear resume fire, so its absence is a silent stall."""
    before = int(time.time())
    sd = _run_session_start(tmp_path, source="clear")
    stamp = sd / "clear-observed.ts"
    assert stamp.is_file(), (
        "SessionStart(source=clear) must record the observation" + _diagnosis(sd)
    )
    observed = int(stamp.read_text(encoding="utf-8").strip())
    assert before <= observed <= int(time.time()) + 1, f"stale/garbage epoch: {observed}"


@pytest.mark.parametrize("source", ["startup", "resume", "compact", "unknown-source", ""])
def test_no_other_source_is_mistaken_for_a_clear(tmp_path: Path, source: str) -> None:
    """Only a real `/clear` may arm the flag. A `compact` in particular restarts the
    hook in the SAME session, so treating it as a clear would consume the PRE-marker
    early — the exact bug this stamp exists to prevent, via a different door.

    The absence assertion alone would pass vacuously if the hook never reached the
    branch, so it is paired with positive proof from the hook's own log that it parsed
    exactly this source — otherwise a hook that died on import would look like five
    passing tests."""
    sd = _run_session_start(tmp_path, source=source)
    log = (sd.parent / "logs" / "session-start.log").read_text(encoding="utf-8")
    # The hook keeps whatever the payload carried, VERBATIM — only a MISSING `source` key
    # falls back to "startup", so an explicitly-empty one stays empty. Either way it is
    # not "clear", which is all this test needs.
    assert f"source={source}" in log, f"the hook did not reach the source branch{_diagnosis(sd)}"
    assert not (sd / "clear-observed.ts").exists(), f"source={source!r} is not a /clear"
