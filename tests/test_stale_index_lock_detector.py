"""The stale-index-lock detector — the only production caller of
`git_utils.clear_stale_index_lock` (janitor#245 follow-up).

Run as a SUBPROCESS with a real `git init`ed tmp repo — this exercises the
actual `ps` snapshot gathering + the real filesystem lock file, not a mocked
decision. Nothing here mocks `git_utils`'s own guards.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DETECTOR = ROOT / "scripts" / "detectors" / "stale-index-lock.py"


# A `ps -eo pid,ppid,etime,command` snapshot with NO git process running —
# makes the live-git guard deterministic regardless of what else is running
# on the host executing this test suite.
_PS_NO_GIT = (
    "  PID  PPID     ELAPSED COMMAND\n"
    "    1     0    10:00:00 /sbin/launchd\n"
    " 4242     1       05:12 /bin/zsh -i\n"
    " 9999  4242       00:03 uv run pytest -q\n"
)

# A snapshot WITH a live git process (e.g. a concurrent `git commit`), pid
# 5150 — used to prove the lock survives when the guard fires.
_PS_WITH_GIT = _PS_NO_GIT + " 5150  4242       00:01 git commit -m wip\n"


def _run(project: Path, *, ps_snapshot: str = _PS_NO_GIT) -> subprocess.CompletedProcess[str]:
    env = {
        # /usr/sbin is where macOS keeps `lsof` — required by both the new
        # G0 lock-holder probe (`git_utils._lock_is_held`) and the existing
        # cwd-resolution guard (`git_utils._pid_cwd`); Linux distros already
        # keep it on /usr/bin, covered below.
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin",
        "HOME": str(project / "home"),
        "CLAUDE_PROJECT_DIR": str(project),
        # Deterministic live-git guard: see JANITOR_PS_SNAPSHOT test seam in
        # scripts/detectors/stale-index-lock.py. Without this, a real `ps`
        # snapshot on a multi-session dev machine almost always contains
        # SOME `git` process, which used to make the (unscoped) guard refuse
        # removal forever — this is exactly the bug this test module exists
        # to catch, so the fixture must not accidentally paper over it.
        "JANITOR_PS_SNAPSHOT": ps_snapshot,
    }
    (project / "home").mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, str(DETECTOR)],
        capture_output=True,
        text=True,
        env=env,
        cwd=project,
    )


def _git_init(project: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)


def test_stale_lock_is_removed_and_reported(tmp_path: Path) -> None:
    """A lock older than the threshold, with no live git process holding it, is deleted and the
    detector prints one drift line naming the removal."""
    project = tmp_path / "repo"
    project.mkdir()
    _git_init(project)
    lock = project / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    stale_ts = time.time() - 3600
    import os

    os.utime(lock, (stale_ts, stale_ts))

    proc = _run(project)
    assert proc.returncode == 0, proc.stderr
    assert not lock.exists(), "the stale lock must be removed"
    assert "[stale-index-lock]" in proc.stdout
    assert "Removed a stale .git/index.lock" in proc.stdout
    stale_markers = list(lock.parent.glob("index.lock.stale-*"))
    assert len(stale_markers) == 1, "removal renames aside rather than unlinking outright"


def test_fresh_lock_is_left_alone_and_silent(tmp_path: Path) -> None:
    """A freshly-created lock (younger than the min-age threshold) is left in place, and the
    detector prints nothing — this is normal, in-progress git activity, not a finding."""
    project = tmp_path / "repo"
    project.mkdir()
    _git_init(project)
    lock = project / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")  # fresh mtime — just created

    proc = _run(project)
    assert proc.returncode == 0, proc.stderr
    assert lock.exists(), "a fresh lock must NOT be removed"
    assert proc.stdout.strip() == ""


def test_lock_survives_when_a_live_git_process_is_in_the_snapshot(tmp_path: Path) -> None:
    """An old, stale-looking lock is left in place when the injected `ps` snapshot shows a
    live `git` process — the live-git guard must still block removal via this seam."""
    project = tmp_path / "repo"
    project.mkdir()
    _git_init(project)
    lock = project / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    stale_ts = time.time() - 3600
    import os

    os.utime(lock, (stale_ts, stale_ts))

    proc = _run(project, ps_snapshot=_PS_WITH_GIT)
    assert proc.returncode == 0, proc.stderr
    assert lock.exists(), "a live git process in the snapshot must block removal"


def test_lock_held_open_by_a_process_is_left_alone_and_silent(tmp_path: Path) -> None:
    """A lock some process holds OPEN (this test process itself, standing in for a
    libgit2 GUI client with no `git` executable in the process table at all) is left
    alone and the detector prints nothing — the new G0 `_lock_is_held` probe, which
    checks the lock FILE itself rather than scanning for a `git` command."""
    project = tmp_path / "repo"
    project.mkdir()
    _git_init(project)
    lock = project / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    stale_ts = time.time() - 3600
    import os

    os.utime(lock, (stale_ts, stale_ts))

    fh = open(lock, "r", encoding="utf-8")
    try:
        proc = _run(project)
    finally:
        fh.close()
    assert proc.returncode == 0, proc.stderr
    assert lock.exists(), "a lock held open by ANY process must survive, ps-scan or not"
    assert proc.stdout.strip() == ""


def test_non_git_dir_is_a_silent_noop(tmp_path: Path) -> None:
    """A directory that is not a git repo at all: the detector exits 0 and prints nothing —
    never attempts to touch a `.git/index.lock` that cannot exist."""
    project = tmp_path / "not-a-repo"
    project.mkdir()

    proc = _run(project)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
