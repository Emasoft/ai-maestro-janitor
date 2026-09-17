"""LOCAL + PROJECT design scopes — the TRDD roots SSOT (3-pillars spec, 2026-07-11;
LOCAL relocated in-tree by TRDD-WY198OIP, owner directive ai-maestro#163).

A TRDD's scope IS its path (like a memory note): PROJECT under `<repo>/design/`,
LOCAL under `<repo>/.claude/local/design/` (gitignored, project-tree-local). LOCAL
mirrors the repo's design/ exactly — the same four lifecycle folders, plus the two
non-task folders `requirements/`/`specs/` — so the two are structurally identical
and no `tasks/tasks/` appears once the lifecycle folders are in use.

No mocks: every test builds a REAL on-disk tree and runs the real resolvers. The
session-default conftest isolation points HOME at a tmp tree — no longer load-bearing
for `local_design_root` (it derives purely from the project dir now), but still
guards against any other resolver in this file touching the real ~/.claude.
"""

from __future__ import annotations

import subprocess
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


def test_local_design_root_is_inside_the_project_tree(tmp_path: Path) -> None:
    """LOCAL design lives at `<project>/.claude/local/design` (TRDD-WY198OIP) — INSIDE
    the project tree now, unlike the old `~/.claude/projects/<slug>/design`. It is
    gitignored by the same `.claude/**` pattern every consumer project already carries,
    so it is safe from `git add` without living outside the repo."""
    root = _project(tmp_path)
    local = trdd_common.local_design_root(str(root))
    assert local == root / ".claude" / "local" / "design"


def test_local_design_root_resolves_a_worktree_to_its_main_checkout(tmp_path: Path) -> None:
    """A linked git worktree must NOT get its own LOCAL corpus — it dies with the branch when
    the worktree is removed (review finding on TRDD-WY198OIP). Real `git init` + commit +
    `git worktree add`; both the worktree's own path AND the main checkout must resolve to
    the SAME `.claude/local/design`, rooted at the main checkout."""
    main = tmp_path / "main"
    main.mkdir()

    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=main, check=True, capture_output=True, text=True)

    _git("init", "-q")
    _git("config", "user.email", "test@example.com")
    _git("config", "user.name", "Test")
    (main / "README.md").write_text("x", encoding="utf-8")
    _git("add", "README.md")
    _git("commit", "-q", "-m", "init")
    worktree = tmp_path / "wt"
    _git("worktree", "add", "-q", "-b", "feature", str(worktree))

    expected = main / ".claude" / "local" / "design"
    assert trdd_common.local_design_root(str(worktree)) == expected
    assert trdd_common.local_design_root(str(main)) == expected


def test_local_design_root_raises_on_a_worktree_list_failure_inside_a_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero `git worktree list --porcelain` exit INSIDE a known git repo is a real
    anomaly (corrupted `.git/worktrees` state, permission-denied on a shared checkout) — it
    must RAISE rather than silently keep using the given root, which could be the wrong one
    for a worktree. Real `git init` (so `rev-parse --is-inside-work-tree` genuinely succeeds);
    only the `worktree list` subprocess call is monkeypatched to fail."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q"], cwd=repo, check=True, capture_output=True, text=True
    )
    real_run = subprocess.run

    def _fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        if "worktree" in cmd and "list" in cmd:
            return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal: simulated")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(trdd_common.subprocess, "run", _fake_run)
    trdd_common._main_checkout_root.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="git worktree list"):
            trdd_common.local_design_root(str(repo))
    finally:
        trdd_common._main_checkout_root.cache_clear()


def test_main_checkout_root_is_memoized_per_project_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`local_design_root()` fans out to ~19 call sites (dispatch.py, fleet_status.py, several
    per-beat detectors) — a second lookup for the SAME project dir must not re-spawn `git`
    subprocesses. `@lru_cache` on `_main_checkout_root` is what makes that true; this asserts
    it empirically rather than trusting the decorator is still there."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q"], cwd=repo, check=True, capture_output=True, text=True
    )
    real_run = subprocess.run
    calls = []

    def _counting_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        return real_run(cmd, *args, **kwargs)

    trdd_common._main_checkout_root.cache_clear()
    monkeypatch.setattr(trdd_common.subprocess, "run", _counting_run)
    try:
        trdd_common.local_design_root(str(repo))
        first_call_count = len(calls)
        assert first_call_count > 0, "the first lookup must actually call git"

        trdd_common.local_design_root(str(repo))
        assert len(calls) == first_call_count, (
            "a second lookup for the same project_dir must hit the lru_cache, not git again"
        )
    finally:
        trdd_common._main_checkout_root.cache_clear()


def test_local_design_root_of_a_submodule_stays_in_the_submodule(tmp_path: Path) -> None:
    """A git SUBMODULE checkout has `.git` as a FILE (pointing at
    `<super>/.git/modules/<name>`), not a directory. `git worktree list --porcelain` run
    inside the submodule operates on the submodule's OWN repo object, so its LOCAL corpus
    must land inside the submodule itself — never hoisted up into the superproject's tree,
    which would mix one submodule's machine-private cards into a sibling checkout's board."""

    def _git(cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

    sub_origin = tmp_path / "sub_origin"
    sub_origin.mkdir()
    _git(sub_origin, "init", "-q")
    _git(sub_origin, "config", "user.email", "test@example.com")
    _git(sub_origin, "config", "user.name", "Test")
    (sub_origin / "f.txt").write_text("x", encoding="utf-8")
    _git(sub_origin, "add", "f.txt")
    _git(sub_origin, "commit", "-q", "-m", "init")

    superproject = tmp_path / "super"
    superproject.mkdir()
    _git(superproject, "init", "-q")
    _git(superproject, "config", "user.email", "test@example.com")
    _git(superproject, "config", "user.name", "Test")
    _git(
        superproject, "-c", "protocol.file.allow=always",
        "submodule", "add", "-q", str(sub_origin), "sub",
    )
    _git(superproject, "commit", "-q", "-m", "add submodule")

    submodule_dir = superproject / "sub"
    assert (submodule_dir / ".git").is_file(), "a submodule checkout's .git is a file"

    trdd_common._main_checkout_root.cache_clear()
    try:
        resolved = trdd_common.local_design_root(str(submodule_dir))
    finally:
        trdd_common._main_checkout_root.cache_clear()

    assert resolved == submodule_dir / ".claude" / "local" / "design", (
        "a submodule's LOCAL corpus must stay in the submodule, not the superproject"
    )


def test_local_design_no_longer_shares_a_slug_dir_with_local_memory(tmp_path: Path) -> None:
    """LOCAL design and LOCAL wikimem memory are DIFFERENT subsystems by owner directive
    (ai-maestro#163: 'different from the wikimem architecture, and it must be so') — design
    moved in-tree, memory still resolves under `~/.claude/projects/<slug>/memory`. They must
    NOT collide or nest inside one another."""
    root = _project(tmp_path)
    design = trdd_common.local_design_root(str(root))
    memory = memory_scopes.resolve_local_dir_for(str(root))
    assert design.parent != memory.parent
    assert design not in memory.parents and memory not in design.parents


def test_local_mirrors_the_repo_design_folders(tmp_path: Path) -> None:
    """LOCAL carries the SAME four lifecycle folders as the repo's design/, plus the two
    non-task folders (`requirements/`, `specs/`) that have no lifecycle of their own —
    mirroring the whole dir is what avoids tasks/tasks/."""
    root = _project(tmp_path)
    created = trdd_common.ensure_local_design(str(root))
    for folder in ("proposals", "tasks", "archived", "refused", "requirements", "specs"):
        assert (created / folder).is_dir(), f"LOCAL design must carry {folder}/"
    assert trdd_common.DESIGN_FOLDERS == ("proposals", "tasks", "archived", "refused")
    assert trdd_common.NON_TASK_FOLDERS == ("requirements", "specs")


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
    """LOCAL is derived from the project root directly, never from the user-supplied
    option — so a typo'd TRDD_PATH cannot take the local board down with it. LOCAL needs
    no containment check either: unlike PROJECT (whose root can be redirected by an
    option that might escape), LOCAL's path is a fixed join off the project root with
    nothing here for a bad option to escape with."""
    root = _project(tmp_path)
    local = trdd_common.ensure_local_design(str(root))
    (local / "tasks" / TRDD2).write_text("column: dev\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_TRDD_PATH", "/etc")

    found = trdd_common.trdd_files("tasks", str(root))

    assert found == [(trdd_common.LOCAL, local / "tasks" / TRDD2)]


@pytest.mark.parametrize("dotted", ["proj.v2", "my_proj", "a-b.c_d"])
def test_local_design_root_survives_dotted_and_underscored_project_paths(
    tmp_path: Path, dotted: str
) -> None:
    """REGRESSION guard for the OLD slug-based resolver, kept post-migration: a project
    path with dots/underscores in its name must resolve LOCAL design correctly. Now that
    LOCAL is a plain `<project>/.claude/local/design` join (no slug involved), this is
    trivially true — but the case is worth keeping as a canary against a future
    regression that re-introduces slug-based derivation."""
    root = tmp_path / dotted
    (root / "design" / "tasks").mkdir(parents=True)

    local = trdd_common.local_design_root(str(root))

    assert local == root / ".claude" / "local" / "design"
