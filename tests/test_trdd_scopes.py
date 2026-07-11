"""LOCAL + PROJECT design scopes — the TRDD roots SSOT (3-pillars spec, 2026-07-11).

A TRDD's scope IS its path (like a memory note): PROJECT under `<repo>/design/`,
LOCAL under `~/.claude/projects/<slug>/design/`. LOCAL mirrors the repo's design/
exactly — the same four lifecycle folders — so the two are structurally identical
and no `tasks/tasks/` appears once the lifecycle folders are in use.

No mocks: every test builds a REAL on-disk tree and runs the real resolvers. The
session-default conftest isolation points HOME at a tmp tree, so `local_design_root`
resolves inside it and nothing here can touch the real ~/.claude.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS / "lib"))

import memory_scopes  # type: ignore[import-not-found]  # noqa: E402
import trdd_common  # type: ignore[import-not-found]  # noqa: E402

TRDD = "TRDD-20260711_120000+0200-ABCD1234-a-task.md"
TRDD2 = "TRDD-20260711_130000+0200-EFGH5678-another-task.md"


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "design" / "tasks").mkdir(parents=True)
    return root


# ── the roots themselves ─────────────────────────────────────────────────────


def test_project_design_root_is_the_repo_design_dir(tmp_path: Path) -> None:
    """PROJECT design is `<repo>/design` — the shared, git-tracked root."""
    root = _project(tmp_path)
    assert trdd_common.project_design_root(str(root)) == root / "design"


def test_local_design_root_is_outside_the_repo(tmp_path: Path) -> None:
    """LOCAL design lives under the harness project dir, NOT in the repo — so it can
    never be committed by accident, and `git clean -fdx` cannot destroy it."""
    root = _project(tmp_path)
    local = trdd_common.local_design_root(str(root))
    assert local.name == "design"
    assert root not in local.parents, "LOCAL design must not sit inside the repo"
    assert local.parent.name == memory_scopes.project_slug(str(root))


def test_local_design_is_a_sibling_of_local_memory(tmp_path: Path) -> None:
    """LOCAL design sits BESIDE LOCAL memory under the same per-project slug dir, and
    routes through the SAME slug fn — a second slug derivation is what once resolved a
    nonexistent dir and silently emptied the LOCAL memory subsystem."""
    root = _project(tmp_path)
    design = trdd_common.local_design_root(str(root))
    memory = memory_scopes.resolve_local_dir_for(str(root))
    assert design.parent == memory.parent
    assert design.name == "design" and memory.name == "memory"


def test_local_mirrors_the_repo_design_folders(tmp_path: Path) -> None:
    """LOCAL carries the SAME four lifecycle folders as the repo's design/ — mirroring
    the whole dir (not hanging a bare tasks/ off the slug) is what avoids tasks/tasks/."""
    root = _project(tmp_path)
    created = trdd_common.ensure_local_design(str(root))
    for folder in ("proposals", "tasks", "archived", "refused"):
        assert (created / folder).is_dir(), f"LOCAL design must carry {folder}/"
    assert trdd_common.DESIGN_FOLDERS == ("proposals", "tasks", "archived", "refused")


# ── discovery across both scopes ─────────────────────────────────────────────


def test_design_roots_lists_only_existing_roots(tmp_path: Path) -> None:
    """A project with no LOCAL design dir yields PROJECT only — that is the norm, not
    an error, and must never be reported as drift."""
    root = _project(tmp_path)
    assert trdd_common.design_roots(str(root)) == [
        (trdd_common.PROJECT, root / "design")
    ]


def test_design_roots_puts_local_first(tmp_path: Path) -> None:
    """LOCAL before PROJECT — most-specific first, mirroring memory_scopes."""
    root = _project(tmp_path)
    trdd_common.ensure_local_design(str(root))
    scopes = [scope for scope, _ in trdd_common.design_roots(str(root))]
    assert scopes == [trdd_common.LOCAL, trdd_common.PROJECT]


def test_trdd_files_sees_BOTH_scopes(tmp_path: Path) -> None:
    """THE point of the SSOT: one call returns the whole board. A consumer that could
    only see one root would make that scope's tasks invisible."""
    root = _project(tmp_path)
    local = trdd_common.ensure_local_design(str(root))
    (root / "design" / "tasks" / TRDD).write_text("column: dev\n", encoding="utf-8")
    (local / "tasks" / TRDD2).write_text("column: dev\n", encoding="utf-8")

    found = trdd_common.trdd_files("tasks", str(root))

    assert {(scope, p.name) for scope, p in found} == {
        (trdd_common.PROJECT, TRDD),
        (trdd_common.LOCAL, TRDD2),
    }


def test_trdd_files_reads_the_named_folder(tmp_path: Path) -> None:
    """Each lifecycle folder is addressable, in both scopes (proposals, archived, …)."""
    root = _project(tmp_path)
    (root / "design" / "proposals").mkdir()
    (root / "design" / "proposals" / TRDD).write_text("column: proposal\n", encoding="utf-8")

    assert [p.name for _, p in trdd_common.trdd_files("proposals", str(root))] == [TRDD]
    assert trdd_common.trdd_files("tasks", str(root)) == []


def test_non_trdd_files_are_ignored(tmp_path: Path) -> None:
    """Only `TRDD-*.md` is a TRDD — a README or a stray note in the folder is not."""
    root = _project(tmp_path)
    tasks = root / "design" / "tasks"
    (tasks / "README.md").write_text("not a trdd", encoding="utf-8")
    (tasks / TRDD).write_text("column: dev\n", encoding="utf-8")

    assert [p.name for _, p in trdd_common.trdd_files("tasks", str(root))] == [TRDD]


def test_resolvers_do_not_create_anything(tmp_path: Path) -> None:
    """Read-only observers (the detectors) must never materialize the thing they observe:
    a resolver that mkdir'd would make every project look like it has local design, and
    would write into ~/.claude on every heartbeat."""
    root = _project(tmp_path)
    local = trdd_common.local_design_root(str(root))

    trdd_common.design_roots(str(root))
    trdd_common.trdd_files("tasks", str(root))

    assert not local.exists(), "resolving a root must not create it"


# ── the CLAUDE_PLUGIN_OPTION_TRDD_PATH override (pre-existing, must survive) ─


def test_project_tasks_dir_honors_the_trdd_path_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project that relocated its TRDDs via CLAUDE_PLUGIN_OPTION_TRDD_PATH must keep
    working — hardcoding <root>/design/tasks in the SSOT would have silently ignored the
    option that every detector honors today."""
    root = _project(tmp_path)
    (root / "docs" / "trdds").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_TRDD_PATH", "docs/trdds")

    assert trdd_common.project_tasks_dir(str(root)) == root / "docs" / "trdds"
    # the whole lifecycle travels with it — the option has only ever governed tasks/
    assert trdd_common.project_design_root(str(root)) == root / "docs"

    # and discovery must follow the override, not re-derive `<design_root>/tasks` —
    # that would look in docs/tasks/, which does not exist.
    (root / "docs" / "trdds" / TRDD).write_text("column: dev\n", encoding="utf-8")
    assert [p.name for _, p in trdd_common.trdd_files("tasks", str(root))] == [TRDD]


def test_trdd_path_escaping_the_project_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A misconfigured option (absolute path / ../ escape) must NEVER make a consumer scan
    outside the project. None = refuse, and the PROJECT root drops off the board."""
    root = _project(tmp_path)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_TRDD_PATH", "../../etc")

    assert trdd_common.project_tasks_dir(str(root)) is None
    assert trdd_common.project_design_root(str(root)) is None
    scopes = [scope for scope, _ in trdd_common.design_roots(str(root))]
    assert trdd_common.PROJECT not in scopes


def test_local_scope_survives_a_broken_project_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LOCAL is derived from the project SLUG, never from the user-supplied option — so a
    typo'd TRDD_PATH cannot take the local board down with it. LOCAL is also deliberately
    OUTSIDE the project root, so the containment check that guards PROJECT must not be
    applied to it (doing so would reject the entire scope)."""
    root = _project(tmp_path)
    local = trdd_common.ensure_local_design(str(root))
    (local / "tasks" / TRDD2).write_text("column: dev\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_TRDD_PATH", "/etc")

    found = trdd_common.trdd_files("tasks", str(root))

    assert found == [(trdd_common.LOCAL, local / "tasks" / TRDD2)]


@pytest.mark.parametrize("dotted", ["proj.v2", "my_proj", "a-b.c_d"])
def test_slug_survives_dotted_and_underscored_paths(tmp_path: Path, dotted: str) -> None:
    """REGRESSION: the harness dashes EVERY non-alphanumeric char, not just separators.
    A separators-only slug resolved a nonexistent dir and silently emptied LOCAL memory;
    routing through memory_scopes.project_slug is what keeps LOCAL design out of that."""
    root = tmp_path / dotted
    (root / "design" / "tasks").mkdir(parents=True)

    local = trdd_common.local_design_root(str(root))

    assert local.parent.name == memory_scopes.project_slug(str(root))
    assert "." not in local.parent.name and "_" not in local.parent.name
