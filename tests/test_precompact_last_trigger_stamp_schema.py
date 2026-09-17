"""PreCompact `precompact-last-trigger.json` schema parity (TRDD-YM65RCZA item 1).

`pre-compact-handoff.py::main` is the REAL writer of `precompact-last-trigger.json` (the stamp
`terminal_trigger.read_landed_stamp(path, "json_written_at")` reads to decide whether a
compaction landed while a verified send was in flight — see that function's own docstring).
Until now only a HAND-BUILT JSON blob was ever fed to the reader
(`tests/test_terminal_trigger.py`), so a schema drift in the real writer (a renamed field, a
string instead of a float `written_at`) could pass every existing test while breaking the guard
in production. This runs the real writer end-to-end and reads its output back through the real
reader, no mocks on either side."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import terminal_trigger  # noqa: E402

_HOOK_PATH = _PROJECT_ROOT / "scripts" / "hooks" / "pre-compact-handoff.py"


def _init_git_repo(root: Path) -> None:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    run = lambda *a: subprocess.run(  # noqa: E731 - terse test helper
        ["git", *a], cwd=str(root), env=env, capture_output=True, text=True, check=True
    )
    run("init", "-q")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    run("add", "README.md")
    run("commit", "-q", "-m", "initial commit")


def test_read_landed_stamp_parses_the_real_writers_output(tmp_path: Path) -> None:
    """Run the REAL `pre-compact-handoff.py` writer against a tmp project, then assert
    `terminal_trigger.read_landed_stamp(path, "json_written_at")` returns the exact
    `written_at` epoch float that writer put on disk — end to end, no hand-built JSON."""
    project = tmp_path / "project"
    project.mkdir()
    _init_git_repo(project)

    before = time.time()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "CLAUDE_PLUGIN_ROOT": str(_PROJECT_ROOT),
        "CLAUDE_PROJECT_DIR": str(project),
    }
    payload = json.dumps(
        {
            "session_id": "sess-schema-1",
            "cwd": str(project),
            "transcript_path": "",
            "trigger": "manual",
            "hook_event_name": "PreCompact",
        }
    )
    proc = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    after = time.time()
    assert proc.returncode == 0, f"hook must always exit 0; stderr={proc.stderr!r}"

    stamp_path = project / ".janitor" / "state" / "precompact-last-trigger.json"
    assert stamp_path.exists(), f"stamp not written; stderr={proc.stderr!r}"
    on_disk = json.loads(stamp_path.read_text(encoding="utf-8"))
    written_at = on_disk["written_at"]

    got = terminal_trigger.read_landed_stamp(stamp_path, "json_written_at")
    assert got == written_at, "reader must parse the exact value the real writer wrote"
    assert isinstance(got, float) and got > 0.0
    assert before <= got <= after, "written_at must be a real wall-clock epoch, not a placeholder"
