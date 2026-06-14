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


def test_runnable_shebang_scripts_are_executable_in_git():
    """The PEP-723 scripts that are RUN (not just imported) must be executable."""
    runnable = [
        "scripts/dispatch.py",
        "scripts/daemon.py",
        "scripts/compact_trigger.py",
        "scripts/reload_trigger.py",
        "scripts/identify_environment.py",
        "scripts/lib/terminal_trigger.py",
    ]
    out = subprocess.run(
        ["git", "ls-files", "-s", *runnable],
        cwd=_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in out.splitlines() if "\t" in line}
    bad = [p for p in runnable if modes.get(p) == "100644"]
    assert not bad, f"runnable shebang scripts not executable in git: {bad} (chmod +x + git add)"
