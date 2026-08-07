"""Tests for the publish-lock guard: publish.py's lock helpers + the companion
PreToolUse hook (scripts/hooks/pre-tool-publish-lock.py).

The hook is invoked as a real subprocess (no mocks): env + stdin payload +
an on-disk `.janitor/state/publish-in-progress.json` lock file -> JSON on
stdout. publish.py's lock helpers are imported directly and exercised
in-process.
"""

from __future__ import annotations

import importlib.util as _u
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK_PATH = _PROJECT_ROOT / "scripts" / "hooks" / "pre-tool-publish-lock.py"
_PUBLISH_PATH = _PROJECT_ROOT / "scripts" / "publish.py"


def _import_module(path: Path, name: str):
    spec = _u.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_hook(payload: dict, *, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", "")}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _init_repo(tmp_path: Path) -> Path:
    """A minimal fake git repo (just needs a `.git` dir for `_repo_root_for`)."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    return repo


def _write_lock(repo: Path, *, pid: int, started: float) -> Path:
    lock_dir = repo / ".janitor" / "state"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "publish-in-progress.json"
    lock_path.write_text(json.dumps({"pid": pid, "started": started, "repo": str(repo)}), encoding="utf-8")
    return lock_path


def _payload(tool: str, file_path: str) -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": file_path}}


def _is_deny(proc: subprocess.CompletedProcess) -> bool:
    if not proc.stdout.strip():
        return False
    data = json.loads(proc.stdout)
    return data.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


# ---------- hook: DENY cases -------------------------------------------------


def test_live_lock_in_same_repo_denies_edit(tmp_path: Path) -> None:
    """A live publish lock in the target's own repo must DENY, naming publish in the reason."""
    repo = _init_repo(tmp_path)
    _write_lock(repo, pid=os.getpid(), started=time.time())
    target = repo / "scripts" / "foo.py"
    target.parent.mkdir(parents=True)
    target.write_text("x = 1\n", encoding="utf-8")

    proc = _run_hook(_payload("Edit", str(target)))

    assert proc.returncode == 0
    assert _is_deny(proc)
    reason = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "publish" in reason.lower()


# ---------- hook: ALLOW cases -------------------------------------------------


def test_dead_pid_allows(tmp_path: Path) -> None:
    """A lock naming a pid that is not running must ALLOW (stale/crashed publish)."""
    repo = _init_repo(tmp_path)
    # A pid essentially guaranteed not to be running.
    _write_lock(repo, pid=2**30 - 1, started=time.time())
    target = repo / "file.py"
    target.write_text("x = 1\n", encoding="utf-8")

    proc = _run_hook(_payload("Edit", str(target)))

    assert proc.returncode == 0
    assert not _is_deny(proc)
    assert proc.stdout.strip() == ""


def test_stale_lock_allows(tmp_path: Path) -> None:
    """A lock older than the staleness cap must ALLOW even with a live pid."""
    repo = _init_repo(tmp_path)
    _write_lock(repo, pid=os.getpid(), started=time.time() - 999999)
    target = repo / "file.py"
    target.write_text("x = 1\n", encoding="utf-8")

    proc = _run_hook(_payload("Edit", str(target)), extra_env={"CLAUDE_PLUGIN_OPTION_PUBLISH_LOCK_MAX_AGE_S": "60"})

    assert proc.returncode == 0
    assert not _is_deny(proc)


def test_no_lock_file_allows(tmp_path: Path) -> None:
    """No lock file at all must ALLOW."""
    repo = _init_repo(tmp_path)
    target = repo / "file.py"
    target.write_text("x = 1\n", encoding="utf-8")

    proc = _run_hook(_payload("Edit", str(target)))

    assert proc.returncode == 0
    assert not _is_deny(proc)


def test_malformed_lock_json_allows(tmp_path: Path) -> None:
    """A truncated/unparseable lock file must fail open (ALLOW), never crash-block."""
    repo = _init_repo(tmp_path)
    lock_dir = repo / ".janitor" / "state"
    lock_dir.mkdir(parents=True)
    (lock_dir / "publish-in-progress.json").write_text("{not json", encoding="utf-8")
    target = repo / "file.py"
    target.write_text("x = 1\n", encoding="utf-8")

    proc = _run_hook(_payload("Edit", str(target)))

    assert proc.returncode == 0
    assert not _is_deny(proc)


def test_different_repo_allows(tmp_path: Path) -> None:
    """A live lock in repo A must not deny an edit in an unrelated repo B."""
    repo_a = _init_repo(tmp_path / "a")
    repo_a.mkdir(parents=True, exist_ok=True)
    _write_lock(repo_a, pid=os.getpid(), started=time.time())

    repo_b = _init_repo(tmp_path / "b")
    target = repo_b / "file.py"
    target.write_text("x = 1\n", encoding="utf-8")

    proc = _run_hook(_payload("Edit", str(target)))

    assert proc.returncode == 0
    assert not _is_deny(proc)


def test_noncovered_tool_allows(tmp_path: Path) -> None:
    """A tool outside {Edit, Write, MultiEdit, NotebookEdit} (e.g. Read) must ALLOW."""
    repo = _init_repo(tmp_path)
    _write_lock(repo, pid=os.getpid(), started=time.time())
    target = repo / "file.py"
    target.write_text("x = 1\n", encoding="utf-8")

    proc = _run_hook({"tool_name": "Read", "tool_input": {"file_path": str(target)}})

    assert proc.returncode == 0
    assert not _is_deny(proc)
    assert proc.stdout.strip() == ""


# ---------- publish.py: lock helpers -----------------------------------------


@pytest.fixture()
def publish_mod():
    return _import_module(_PUBLISH_PATH, "publish_under_test_lock")


def test_acquire_and_release_publish_lock(tmp_path: Path, publish_mod) -> None:
    """acquire() creates the lock file with pid/started/repo; release() removes it;
    the lock path stays inside the gitignored `.janitor/` dir the whole time."""
    repo = tmp_path / "repo"
    repo.mkdir()

    lock_path = publish_mod._acquire_publish_lock(repo)
    assert lock_path is not None
    assert lock_path.is_file()
    assert lock_path == repo / ".janitor" / "state" / "publish-in-progress.json"

    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()
    assert payload["repo"] == str(repo)
    assert isinstance(payload["started"], int)

    publish_mod._release_publish_lock(lock_path)
    assert not lock_path.exists()


def test_reassert_rearms_a_lock_the_test_gate_deleted(tmp_path: Path, publish_mod) -> None:
    """The test gate runs arbitrary plugin test code with write access to the repo, and one
    of its tests really did delete this lock — disarming the guard for the remaining ~10
    minutes of every publish. Re-assert must notice and re-arm."""
    repo = tmp_path / "repo"
    repo.mkdir()
    lock_path = publish_mod._acquire_publish_lock(repo)
    lock_path.unlink()

    live = publish_mod._reassert_publish_lock(repo, lock_path)

    assert live is not None and live.is_file()
    assert json.loads(live.read_text(encoding="utf-8"))["pid"] == os.getpid()


def test_reassert_rearms_a_lock_another_process_overwrote(tmp_path: Path, publish_mod) -> None:
    """A lock naming someone else's pid is not ours — our guard is disarmed just as surely
    as if it were gone, because the companion hook checks THAT pid's liveness, not ours."""
    repo = tmp_path / "repo"
    repo.mkdir()
    lock_path = publish_mod._acquire_publish_lock(repo)
    lock_path.write_text(json.dumps({"pid": 2**30 - 1, "started": time.time()}), encoding="utf-8")

    live = publish_mod._reassert_publish_lock(repo, lock_path)

    assert json.loads(live.read_text(encoding="utf-8"))["pid"] == os.getpid()


def test_reassert_leaves_an_intact_lock_untouched(tmp_path: Path, publish_mod) -> None:
    """The healthy path must not rewrite the lock — a needless rewrite is churn, and the
    warning it would print teaches the reader to ignore a real one."""
    repo = tmp_path / "repo"
    repo.mkdir()
    lock_path = publish_mod._acquire_publish_lock(repo)
    before = lock_path.stat().st_mtime_ns

    live = publish_mod._reassert_publish_lock(repo, lock_path)

    assert live == lock_path
    assert lock_path.stat().st_mtime_ns == before


def test_reassert_is_a_noop_when_the_lock_was_never_acquired(tmp_path: Path, publish_mod) -> None:
    """Acquisition failure is already non-fatal (it warns and returns None). Re-assert must
    not resurrect a lock the run deliberately proceeded without."""
    assert publish_mod._reassert_publish_lock(tmp_path, None) is None


def test_publish_lock_path_is_gitignored(publish_mod) -> None:
    """The lock file must never dirty the tree — `.janitor/` is gitignored repo-wide.

    Asks git about the PATH and never creates it. The first version of this test wrote a
    lock file at the REAL repo root and unlinked it in a finally — which meant that every
    `publish.py` run, whose test gate runs this suite, clobbered and then DELETED the live
    lock it had just taken, disarming the guard for the rest of its own publish. `git
    check-ignore` answers on a path that does not exist, so there is nothing to create.
    """
    lock_path = publish_mod._publish_lock_path(_PROJECT_ROOT)
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(lock_path)],
        cwd=_PROJECT_ROOT,
        timeout=10,
    )
    assert result.returncode == 0
