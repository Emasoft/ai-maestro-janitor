"""previous_transcript skips transcripts of sessions still live in ~/.claude/sessions (TRDD-LXUZYFD9)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import jev_compaction_lane as jcl  # noqa: E402
import memory_scopes  # noqa: E402
import state  # noqa: E402


def _dead_pid() -> int:
    """A pid that existed and is now reaped, so os.kill(pid, 0) raises."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _setup(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv("HOME", str(home))
    tdir = home / ".claude" / "projects" / memory_scopes.project_slug(str(root))
    tdir.mkdir(parents=True)
    sessions = home / ".claude" / "sessions"
    # The hook hands the owning claude pid down in JANITOR_CLAUDE_PID; here "own" is the test
    # process's parent, so a sessions file with os.getpid() is a different, live, sibling process.
    monkeypatch.setenv("JANITOR_CLAUDE_PID", str(os.getppid()))
    return root, tdir, sessions


def _transcript(tdir: Path, sid: str, mtime: int) -> Path:
    p = tdir / f"{sid}.jsonl"
    p.write_text("{}\n")
    os.utime(p, (mtime, mtime))
    return p


def _session_file(sessions: Path, pid: int, sid: str) -> None:
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f"{pid}.json").write_text(json.dumps({"pid": pid, "sessionId": sid}))


def test_live_sibling_transcript_is_skipped(tmp_path, monkeypatch):
    """A newer transcript whose session is live (alive pid, matching sessionId) is skipped."""
    root, tdir, sessions = _setup(tmp_path, monkeypatch)
    own = _transcript(tdir, "own-old", 1000)
    _transcript(tdir, "sibling-live", 2000)
    _session_file(sessions, os.getpid(), "sibling-live")
    assert jcl.previous_transcript(root, "current-new") == own


def test_dead_pid_does_not_skip(tmp_path, monkeypatch):
    """A sessions file whose pid is dead does not cause a skip."""
    root, tdir, sessions = _setup(tmp_path, monkeypatch)
    _transcript(tdir, "own-old", 1000)
    sib = _transcript(tdir, "sibling-dead", 2000)
    _session_file(sessions, _dead_pid(), "sibling-dead")
    assert jcl.previous_transcript(root, "current-new") == sib


def test_no_sessions_dir_keeps_newest_other(tmp_path, monkeypatch):
    """With no sessions directory the newest other transcript is chosen, as before."""
    root, tdir, _ = _setup(tmp_path, monkeypatch)
    _transcript(tdir, "own-old", 1000)
    newer = _transcript(tdir, "other", 2000)
    assert jcl.previous_transcript(root, "current-new") == newer


def test_own_pid_session_file_naming_cleared_session_is_not_skipped(tmp_path, monkeypatch):
    """After /clear the own process's sessions file may still name the cleared session: keep it."""
    root, tdir, sessions = _setup(tmp_path, monkeypatch)
    old = _transcript(tdir, "cleared-old", 2000)
    _transcript(tdir, "sibling-older", 1000)
    _session_file(sessions, os.getppid(), "cleared-old")
    assert jcl.previous_transcript(root, "current-new") == old


def test_unknown_own_pid_skips_nothing(tmp_path, monkeypatch):
    """With no own pid known, no live session is skipped (fail toward the old behaviour)."""
    root, tdir, sessions = _setup(tmp_path, monkeypatch)
    monkeypatch.delenv("JANITOR_CLAUDE_PID")
    _transcript(tdir, "own-old", 1000)
    live = _transcript(tdir, "sibling-live", 2000)
    _session_file(sessions, os.getpid(), "sibling-live")
    assert jcl.previous_transcript(root, "current-new") == live


def test_claude_ancestor_pid_walks_past_bash_and_uv():
    """claude -> bash -> uv -> python: the walk returns the claude pid, not the parent."""
    table = state.parse_ps_table(
        "  100     1 /usr/local/bin/claude --resume\n"
        "  200   100 bash /plugin/hooks/hook-run.sh\n"
        "  300   200 uv run --script hook.py\n"
        "  400   300 python hook.py\n"
    )
    assert state.claude_ancestor_pid(400, table) == 100


def test_claude_ancestor_pid_none_without_claude():
    """No claude executable among the ancestors (a flag merely mentioning it is not one): None."""
    table = state.parse_ps_table(
        "  100     1 /bin/zsh\n"
        "  200   100 vim --add-dir /src/claude-plugins\n"
        "  300   200 python hook.py\n"
    )
    assert state.claude_ancestor_pid(300, table) is None
