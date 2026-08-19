"""Filesystem-write faults must never break SessionStart (TRDD-LMLKF0JV).

`on-session-start.py` declares a file-wide invariant: no exception may propagate out of
the hook — a raise degrades every session boot on the machine. This is a REAL fault
injection, not a mock of the code under test: a read-only `CLAUDE_PROJECT_DIR` makes
every `mkdir`/`open(...,'w')`/`os.replace` under it raise `PermissionError`, including
inside `state.log_line()` itself (which calls `init_state()` and opens a log file for
append). Proven live before the fix: the bare `state.log_line("source=...")` call in
`main()` crashed the hook with an unhandled `PermissionError` and exit code 1, even
though the other writes in the file were already guarded — the diagnostic logger was
itself the unguarded write path. `_slog()` wraps every call site for exactly this reason.

Real subprocess, real filesystem permissions — no mocking of the hook's own code.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "scripts" / "hooks" / "on-session-start.py"

_EVENT = {
    "session_id": "test-session-write-faults",
    "source": "startup",
    "hook_event_name": "SessionStart",
}


def test_hook_survives_and_still_emits_context_when_project_dir_is_read_only(
    tmp_path: Path,
) -> None:
    """A read-only project dir faults every write under it; the hook must still exit 0
    and still print its session-start context line."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"ai-maestro-janitor@ai-maestro-plugins": True}}),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    # Make the project dir itself unwritable so `.janitor/` can never be created under
    # it — `mkdir`, `atomic_write`, and `log_line`'s own file-open all fault here.
    project.chmod(stat.S_IRUSR | stat.S_IXUSR)

    env = {
        **os.environ,
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(REPO),
        "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "global-state"),
        "CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED": "false",
        "CLAUDE_PLUGIN_OPTION_OS_KEEPALIVE_ENABLED": "false",
    }

    try:
        proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
            [sys.executable, str(HOOK)],
            input=json.dumps(_EVENT),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
        )
    finally:
        # Restore write perms so tmp_path teardown can actually delete the tree.
        project.chmod(stat.S_IRWXU)

    assert proc.returncode == 0, (
        f"hook must exit 0 even when every filesystem write faults; "
        f"got rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert "Traceback" not in proc.stderr, f"an exception escaped the hook:\n{proc.stderr}"
    # The hook's normal session-start payload (the /janitor-arm nudge) must still reach
    # stdout — a write fault must degrade logging/state, never the context it emits.
    assert "janitor" in proc.stdout.lower(), f"no session-start payload on stdout:\n{proc.stdout}"
