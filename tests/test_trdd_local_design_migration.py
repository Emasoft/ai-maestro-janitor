"""Tests for `_migrate_local_design` in on-session-start-trdd-state.py (TRDD-WY198OIP).

LOCAL design moved from `~/.claude/projects/<slug>/design` to
`<project_root>/.claude/local/design` (owner directive ai-maestro#163). This hook
carries a one-time, best-effort migration that runs at SessionStart. Real fixtures
only: HOME is monkeypatched to a tmp dir so nothing here can touch the real
`~/.claude`, matching the isolation `test_local_design_mirror.py` already uses.
"""

from __future__ import annotations

import importlib.util as _u
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "on-session-start-trdd-state.py"
_LIB = _PROJECT_ROOT / "scripts" / "lib"

if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
import memory_scopes  # noqa: E402


def _import_hook():
    # The hook filename has dashes, so it cannot be a normal import — load it by path.
    spec = _u.spec_from_file_location("on_session_start_trdd_state_under_test", str(_HOOK))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Redirect HOME + CLAUDE_PLUGIN_ROOT so nothing here can touch the real ~/.claude."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_PROJECT_ROOT))
    return home


def test_fresh_move_relocates_old_local_design(tmp_path, _isolate):
    """Old `~/.claude/projects/<slug>/design` present, new absent -> moved, marker dropped."""
    mod = _import_hook()
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    slug = memory_scopes.project_slug(str(project_dir))
    old = _isolate / ".claude" / "projects" / slug / "design"
    (old / "tasks").mkdir(parents=True)
    (old / "tasks" / "TRDD-1-foo.md").write_text("column: dev\n", encoding="utf-8")

    mod._migrate_local_design(project_dir)

    new = project_dir / ".claude" / "local" / "design"
    assert (new / "tasks" / "TRDD-1-foo.md").read_text(encoding="utf-8") == "column: dev\n"
    assert not old.exists(), "the old dir must be MOVED, not copied"
    assert (old.parent / "MOVED-TO.txt").read_text(encoding="utf-8").strip() == str(new)


def test_both_present_refuses_and_does_not_touch_either(tmp_path, _isolate):
    """Old AND new both exist -> refuse (no merge), log a drift line, leave both untouched."""
    mod = _import_hook()
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    slug = memory_scopes.project_slug(str(project_dir))
    old = _isolate / ".claude" / "projects" / slug / "design"
    (old / "tasks").mkdir(parents=True)
    (old / "tasks" / "TRDD-old.md").write_text("old", encoding="utf-8")
    new = project_dir / ".claude" / "local" / "design"
    (new / "tasks").mkdir(parents=True)
    (new / "tasks" / "TRDD-new.md").write_text("new", encoding="utf-8")

    mod._migrate_local_design(project_dir)

    assert (old / "tasks" / "TRDD-old.md").read_text(encoding="utf-8") == "old"
    assert (new / "tasks" / "TRDD-new.md").read_text(encoding="utf-8") == "new"
    log = (project_dir / ".janitor" / "logs" / "dispatch.log").read_text(encoding="utf-8")
    assert "DRIFT" in log and str(old) in log and str(new) in log


def test_empty_scaffold_at_new_is_not_mistaken_for_already_migrated(tmp_path, _isolate):
    """`ensure_local_design()` can mkdir the new root's lifecycle folders (empty) before this
    hook's SessionStart ever fires for a project — e.g. a non-interactive caller runs first.
    That empty scaffold must NOT be treated as 'already migrated': old's real cards still move."""
    mod = _import_hook()
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    slug = memory_scopes.project_slug(str(project_dir))
    old = _isolate / ".claude" / "projects" / slug / "design"
    (old / "tasks").mkdir(parents=True)
    (old / "tasks" / "TRDD-1-foo.md").write_text("column: dev\n", encoding="utf-8")
    new = project_dir / ".claude" / "local" / "design"
    for folder in ("proposals", "tasks", "archived", "refused", "requirements", "specs"):
        (new / folder).mkdir(parents=True)  # empty scaffold, no TRDD-*.md anywhere

    mod._migrate_local_design(project_dir)

    assert (new / "tasks" / "TRDD-1-foo.md").read_text(encoding="utf-8") == "column: dev\n"
    assert not old.exists()


def test_move_failure_is_logged_not_swallowed(tmp_path, _isolate, monkeypatch):
    """Fail-open must never mean silent: if `shutil.move` raises, the except path logs the
    exception class + message + both paths, and does NOT half-apply the migration (old stays,
    no MOVED-TO.txt, new not created)."""
    mod = _import_hook()
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    slug = memory_scopes.project_slug(str(project_dir))
    old = _isolate / ".claude" / "projects" / slug / "design"
    (old / "tasks").mkdir(parents=True)
    (old / "tasks" / "TRDD-1-foo.md").write_text("column: dev\n", encoding="utf-8")

    import shutil

    real_move = shutil.move

    def _boom(*_a, **_k):
        raise OSError("simulated disk full")

    # `_migrate_local_design` does `import shutil` locally — that binds the SAME module object
    # already in sys.modules, so patching the real module's attribute is what the function sees.
    # Restored manually (not via monkeypatch.undo(), which is SHARED with the autouse `_isolate`
    # fixture's HOME/CLAUDE_PLUGIN_ROOT patches within this same test) before the retry below.
    monkeypatch.setattr(shutil, "move", _boom)

    mod._migrate_local_design(project_dir)

    new = project_dir / ".claude" / "local" / "design"
    log = (project_dir / ".janitor" / "logs" / "dispatch.log").read_text(encoding="utf-8")
    assert "local-design migration FAILED" in log
    assert "OSError" in log and "simulated disk full" in log
    assert str(old) in log and str(new) in log
    assert (old / "tasks" / "TRDD-1-foo.md").exists(), "old must be untouched on failure"
    assert not (old.parent / "MOVED-TO.txt").exists()

    # Self-heal: a retry (e.g. next SessionStart) with shutil.move working must still succeed,
    # even if the failed attempt left `new`'s parent (`.claude/local/`) on disk — the
    # empty-scaffold check treats a `new` with no TRDD-*.md as not-yet-migrated.
    monkeypatch.setattr(shutil, "move", real_move)
    mod._migrate_local_design(project_dir)
    assert (new / "tasks" / "TRDD-1-foo.md").exists(), "retry after a failed attempt must succeed"


def test_neither_present_logs_the_old_path_it_looked_for_once(tmp_path, _isolate):
    """No old dir at all (the common case: a project that never had LOCAL design) -> no-op,
    nothing created, but ONE log line names the slug dir it looked for on the FIRST call (so a
    genuinely stuck migration — wrong slug, half-cleared old dir — leaves a trace instead of
    looking identical to "nothing to do"). A SECOND call must NOT log again — this branch fires
    on nearly every SessionStart for a project with no LOCAL corpus, so unconditional logging
    would grow the log file forever for zero new information."""
    mod = _import_hook()
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    slug = memory_scopes.project_slug(str(project_dir))
    old = _isolate / ".claude" / "projects" / slug / "design"

    mod._migrate_local_design(project_dir)
    mod._migrate_local_design(project_dir)  # second SessionStart, same project

    assert not (project_dir / ".claude" / "local" / "design").exists()
    log = (project_dir / ".janitor" / "logs" / "dispatch.log").read_text(encoding="utf-8")
    assert log.count("local-design migration: nothing at") == 1
    assert str(old) in log


def test_leak_guard_refuses_when_git_does_not_ignore_the_new_root(tmp_path, _isolate):
    """A project whose git does NOT ignore `.claude/local/design` must refuse the move: the
    next `git add -A` there would commit machine-private LOCAL cards to a pushed repo — the
    exact leak the LOCAL/PROJECT split exists to prevent."""
    mod = _import_hook()
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    subprocess.run(
        ["git", "init", "-q"], cwd=project_dir, check=True, capture_output=True, text=True
    )
    slug = memory_scopes.project_slug(str(project_dir))
    old = _isolate / ".claude" / "projects" / slug / "design"
    (old / "tasks").mkdir(parents=True)
    (old / "tasks" / "TRDD-1-foo.md").write_text("column: dev\n", encoding="utf-8")

    mod._migrate_local_design(project_dir)

    new = project_dir / ".claude" / "local" / "design"
    assert not new.exists(), "must not move into an unignored root"
    assert (old / "tasks" / "TRDD-1-foo.md").exists(), "old must be untouched on refusal"
    log = (project_dir / ".janitor" / "logs" / "dispatch.log").read_text(encoding="utf-8")
    assert "DRIFT" in log and "does not ignore" in log


def test_leak_guard_proceeds_when_git_ignores_the_new_root(tmp_path, _isolate):
    """A project whose `.gitignore` already covers `.claude/**` (the standard convention every
    consumer project carries) must migrate normally — the leak guard is not a blanket refusal
    whenever a project happens to be a git repo."""
    mod = _import_hook()
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    subprocess.run(
        ["git", "init", "-q"], cwd=project_dir, check=True, capture_output=True, text=True
    )
    (project_dir / ".gitignore").write_text(".claude/**\n", encoding="utf-8")
    slug = memory_scopes.project_slug(str(project_dir))
    old = _isolate / ".claude" / "projects" / slug / "design"
    (old / "tasks").mkdir(parents=True)
    (old / "tasks" / "TRDD-1-foo.md").write_text("column: dev\n", encoding="utf-8")

    mod._migrate_local_design(project_dir)

    new = project_dir / ".claude" / "local" / "design"
    assert (new / "tasks" / "TRDD-1-foo.md").read_text(encoding="utf-8") == "column: dev\n"
    assert not old.exists()


def test_leak_guard_refuses_when_the_new_root_is_explicitly_unignored(tmp_path, _isolate):
    """Mutation-resistant version of the leak-guard test: a `.gitignore` with `.claude/**`
    PLUS an explicit `!` re-include of the new root specifically. A guard that merely checked
    "does a .gitignore file exist" (rather than actually asking git) would wrongly proceed
    here; only a real `git check-ignore` call correctly reports this path as NOT ignored."""
    mod = _import_hook()
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    subprocess.run(
        ["git", "init", "-q"], cwd=project_dir, check=True, capture_output=True, text=True
    )
    # A NAIVE guard that only checked "does a .gitignore exist mentioning .claude" would
    # wrongly call this "ignored" (line 1 alone would match without the negations below).
    # A full un-ignore chain (each parent dir must be re-included too — a documented
    # gitignore gotcha) makes the path GENUINELY not-ignored; only a real `git
    # check-ignore` call reports that correctly (verified with a real `git init` here).
    (project_dir / ".gitignore").write_text(
        ".claude/**\n"
        "!.claude/\n"
        "!.claude/local/\n"
        "!.claude/local/design/\n"
        "!.claude/local/design/**\n",
        encoding="utf-8",
    )
    slug = memory_scopes.project_slug(str(project_dir))
    old = _isolate / ".claude" / "projects" / slug / "design"
    (old / "tasks").mkdir(parents=True)
    (old / "tasks" / "TRDD-1-foo.md").write_text("column: dev\n", encoding="utf-8")

    mod._migrate_local_design(project_dir)

    new = project_dir / ".claude" / "local" / "design"
    assert not new.exists(), "an explicitly un-ignored new root must still refuse"
    assert (old / "tasks" / "TRDD-1-foo.md").exists()
    log = (project_dir / ".janitor" / "logs" / "dispatch.log").read_text(encoding="utf-8")
    assert "DRIFT" in log and "does not ignore" in log


def test_local_memory_dir_is_never_touched(tmp_path, _isolate):
    """The wikimem LOCAL memory dir sits BESIDE the old design dir under the same slug —
    the migration must move `design/` only, never touch the sibling `memory/`."""
    mod = _import_hook()
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    slug = memory_scopes.project_slug(str(project_dir))
    old_design = _isolate / ".claude" / "projects" / slug / "design"
    (old_design / "tasks").mkdir(parents=True)
    (old_design / "tasks" / "TRDD-1.md").write_text("x", encoding="utf-8")
    memory_dir = _isolate / ".claude" / "projects" / slug / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "note.md").write_text("keep me", encoding="utf-8")

    mod._migrate_local_design(project_dir)

    assert (memory_dir / "note.md").read_text(encoding="utf-8") == "keep me"
    assert not old_design.exists()
