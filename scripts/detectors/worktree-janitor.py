#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Worktree janitor — Python port of worktree-janitor.sh.

Scans `git worktree list --porcelain` and reports worktrees whose branch
has been deleted or fully merged into origin/main.

Two safety rules baked in (issue #5, plugin v0.3.12):

  * Locked worktrees are NEVER reported. A `locked` line in the porcelain
    output means an agent or user actively owns the worktree (e.g. an
    in-flight `Agent({isolation: "worktree"})` run); a `--force` removal
    suggestion at that moment would destroy unsaved work.

  * The 'merged' check requires the branch to be a STRICT ancestor of
    origin/main, not just an ancestor. `git merge-base --is-ancestor A B`
    returns true when A == B, so a freshly-spawned branch that hasn't
    committed yet (still pointing at main HEAD) would otherwise be
    misreported as 'merged — prunable' and the suggested command would
    destroy the agent's just-started work.

We collect each porcelain block fully before deciding whether to emit,
because `locked` can appear after `branch` in the block.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import git_utils  # noqa: E402
import state  # noqa: E402


def _git(*args: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True, text=True, check=False,
    )


def _canonical(path: Path) -> Path:
    """Return the realpath if accessible, else the input unchanged.

    Canonicalisation matters because macOS /tmp vs /private/tmp symlink
    asymmetry would otherwise break the 'is this the primary worktree'
    comparison.
    """
    try:
        return path.resolve(strict=False)
    except OSError:
        return path


def _process_block(
    *,
    path_str: str,
    branch: str,
    locked: bool,
    main_sha: str,
    project_root_canon: Path,
    seen: Path,
) -> None:
    if not path_str:
        return
    path = Path(path_str)
    canonical_current = _canonical(path)

    # Skip the primary worktree — that's our active checkout.
    if canonical_current == project_root_canon:
        return

    # Locked worktree → in active use. Suggesting `git worktree remove --force`
    # here is the dangerous case the issue called out: a locked worktree
    # means an agent or user explicitly held the lock to protect work in
    # progress, and `--force` bypasses that lock.
    if locked:
        state.log_line("worktree-janitor", f"skipping locked worktree '{path_str}' (branch '{branch or '<detached>'}')")
        return

    # Detached HEAD — no branch ref to reason about. Skip rather than guess.
    if not branch:
        return

    # shell-quote path + branch for the emitted remediation command.
    # Worktree paths can contain spaces and git's check-ref-format accepts
    # branch names with `;`, `&`, `|`, and `$(...)`. Unquoted use of those
    # strings in the printed command would be a paste-and-run injection
    # vector for anyone who copies the suggestion blindly.
    safe_path = shlex.quote(path_str)
    safe_branch = shlex.quote(branch)

    # Branch ref deleted out from under the worktree.
    show_ref = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        capture_output=True, text=True, check=False,
    )
    if show_ref.returncode != 0:
        line = dedupe.emit_once(
            seen,
            f"gone@{path_str}@{branch}",
            f"[worktree-janitor] worktree {path_str} — branch '{branch}' no longer exists — prunable. "
            f"Run: git worktree remove --force {safe_path} && git worktree prune",
        )
        if line is not None:
            print(line)
        return

    # Branch fully merged into origin/main. STRICT ancestry only — branch_sha
    # MUST differ from main_sha, otherwise we'd flag fresh just-spawned
    # branches that still point at main HEAD because no commits have landed
    # yet. `git merge-base --is-ancestor A B` is true when A == B, so
    # without the equality guard the 'no work done yet' steady state is
    # conflated with 'fully merged'.
    if not main_sha:
        return

    branch_sha_proc = _git("rev-parse", f"refs/heads/{branch}")
    if branch_sha_proc.returncode != 0:
        return
    branch_sha = branch_sha_proc.stdout.strip()
    if not branch_sha or branch_sha == main_sha:
        return

    merge_kind = ""
    if _git("merge-base", "--is-ancestor", branch_sha, main_sha).returncode == 0:
        merge_kind = "merged"
    elif git_utils.is_squash_merged(f"refs/heads/{branch}", main_sha):
        merge_kind = "squash-merged"
    if not merge_kind:
        return

    # Safety gate 1: uncommitted changes inside the worktree.
    porcelain = _git("-C", path_str, "status", "--porcelain")
    if porcelain.stdout.strip():
        state.log_line("worktree-janitor", f"skipping {merge_kind} worktree '{path_str}' — has uncommitted changes")
        return

    # Safety gate 2: unpushed commits. Compare branch tip against its
    # configured upstream (if any). If no upstream is configured, fall
    # back to comparing against origin/<branch>; if that also doesn't
    # exist, conservatively skip (better a false silent than data loss).
    upstream = ""
    upstream_proc = _git("-C", path_str, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if upstream_proc.returncode == 0:
        upstream = upstream_proc.stdout.strip()
    if not upstream:
        if subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
            capture_output=True, text=True, check=False,
        ).returncode == 0:
            upstream = f"origin/{branch}"

    if not upstream:
        state.log_line(
            "worktree-janitor",
            f"skipping {merge_kind} worktree '{path_str}' — branch '{branch}' has no upstream tracking and no origin/<branch> — cannot verify all commits are safe",
        )
        return

    unpushed_proc = _git("-C", path_str, "rev-list", "--count", f"{upstream}..HEAD")
    unpushed = unpushed_proc.stdout.strip() if unpushed_proc.returncode == 0 else ""
    if unpushed and unpushed != "0":
        state.log_line(
            "worktree-janitor",
            f"skipping {merge_kind} worktree '{path_str}' — has {unpushed} unpushed commit(s) past {upstream}",
        )
        return

    line = dedupe.emit_once(
        seen,
        f"{merge_kind}@{path_str}@{branch}",
        f"[worktree-janitor] worktree {path_str} — branch '{branch}' is {merge_kind} into main — prunable. "
        f"Run: git worktree remove --force {safe_path} && git update-ref -d refs/heads/{safe_branch} && git worktree prune",
    )
    if line is not None:
        print(line)


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "worktree-janitor-seen.txt"
    project_root = state.project_root()

    if _git("rev-parse", "--git-dir", cwd=project_root).returncode != 0:
        state.log_line("worktree-janitor", "not a git repo — skipping")
        return 0

    main_sha_proc = _git("rev-parse", "origin/main", cwd=project_root)
    main_sha = main_sha_proc.stdout.strip() if main_sha_proc.returncode == 0 else ""

    project_root_canon = _canonical(project_root)

    porcelain_proc = _git("worktree", "list", "--porcelain", cwd=project_root)
    porcelain = porcelain_proc.stdout if porcelain_proc.returncode == 0 else ""

    # Parse porcelain format: blocks separated by blank lines, each carrying
    # `worktree <path>`, optionally `HEAD <sha>`, `branch <ref>` or
    # `detached`, plus optional `bare`, `locked [reason]`, `prunable`
    # lines. The order of `branch` and `locked` is not guaranteed, so
    # accumulate the full block before calling _process_block.
    current_path = ""
    current_branch = ""
    current_locked = False

    def flush() -> None:
        nonlocal current_path, current_branch, current_locked
        _process_block(
            path_str=current_path,
            branch=current_branch,
            locked=current_locked,
            main_sha=main_sha,
            project_root_canon=project_root_canon,
            seen=seen,
        )
        current_path = ""
        current_branch = ""
        current_locked = False

    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            flush()
            current_path = line[len("worktree "):]
        elif line.startswith("branch refs/heads/"):
            current_branch = line[len("branch refs/heads/"):]
        elif line == "locked" or line.startswith("locked "):
            current_locked = True
        elif line == "":
            flush()

    flush()

    state.rotate_log_if_big("worktree-janitor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
