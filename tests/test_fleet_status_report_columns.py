"""Five reporting defects the owner found in the fleet dashboard (2026-08-05).

Each test below is one of them, and each was a wrong ANSWER rather than a missing feature —
the table was confidently reporting something untrue:

  1. The `github repo` column printed `origin` alone. On `~/ai-maestro`, `origin` is the
     UPSTREAM (`23blocks-OS/ai-maestro`) and the owner's fork sits on a remote named `fork`,
     so the dashboard named a repository the owner does not own, next to the issue-filing
     workflow that PRRD G11.2 governs. Ownership is now computed by comparing remote OWNERS
     to the gh auth user, never by trusting remote names.
  2. Nested repositories were invisible, because the probe used `os.path.isdir(".git")` and a
     submodule (and a linked worktree) carries `.git` as a FILE.
  3. A project whose ROOT is not a repo reported `—` for branch and repo, as if it were not
     under version control, when its repo simply lives one level down.
  4. Two claude processes sharing a project rendered as two rows with every janitor column
     duplicated — janitor state is per-project, so that is one janitor, one row.
  5. The session column said `active: no`, which reads as "the janitor is inactive". Every
     janitor deactivation route except `/janitor-disarm` was removed, so a quiet janitor is
     armed-and-between-fires, deliberately disarmed, or BROKEN — one "no" hid the third.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import fleet_status as fstat  # type: ignore[import-not-found]  # noqa: E402


@dataclass
class _Inst:
    """Only the Instance fields the reporting helpers read."""
    pid: int = 1
    project_root: str = "/tmp/proj"
    diagnosis: str = "healthy"
    active: bool = False
    terminal: dict | None = None


def _git_init(path: Path, *, remotes: dict[str, str]) -> None:
    """A real git repo — these helpers shell out to git, so a fake tree would prove nothing.

    The initial commit is load-bearing: `rev-parse --abbrev-ref HEAD` on a repo with NO
    commits returns the literal `HEAD` (an unborn branch), not the branch name. Without a
    commit the fixture would assert against a state no real project is ever in.
    """
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=path, check=True)
    for name, url in remotes.items():
        subprocess.run(["git", "remote", "add", name, url], cwd=path, check=True)


# ── 1. origin is not necessarily yours ────────────────────────────────────────────────


def test_yours_is_the_remote_whose_OWNER_matches_the_gh_user_not_the_one_named_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ~/ai-maestro shape: origin is the upstream, the owned fork is a remote named `fork`."""
    _git_init(tmp_path / "r", remotes={
        "origin": "https://github.com/23blocks-OS/ai-maestro.git",
        "fork": "https://github.com/Emasoft/ai-maestro.git",
    })
    monkeypatch.setattr(fstat, "_gh_user", lambda: "Emasoft")

    g = fstat._git(str(tmp_path / "r"))
    assert g["origin"] == "23blocks-OS/ai-maestro", "origin is still reported faithfully"
    assert g["yours"] == "Emasoft/ai-maestro", "the OWNED repo must be found by owner, not name"
    assert "fork → Emasoft/ai-maestro" in g["remotes"], "every remote stays visible in the tooltip"


def test_ownership_is_case_insensitive_and_absent_gh_user_yields_no_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unresolvable gh user must mean UNKNOWN, never 'you own nothing' — the latter would
    silently drop the G11.2 warning flag on every row."""
    _git_init(tmp_path / "r", remotes={"origin": "https://github.com/EMASOFT/thing.git"})
    monkeypatch.setattr(fstat, "_gh_user", lambda: "emasoft")
    assert fstat._git(str(tmp_path / "r"))["yours"] == "EMASOFT/thing"

    monkeypatch.setattr(fstat, "_gh_user", lambda: "")
    assert fstat._git(str(tmp_path / "r"))["yours"] == "—"


def test_flags_warn_when_origin_is_not_the_repo_you_own() -> None:
    row = {"diag": "healthy", "armed": "yes", "ci": "success", "prrd": "ok", "ghsec": "0 open",
           "uncommitted": "0", "kanban": {}, "origin": "23blocks-OS/ai-maestro",
           "yours": "Emasoft/ai-maestro"}
    assert "NOT yours" in fstat._flags(row)


def test_flags_stay_quiet_when_origin_is_your_own_repo() -> None:
    row = {"diag": "healthy", "armed": "yes", "ci": "success", "prrd": "ok", "ghsec": "0 open",
           "uncommitted": "0", "kanban": {}, "origin": "Emasoft/thing", "yours": "Emasoft/thing"}
    assert "NOT yours" not in fstat._flags(row)


# ── 2 + 3. nested repositories ────────────────────────────────────────────────────────


def test_a_submodule_whose_dotgit_is_a_FILE_is_still_found(tmp_path: Path) -> None:
    """THE regression: `isdir` skipped every submodule and linked worktree."""
    root = tmp_path / "proj"
    _git_init(root, remotes={"origin": "https://github.com/Emasoft/proj.git"})
    sub = root / "plugins" / "thing"
    sub.mkdir(parents=True)
    (sub / ".git").write_text("gitdir: ../../.git/modules/plugins/thing\n")

    found = dict(fstat._nested_repos(str(root)))
    assert "plugins/thing" in found, "a .git FILE is a repository too"


def test_a_project_whose_root_is_not_a_repo_adopts_its_nested_one(tmp_path: Path) -> None:
    """The EMASOFT-ASSISTANT-MANAGER shape — previously reported as having no version control."""
    root = tmp_path / "workspace"
    root.mkdir()
    _git_init(root / "the-agent", remotes={"origin": "https://github.com/Emasoft/the-agent.git"})

    g = fstat._git(str(root))
    assert g["origin"] == "Emasoft/the-agent", "must not report — for a project that has a repo"
    assert g["branch"] == "main"
    assert "root not a repo" in g["subrepos"], "and must say WHERE that repo came from"


def test_nested_scan_skips_dependency_and_dev_directories(tmp_path: Path) -> None:
    """A vendored checkout under node_modules/ or a gitignored *_dev/ tree is not a sub-project."""
    root = tmp_path / "proj"
    _git_init(root, remotes={"origin": "https://github.com/Emasoft/proj.git"})
    for noise in ("node_modules/dep", "downloads_dev/vendored"):
        d = root / noise
        d.mkdir(parents=True)
        (d / ".git").mkdir()

    assert fstat._nested_repos(str(root)) == []


# ── 4. one row per janitor ────────────────────────────────────────────────────────────


def test_processes_sharing_a_project_collapse_to_one_row() -> None:
    fleet = [_Inst(pid=1, project_root="/a"), _Inst(pid=2, project_root="/a"),
             _Inst(pid=3, project_root="/b")]
    grouped = fstat._group_by_root(fleet)

    assert [root for root, _g in grouped] == ["/a", "/b"], "scan order preserved for the sort"
    assert [len(g) for _root, g in grouped] == [2, 1], "no instance is dropped, only merged"


def test_grouping_keeps_every_pid_so_nothing_is_hidden() -> None:
    fleet = [_Inst(pid=7, project_root="/a"), _Inst(pid=9, project_root="/a")]
    (_root, group), = fstat._group_by_root(fleet)
    assert sorted(i.pid for i in group) == [7, 9]


# ── 5. the session column never says "inactive" ───────────────────────────────────────


@pytest.mark.parametrize("diagnosis", ["healthy", "frozen", "cron_dead", "version_mismatch",
                                       "unarmed", "dead"])
def test_no_diagnosis_ever_renders_as_inactive(diagnosis: str) -> None:
    state = fstat._run_state(_Inst(diagnosis=diagnosis), server_up=True)
    assert "inactive" not in state.lower()
    assert state.strip() not in ("", "no", "—")


def test_a_working_session_says_working() -> None:
    assert fstat._run_state(_Inst(active=True), server_up=True) == "working"


def test_disarmed_is_named_as_the_deliberate_opt_out_it_is() -> None:
    assert "disarmed" in fstat._run_state(_Inst(diagnosis="unarmed"), server_up=True)


def test_an_aimaestro_agent_with_the_server_down_is_STOPPED_not_idle() -> None:
    """The owner's distinction: a stopped agent RESUMES when the server returns; a hibernated
    one does not. Calling this 'idle' hides that the whole fleet is waiting on one process."""
    agent = _Inst(terminal={"aimaestro_session": "abc"})
    assert "STOPPED" in fstat._run_state(agent, server_up=False)
    assert "auto-resumes" in fstat._run_state(agent, server_up=False)


def test_the_same_agent_with_the_server_up_is_merely_idle() -> None:
    agent = _Inst(terminal={"aimaestro_session": "abc"})
    assert "STOPPED" not in fstat._run_state(agent, server_up=True)


def test_hibernated_is_never_claimed_because_it_cannot_be_observed() -> None:
    """Guessing 'hibernated' would tell a human a recoverable session is a parked one."""
    for server_up in (True, False):
        for diagnosis in ("healthy", "frozen", "cron_dead", "unarmed", "dead"):
            inst = _Inst(diagnosis=diagnosis, terminal={"aimaestro_session": "x"})
            assert "hibernat" not in fstat._run_state(inst, server_up=server_up).lower()


# ── the folder column ─────────────────────────────────────────────────────────────────


def test_folder_column_is_relative_to_home_so_the_dashboard_can_be_shared() -> None:
    home = str(Path.home())
    assert fstat._tilde(home + "/Code/thing") == "~/Code/thing"
    assert fstat._tilde("/opt/elsewhere") == "/opt/elsewhere", "paths outside home are untouched"
