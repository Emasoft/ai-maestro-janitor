# Shared git helpers — Python port of scripts/lib/git-utils.sh.
#
# Stdlib-only: subprocess + pathlib. Functions are cwd-respecting (each
# detector cds into the project root before calling) but `scope_tracking_status`
# resolves the project root itself via state.project_root() so callers can
# stay cwd-agnostic.

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

# When this module is loaded by a PEP 723 detector, the detector prepends
# scripts/lib/ to sys.path. When loaded any other way (tests, REPL),
# self-bootstrap to find sibling modules.
_LIB_DIR = str(Path(__file__).resolve().parent)
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

import state  # noqa: E402  (after sys.path bootstrap)


def _git(
    *args: str, cwd: Optional[Path] = None, _stdin: Optional[str] = None
) -> subprocess.CompletedProcess[str]:
    """Run a git command with text output, never raises on non-zero.

    Centralised so we get consistent capture behaviour. Callers inspect
    .returncode and .stdout themselves. `_stdin` feeds a payload to commands that
    read one (`check-ignore --stdin`) so a large batch costs ONE fork instead of
    one per item; it is underscore-prefixed to keep it out of the *args passthrough.

    Every call here is read-only, so the child gets `GIT_OPTIONAL_LOCKS=0`
    (janitor#245): `git status`/`git diff` still WRITE `.git/index.lock` for
    their optional stat-cache write-back, and that collided with a concurrent
    `publish.py` commit — a read-only helper must never contend for that lock.
    """
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd is not None else None,
        input=_stdin,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def is_squash_merged(branch_ref: str, base_ref: str, cwd: Optional[Path] = None) -> bool:
    """Detect whether <branch_ref> was squash-merged into <base_ref>.

    Plain `git branch --merged` and `git merge-base --is-ancestor` only
    catch branches whose tip commit appears in <base_ref>'s history.
    Squash-merge does NOT preserve the branch tip — it lands a single new
    commit on the base whose tree captures the cumulative diff — so those
    checks miss it. Without this helper, every squash-merged branch would
    be permanently flagged as "unmerged" by worktree-janitor and
    pr-reconciler, producing persistent false-positive drift lines that
    erode user trust.

    Algorithm (canonical `git-delete-squashed` pattern):

      1. Find the merge base mb = git merge-base <branch> <base>.
      2. Construct a synthetic commit S with the BRANCH's tree, parented at
         the merge base. S represents "what a squash of <branch> onto mb
         would look like as a single commit".
      3. Run `git cherry <base> S` — git lists each commit reachable from S
         but not from <base> (so just S itself) and prefixes each line with
         '-' if a commit with the SAME patch-id already exists in <base>'s
         history, '+' otherwise. A '-' means S's diff is already in <base>,
         i.e. <branch> was squash-merged.

    This works even when <base> has additional commits AFTER the squash
    merge (the tree-equality approach in earlier drafts of the helper
    missed that case). False negatives only happen on heavy rebases that
    change patch-ids — which is the safe direction (caller's --is-ancestor
    check stands in, no false flagging).
    """
    if not branch_ref or not base_ref:
        return False

    # Resolve both refs; bail if either is unknown.
    branch = _git("rev-parse", "--verify", "--quiet", branch_ref, cwd=cwd)
    if branch.returncode != 0:
        return False
    branch_sha = branch.stdout.strip()

    base = _git("rev-parse", "--verify", "--quiet", base_ref, cwd=cwd)
    if base.returncode != 0:
        return False
    base_sha = base.stdout.strip()

    # Empty branch (tip equals base) is not "squash-merged" — it has
    # nothing to merge. Caller's existing --is-ancestor check handles this
    # correctly, but we add a guard to avoid producing a confusing positive.
    if branch_sha == base_sha:
        return False

    # If branch is a regular ancestor, the caller's --is-ancestor check
    # already returned true and we wouldn't be invoked. Returning False
    # here is harmless — we trust the caller to have run --is-ancestor first.
    if _git("merge-base", "--is-ancestor", branch_sha, base_sha, cwd=cwd).returncode == 0:
        return False

    mb_proc = _git("merge-base", branch_sha, base_sha, cwd=cwd)
    if mb_proc.returncode != 0:
        return False
    mb = mb_proc.stdout.strip()
    if not mb:
        return False

    tree_proc = _git("rev-parse", "--verify", "--quiet", f"{branch_ref}^{{tree}}", cwd=cwd)
    if tree_proc.returncode != 0:
        return False
    branch_tree = tree_proc.stdout.strip()

    # `git commit-tree` writes a new commit object referencing branch_tree
    # as its tree and mb as its parent. The commit message is irrelevant;
    # we only need the SHA so `git cherry` can compute its patch-id.
    syn_proc = _git("commit-tree", branch_tree, "-p", mb, "-m", "_janitor_squash_probe_", cwd=cwd)
    if syn_proc.returncode != 0:
        return False
    synthetic = syn_proc.stdout.strip()
    if not synthetic:
        return False

    # `git cherry <upstream> <head>` prints one line per commit in
    # <upstream>..<head>, prefixed with '-' if the commit's patch-id matches
    # something on <upstream>, '+' if it's unique. We pass <base_ref> as
    # upstream and our synthetic commit as head, so a single line comes back.
    cherry = _git("cherry", base_ref, synthetic, cwd=cwd)
    if cherry.returncode != 0:
        return False

    # `- <sha>` means the synthetic patch is already in base → squash-merged.
    return cherry.stdout.lstrip().startswith("- ")


# Tracking-status return tokens. Kept as plain strings (not an Enum) so the
# values match the bash port verbatim — detector code that pattern-matches
# on these strings (and the test fixtures asserting them) keeps working.
TRACKED = "tracked"
GITIGNORED = "gitignored"
AMBIGUOUS = "ambiguous"
MISSING = "missing"
NO_REPO = "no-repo"


def scope_tracking_status(rel: str) -> str:
    """Probe git tracking status of `rel` (relative to project root).

    Returns one of:
      - TRACKED     — file is in `git ls-files`
      - GITIGNORED  — file is matched by a `.gitignore` rule
      - AMBIGUOUS   — file exists on disk but is neither tracked nor ignored
      - MISSING     — file does not exist on disk (no nudge needed)
      - NO_REPO     — project root is not a git repo

    Shared primitive driving every "scope drift" detector
    (mcp-config-drift, settings-scope-drift, subagent-scope-drift,
    claude-md-scope-drift). Each detector applies its own policy on top:

      * `.mcp.json` and subagent files: either tracked OR gitignored is
        fine — only `ambiguous` is a problem.
      * `.claude/settings.json` / `CLAUDE.md`: SHOULD be tracked. Flag
        `gitignored` AND `ambiguous`.
      * `.claude/settings.local.json` / `CLAUDE.local.md`: SHOULD be
        gitignored. Flag `tracked` AND `ambiguous`.
    """
    root = state.project_root()
    if not (root / ".git").exists():
        # Cheap pre-check: a project with no .git/ at the root is not a
        # repo. We also confirm via git below so worktrees (where .git is
        # a file pointing into the main repo) still count as "in repo".
        rev = _git("rev-parse", "--git-dir", cwd=root)
        if rev.returncode != 0:
            return NO_REPO

    abs_path = root / rel
    if not abs_path.exists() and not abs_path.is_symlink():
        return MISSING

    # `--error-unmatch` makes `ls-files` fail loudly when the path is not
    # tracked; otherwise it silently prints nothing and exits 0.
    ls = _git("ls-files", "--error-unmatch", "--", rel, cwd=root)
    if ls.returncode == 0:
        return TRACKED

    # `-q` suppresses output; we only care about exit status.
    if _git("check-ignore", "-q", "--", rel, cwd=root).returncode == 0:
        return GITIGNORED

    return AMBIGUOUS


def drop_gitignored(paths: list[Path], *, root: Path) -> list[Path]:
    """Return `paths` minus the ones git ignores, order preserved (janitor#99).

    THE SHARED WALK FILTER for scanners that `rglob` a working tree. Without it a
    detector scores whatever happens to be on disk — including a DOWNLOADED RESEARCH
    CORPUS under gitignored `*_dev/` dirs — as if it were the project's own supply
    chain. Measured downstream on AgentlensPro: 313 of 313 binaries in the tree were
    gitignored, all under `downloads_dev/`, and `repo-trust-score` reported 393
    ("dropper-shape") for a repo whose TRACKED surface is clean. The tracked surface is
    what the project actually ships, so it is what a supply-chain scanner may judge.

    BATCHED — exactly one `git check-ignore --stdin` for the whole walk, never one
    subprocess per path. A heartbeat detector that forks 300+ times per fire is its own
    defect, and that is the scale this filter is for. `-z` on both ends so a path with a
    newline or a space in it cannot split a record.

    FAILS OPEN in every failure mode — git missing, not a repo, a git error, an
    unparseable answer: the input is returned UNCHANGED. Suppressing findings on an
    unreadable signal is the one direction a security scanner must never take, and it
    is the direction that looks like success (fewer findings) while being blind.
    """
    if not paths:
        return list(paths)  # no fork for an empty batch — the clean-tree common case
    try:
        proc = _git(
            "check-ignore", "-z", "--stdin",
            cwd=root,
            _stdin="\0".join(str(p) for p in paths) + "\0",
        )
    except OSError:
        return list(paths)  # git missing / unrunnable → fail OPEN
    # 0 = some path is ignored, 1 = none are, >=2 = a real error (not a repo, bad args).
    if proc.returncode >= 2:
        return list(paths)  # fail OPEN — never treat "cannot tell" as "not ignored"
    if proc.returncode == 1:
        return list(paths)  # nothing ignored
    ignored = {line for line in proc.stdout.split("\0") if line}
    return [p for p in paths if str(p) not in ignored]
