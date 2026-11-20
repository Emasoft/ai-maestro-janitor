"""TRDD-56FOY1U1: the two TRDD hooks must say so when git fails resolving the design root.

Both hooks run as real subprocesses (no mocks). The `failing_worktree_list_git_path` fixture
puts a fake `git` first on PATH whose `worktree list` exits 1. Assertions read output text
only: the hooks import `lib.trdd_common` while a test would import bare `trdd_common`, which
are two module objects, so an exception class or a cache state cannot be compared here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SESSION_HOOK = _ROOT / "scripts" / "hooks" / "on-session-start-trdd-state.py"
_COMPACT_HOOK = _ROOT / "scripts" / "hooks" / "post-compact-resume.py"
_CARD_ID = "ABCDEFGH"
_SESSION_LINE_START = "[janitor-trdd] git failed resolving the design root ("
_SESSION_LINE_END = (
    "); LOCAL-scope cards are not shown this time "
    "(informational; not a task - do not investigate unless asked)"
)
_COMPACT_LINE_START = "[post-compact-resume] git failed resolving the design root ("
_COMPACT_LINE_END = "); the resume directive uses PROJECT-scope cards only"


def _project(tmp_path: Path) -> Path:
    """A temp project holding one in-progress PROJECT card."""
    project = tmp_path / "project"
    tasks = project / "design" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / f"TRDD-20260602_044555+0200-{_CARD_ID}-x.md").write_text(
        "---\n"
        f"trdd-id: {_CARD_ID}\n"
        "title: Active thing\n"
        "column: dev\n"
        "created: 2026-06-02T04:45:55+0200\n"
        "updated: 2026-06-02T05:00:00+0200\n"
        "---\n\n"
        "## STATE\n\n### NEXT ACTION\nDo the next step.\n",
        encoding="utf-8",
    )
    return project


def _env(tmp_path: Path, project: Path, path: str, plugin_root: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "PATH": path,
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "CLAUDE_PROJECT_DIR": str(project),
        # No detached resume push from post-compact-resume.
        "CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ENABLED": "false",
    }


def _run(hook: Path, project: Path, env: dict[str, str], payload: dict[str, str]) -> subprocess.CompletedProcess[str]:
    body = json.dumps({"cwd": str(project), **payload})
    return subprocess.run(
        [sys.executable, str(hook)], input=body, capture_output=True, text=True, env=env, timeout=60,
    )


def _plugin_root_without_trdd_common(tmp_path: Path) -> Path:
    """A plugin root whose scripts/lib has everything except trdd_common.py, with both hooks copied in.

    WHY the hooks are copied (TRDD-3MUWV3PJ): the SessionStart hook resolves the git toplevel of the
    payload cwd first (_git_toplevel, added by a5b7027e), which puts ITS OWN scripts/ on sys.path and
    imports `lib.exe_path`; that caches the `lib` package of the tree the hook lives in. A hook run
    from the real tree therefore finds the real trdd_common whatever CLAUDE_PLUGIN_ROOT says (observed
    with an import spy: the first lib import is lib.exe_path at the _git_toplevel call; the test file
    passes at a5b7027e^ and failed from a5b7027e on). Running the copy from inside this stripped root
    is what makes trdd_common truly unimportable. The PostCompact hook gets the same copy for symmetry.
    """
    root = tmp_path / "plugin-no-trdd-common"
    shutil.copytree(
        _ROOT / "scripts" / "lib", root / "scripts" / "lib", ignore=shutil.ignore_patterns("__pycache__"),
    )
    (root / "scripts" / "lib" / "trdd_common.py").unlink()
    (root / "scripts" / "hooks").mkdir()
    for hook in (_SESSION_HOOK, _COMPACT_HOOK):
        shutil.copy2(hook, root / "scripts" / "hooks" / hook.name)
    return root


def test_session_start_says_git_failed_first_and_still_injects_project_card(
    tmp_path: Path, failing_worktree_list_git_path: str
) -> None:
    """SessionStart: git failure is the FIRST stdout line, the PROJECT card is still injected, exit 0."""
    project = _project(tmp_path)
    env = _env(tmp_path, project, failing_worktree_list_git_path, _ROOT)
    proc = _run(_SESSION_HOOK, project, env, {"source": "startup", "hook_event_name": "SessionStart"})
    assert proc.returncode == 0, proc.stderr
    first = proc.stdout.splitlines()[0]
    assert first.startswith(_SESSION_LINE_START) and first.endswith(_SESSION_LINE_END), proc.stdout
    assert "boom" in first and "<path>" in first and str(tmp_path) not in first, first
    assert _CARD_ID in proc.stdout, proc.stdout
    assert "Traceback" not in proc.stdout + proc.stderr


def test_post_compact_resume_says_git_failed_on_stderr(
    tmp_path: Path, failing_worktree_list_git_path: str
) -> None:
    """PostCompact: the git failure line is on stderr, the PROJECT card still drives the directive, exit 0."""
    project = _project(tmp_path)
    env = _env(tmp_path, project, failing_worktree_list_git_path, _ROOT)
    proc = _run(_COMPACT_HOOK, project, env, {"trigger": "manual", "hook_event_name": "PostCompact"})
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stderr.splitlines() if ln.startswith(_COMPACT_LINE_START)]
    assert len(lines) == 1 and lines[0].endswith(_COMPACT_LINE_END), proc.stderr
    assert "boom" in lines[0] and "<path>" in lines[0] and str(tmp_path) not in lines[0], lines[0]
    flag = project / ".janitor" / "state" / "resume-after-compact.flag"
    assert flag.exists() and f"TRDD-{_CARD_ID}" in flag.read_text(encoding="utf-8")
    assert "Traceback" not in proc.stdout + proc.stderr


def test_session_start_import_broken_empty_plugin_root_exits_0_without_traceback(
    tmp_path: Path, failing_worktree_list_git_path: str
) -> None:
    """SessionStart with an empty plugin root: exit 0, no traceback, PROJECT card still injected."""
    project = _project(tmp_path)
    empty = tmp_path / "empty-plugin"
    empty.mkdir()
    env = _env(tmp_path, project, failing_worktree_list_git_path, empty)
    proc = _run(_SESSION_HOOK, project, env, {"source": "startup", "hook_event_name": "SessionStart"})
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr
    assert _CARD_ID in proc.stdout, proc.stdout


def test_post_compact_resume_import_broken_empty_plugin_root_exits_0_without_traceback(
    tmp_path: Path, failing_worktree_list_git_path: str
) -> None:
    """PostCompact with an empty plugin root: exit 0, no traceback."""
    project = _project(tmp_path)
    empty = tmp_path / "empty-plugin"
    empty.mkdir()
    env = _env(tmp_path, project, failing_worktree_list_git_path, empty)
    proc = _run(_COMPACT_HOOK, project, env, {"trigger": "manual", "hook_event_name": "PostCompact"})
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr


def test_session_start_without_trdd_common_falls_back_to_project_glob_silently(
    tmp_path: Path, failing_worktree_list_git_path: str
) -> None:
    """SessionStart when only trdd_common is missing: no NameError, no git line, PROJECT card injected."""
    project = _project(tmp_path)
    plugin_root = _plugin_root_without_trdd_common(tmp_path)
    env = _env(tmp_path, project, failing_worktree_list_git_path, plugin_root)
    hook = plugin_root / "scripts" / "hooks" / _SESSION_HOOK.name
    proc = _run(hook, project, env, {"source": "startup", "hook_event_name": "SessionStart"})
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr
    assert "git failed resolving" not in proc.stdout + proc.stderr
    assert _CARD_ID in proc.stdout, proc.stdout


def test_post_compact_resume_without_trdd_common_falls_back_to_project_glob_silently(
    tmp_path: Path, failing_worktree_list_git_path: str
) -> None:
    """PostCompact when only trdd_common is missing: no NameError, no git line, PROJECT card drives the flag."""
    project = _project(tmp_path)
    plugin_root = _plugin_root_without_trdd_common(tmp_path)
    env = _env(tmp_path, project, failing_worktree_list_git_path, plugin_root)
    hook = plugin_root / "scripts" / "hooks" / _COMPACT_HOOK.name
    proc = _run(hook, project, env, {"trigger": "manual", "hook_event_name": "PostCompact"})
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr
    assert "git failed resolving" not in proc.stdout + proc.stderr
    flag = project / ".janitor" / "state" / "resume-after-compact.flag"
    assert flag.exists() and f"TRDD-{_CARD_ID}" in flag.read_text(encoding="utf-8")


def test_post_compact_resume_with_stderr_closed_still_writes_the_directive(
    tmp_path: Path, failing_worktree_list_git_path: str
) -> None:
    """PostCompact with fd 2 closed (sys.stderr is None): the git notice is skipped, nothing leaks to stdout, the directive is still written, exit 0."""
    project = _project(tmp_path)
    env = _env(tmp_path, project, failing_worktree_list_git_path, _ROOT)
    body = json.dumps({"cwd": str(project), "trigger": "manual", "hook_event_name": "PostCompact"})
    proc = subprocess.run(
        [sys.executable, str(_COMPACT_HOOK)],
        input=body, capture_output=True, text=True, env=env, timeout=60,
        preexec_fn=lambda: os.close(2),
    )
    assert proc.returncode == 0, proc.stdout
    assert "git failed resolving" not in proc.stdout, proc.stdout
    assert "Traceback" not in proc.stdout, proc.stdout
    flag = project / ".janitor" / "state" / "resume-after-compact.flag"
    assert flag.exists() and f"TRDD-{_CARD_ID}" in flag.read_text(encoding="utf-8")
