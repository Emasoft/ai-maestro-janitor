"""The write sandbox must BLOCK any test writing outside its boundaries (TRDD-RYZCVVKA, S1e).

These are the positive controls for the guard itself. A guard that never fires is
indistinguishable from a guard that is broken, and this suite already shipped two
"isolation" layers that were silently escaped for months — so the sandbox does not get to
be trusted on its docstring.

Each test below reproduces a REAL mechanism of the 2026-07-11 incident, in which the repo's
whole daemon closure was overwritten with the installed plugin's v0.39.0 copies:
  * `os.replace` — how `keepalive_stage.stage_closure` lands each file (tmp + atomic rename).
  * `os.chmod`   — how the exec bits died (a fresh tmp file at the 0644 umask).
  * a plain `open(..., "w")` into the real ~/.claude tree — how 296 lines of test output
    leaked into the REAL keepalive boot log.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from conftest import (  # type: ignore[import-not-found]
    _REAL_HOME_AT_IMPORT,
    _REPO_ROOT,
    SandboxViolation,
)

# Targets that must be unwritable. They are never created — the guard raises first; if it
# ever does NOT raise, the test fails loudly rather than actually writing these paths.
REAL_CLAUDE_FILE = _REAL_HOME_AT_IMPORT / ".claude" / "sandbox-probe-must-never-exist.txt"
REPO_SOURCE_FILE = _REPO_ROOT / "scripts" / "sandbox-probe-must-never-exist.py"
REPO_DAEMON = _REPO_ROOT / "scripts" / "daemon.py"


def test_open_write_into_real_claude_tree_is_blocked() -> None:
    """Writing into the user's live ~/.claude tree is refused (the real-boot-log leak)."""
    with pytest.raises(SandboxViolation):
        with open(REAL_CLAUDE_FILE, "w", encoding="utf-8") as fh:
            fh.write("this must never reach disk")
    assert not REAL_CLAUDE_FILE.exists(), "the guard raised but the file was still created"


def test_open_write_into_repo_source_is_blocked() -> None:
    """Writing into the repo's scripts/ source tree is refused."""
    with pytest.raises(SandboxViolation):
        with open(REPO_SOURCE_FILE, "w", encoding="utf-8") as fh:
            fh.write("# must never reach disk")
    assert not REPO_SOURCE_FILE.exists(), "the guard raised but the file was still created"


def test_pathlib_write_text_into_repo_source_is_blocked() -> None:
    """pathlib bottoms out in builtins.open, so Path.write_text is covered by the same choke point."""
    with pytest.raises(SandboxViolation):
        REPO_SOURCE_FILE.write_text("# must never reach disk", encoding="utf-8")
    assert not REPO_SOURCE_FILE.exists()


def test_os_replace_over_repo_source_is_blocked(tmp_path: Path) -> None:
    """THE clobber mechanism: stage_closure lands each file with tmp + os.replace(). The
    DESTINATION is what gets destroyed, so that is the argument the guard must police."""
    staged = tmp_path / "daemon.py"
    staged.write_text("# the installed v0.39.0 copy\n", encoding="utf-8")
    before = REPO_DAEMON.read_bytes()

    with pytest.raises(SandboxViolation):
        os.replace(staged, REPO_DAEMON)

    assert REPO_DAEMON.read_bytes() == before, "the repo's daemon.py was overwritten"


def test_os_chmod_on_repo_source_is_blocked() -> None:
    """The clobber's most damaging side effect was a CLEARED EXEC BIT (100755 -> 100644) — no
    content manifest would flag that, so the guard polices chmod too."""
    before = REPO_DAEMON.stat().st_mode
    with pytest.raises(SandboxViolation):
        os.chmod(REPO_DAEMON, 0o644)
    assert REPO_DAEMON.stat().st_mode == before, "the repo's exec bit was changed"


def test_os_unlink_of_repo_source_is_blocked() -> None:
    """Deletion is a write. A test may not remove repo source."""
    with pytest.raises(SandboxViolation):
        os.unlink(REPO_DAEMON)
    assert REPO_DAEMON.exists(), "the repo's daemon.py was deleted"


def test_shutil_rmtree_of_repo_source_is_blocked() -> None:
    """rmtree deletes children with fd-relative syscalls, which never reach the os.* guards —
    so it must be blocked at its ENTRY POINT or an entire protected tree could vanish."""
    with pytest.raises(SandboxViolation):
        shutil.rmtree(_REPO_ROOT / "scripts")
    assert REPO_DAEMON.exists(), "the repo's scripts/ tree was deleted"


def test_temporary_directory_cleanup_is_not_blocked() -> None:
    """The fd-relative skip must not misfire: TemporaryDirectory's cleanup calls
    `os.rmdir("design", dir_fd=...)` with a BARE name. Resolving that against the cwd made a
    tmp cleanup look like an attack on the real repo's design/ and failed 68 innocent tests."""
    with TemporaryDirectory() as tmp:
        nested = Path(tmp) / "design" / "tasks"
        nested.mkdir(parents=True)
        (nested / "TRDD-probe.md").write_text("column: dev\n", encoding="utf-8")
    assert not Path(tmp).exists(), "the tmp tree should have been cleaned up normally"


def test_reads_of_protected_paths_still_work() -> None:
    """The sandbox polices WRITES only — the suite legitimately reads its own source."""
    body = REPO_DAEMON.read_text(encoding="utf-8")
    assert body.startswith("#!"), "daemon.py must still open with its shebang"
    assert "def main(" in body, "daemon.py must still hold its real source"


def test_tmp_writes_are_allowed(tmp_path: Path) -> None:
    """A test writing inside its own boundary is untouched (no over-blocking)."""
    target = tmp_path / "nested" / "ok.txt"
    target.parent.mkdir(parents=True)
    target.write_text("fine", encoding="utf-8")
    os.chmod(target, 0o600)
    assert target.read_text(encoding="utf-8") == "fine"


def test_isolated_janitor_state_writes_are_allowed() -> None:
    """The session-default fake HOME / DATA / global-state dirs are writable — the sandbox
    blocks the REAL tree, not the isolated one the suite is supposed to use."""
    gsd = Path(os.environ["JANITOR_GLOBAL_STATE_DIR"])
    probe = gsd / "sandbox-allows-isolated-writes.flag"
    probe.write_text("ok", encoding="utf-8")
    assert probe.read_text(encoding="utf-8") == "ok"
    assert _REAL_HOME_AT_IMPORT not in probe.parents, "the isolated dir must not be the real HOME"
