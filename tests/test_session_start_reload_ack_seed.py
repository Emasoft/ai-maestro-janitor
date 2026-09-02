"""SessionStart seeds `reload-acked.ts` for every FRESH-PROCESS source, `clear` included.

janitor#290 §1 / TRDD-38PB1B86: the seed tuple covered startup/resume/fork but not `clear`,
so every `/clear`-born session read an absent stamp as generation 0 and paid one spurious
`[janitor-reload]`. These tests run the real hook in a sandbox HOME/project and assert the
OUTCOME on disk — the stamp's presence and value — never the tuple's spelling.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "scripts" / "hooks" / "on-session-start.py"
GENERATION = "1700000000"


def _run_hook(tmp_path: Path, source: str) -> Path:
    """Run on-session-start.py with the given SessionStart `source`; return the project's state dir."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"ai-maestro-janitor@ai-maestro-plugins": True}}),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    global_state = tmp_path / "global-state"
    global_state.mkdir()
    # The daemon's reload generation is max(flag epoch, server epoch); a flag alone is enough
    # to make the seeded value non-trivial, so a stamp of "0" cannot pass as a seed.
    (global_state / "reload-needed.flag").write_text(GENERATION, encoding="utf-8")
    env = {
        **os.environ,
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(REPO),
        "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(global_state),
        "CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED": "false",
        "CLAUDE_PLUGIN_OPTION_OS_KEEPALIVE_ENABLED": "false",
    }
    subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, str(HOOK)],
        input=json.dumps(
            {
                "session_id": "test-session-reload-ack-seed",
                "source": source,
                "hook_event_name": "SessionStart",
                "transcript_path": "/nonexistent/transcript.jsonl",
            }
        ),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(project),
    )
    return project / ".janitor" / "state"


@pytest.mark.parametrize("source", ["startup", "resume", "fork", "clear"])
def test_fresh_process_source_seeds_the_reload_ack(tmp_path: Path, source: str) -> None:
    """Every fresh-process SessionStart source — clear included — seeds reload-acked.ts to the current generation."""
    state_dir = _run_hook(tmp_path, source)
    stamp = state_dir / "reload-acked.ts"
    assert stamp.is_file(), f"source={source!r} did not seed reload-acked.ts (janitor#290 §1 class)"
    assert stamp.read_text(encoding="utf-8").strip() == GENERATION


def test_non_fresh_source_does_not_seed(tmp_path: Path) -> None:
    """A source that is not a fresh process (compact) must NOT seed — the seed marks 'already on current plugins'."""
    state_dir = _run_hook(tmp_path, "compact")
    assert not (state_dir / "reload-acked.ts").exists()
