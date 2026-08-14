# Shared git helpers — Python port of scripts/lib/git-utils.sh.
#
# Stdlib-only: subprocess + pathlib. Functions are cwd-respecting (each
# detector cds into the project root before calling) but `scope_tracking_status`
# resolves the project root itself via state.project_root() so callers can
# stay cwd-agnostic.

from __future__ import annotations

import errno
import os
import subprocess
import sys
import time
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


def run_git_readonly(
    cmd: list[str], *, cwd: Optional[Path] = None, timeout: Optional[float] = None
) -> subprocess.CompletedProcess[str]:
    """Run a READ-ONLY git invocation (`cmd` starts with "git") with
    `GIT_OPTIONAL_LOCKS=0`, so it never contends for `.git/index.lock`.

    The public, drop-in-friendly sibling of the module-private `_git` above —
    `_git(*args)` builds the argv for you (`["git", *args]`); this one takes the
    full argv (including `"git"`) so an existing `subprocess.run(["git", ...])`
    call site can switch to it with a one-line change. Same fix, same reason
    (janitor#245 — see `_git`'s docstring for the measured incident): `git
    status`/`git diff` WRITE `.git/index.lock` for an OPTIONAL stat-cache
    write-back even on a pure read, and that collided with a concurrent
    WRITER's real lock need. GIT_OPTIONAL_LOCKS=0 is git's own documented
    escape hatch for that write-back and is a no-op for every WRITE command
    (add/commit/push/mv/rm/checkout/reset/clean/tag) that legitimately needs
    the lock — so callers should reserve this helper for read-only argvs and
    keep write invocations going through a plain `subprocess.run`/`run()` that
    is allowed to take the lock.

    `tests/test_git_optional_locks_guard.py` is the drift guard that keeps
    every read-only git call site under `scripts/` routed through this
    (or an equivalent explicit `GIT_OPTIONAL_LOCKS=0`) pattern.
    """
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=env,
    )


def _lock_is_held(lock_path: Path) -> Optional[bool]:
    """PRIMARY guard (G0): does ANY process have `lock_path` open right now?

    Probes the LOCK FILE ITSELF via `lsof -a -- <lock_path>` — never a
    process-table scan. `_live_git_holds` (the belt-and-braces SECOND guard,
    below) only recognises a holder that shows up as a `git` command in a
    `ps` snapshot with a cwd inside `repo_root`. That misses a real, live
    holder: libgit2-based GUI clients (Fork, GitKraken, JetBrains' built-in
    git, several VS Code extensions) take `.git/index.lock` themselves with
    NO `git` executable in the process table at all — the cwd guard passes
    clean and this module would delete a LIVE lock out from under a running
    write. It also naturally covers `GIT_DIR=... git ...` invoked from a
    cwd outside `repo_root` (which the cwd guard's `git status` proxy could
    miss). Probing the file's own open-fd table sidesteps all of that: it
    does not care WHO opened the file, only WHETHER it is open.

    Returns:
      True  — `lsof` exits 0 with non-empty stdout: some process holds the
              file open right now. The caller must not remove it.
      False — `lsof` exits 1 with empty stdout: nothing holds it open.
              Falls through to the remaining (cwd + age) guards below —
              this probe ALONE is not sufficient, because git's lockfile
              API can briefly CLOSE the fd before it calls
              `commit_lock_file` to finalise the write, so a momentary
              "not held" reading does not itself prove the lock is
              abandoned. The age guard is the tie-breaker that makes that
              gap safe.
      None  — anything else: a non-0/1 exit code, an unparseable result,
              `lsof` missing, a timeout, or any other OSError. UNKNOWN, and
              the caller must fail CLOSED (refuse to remove) rather than
              silently falling back to the weaker cwd-only guard.
    """
    try:
        proc = subprocess.run(
            ["lsof", "-a", "--", str(lock_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode == 0 and proc.stdout.strip():
        return True
    if proc.returncode == 1 and not proc.stdout.strip():
        return False
    return None


def clear_stale_index_lock(
    repo_root: Path,
    *,
    min_age_s: float = 1800.0,
    ps_snapshot: Optional[str] = None,
) -> str:
    """Remove an ORPHANED `<repo_root>/.git/index.lock`, never raises.

    Owner ruling (janitor#245 follow-up): prevention (GIT_OPTIONAL_LOCKS=0 on
    every reader, above) stops READERS from ever taking the lock — but it
    cannot stop a WRITER (a real `git add`/`git commit`) from being SIGKILLed,
    crashing, or dying to an OOM guard mid-write, which leaves the lock file
    behind forever. An unattended run then stalls indefinitely on a lock
    nothing will ever release. This is the recovery half.

    This function's SOLE PRODUCTION CALLER is a heartbeat DETECTOR
    (`scripts/detectors/stale-index-lock.py`), not a write path. That is
    deliberate, not an oversight: the stalled writer is usually a FOREIGN
    process (a user's own `git commit`, a pre-commit hook, another tool
    entirely) that the janitor has no way to intercept or be called from —
    the only place this recovery CAN run is an independent, periodically
    firing observer. A write path calling this immediately before its own
    git invocation would only ever see its OWN lock (which it never left
    behind, being the process about to take it), so it would never have
    anything to recover.

    Why it is safe to remove WITHOUT asking a human: `.git/index.lock` is a
    transient marker file, never work product — git recreates it on its next
    write and its removal (`rm .git/index.lock`) is git's OWN documented
    recovery procedure for "fatal: Unable to create '.git/index.lock': File
    exists." The only real danger is removing a lock a *live* git process
    (or a libgit2-based GUI client — see `_lock_is_held`) still holds (that
    would corrupt its concurrent write), so this function is built around
    excluding exactly that case via guards that must ALL clear before
    anything is removed:

      0. `_lock_is_held(lock_path)` — the PRIMARY guard: is the lock FILE
         itself open by any process right now (`lsof`, not a `ps` scan)?
         True blocks removal outright (`"held"`). Unknown (lsof missing,
         errored, timed out) fails CLOSED — remove NOTHING (`"no-probe"`).
         Only False falls through to the guards below; see `_lock_is_held`'s
         own docstring for why this probe alone is not sufficient (git can
         briefly close the fd mid-write) and why the older cwd-based check
         is kept as a second, belt-and-braces guard rather than replaced.
      1. No LIVE git process that could HOLD *this repo's* lock appears in a
         `ps` snapshot. `ps_snapshot` may be INJECTED (which keeps the
         decision pure and unit-testable); when it is None we gather one
         ourselves with a bare `ps -eo pid,ppid,etime,command` and match in
         Python.

         That is the sanctioned snapshot-then-match shape. The thing to avoid
         is `pgrep -f` / `ps | grep`, where the scanning pipeline carries the
         search pattern in its OWN argv and so matches itself; a bare `ps`
         argv carries no pattern and its own command token is `ps`, so it
         cannot self-match.

         A git process whose CWD is a *different* repository cannot be
         holding `<repo_root>/.git/index.lock` — its own working tree has
         its own index. On a multi-session host (many terminals, many
         repos) there is almost always SOME `git` process running
         somewhere, so treating "any git process exists on the machine" as
         "this repo's lock is live" makes the guard refuse forever — a
         guard that always refuses is equivalent to no guard at all
         (janitor#245 follow-up: this was measured, not theorised — see
         `_live_git_holds` for the scoped check that replaced it). So each
         candidate pid's cwd is resolved and compared against `repo_root`:
         a pid whose cwd is confirmed to be OUTSIDE `repo_root` is excluded;
         only a pid whose cwd IS `repo_root` (or whose cwd could not be
         resolved at all — fail CLOSED, see `_live_git_holds`) blocks
         removal.

         **If the snapshot cannot be gathered we return `"no-snapshot"` and
         remove NOTHING.** Letting a missing snapshot silently skip this
         guard would leave the age check deciding alone — and a long-running
         live writer still holding a lock older than `min_age_s` is exactly
         the case guard 1 exists to exclude.
      2. The lock file is at least `min_age_s` OLD (by mtime). A FRESH lock
         means a real git process only just started writing (it may not have
         shown up in the ps snapshot yet, or the snapshot may be stale by a
         few hundred ms) — age is the tie-breaker that makes the race safe.
         A big `git add` or a slow pre-commit hook legitimately holds the
         lock for minutes, so the default is 30 minutes, not seconds.
      3. TOCTOU re-check: immediately before removing, the lock is re-stat'd
         and compared (inode + mtime) against the FIRST stat taken at the top
         of this call. Two sessions in the same project can both run this
         detector; if session A's guards clear on a genuinely orphaned lock
         but session B reaps it (or a fresh writer takes it) in the window
         between A's first stat and A's removal, the identity check catches
         it and A backs off (`"raced"`) instead of destroying a brand-new,
         live lock.

    Any guard failing means "do not remove" — that asymmetry is the whole
    safety property: wrongly refusing to remove a stale lock only costs the
    caller a retry; wrongly removing a live one corrupts a concurrent write.

    Removal itself RENAMES the lock aside (`index.lock.stale-<epoch>`, same
    directory, atomic `os.replace`) rather than unlinking it — git regains
    the ability to write immediately either way, but the renamed file stays
    on disk as a forensic trace of what was cleared and when, matching this
    project's "a recoverable action needs no human permission" philosophy
    (`~/.claude/rules/use-safe-delete.md`).

    Returns one of:
      "absent"      — no lock file exists; nothing to do (not an error).
      "held"        — `_lock_is_held` confirmed a live holder; left alone.
      "no-probe"    — `_lock_is_held` could not determine holder status
                      (lsof missing/errored/timed out); left alone
                      (fail-closed).
      "live-git"    — a git process that could hold THIS repo's lock (cwd
                      inside repo_root, or cwd unresolvable) appears in the
                      snapshot; left alone.
      "no-snapshot" — no snapshot could be gathered, so guard 1 could not be
                      evaluated; left alone (fail-closed).
      "too-young"   — the lock is younger than `min_age_s`; left alone.
      "raced"       — the lock's identity changed between the initial stat
                      and the removal step (TOCTOU); left alone.
      "removed"     — the lock was stale and ownerless; renamed aside.
      "error"       — the rename failed for a reason other than the lock
                      having already vanished (e.g. permission denied);
                      left alone (or in an indeterminate state — the error
                      is real and must not be reported as success).
    """
    lock_path = _resolve_git_dir(Path(repo_root)) / "index.lock"
    try:
        stat_result = lock_path.stat()
    except OSError:
        return "absent"

    # Guard 0 — PRIMARY: is the lock FILE itself open right now? See
    # `_lock_is_held`'s docstring for why this exists ALONGSIDE, not INSTEAD
    # of, the cwd-based guard below (a libgit2 GUI client vs. the momentary
    # fd-close gap in git's own lockfile API — each guard covers what the
    # other misses).
    held = _lock_is_held(lock_path)
    if held is True:
        return "held"
    if held is None:
        return "no-probe"
    # held is False: fall through to the belt-and-braces guards below.

    # Fail CLOSED: an absent snapshot must never degrade this into an age-only
    # decision (see guard 1 above) — gather one, and refuse if we cannot.
    if ps_snapshot is None:
        ps_snapshot = _gather_ps_snapshot()
    if ps_snapshot is None:
        return "no-snapshot"
    if _live_git_holds(ps_snapshot, Path(repo_root)):
        return "live-git"

    age_s = time.time() - stat_result.st_mtime
    if age_s < min_age_s:
        return "too-young"

    # Guard 3 — TOCTOU: re-stat immediately before removing. A DIFFERENT
    # inode, or the same inode with a changed mtime, means the file we are
    # about to remove is not the one all the guards above judged safe —
    # abort rather than risk destroying a fresh, live lock.
    try:
        restat = lock_path.stat()
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return "removed"  # vanished between checks — already cleared
        return "error"
    if restat.st_ino != stat_result.st_ino or restat.st_mtime != stat_result.st_mtime:
        return "raced"

    stale_path = lock_path.with_name(f"index.lock.stale-{int(time.time())}")
    try:
        os.replace(lock_path, stale_path)
    except OSError as exc:
        # Only a confirmed "it's already gone" (ENOENT — another process, or
        # a concurrent recovery pass, cleared it first) may report success.
        # Any OTHER errno (EACCES/EPERM etc.) is a REAL failure and must be
        # reported as one — conflating them previously made a permission
        # error look like a successful removal.
        if exc.errno == errno.ENOENT:
            return "removed"
        return "error"
    return "removed"


def _resolve_git_dir(repo_root: Path) -> Path:
    """The real git dir for `repo_root` — `<root>/.git`, or what it POINTS AT.

    In a LINKED WORKTREE `.git` is a FILE containing `gitdir: <path>`, and the
    index (and therefore `index.lock`) lives at that path, not under the
    worktree. Treating `.git` as a directory unconditionally would make every
    lookup in a worktree return "absent" — a silent no-op that looks exactly
    like "there is no stale lock", which is the failure mode this whole module
    exists to avoid. This repo is routinely worked in worktrees, so that is the
    common case, not an exotic one.

    Falls back to `<root>/.git` whenever the pointer cannot be read, so a
    malformed file degrades to the ordinary layout rather than raising.
    """
    dot_git = repo_root / ".git"
    try:
        if dot_git.is_file():
            text = dot_git.read_text(encoding="utf-8", errors="replace").strip()
            if text.startswith("gitdir:"):
                target = Path(text.split(":", 1)[1].strip())
                # A relative pointer is relative to the worktree root.
                return target if target.is_absolute() else (repo_root / target).resolve()
    except OSError:
        pass
    return dot_git


def _gather_ps_snapshot() -> Optional[str]:
    """A process-table snapshot as TEXT, or None when it cannot be taken.

    A bare `ps` argv — no pattern, no shell, no pipe — so the scan cannot match
    itself the way `pgrep -f <pat>` / `ps | grep <pat>` do (there, the scanning
    process carries `<pat>` in its own argv). Returning None on ANY failure is
    what makes the caller's fail-closed branch reachable: a snapshot we could
    not take must never read as "no git is running".
    """
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid,ppid,etime,command"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout


def _live_git_pids(ps_snapshot: str) -> list[int]:
    """The pids of every running `git` process in `ps_snapshot`.

    Matches on the COMMAND column (basename of any argv token equal to "git"
    exactly — never a substring match, so a path like `/Users/x/git-utils.py`
    is not mistaken for the `git` executable), returning the pids so
    `_live_git_holds` can go on to ask WHERE each one is running.
    """
    pids: list[int] = []
    for line in ps_snapshot.splitlines():
        fields = line.split()
        if not fields:
            continue
        # fields[0] is pid, fields[1] ppid, fields[2] etime — a header line
        # ("PID PPID ELAPSED COMMAND") fails the int() conversion and is
        # skipped, same as any other unparseable line.
        try:
            pid = int(fields[0])
        except ValueError:
            continue
        # The COMMAND column starts after pid, ppid, etime — but etime can
        # itself contain no spaces (e.g. "01:23:45"), so fields[3] is the
        # start of the command for a well-formed `ps -eo pid,ppid,etime,command`
        # line. Match on the basename of that token (or the next token, for a
        # command invoked as `/usr/bin/git ...`) equal to "git" exactly, or a
        # later argv token equal to "git" (covers `sh -c git ...` wrappers).
        command_tokens = fields[3:]
        for tok in command_tokens:
            base = tok.rsplit("/", 1)[-1]
            if base == "git":
                pids.append(pid)
                break
    return pids


def _pid_cwd(pid: int) -> Optional[Path]:
    """The current working directory of `pid`, or None if it cannot be resolved.

    Uses `lsof -a -p <pid> -d cwd -Fn` (the `-F` "field output" format: a `p<pid>`
    line followed by an `n<path>` line for the cwd file descriptor) rather than
    `lsof -p <pid> | grep cwd`, for the same reason the rest of this module
    avoids `ps | grep`-shaped pipelines — no shell, no self-matching pattern,
    just a parseable machine format. Returns None on ANY failure (binary
    missing, pid gone, permission denied, timeout, unparseable output) — the
    caller (`_live_git_holds`) treats an unresolvable cwd as FAIL CLOSED
    (i.e. "assume it could be holding our lock"), so returning None here must
    never be conflated with "confirmed outside the repo".
    """
    try:
        proc = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        if line.startswith("n"):
            candidate = line[1:].strip()
            if candidate:
                try:
                    return Path(candidate).resolve()
                except OSError:
                    return None
    return None


def _live_git_holds(ps_snapshot: str, repo_root: Path) -> bool:
    """True iff SOME live `git` process in `ps_snapshot` could be holding
    `repo_root`'s `.git/index.lock` — i.e. its cwd is inside `repo_root`, or
    its cwd could not be positively confirmed to be elsewhere.

    A git process running in a DIFFERENT repository cannot hold THIS repo's
    index.lock (each repo has its own index), so on a multi-session host —
    where some unrelated `git status` in another project's terminal is
    almost always running — a bare "is any git process alive anywhere on the
    machine" check would refuse removal forever (an earlier, unscoped
    version of this guard did exactly that). A guard that always refuses is
    equivalent to no guard at all, so this is the scoped replacement — guard
    1 of `clear_stale_index_lock`.

    The asymmetry that keeps this safe: exclude a pid ONLY when its cwd is
    resolved AND positively outside `repo_root`. Every other case — cwd
    resolves inside `repo_root`, or cwd could not be resolved at all — is
    treated as "might hold the lock" and blocks removal. An unresolvable cwd
    fails CLOSED (counts as blocking) rather than being silently excluded,
    because "I could not find out" must never read as "confirmed safe" for a
    guard whose only job is preventing a live writer's lock from being
    deleted out from under it.
    """
    root = repo_root.resolve()
    for pid in _live_git_pids(ps_snapshot):
        cwd = _pid_cwd(pid)
        if cwd is None:
            return True  # fail closed: could not confirm this pid is elsewhere
        try:
            cwd.relative_to(root)
        except ValueError:
            continue  # positively outside repo_root — cannot hold our lock
        return True  # cwd is inside repo_root — treat as holding the lock
    return False


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
