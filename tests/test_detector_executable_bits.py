"""Guard: every detector + runnable shebang script is EXECUTABLE in git.

CI's Smoke job runs each detector as `./scripts/detectors/<name>.py --one-shot`
(via the shebang), and the heartbeat's `_run_detector` skips any script that
fails `os.access(..., X_OK)`. So a detector committed without the +x bit (git
mode 100644) BOTH fails CI with exit 126 AND is silently skipped at runtime —
exactly what happened to janitor-install-scope.py (created via an editor that
doesn't set +x). The local test suite missed it because the detector tests
invoke `[sys.executable, detector]` (explicit python — mode-agnostic). This
test closes that gap by asserting the GIT mode (what CI checks out), not just
the working-tree bit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _git_mode_644_pyfiles(subdir: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-s", subdir],
        cwd=_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    bad: list[str] = []
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        mode = parts[0].split()[0]
        path = parts[1]
        if path.endswith(".py") and mode == "100644":
            bad.append(path)
    return bad


def test_every_detector_is_executable_in_git():
    """Non-executable detector → CI `./detector` exits 126 + heartbeat skips it."""
    non_exec = _git_mode_644_pyfiles("scripts/detectors")
    assert not non_exec, (
        "these detectors are NOT executable in git (mode 100644) — CI runs "
        f"`./scripts/detectors/<name>.py` and the heartbeat needs X_OK: {non_exec}. "
        "Run: chmod +x <file> && git add <file>"
    )


def test_every_hook_is_executable_in_git():
    """CI's Smoke job execs each scripts/hooks/*.py directly; mode 100644 -> exit 126."""
    non_exec = _git_mode_644_pyfiles("scripts/hooks")
    assert not non_exec, (
        "these hooks are NOT executable in git (mode 100644) — CI Smoke execs "
        f"`./scripts/hooks/<name>.py` directly and fails with rc=126: {non_exec}. "
        "Run: chmod +x <file> && git add <file>"
    )


def test_runnable_shebang_scripts_are_executable_in_git():
    """Every tracked scripts/**/*.py that starts with a `#!` shebang must be 100755 in git."""
    out = subprocess.run(
        ["git", "ls-files", "-s", "scripts"],
        cwd=_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    bad: list[str] = []
    for line in out.splitlines():
        meta, _, path = line.partition("\t")
        if not path.endswith(".py") or meta.split()[0] != "100644":
            continue
        with (_ROOT / path).open("rb") as fh:
            if fh.read(2) == b"#!":
                bad.append(path)
    assert not bad, f"shebang scripts not executable in git: {bad} (chmod +x + git add)"
