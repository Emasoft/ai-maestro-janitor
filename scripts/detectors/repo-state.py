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
# The capture groups are parsed for semver ordering in _last_release_tag.
_TAG_NAME = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


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


def _last_release_tag(repo: Path) -> str | None:
    """Newest `v<semver>` tag, or None.

    Order by PARSED semver, never by `--sort=-creatordate`: two tags created
    within the same clock second (a fast publish, or a test fixture) tie on
    creatordate and git's refname tiebreak is ASCENDING, so the OLDER tag
    wins and the detector reports already-released commits as unreleased.

    One for-each-ref pass, never a per-tag `rev-parse` peel (TRDD-GXXKAGY6
    review cure 4): a 2000-tag repo would pay 2000 subprocess spawns per
    heartbeat. `%(*objectname)` carries the peeled commit for an annotated
    tag, `%(objectname)` the commit for a lightweight one.
    """
    proc = _git(
        repo,
        "for-each-ref",
        "--format=%(refname:short) %(objectname) %(*objectname)",
        "refs/tags/",
    )
    if proc is None or proc.returncode != 0:
        return None
    best: tuple[tuple[int, int, int], str] | None = None
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name, obj = parts[0], parts[1]
        # %(*objectname) is EMPTY for a lightweight tag — the line then has two
        # fields, and the peel falls back to %(objectname), which IS the commit.
        peeled = parts[2] if len(parts) > 2 else ""
        m = _TAG_NAME.match(name)
        if not m:
            continue
        commit = peeled or obj
        if commit:
            ver = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if best is None or ver > best[0]:
                best = (ver, name)
    return best[1] if best else None


def _unreleased_subjects(repo: Path, tag: str, branch: str) -> list[str]:
    """Subjects of the UNRELEASED commits on `branch` since `tag`, oldest-first.

    UNRELEASED = on the release line, since the reported release, and
    contained in NO release that was cut FROM THE RELEASE LINE.

    The last clause is what the tag subtraction buys. `git log A..B` is a SET
    DIFFERENCE over the DAG, so a commit that ANOTHER release already shipped
    — a backdated semver-newer tag pointing at a NEWER commit than the
    reported one — would be counted as unreleased work, and the escalated line
    would state a shipped commit as a backlog.

    THE SUBTRACTION MUST BE LIMITED TO THE RELEASE LINE'S OWN TAGS, and this
    is the part that is easy to get wrong. `git log A..B --not --tags`
    subtracts the commits reachable from EVERY tag, and `--tags` includes a
    tag cut on a SIDE branch. A side-branch tag's history usually CONTAINS
    release-line commits (the side branch forked from the release line), so
    subtracting it drops genuine unreleased release-line work: measured on a
    fixture with a side-branch tag, `--not --tags` reported 1 unreleased
    commit where the truth was 2, silently under-reporting the very quantity
    the escalated line states as a fact. The subtraction must therefore name
    the tags that are MERGED INTO the release line (`git tag --merged
    <branch>`), which are exactly the releases that shipped release-line
    work. A tag on a side branch is not a release of the release line, and
    the commits it happens to contain are still unreleased ON THE RELEASE
    LINE.

    The `tag..branch` range keeps the "since TAG" anchoring; the tag
    subtraction removes the commits those releases already shipped. On a
    healthy repo — one whose newest tag is the reported one — the two agree
    and the count is unchanged; the difference appears exactly where the
    naive form was wrong.

    The bump-subject exclusion is NOT applied here: the caller applies it, so
    the raw subject list and the "unreleased work" count stay separable.
    """
    release_tags = _release_line_tags(repo, branch)
    argv = [
        "rev-list",
        "--no-commit-header",
        "--format=%s",
        "--reverse",
        f"{tag}..{branch}",
    ]
    for release in release_tags:
        argv.extend(["--not", release])
    proc = _git(repo, *argv)
    if proc is None or proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _release_line_tags(repo: Path, branch: str) -> list[str]:
    """The release tags that were cut FROM the release line, oldest first.

    These are the tags `git tag --merged <branch>` reports: the tags whose
    commits are reachable from the branch a release would be cut from. A tag
    cut on a side branch is NOT one of them, and that distinction is
    load-bearing — see `_unreleased_subjects`, whose subtraction is limited to
    these tags so that a side-branch tag cannot silently remove genuine
    unreleased release-line work from the count.

    Returns an empty list when the branch cannot be resolved or has no
    merged tags, which makes the caller fall back to counting the range
    as-is rather than to counting nothing.
    """
    proc = _git(repo, "tag", "--merged", branch)
    if proc is None or proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

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
    match, not a `v*` glob. A glob would admit `v1.2.3-rc1` or a
    calendar-versioned `v2024.10.31`, and such a tag would inflate the bar
    while never being the reported tag — two different definitions of
    "release tag" in one file.
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
    repo: Path, today: datetime.date
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
    release_line = _release_branch(repo)
    if release_line is None:
        return None
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

        tag = _last_release_tag(repo)
        if tag is not None:
            subjects = _unreleased_subjects(repo, tag, branch)
            outside = [s for s in subjects if not _BUMP_SUBJECT.match(s)]
            if outside:
                key = f"outside@{tag}@{len(outside)}@{now // 86400}"
                preview = "; ".join(outside[-3:])
                msg = f"[repo-state] {len(outside)} commit(s) on {branch} since release {tag} were NOT made through publish.py (neither release-tagged nor a 'chore: bump version to x.y.z' bump): {preview}. Run scripts/publish.py to cut a release."
                line = dedupe.emit_once(seen, key, msg)
                if line:
                    lines.append(line)

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

        gap = _release_gap(repo, datetime.date.today())
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
            # The phrase "not made through publish.py" is an INFERENCE from
            # publish.py's own behaviour (it makes exactly one commit, the
            # version bump — publish.py's expected_subject), not something
            # this detector verifies against the publish pipeline. It is
            # stated as a fact because the number it qualifies is a fact, and
            # a reader acting on it (cut a release) is right either way.
            msg = (
                f"[repo-state] HIGH: RELEASE GAP ESCALATION — {gap_count} commit(s) since release {gap_tag} "
                f"are unreleased (not made through publish.py), and the release is {gap_days} day(s) old, "
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
