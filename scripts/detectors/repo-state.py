#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Repo-state detector (TRDD-DG2V7D5P) — reports branch ahead/behind origin and
unreleased commits on the default branch.

Nothing computed ahead/behind before this: main sat 157 commits past the last
release on 2026-09-24 and no detector noticed. THREE findings — the first two
advisory, the third severity-bearing:

1. ahead/behind: the current branch vs its upstream. Behind means a stale
   checkout; ahead means unpublished work. Skipped entirely when no upstream
   is configured (fresh local repo, or a repo cloned without an origin).
2. outside-publish commits: default-branch commits newer than the newest
   `v*` release tag. publish.py marks a release two ways — it creates the
   version-bump commit with subject exactly `chore: bump version to <semver>`
   and tags the release `v<semver>`. So "made through publish.py" resolves to
   (reachable from a v* tag) OR (subject is the bump subject); anything else
   newer than the newest v* tag is unreleased work that never went through the
   publish gate. Deliberately conservative: an ordinary commit made BETWEEN
   releases is normal workflow, so this reports an informational count rather
   than an alarm, and dedupes on (tag, count) so the same state does not
   re-nag every hour.

3. release-gap escalation (TRDD-03G3CSUU): the OUT gap itself is a third
   finding, computed from this repo's OWN tag history rather than a fixed
   number of days. The bar is the repo's historical maximum release interval,
   recomputed from the tag history at detection time. It is the maximum over
   COMPLETED intervals only — the currently-open gap has no successor release
   date, contributes NO interval, and cannot enter the bar WITHIN the episode
   it is open in (that is why a max-over-completed-intervals rule does not
   self-contaminate WITHIN an episode; a ROLLING max over recent history
   would, and must not be introduced here). ACROSS episodes the bar CAN
   ratchet: when a gap that EXCEEDED the bar closes, that completed interval
   becomes the new maximum, so a repo whose releases are getting slower
   raises its own bar for the next cycle — and a repo that releases badly
   becomes progressively harder to warn about. A gap that closed UNDER the bar
   leaves the bar unchanged. That is the card's "the repo's historical
   maximum" rule, and it is a property of the rule, not an accident. The bar
   is a max over the FULL retained history, so
   it never falls: a repo that slows down does NOT raise its own bar when it
   slows, only once the slow interval has closed and entered the history.

   Owner knobs (state.coerce_int, so a malformed value degrades to the
   default instead of raising inside a detector):
   - CLAUDE_PLUGIN_OPTION_RELEASE_GAP_MAX_DAYS — an ABSOLUTE override for the
     computed bar; when set and valid it replaces the self-calibrating bar.
     Unset or unparseable -> the computed bar is used.
   - CLAUDE_PLUGIN_OPTION_RELEASE_GAP_MIN_COMMITS — the size floor, default 5.
     The floor is a FLOOR, not a conjunct for the rule's spirit: age is the
     operative signal and the floor's only job is to keep a lightly-dirty
     tree (1-4 unreleased commits) quiet, so 5 is low enough that "a handful
     of commits" still clears it. The owner can raise it to be more
     conservative.

   No options-documentation file exists for CLAUDE_PLUGIN_OPTION_* vars in
   this repo (checked: README.md, CHANGELOG.md, docs/ — none name
   CLAUDE_PLUGIN_OPTION_REPO_STATE_INTERVAL either), so these are documented
   here by spec instruction.

   The escalated line is printed ONCE PER EPISODE, keyed on the release tag
   alone (f"gap@{tag}") in a SEPARATE seen-file, repo-state-gap-seen.txt —
   a day- or count-bearing key would re-fire daily, the exact shape the card
   forbids. The stdout line carries measurement-derived facts — the severity
   word, the unreleased commit COUNT (a number), the release TAG (matched by
   _TAG_NAME, so it cannot carry prose), the gap in DAYS and the bar in DAYS —
   plus ONE derived consequence (the running plugin cannot contain the counted
   commits, because no release contains them). NO commit subjects and NO
   branch name: commit subjects are arbitrary prose, and one containing
   "ERROR" or "FAIL" would make the line survive dispatch's _URGENT_LINE_RE
   quiet filter for a reason unrelated to the measurement (or a prose-free one
   be dropped despite being genuinely urgent). A branch name is repo-controlled
   prose too, and the count is measured on the RELEASE branch, so naming that
   branch would be a falsehood on any other repo. The one file name the
   stdout line carries, scripts/publish.py, is a FIXED LITERAL — not
   repo-controlled text. The advisory outside-publish line keeps its subjects
   — it is never severity-bearing, so it is unchanged.

   The ledger entry is recorded under the same once-per-episode gate, with
   actor="human": the agent can act (cut a release) only with the owner's
   authorisation, so the correct runtime classification is owner-only. The
   ledger is a NEXT-SESSION surface (severity-first, findings_ledger.
   surface_block), not a pager; the stdout half is what reaches the current
   session. Acceptance clause (5) — the TRDD-F3LVCQ39 actionability
   vocabulary — is NOT discharged here; actor="human" is the closest existing
   runtime marker, not that classification.
Read-only on the repo: every git call runs with GIT_OPTIONAL_LOCKS=0 so it
never takes .git/index.lock and cannot collide with a concurrent publish.py
commit (janitor#245, the named repro site).
"""

from __future__ import annotations

import datetime
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Locate scripts/lib relative to this file so the detector works regardless
# of the user's cwd. The same idiom is reused by every Python detector.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import findings_ledger  # noqa: E402
import state  # noqa: E402

# publish.py's own version-bump subject (scripts/publish.py: expected_subject
# = f"chore: bump version to {new_ver}"). A commit whose subject matches this
# was made by the publish pipeline, even before its release tag exists.
_BUMP_SUBJECT = re.compile(r"^chore: bump version to \d+\.\d+\.\d+$")

# A release tag: publish.py creates exactly `v<semver>` (tag = f"v{new_ver}").
# The capture groups are parsed for semver ordering in _last_release_tag_on.
_TAG_NAME = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

# THE LEDGER'S BUDGETS, restated here so the detector does not depend on
# another module's constants without saying so.
#
# `findings_ledger.MAX_MSG_CHARS` is 120 and the ledger truncates HARD,
# mid-word. `ref` is capped at 24. Both are the ledger's, not the
# detector's, and a field that overflows is cut without ceremony — so
# every value written into a ledger field from here is bounded BY
# CONSTRUCTION rather than hoped to fit.
_LEDGER_MSG_MAX = 120
_LEDGER_REF_MAX = 24

# A commit subject is UNBOUNDED — this repo's own history runs to 643
# characters (measured over 5795 commits: min 21, p50 90, p99 265, max
# 643), and 950 of the 5795 exceed the ledger's 120-character budget. So
# a subject can never be written into a ledger field whole, and the
# number that matters is the COUNT of subjects over the budget, not one
# subject's length.
_SUBJECT_MAX = 40

# A branch name is repo-controlled and unbounded too, so it is bounded
# explicitly for the same reason.
_BRANCH_MAX = 40


def _ledger_msg(*, count: int, branch: str, tag: str, subjects: list[str]) -> str:
    """Build the outside-publish finding's ledger message, PROVABLY bounded.

    The ledger's `msg` is capped at 120 characters and truncates HARD,
    mid-word, so a message that merely HAPPENS to fit on the fixtures
    is not a message that fits: the branch name is repo-controlled and
    unbounded, and a commit subject is unbounded too (this repo's own
    history runs to 643 characters).

    So the message is built to a FIXED budget, and the parts that must
    stay exact — the COUNT and the TAG — are never the parts at risk:
    the branch and each subject are truncated to their own explicit
    widths, and the subject list is dropped entirely if what remains
    will not fit. Every returned string is at most `_LEDGER_MSG_MAX`
    characters, which is what makes the guarantee a guarantee rather
    than an observation.
    """
    head = f"{count} commit(s) on {branch[:_BRANCH_MAX]} since release {tag}: "
    # The tag is repo-controlled too, so it is bounded — but it is the
    # finding's SUBJECT, so it is bounded LAST and only as a tail.
    room = _LEDGER_MSG_MAX - len(head) - 2
    if room <= 0:
        return head[:_LEDGER_MSG_MAX]
    # The OLDEST unreleased subject goes first: it is the EARLIEST work
    # that has been sitting unreleased, which is the one the owner most
    # needs to see. The list is in chronological order, so the head is
    # the oldest.
    parts: list[str] = []
    for subject in subjects:
        piece = subject[:_SUBJECT_MAX]
        if not parts:
            if len(piece) > room:
                piece = piece[:room]
            parts.append(piece)
        else:
            candidate = "; ".join(parts + [piece])
            if len(candidate) > room:
                break
            parts.append(piece)
    if not parts:
        return head[:_LEDGER_MSG_MAX]
    return (head + "; ".join(parts))[:_LEDGER_MSG_MAX]


def _git_env() -> dict[str, str]:
    # GIT_OPTIONAL_LOCKS=0 — see module docstring (janitor#245).
    git_env = dict(os.environ)
    git_env["GIT_OPTIONAL_LOCKS"] = "0"
    return git_env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run a read-only git command in `repo`; None only if git itself is missing."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=_git_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _resolve_repo(project_root: Path) -> Path | None:
    """The repo to report on: the project root, or its tracked-repo delegate."""
    proc = _git(project_root, "rev-parse", "--git-dir")
    if proc is not None and proc.returncode == 0:
        return project_root
    tracked = state.tracked_repo(str(project_root))
    return tracked


def _ahead_behind(repo: Path, branch: str) -> tuple[int, int] | None:
    """(behind, ahead) of the branch's upstream, or None when no upstream exists."""
    proc = _git(repo, "rev-list", "--left-right", "--count", f"{branch}@{{upstream}}...{branch}")
    if proc is None or proc.returncode != 0:
        # No upstream configured (or branch has none) — an informational skip,
        # not an error: fresh local repos and detached checkouts are normal.
        return None
    try:
        behind_s, ahead_s = proc.stdout.split()
        return int(behind_s), int(ahead_s)
    except ValueError:
        return None


def _current_branch(repo: Path) -> str | None:
    proc = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if proc is None or proc.returncode != 0:
        return None
    branch = proc.stdout.strip()
    return branch or None  # "HEAD" when detached — still reportable


def _release_branch(repo: Path) -> str | None:
    """The branch releases are cut from — the remote's default branch.

    The escalated line claims the RUNNING BUILD is older than the working
    tree, and that claim is about what a release would contain. So the count
    must be measured on the release line, not on whatever branch happens to
    be checked out: on a feature branch, `git log tag..feature` counts work
    nobody intends to release, and the line would attribute a stale-install
    alarm to it.

    Resolved from `origin/HEAD` (the remote's own pointer at its default
    branch) but taken as the LOCAL branch of that name: `origin/main` is the
    REMOTE's tip, which is typically the last release, so counting on it
    would count the unreleased work as zero. The local `main` is where the
    next release is cut from, and it is what the running build lags behind.

    Returns None when the release line cannot be resolved. There is NO
    fallback to the checked-out branch: the fallback silently undid the
    round-4 fix that the count be measured on the release line — on a
    feature branch it measured work nobody intends to release, and the
    printed consequence ("the running plugin build is OLDER than the working
    tree") became a falsehood with no marker in the output, because the line
    deliberately carries no branch name. A caller that cannot resolve the
    release line must say so (an advisory), not measure something else.
    """
    proc = _git(repo, "rev-parse", "--abbrev-ref", "origin/HEAD")
    if proc is not None and proc.returncode == 0:
        name = proc.stdout.strip()
        if name and name != "origin/HEAD":
            local = name.split("/", 1)[1] if "/" in name else name
            # `returncode == 0`, NOT `is not None`: _git returns None only when
            # git itself is missing or timed out, so a MISSING branch comes
            # back as a CompletedProcess with a non-zero code. Checking
            # `is not None` accepted every branch name, and the rule then went
            # SILENT on a repo whose origin/HEAD names a branch it does not
            # have locally — "silent" being indistinguishable from "healthy".
            probe = _git(repo, "rev-parse", "--verify", local)
            if probe is not None and probe.returncode == 0:
                return local
    return None


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    """True when `ancestor` is an ancestor of `descendant` in the commit DAG.

    `git log A..B` is a SET DIFFERENCE over the DAG, not "the commits since
    A": when A is not an ancestor of B the result includes A's own divergent
    history. The unreleased count must therefore be measured only against a
    release that IS on the branch — otherwise the number the escalated line
    states as fact is the size of a symmetric difference.
    """
    proc = _git(repo, "merge-base", "--is-ancestor", ancestor, descendant)
    return proc is not None and proc.returncode == 0


def _last_release_tag_on(repo: Path, branch: str) -> str | None:
    """Newest `v<semver>` tag whose commit is ON `branch`, or None.

    The branch-scoped counterpart of `_last_release_tag`. The "outside@"
    line names a release in its message ("N commit(s) on <branch> since
    release <tag>"), so the tag it names must be ON that branch — a tag
    from a divergent history makes the sentence a falsehood, and a set
    difference over a divergent history is not a count of unreleased work.

    Scoping the SEARCH to the branch, rather than guarding the whole line
    against an off-branch tag, keeps the signal: a branch that was cut
    before the newest release still has its OWN releases, and the count
    against those is exactly the staleness the line exists to report. The
    earlier guard — the newest tag ANYWHERE, and no report unless it is an
    ancestor of the branch — silenced the line entirely in that case,
    losing a true finding to satisfy an analogy with the release-gap rule,
    whose consequence is a claim about the RELEASE LINE rather than about
    the checked-out branch.

    ONE SUBPROCESS, NOT ONE PER TAG. The first version of this helper
    listed every tag with `for-each-ref` and then ran
    `git merge-base --is-ancestor` for EACH ONE — re-introducing exactly
    the cost that `_last_release_tag`'s own docstring records as a
    deliberately-cured regression (TRDD-GXXKAGY6 review cure 4: "a
    2000-tag repo would pay 2000 subprocess spawns per heartbeat"). The
    fix is that `git tag --merged <branch>` ALREADY returns exactly the
    RELEASE TAGS whose commit is reachable from the branch, so
    reachability needs no per-tag test at all. One call, then a semver
    max over the result.

    THE EQUIVALENCE HAS TWO HALVES, AND THEY ARE NOT INTERCHANGEABLE.
    The git command does the REACHABILITY, and it does it over COMMITS:
    `git tag --merged` reports the tags whose peeled commit is an
    ancestor of the branch, and it OMITS a tag that points at a tree or a
    blob outright (measured: on a repo with an annotated commit tag
    v1.0.0 and annotated TREE and BLOB tags v9.9.9 and v8.8.8, it
    returned only v1.0.0). The `_TAG_NAME` filter does the "RELEASE
    TAG" half, and it filters on the tag's NAME: it keeps `v1.2.3` and
    rejects `nightly-x` and `v1.2.3-rc1`.

    THE TWO MECHANISMS ARE ORTHOGONAL, AND NEITHER SUBSTITUTES FOR THE
    OTHER. The name filter does NOT exclude a tree or blob tag: a tag
    named `v9.9.9` that points at a tree passes `_TAG_NAME` perfectly
    (measured). The git command does NOT exclude a non-release-named
    tag: a `nightly-*` tag merged into the release line is reported by
    `git tag --merged` perfectly well. So the sentence "the filter, not
    the git command, is what makes the guarantee hold" is FALSE for one
    of the two cases, and true for the other.

    WHY THE NAME FILTER MUST STAY STRICT — and the consequence is
    SPECIFIC TO THIS MECHANISM, not to the bar. A looser filter would not
    merely inflate the bar; it would let `nightly-*` and rc tags be
    SUBTRACTED from the count, re-introducing exactly the
    non-release-marker defect that commit 82d16c3d fixed and that
    `test_release_gap_does_not_subtract_a_non_release_tag_on_the_release_line`
    pins. This file's own history records a past version that used a `v*`
    glob instead of the strict semver match; a glob admits `v1.2.3-rc1`
    and `v1.2.3-rc1`-shaped names, and that is precisely how the
    non-release-marker bug would come back. So a future change to the
    filter must keep the semver match.

    (One caveat on the strict match, so nobody assumes more than it
    gives: it does NOT reject every calendar-versioned tag. `v2024.10.31`
    HAS three numeric components and therefore MATCHES `_TAG_NAME`. A
    repository that versions its releases by calendar date would have
    those tags counted as releases — which is CORRECT for this file's
    purpose, since such a tag really is that repository's release.)

    Order by PARSED semver, for the same reason as `_last_release_tag`:
    two tags created within the same clock second tie on creatordate, and
    git's refname tiebreak is ASCENDING, so the OLDER tag would win.
    """
    proc = _git(repo, "tag", "--merged", branch)
    if proc is None or proc.returncode != 0:
        return None
    best: tuple[tuple[int, int, int], str] | None = None
    for line in proc.stdout.splitlines():
        name = line.strip()
        m = _TAG_NAME.match(name)
        if not m:
            continue
        ver = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if best is None or ver > best[0]:
            best = (ver, name)
    return best[1] if best else None


def _unreleased_subjects(repo: Path, tag: str, branch: str) -> list[str] | None:
    """Subjects of the UNRELEASED commits on `branch` since `tag`, oldest-first.

    UNRELEASED = on `branch`, since the reported release, and contained in NO
    RELEASE that is merged into `branch`.

    Returns None when the subtraction set cannot be determined — see (c).

    The last clause is what the tag subtraction buys. `git log A..B` is a SET
    DIFFERENCE over the DAG, so a commit that ANOTHER release already shipped
    — a backdated semver-newer tag pointing at a NEWER commit than the
    reported one — would be counted as unreleased work, and the escalated line
    would state a shipped commit as a backlog.

    THE SUBTRACTION IS LIMITED TO THE RELEASE TAGS MERGED INTO `branch`, and
    every part of that restriction is load-bearing.

    (a) ONLY TAGS MERGED INTO `branch` MAY BE SUBTRACTED. `git log A..B
    --not --tags` subtracts the commits reachable from EVERY tag, and
    `--tags` includes a tag cut on a SIDE branch. A side-branch tag's
    history usually CONTAINS release-line commits (the side branch forked
    from the release line), so subtracting it drops genuine unreleased
    release-line work: measured on a fixture with a side-branch tag,
    `--not --tags` reported 1 unreleased commit where the truth was 2,
    silently under-reporting the very quantity the escalated line states as
    a fact. The subtraction must therefore name the tags that are MERGED
    INTO the branch being measured (`git tag --merged <branch>`), which are
    the releases that shipped that branch's work. A tag on a side branch is
    not a release of the branch, and the commits it happens to contain are
    still unreleased ON IT.

    (b) ONLY RELEASE TAGS MAY BE SUBTRACTED — see `_release_line_tags`,
    which filters the merged set through the strict `_TAG_NAME` match. A
    non-release marker (a `nightly-*` tag, a `v1.2.3-rc1` candidate) sits
    on the branch between two releases and points AT a commit that was never
    shipped, so subtracting it removes genuine unreleased work: measured on
    a fixture with a nightly marker, the count came out 6 where the truth
    was 13.

    (c) WHEN THE SUBTRACTION SET CANNOT BE DETERMINED, MEASURE NOTHING.
    `git tag --merged` fails on a bad branch name (it exits 128 with
    "fatal: malformed object name"), and an empty set is ALSO what a repo
    with no tags returns. Those two cases are not the same, and treating
    them alike is a defect in the SAFE direction: with an empty `--not` set
    the subtraction removes nothing, so the count becomes the raw size of
    `tag..branch` — the PRE-C1 behaviour, which counts commits a release
    already shipped. The count would then overstate the backlog, and the
    line's consequence ("the running build is older than the tree") is
    still stated as fact. So the helper returns None for "the set is
    unknown" and an EMPTY LIST for "the set is known and empty", and this
    function refuses (returns None) in the first case.

    `branch` IS THE LINE BEING MEASURED, and the two call sites use it
    differently on purpose. The release-gap escalation passes the RELEASE
    line, because its printed consequence is a claim about what a release
    would contain. The older "outside@" line passes the CHECKED-OUT branch,
    because its message names that branch explicitly ("N commit(s) on
    <branch> since release <tag>"); for it, excluding release-tagged commits
    is what its own text already claims ("not in any release reachable from
    the branch, and not a version bump").

    The `tag..branch` range keeps the "since TAG" anchoring; the tag
    subtraction removes the commits those releases already shipped. On a
    healthy repo — one whose newest tag is the reported one — the two agree
    and the count is unchanged; the difference appears exactly where the
    naive form was wrong.

    THE COMMAND IS `git log`, NOT `git rev-list --no-commit-header`. Both
    accept the same `--not` set and produce the same subjects, but
    `--no-commit-header` is a git 2.33 (2021) addition and the plugin
    declares no minimum git version. On an older git the flag is rejected,
    `rev-list` exits non-zero, and the helper returned an empty list — the
    count collapses to zero and the rule goes SILENT on exactly the repos it
    exists to watch. `git log --format=%s` has no such dependency, and
    `git log` accepts `--not` exactly as `rev-list` does, so the version
    constraint buys nothing.

    The bump-subject exclusion is NOT applied here: the caller applies it, so
    the raw subject list and the "unreleased work" count stay separable.
    """
    release_tags = _release_line_tags(repo, branch)
    if release_tags is None:
        return None
    argv = [
        "log",
        "--format=%s",
        "--reverse",
        f"{tag}..{branch}",
    ]
    for release in release_tags:
        argv.append("--not")
        argv.append(release)
    proc = _git(repo, *argv)
    if proc is None or proc.returncode != 0:
        return None
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _release_line_tags(repo: Path, branch: str) -> list[str] | None:
    """The RELEASE tags that were cut FROM the release line, or None if unknown.

    These are the tags `git tag --merged <branch>` reports, FILTERED to the
    strict-semver release tags the rest of this file calls a release
    (`_TAG_NAME`). Every part of that filter is load-bearing.

    WHAT "MERGED INTO" MEANS, precisely: `git tag --merged <branch>` reports
    the tags whose PEELED COMMIT is an ancestor of the branch tip in the
    whole DAG — not a first-parent walk. So a tag cut on a hotfix branch
    that was later merged back into the release line IS in this set (correct:
    it did ship release-line work), and so is a tag on a commit that reached
    the tip only through a merge that was later REVERTED (a release-line
    commit that was in fact rolled back would be subtracted, removing it
    from the count). The set is "releases REACHABLE FROM the release line",
    which is not identical to "releases CUT FROM the release line" — the
    phrase this file uses elsewhere. The difference is narrow and the
    direction is safe: both the C1 and the non-release-marker fixes make the
    subtraction NARROWER, so the reachable-from set over-subtracts only in
    the revert case, and a reverted release is rare enough that the
    docstring records the imprecision rather than the code compensating for
    it.

    The merge half: a tag cut on a SIDE branch is NOT a release of the
    release line, and that distinction is load-bearing — see
    `_unreleased_subjects`, whose subtraction is limited to these tags so
    that a side-branch tag cannot silently remove genuine unreleased
    release-line work from the count.

    The semver half: `git tag --merged` returns EVERY tag whose commit is
    reachable from the branch, including NON-RELEASE markers — a nightly
    build tag, a `v1.2.3-rc1` candidate. Subtracting one of those removes
    the commits it points at, and a nightly marker sits on the release
    line between releases, so it removes GENUINE unreleased work: measured
    on a fixture with a non-semver tag dated between two releases, the
    count came out 6 where the truth was 13. (A CALENDAR-versioned tag is
    NOT in this class: `v2024.10.31` matches the strict semver match, so
    it is treated as the release it is.) The
    detector already insists on ONE definition of "release tag" everywhere
    else — the strict `_TAG_NAME` match, not a `v*` glob — because a glob
    would admit `v1.2.3-rc1` and inflate the bar with a tag that is never
    the reported one. The subtraction must use the SAME definition, or the
    count states a number that means something else.

    NONE MEANS "THE SET IS UNKNOWN", which is NOT the same as an empty list:
      * an empty list means the branch genuinely has no merged release tags
        (a repo with no tags at all) — the subtraction set is KNOWN to be
        empty, so there is nothing to subtract;
      * None means `git tag --merged` FAILED — a bad branch name (it exits
        128 with "fatal: malformed object name"), a corrupt tag ref, a
        git that errors. The set is UNKNOWN.

    The distinction is load-bearing because the two cases must be measured
    differently: with an unknown set, the caller must measure NOTHING
    (return None), because counting the raw range instead would OVERSTATE
    the backlog by including commits a release already shipped. Merging the
    two into one empty list is what made the earlier version of this helper
    over-report.

    Returns None when the branch cannot be resolved or the git call fails.
    """
    proc = _git(repo, "tag", "--merged", branch)
    if proc is None or proc.returncode != 0:
        return None
    return [
        line.strip()
        for line in proc.stdout.splitlines()
        if line.strip() and _TAG_NAME.match(line.strip())
    ]

_GAP_SEEN_NAME = "repo-state-gap-seen.txt"
_GAP_FLOOR_DEFAULT = 5
_GAP_SEV = "HIGH"


def _release_tags(repo: Path) -> list[tuple[tuple[int, int, int], str, str]]:
    """Every strict-semver release tag as (semver, name, YYYY-MM-DD), sorted by semver.

    One git call, one pass, and the SEMVER and the DATE are both available for
    every tag — so the rule can pick the release it reports by DATE (the
    newest one) while keeping the tag's own identity, instead of picking by
    semver and refusing to report when the two disagree.
    """
    proc = _git(repo, "for-each-ref", "--format=%(refname:short) %(creatordate:short)", "refs/tags/")
    if proc is None:
        return []
    rows: list[tuple[tuple[int, int, int], str, str]] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        name, date = parts
        m = _TAG_NAME.match(name)
        if m and date:
            rows.append(((int(m.group(1)), int(m.group(2)), int(m.group(3))), name, date))
    rows.sort()
    return rows


def _release_dates(repo: Path) -> list[str]:
    """Dates (YYYY-MM-DD, deduped, sorted) of all strict-semver release tags.

    The SAME tag set the reported tag is drawn from: a strict `v<semver>`
    match, not a `v*` glob. A glob would admit `v1.2.3-rc1` or `v1.2` — a
    release CANDIDATE and a two-component version — and such a tag would
    inflate the bar while never being the reported tag: two different
    definitions of "release tag" in one file.

    NOTE WHAT THE STRICT MATCH DOES *NOT* REJECT. `v2024.10.31` — a
    calendar-versioned tag — HAS three numeric components, so it MATCHES
    `_TAG_NAME` and is counted as a release. That is CORRECT here: a
    repository that versions its releases by calendar date really is
    publishing releases, and the bar and the reported tag are drawn from
    the same set, which is the property that matters here. A glob would
    additionally admit the shapes the strict match rejects, and THOSE are
    the ones that break the measurement.
    """
    return sorted({date for _ver, _name, date in _release_tags(repo)})



def _release_gap_bar(repo: Path) -> int | None:
    """The bar the release gap is measured against, or None when there is none.

    Two cases, read in this order:
      * the owner set CLAUDE_PLUGIN_OPTION_RELEASE_GAP_MAX_DAYS to a positive
        integer: that value IS the bar, measured or not. With no measured bar
        to replace it is an OWNER-SET bar — it has no measured provenance,
        because the default bar is the repo's own historical maximum and this
        repo has no completed interval to take a maximum of.
      * the owner set nothing and the repo has fewer than two release dates:
        there is NO bar, so the rule stays SILENT. Nothing is invented — there
        is no evidence such a repo releases slowly, and a fabricated default
        would either nag a young repo or mask a genuinely slow one.

    The override is read BEFORE the "not enough releases" early return, so the
    owner can rescue a repo that has fewer than two releases. Reading it
    afterwards made the knob unreachable for exactly the repos that had no
    other way to set a bar.
    """
    dates = _release_dates(repo)
    override = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_RELEASE_GAP_MAX_DAYS"), 0
    )
    if len(dates) < 2:
        # No completed interval, so no measured maximum to take. The owner's
        # absolute value is the only bar that can exist here.
        return override if override > 0 else None
    intervals = [
        (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days
        for a, b in zip(dates, dates[1:])
    ]
    bar = max(intervals)
    if override:
        bar = override
    return bar


def _newest_release_by_date(
    repo: Path, dates: list[str]
) -> tuple[str, str] | None:
    """The release tag with the NEWEST date, and that date — (name, YYYY-MM-DD).

    Selected by DATE, not by semver: a backdated or cherry-picked release tag
    carries an old creatordate, and picking by semver would measure the gap
    from a release that is not the latest. Among the tags sharing the newest
    date, the semver-highest wins — so two releases cut on the same day
    resolve to the later version, and the reported tag, the measured gap and
    the dedupe key are all the SAME identity.
    """
    if not dates:
        return None
    newest_date = dates[-1]
    candidates = [
        (ver, name)
        for ver, name, date in _release_tags(repo)
        if date == newest_date
    ]
    if not candidates:
        return None
    return max(candidates)[1], newest_date


def _release_gap(
    repo: Path, today: datetime.date, release_line: str
) -> tuple[int, int, str, int] | None:
    """Compute the release-gap finding for `repo`, or None if it does not fire.

    Returns (gap_days, bar_days, tag, unreleased commit count outside
    publish.py — the gate quantity, so the reported number and the floor are
    the same measure).

    The bar is the maximum over COMPLETED intervals — intervals between two
    consecutive release dates that both exist. The currently-open gap has no
    successor release date, contributes no interval, and cannot enter the bar,
    so it never inflates the threshold it is measured against. See
    `_release_gap_bar` for the two cases (owner override, or no bar at all).

    The bar is a max over the FULL retained history, so it never falls: a repo
    that slows down does NOT raise its own bar at the time it slows, only once
    the slow interval has closed and entered the history. Do not "fix" this
    into a rolling max over recent history — a rolling max fires on ordinary
    gaps and is the shape the card warns about.

    The gap is measured from the NEWEST RELEASE DATE (dates[-1]), and the
    reported tag is the release carrying that date — the spec's rule. A
    backdated or cherry-picked release tag carries an old creatordate, so
    picking the reported release by SEMVER instead would measure the gap from
    a release that is not the latest, and the dedupe key (the reported tag)
    would then name a release the gap was never measured from. Selecting by
    DATE keeps the measured gap, the reported tag and the dedupe key the SAME
    identity, so a new release always opens a new episode.

    The count is measured on the RELEASE line (the remote's default branch),
    resolved HERE from origin/HEAD. It must never be measured on the
    checked-out branch: the printed consequence is a claim about what a
    release would contain, and on a feature branch the count would include
    work nobody intends to release, making that claim a falsehood. When the
    release line cannot be resolved the rule REFUSES (returns None) instead
    of measuring something else.
    """
    dates = _release_dates(repo)
    bar = _release_gap_bar(repo)
    if bar is None:
        return None
    floor = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_RELEASE_GAP_MIN_COMMITS"),
        _GAP_FLOOR_DEFAULT,
    )
    newest_release = _newest_release_by_date(repo, dates)
    if newest_release is None:
        return None
    tag, tag_date = newest_release
    newest = datetime.date.fromisoformat(tag_date)
    if not _is_ancestor(repo, tag, release_line):
        # The reported release is NOT on the release branch (a release cut on
        # a side branch, or a tag applied to a commit outside this history).
        # `git log tag..branch` would then be a set difference over a divergent
        # history, and the number the line states as fact would be that
        # difference's size, not the count of unreleased work. Stay silent
        # rather than report a count that means something else.
        return None
    subjects = _unreleased_subjects(repo, tag, release_line)
    if subjects is None:
        # The subtraction set could not be determined (see `_release_line_tags`
        # clause (c)). Counting the raw range instead would OVERSTATE the
        # backlog by including commits a release already shipped, and the
        # line's consequence is stated as fact. Measure nothing.
        return None
    outside = [s for s in subjects if not _BUMP_SUBJECT.match(s)]
    if len(outside) < floor:
        return None
    gap = (today - newest).days
    if gap <= bar:
        return None
    return gap, bar, tag, len(outside)


def main() -> int:
    state.init_state()

    repo = _resolve_repo(state.project_root())
    if repo is None:
        state.log_line("repo-state", "project root is not a git repo and no .janitor/track-repo is registered — skipping")
        return 0

    seen = state.state_dir() / "repo-state-seen.txt"
    now = int(time.time())
    lines: list[str] = []

    gap_seen = state.state_dir() / _GAP_SEEN_NAME

    branch = _current_branch(repo)
    if branch is not None:
        counts = _ahead_behind(repo, branch)
        if counts is not None:
            behind, ahead = counts
            if ahead or behind:
                key = f"ab@{branch}@{behind}@{ahead}"
                msg = f"[repo-state] Branch {branch} is {ahead} commit(s) ahead and {behind} behind its upstream. Publish unreleased work through scripts/publish.py, or pull to update a stale checkout."
                line = dedupe.emit_once(seen, key, msg)
                if line:
                    lines.append(line)

        # The release named in this line's message must be ON the branch the
        # count is measured from: "N commit(s) on <branch> since release
        # <tag>" names a release the branch may not contain, and
        # `tag..branch` over a divergent history is a set difference whose
        # size is not a count of unreleased work.
        #
        # The tag is scoped to the BRANCH, not guarded against. An earlier
        # version took the newest tag ANYWHERE in the repo and suppressed
        # the line unless that tag happened to be an ancestor of the branch
        # — which silenced it entirely on a branch cut before the newest
        # release, losing a TRUE finding. The branch's OWN newest release
        # is the right reference point, and the count against it is exactly
        # the staleness this line exists to report. The release-gap rule
        # refuses to report across a divergent history because its
        # CONSEQUENCE is a claim about the RELEASE LINE; this line's claim
        # is about the checked-out branch, and the two are not the same
        # claim, so they do not need the same rule.
        # THIS LINE NAMES THE BRANCH, AND THE ESCALATED LINE MUST NOT —
        # the asymmetry is deliberate, and the reason belongs here. The
        # escalated line's consequence is a claim about the RELEASE LINE
        # ("a release would contain N commits"), so naming any branch
        # would be a falsehood on a repo whose release line is named
        # something else; it carries no branch name for that reason. THIS
        # line's claim is about the CHECKED-OUT branch, and it has always
        # said so in its first clause ("N commit(s) on <branch> since
        # release <tag>") — the branch here is not repo-controlled prose
        # appended to a measurement, it is WHAT WAS MEASURED. The
        # parenthetical repeats it because the subtraction is over the
        # releases reachable from that same branch.
        tag = _last_release_tag_on(repo, branch)
        if tag is not None:
            subjects = _unreleased_subjects(repo, tag, branch)
            if subjects is None:
                # The subtraction set is UNKNOWN, so the count is unknown.
                # Stating the raw range size would over-report the backlog.
                subjects = []
            outside = [s for s in subjects if not _BUMP_SUBJECT.match(s)]
            if outside:
                key = f"outside@{tag}@{len(outside)}@{now // 86400}"
                # NO COMMIT SUBJECTS IN THIS LINE. A commit subject is
                # arbitrary REPOSITORY-CONTROLLED text, and this line's fate
                # is decided by dispatch's quiet filter, which promotes any
                # line containing a severity word (CRITICAL, HIGH, ERROR,
                # FAIL…). So a subject reading "feat: FAIL unrelated prose"
                # would push a plain LOW advisory past quiet mode and into
                # the owner's face, for a reason that has nothing to do with
                # the measurement. MEASURED: with the subject in the line,
                # `_quiet_filter("repo-state", line)` KEEPS it; with an
                # ordinary subject it DROPS it. The escalated line has
                # always excluded subjects for this reason, and it has a
                # test asserting it. This line now matches.
                #
                # THE BRANCH NAME GOES TO THE LEDGER TOO. It is
                # REPOSITORY-CONTROLLED text on a FILTERABLE surface, and
                # the same reasoning that disqualified the subjects
                # disqualifies it: MEASURED, a branch named
                # `fix-error-handling` promotes this line past quiet mode,
                # and so does `critical-hotfix` — the branch name appears
                # in the message TWICE and either occurrence is enough. A
                # repository could choose to promote its own LOW advisory
                # into the owner's face, for a reason that has nothing to
                # do with the measurement. THE BRANCH IS A MEASUREMENT, NOT
                # A REASON TO TRUST IT: it is what the count was measured
                # on, so it is NECESSARY information — but necessary is not
                # safe, and the line's actionable content is the COUNT. The
                # escalated line avoids the problem by carrying no branch
                # name at all; this line now does the same, and the ledger
                # keeps the branch.
                msg = f"[repo-state] {len(outside)} commit(s) since release {tag} are NOT made through publish.py (not in any release, and not a version bump). Run scripts/publish.py to cut a release."
                line = dedupe.emit_once(seen, key, msg)
                if line:
                    lines.append(line)
                    # THE BRANCH AND THE SUBJECTS GO TO THE LEDGER, NOT TO
                    # STDOUT. The "which commits, on which branch" detail is
                    # what the owner needs to act, and it must survive — but
                    # it must not be in the FILTERABLE text, because both are
                    # repository-controlled and this line's fate is decided
                    # by dispatch's quiet filter. THE LEDGER'S `msg` FIELD,
                    # NOT `ref`: `ref` is capped at 24 characters and the
                    # ledger truncates HARD, mid-word, so the subjects (77
                    # characters here) would be reduced to a fragment. `msg`
                    # is capped at 120 and holds them in full.
                    try:
                        findings_ledger.record(
                            sev="LOW",
                            code="REPO-OUTSIDE-PUBLISH",
                            src="repo-state",
                            # THE COUNT, THE BRANCH, AND THE SUBJECTS —
                            # ALL THREE, AND ALL THREE BOUNDED BY
                            # CONSTRUCTION.
                            #
                            # The ledger's `msg` is capped at 120 characters
                            # and truncates HARD, mid-word, and this repo's
                            # OWN commit subjects are UNBOUNDED: measured
                            # over 5795 commits, min 21, p50 90, p99 265,
                            # max 643, and 950 of them exceed 120. So a
                            # subject can never be written whole, and a
                            # message that depends on the subjects' length
                            # can never be proven to fit.
                            #
                            # So every part is bounded: the branch to 40
                            # characters, each subject to 40, and the
                            # whole message to the ledger's own budget.
                            # The COUNT and the TAG are exact and never
                            # truncated — they are the finding's quantity
                            # and its subject, and truncating either would
                            # make the finding say something false.
                            #
                            # WHY THE SUBJECTS ARE HERE AND NOT ONLY IN
                            # THE LOG: `/janitor-findings` — the one
                            # user-facing way to browse findings — reads
                            # ONLY the ledger, and nothing in the codebase
                            # reads the detector's log. A finding whose
                            # detail lives where nobody looks is a finding
                            # nobody can act on. The log keeps the FULL
                            # subjects for anyone who wants them; the
                            # ledger keeps a BOUNDED excerpt where the
                            # owner will actually see it.
                            msg=_ledger_msg(
                                count=len(outside),
                                branch=branch,
                                tag=tag,
                                subjects=outside,
                            ),
                            ref=tag,
                            # `actor="human"` IS TRUE FOR THIS FINDING, and
                            # that is why it is set. The remedy is "cut a
                            # release", and the agent CANNOT cut one without
                            # the owner's authorisation — so the finding is
                            # one an agent structurally cannot act on, which
                            # is exactly what the field means. The escalated
                            # line sets it for the same reason.
                            #
                            # It ALSO dedupes the drift line on (code,
                            # content): without it the same finding is
                            # injected twice into the session, once as the
                            # quiet filter's ADVISORY-REPO-STATE record of
                            # the stdout line and once as this record. The
                            # ledger's "unread" is CURSOR-based, not
                            # content-based, so two different codes are two
                            # different injected lines for ONE finding.
                            #
                            # The dedup is a CONSEQUENCE of the semantic
                            # choice, not the reason for it. The reason is
                            # that the remedy needs the owner. (A finding
                            # that is NOT human-only must not set this field
                            # for a dedup reason: the directive it renders
                            # would be a lie.)
                            actor="human",
                        )
                    except Exception:  # noqa: BLE001 — a ledger failure must never break the detector
                        state.log_line(
                            "repo-state",
                            "could not record the outside-publish commit subjects",
                        )
                    # THE SUBJECTS, IN FULL, IN THE DETECTOR'S OWN LOG. The
                    # ledger holds a BOUNDED excerpt (see `_ledger_msg`),
                    # and the stdout line must not carry them at all (they
                    # are repository-controlled text on a surface the
                    # quiet filter scans). The log keeps them whole — and
                    # the log is NOT unbounded: `state.log_line` rotates
                    # it at 1 MiB and dispatch prunes it by age. It IS
                    # never scanned by the urgency override, which is the
                    # property that matters here.
                    state.log_line(
                        "repo-state",
                        f"outside-publish subjects on {branch} since {tag}: "
                        + " | ".join(outside[-10:]),
                    )

    # THE RELEASE-GAP BLOCK IS NOT NESTED INSIDE `if branch is not None:`.
    # The release-gap condition is a fact about the RELEASE LINE, so its
    # evaluation must not depend on whether the CHECKED-OUT branch could be
    # resolved — the two are unrelated: `origin/HEAD` names the remote's
    # default branch, while `_current_branch` reads the local HEAD. Nesting
    # the block under the checked-out branch made the whole feature — the
    # escalation AND its refusal — silently vanish whenever the local HEAD
    # was unreadable, which is precisely the "silent is indistinguishable
    # from healthy" failure this feature exists to end.
    #
    # The release line is what the release-gap condition is measured on.
    # When it cannot be resolved, the condition CANNOT BE EVALUATED — and
    # a silent None is indistinguishable from a healthy repo, which is the
    # exact failure mode this feature exists to end. So the refusal is
    # stated, as a LOW advisory, never as the HIGH escalation: nothing
    # was measured, so nothing escalates. The advisory is emitted only
    # when the repo HAS releases (otherwise there is no release-gap
    # condition to evaluate and nothing to refuse), and it is latched
    # through the same dedupe.emit_once as every other line, so it does
    # not repeat on every fire. It is forgotten as soon as the release
    # line resolves again, so a later breakage is reported afresh.
    release_line = _release_branch(repo)
    if release_line is None:
        if _release_dates(repo):
            key = "release-line-unresolved"
            msg = (
                "[repo-state] LOW: the release line could not be resolved "
                "(no origin/HEAD naming a local default branch), so the "
                "release-gap condition cannot be evaluated on this repo. "
                "Point origin/HEAD at the branch releases are cut from to "
                "restore the check."
            )
            line = dedupe.emit_once(seen, key, msg)
            if line:
                lines.append(line)
    else:
        dedupe.emit_forget(seen, "release-line-unresolved")

    # The release line is resolved ONCE, above, and passed in. Resolving
    # it a second time inside `_release_gap` would run the same
    # `git rev-parse` twice and could disagree with the advisory above
    # if a concurrent `git fetch` moved origin/HEAD between the two
    # calls — the advisory could say "resolved" while the escalation
    # says "unresolved". One resolution, one answer.
    #
    # The parameter is REQUIRED, so a caller cannot re-enter the
    # double-resolution path by forgetting it. When the line is unresolved
    # the rule measures nothing — the advisory above has already said so.
    gap = (
        _release_gap(repo, datetime.date.today(), release_line)
        if release_line is not None
        else None
    )
    if gap is not None:
        gap_days, bar, gap_tag, gap_count = gap
        key = f"gap@{gap_tag}"
        # The STDOUT line carries ONLY measurement-derived facts: the count
        # (a number), the tag (matched by _TAG_NAME, so it cannot carry
        # prose), the gap in days and the bar in days. NO branch name and
        # NO commit subjects: commit subjects are arbitrary prose, and one
        # containing "ERROR" or "FAIL" would make the line survive
        # dispatch's _URGENT_LINE_RE quiet filter for a reason unrelated
        # to the measurement (or a prose-free one be dropped despite being
        # genuinely urgent). A branch name is repo-controlled prose too,
        # and the count is measured on the RELEASE branch (the remote's
        # default branch), so naming that branch would be a falsehood on
        # any other repo.
        # THE PARENTHETICAL DESCRIBES THE MEASUREMENT, NOT AN INFERENCE
        # ABOUT THE AUTHOR. An earlier version said "not made through
        # publish.py", which is an INFERENCE from publish.py's own behaviour
        # (it makes exactly one commit, the version bump) that this detector
        # never verifies — and it read as an ACCUSATION ("you committed
        # outside the pipeline") when the measurement is "these commits have
        # not been released yet". It was also NARROWER than the measurement:
        # the count excludes everything contained in ANY release merged into
        # the release line, not merely "release-tagged" commits, so a commit
        # shipped by v1.1.0 is absent from the count without being itself
        # release-tagged. The wording now states what was measured.
        msg = (
            f"[repo-state] HIGH: RELEASE GAP ESCALATION — {gap_count} commit(s) since release {gap_tag} "
            f"are unreleased (not in any release reachable from the release line, "
            f"and not a version bump), "
            f"and the release is {gap_days} day(s) old, "
            f"versus this repo's historical maximum release interval of {bar} day(s). "
            f"The running plugin build is OLDER than the working tree: it cannot contain them. "
            f"Cut a release (scripts/publish.py) so the update carries them."
        )
        # The LEDGER message is a SEPARATE, shorter string: findings_ledger
        # caps `msg` at MAX_MSG_CHARS (120) and truncates from the end, so
        # the long stdout line would lose exactly its last sentence — the
        # CONSEQUENCE, which acceptance clause (2) requires — in the durable
        # record. The ledger is the next-session surface, so the content
        # that must survive is the count, the tag, the ages and the
        # consequence; the "cut a release" advice is already in the stdout
        # line. The CONSEQUENCE LEADS the message, so that if a longer tag
        # or count pushes it past the cap the truncation drops the least
        # important tail (the ages), not the finding itself.
        ledger_msg = (
            f"Build OLDER than tree: {gap_count} unreleased since {gap_tag} "
            f"({gap_days}d old, bar {bar}d). Unreleased commits unreachable"
        )
        line = dedupe.emit_once(gap_seen, key, msg)
        if line:
            lines.append(line)
            try:
                findings_ledger.record(
                    sev=_GAP_SEV,
                    code="REPO-RELEASE-GAP",
                    src="repo-state",
                    msg=ledger_msg,
                    ref=gap_tag,
                    actor="human",
                )
            except Exception:  # noqa: BLE001 -- the mailbox must never break the detector
                # The episode is already latched in the seen-file (emit_once
                # wrote the key before returning), so a failed ledger write
                # would lose this episode's durable record for good. Unlatch
                # it: the next fire retries the write. The stdout half of
                # the finding is already out, and the ledger half is the
                # only durable one.
                dedupe.emit_forget(gap_seen, key)

    for line in lines:
        print(line)
    if lines:
        state.rotate_log_if_big("repo-state")
    return 0


if __name__ == "__main__":
    # `--one-shot` is the historical flag from the bash port. We accept it
    # as a no-op for backward compatibility — every Python detector is
    # one-shot by construction (no daemon mode).
    sys.exit(main())
