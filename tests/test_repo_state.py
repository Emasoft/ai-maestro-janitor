"""Tests for the repo-state detector (TRDD-DG2V7D5P).

The detector lives at scripts/detectors/repo-state.py. It reports (1) the
current branch's ahead/behind count against its upstream and (2) default-branch
commits newer than the newest `v*` release tag that were not made through
publish.py — publish.py's signature is the `chore: bump version to <semver>`
bump subject plus the `v<semver>` release tag.

Real git repos in temp dirs; no mocks.
"""

from __future__ import annotations

import datetime
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "repo-state.py"


def _load():
    spec = importlib.util.spec_from_file_location("repo_state_detector", DETECTOR)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["repo_state_detector"] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load()


# --------------------------------------------------------------------------- #
# fixture helpers — a real repo with a real `origin` (a local bare clone)
# --------------------------------------------------------------------------- #


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _commit(repo: Path, msg: str, filename: str = "f.txt", date: str | None = None) -> None:
    """Commit `msg`; `date` sets GIT_COMMITTER_DATE so a tag's creatordate is exact."""
    if date is not None:
        old = os.environ.get("GIT_COMMITTER_DATE")
        os.environ["GIT_COMMITTER_DATE"] = date
        try:
            (repo / filename).write_text(msg, encoding="utf-8")
            _git(repo, "add", filename)
            _git(repo, "commit", "-qm", msg)
        finally:
            if old is None:
                os.environ.pop("GIT_COMMITTER_DATE", None)
            else:
                os.environ["GIT_COMMITTER_DATE"] = old
        return
    (repo / filename).write_text(msg, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-qm", msg)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A work repo cloned from a local bare `origin`, one release already published."""
    work = tmp_path / "work"
    origin = tmp_path / "origin.git"
    # cwd=tmp_path on every git call whose cwd would otherwise be the project
    # root: the sandbox guard reads the CALLING cwd, and `git init` invoked
    # from the project tree reads as a mutation of the real repo.
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True, cwd=tmp_path)
    # A fresh bare repo's HEAD points at refs/heads/master, so a later
    # `git push origin HEAD:refs/heads/main` from a clone is rejected as
    # non-fast-forward against a ref that does not even exist. Point HEAD at
    # main BEFORE cloning so the work clone starts on `main`.
    subprocess.run(
        ["git", "-C", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True, cwd=tmp_path)
    _git(work, "config", "user.email", "t@t.t")
    _git(work, "config", "user.name", "t")

    _commit(work, "seed")
    # The fixture's release tag gets a controlled committer date 14 days ago,
    # so every gap test computes bar/gap from exact creatordates.
    _commit(work, "chore: bump version to 1.2.3", date=_days_ago(14))
    _git(work, "tag", "v1.2.3")
    _git(work, "push", "-q", "origin", "HEAD:refs/heads/main")
    _git(work, "push", "-q", "origin", "v1.2.3")
    _git(work, "branch", "--set-upstream-to=origin/main")
    # The remote-tracking pointer at the remote's default branch. A fresh
    # clone does not have one, and the release-gap rule resolves the release
    # line from it.
    _git(work, "remote", "set-head", "origin", "main")
    return work


def _run(project: Path, home: Path) -> str:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    res = subprocess.run([sys.executable, str(DETECTOR)], capture_output=True, text=True, env=env, timeout=60)
    assert res.returncode == 0, res.stderr
    return res.stdout


# --------------------------------------------------------------------------- #
# ahead / behind
# --------------------------------------------------------------------------- #


def test_ahead_count_after_local_commit(repo: Path, tmp_path: Path) -> None:
    _commit(repo, "local work one")
    _commit(repo, "local work two")

    out = _run(repo, tmp_path / "home1")

    assert "2 commit(s) ahead" in out


def test_behind_count_after_remote_commit(repo: Path, tmp_path: Path) -> None:
    # Push a commit from a second clone, then fetch: local is now behind.
    other = repo.parent / "other"
    subprocess.run(["git", "clone", "-q", repo.parent / "origin.git", str(other)], check=True, capture_output=True, cwd=tmp_path)
    _git(other, "config", "user.email", "t@t.t")
    _git(other, "config", "user.name", "t")
    _commit(other, "remote side work")
    _git(other, "push", "-q", "origin", "HEAD:refs/heads/main")
    _git(repo, "fetch", "-q", "origin")

    out = _run(repo, tmp_path / "home2")

    assert "1 behind" in out


def test_synced_branch_is_silent(repo: Path, tmp_path: Path) -> None:
    assert _run(repo, tmp_path / "home3") == ""


def test_no_upstream_is_silent(tmp_path: Path) -> None:
    """A repo with no upstream at all (local init, no remote) must not error or nag."""
    solo = tmp_path / "solo"
    solo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=solo, check=True, capture_output=True)
    _git(solo, "config", "user.email", "t@t.t")
    _git(solo, "config", "user.name", "t")
    _commit(solo, "seed")

    assert _run(solo, tmp_path / "home4") == ""


# --------------------------------------------------------------------------- #
# outside-publish detection
# --------------------------------------------------------------------------- #


def test_outside_publish_commit_is_flagged(repo: Path, tmp_path: Path) -> None:
    _commit(repo, "feat: sneaky direct commit")

    out = _run(repo, tmp_path / "home5")

    assert "NOT" in out and "publish.py" in out
    assert "feat: sneaky direct commit" in out


def test_publish_bump_commit_is_silent(repo: Path, tmp_path: Path) -> None:
    """A commit whose subject is publish.py's exact bump signature is not flagged."""
    _commit(repo, "chore: bump version to 1.3.0")

    out = _run(repo, tmp_path / "home6")

    assert "NOT" not in out, f"bump-subject commit flagged as outside-publish: {out!r}"


def test_new_release_tag_resets_the_count(repo: Path, tmp_path: Path) -> None:
    """After a real release (tag pushed), commits older than the new tag are no longer reported."""
    _commit(repo, "feat: sneaky direct commit")
    _commit(repo, "chore: bump version to 1.3.0")
    _git(repo, "tag", "v1.3.0")

    out = _run(repo, tmp_path / "home7")

    assert "NOT" not in out, f"released commit still flagged: {out!r}"


# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# release-gap escalation (TRDD-03G3CSUU)
# --------------------------------------------------------------------------- #


def _tagged_commit(repo: Path, msg: str, date: str, tag: str) -> None:
    """Commit with a fixed committer date, so the tag's creatordate is exact."""
    (repo / "g.txt").write_text(msg, encoding="utf-8")
    _git(repo, "add", "g.txt")
    old = os.environ.get("GIT_COMMITTER_DATE")
    os.environ["GIT_COMMITTER_DATE"] = date
    try:
        _git(repo, "commit", "-qm", msg)
    finally:
        if old is None:
            os.environ.pop("GIT_COMMITTER_DATE", None)
        else:
            os.environ["GIT_COMMITTER_DATE"] = old
    _git(repo, "tag", tag)


def _days_ago(n: int) -> str:
    """A committer date n days before today, so tag creatordates track the clock."""
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat() + "T10:00:00"


def _gap(repo: Path) -> tuple[int, int, str, int] | None:
    """The detector's own verdict on `repo`, computed in-process."""
    return rs._release_gap(repo, datetime.date.today())


def test_release_gap_stale_release_fires(repo: Path, tmp_path: Path) -> None:
    """A gap past the repo's own bar, with enough unreleased commits, fires."""
    # History: v1.0.0 (12d ago) -> v2.0.0 (10d ago) gives bar = 2 completed-interval
    # days; the OPEN gap (10d since v2.0.0) can never enter the bar, so 10 > 2 fires.
    _tagged_commit(repo, "feat: one", _days_ago(12), "v1.0.0")
    _tagged_commit(repo, "feat: two", _days_ago(10), "v2.0.0")
    for i in range(5):
        _commit(repo, f"feat: unreleased work {i}")
    out = _run(repo, tmp_path / "homeg2")
    assert "GAP ESCALATION" in out and "v2.0.0" in out, out


def test_release_gap_bar_is_the_computed_maximum_not_zero(repo: Path) -> None:
    """THE BAR IS PINNED: a gap under the bar must not fire, with the count ABOVE the floor.

    This is the test the rule's whole thesis rests on. Without it, replacing
    `max(intervals)` with 0 (or with a rolling window) keeps every other test
    green — the age condition would never be the deciding factor, and
    acceptance clause (1) would be unverified.
    """
    # v1.0.0 (20d ago) -> v1.2.3 (14d ago, the fixture) => ONE completed
    # interval of 6 days, so bar = 6. The open gap is measured from the
    # newest release date, 14 days ago, so gap = 14 — ABOVE the bar, which
    # fires. The companion test test_release_gap_under_the_bar_is_silent
    # covers the silent side of the same bar.
    _tagged_commit(repo, "feat: one", _days_ago(20), "v1.0.0")
    for i in range(6):
        _commit(repo, f"feat: unreleased work {i}")
    verdict = _gap(repo)
    assert verdict is not None, "the rule must be able to compute a verdict here"
    gap_days, bar, tag, count = verdict
    assert bar == 6, f"the bar must be the completed-interval maximum, got {bar}"
    assert gap_days == 14, gap_days
    # 6, not 7: the v1.0.0 commit is a DESCENDANT of the fixture's v1.2.3
    # commit (it was made later, with an older date), so it is inside the
    # range — but v1.0.0 SHIPPED it, so it is not unreleased work. The
    # count excludes every commit contained in ANY release tag, which is
    # what makes the number "unreleased" rather than "newer than the
    # reported release".
    assert count == 6, count
    # gap_days (14) > bar (6) => the verdict is a FIRE, which is what makes
    # the companion case below discriminating.
    assert gap_days > bar


def test_release_gap_under_the_bar_is_silent(repo: Path, tmp_path: Path) -> None:
    """A fresh release with commits ahead stays quiet — the age is under the bar.

    Acceptance clause (3): a repository a few commits ahead and releasing this
    week does NOT raise it. The count clears the floor on purpose, so the BAR
    is the only thing that can keep this silent.
    """
    # v1.0.0 (20d ago) -> v1.2.3 (14d ago) -> v1.3.0 (2d ago) gives completed
    # intervals of 6 and 12 days, so bar = 12; the open gap from the newest
    # release is 2 days, UNDER the bar, while 6 unreleased commits clear the
    # floor of 5. Only the BAR can keep this silent.
    # (A bar of 6 is not constructible here: a release newer than the previous
    # one always creates a completed interval as long as the gap it would
    # have made, so the bar is always at least the interval preceding the
    # newest release.)
    _tagged_commit(repo, "feat: one", _days_ago(20), "v1.0.0")
    _tagged_commit(repo, "feat: two", _days_ago(2), "v1.3.0")
    for i in range(6):
        _commit(repo, f"feat: unreleased work {i}")
    verdict = _gap(repo)
    assert verdict is None, f"a gap under the bar must not fire, got {verdict}"
    out = _run(repo, tmp_path / "homeg1")
    assert "GAP ESCALATION" not in out, out


def test_release_gap_once_per_episode(repo: Path, tmp_path: Path) -> None:
    """A second run in the same episode does not re-fire the gap line."""
    _tagged_commit(repo, "feat: one", _days_ago(12), "v1.0.0")
    _tagged_commit(repo, "feat: two", _days_ago(10), "v2.0.0")
    for i in range(5):
        _commit(repo, f"feat: unreleased work {i}")
    home = tmp_path / "homeg3"
    assert "GAP ESCALATION" in _run(repo, home)
    assert "GAP ESCALATION" not in _run(repo, home)


def test_release_gap_needs_two_release_dates(repo: Path, tmp_path: Path) -> None:
    """With one release date there is no bar; the rule stays silent and does not crash."""
    out = _run(repo, tmp_path / "homeg4")
    assert "GAP ESCALATION" not in out, out


def test_release_gap_below_floor_is_silent(repo: Path, tmp_path: Path) -> None:
    """Fewer unreleased commits than the floor (default 5) stays quiet.

    The age is deliberately OVER the bar here, so the count is the only thing
    that can keep this silent: the floor keeps its coverage.
    """
    # v1.0.0 (12d ago) -> v2.0.0 (10d ago) => bar = 2 days; the open gap is
    # 10 days, well over the bar. Only the count (4) is under the floor (5).
    _tagged_commit(repo, "feat: one", _days_ago(12), "v1.0.0")
    _tagged_commit(repo, "feat: two", _days_ago(10), "v2.0.0")
    for i in range(4):
        _commit(repo, f"feat: unreleased work {i}")
    verdict = _gap(repo)
    assert verdict is None, f"a count under the floor must not fire, got {verdict}"
    out = _run(repo, tmp_path / "homeg5")
    assert "GAP ESCALATION" not in out, out


def test_release_gap_reports_the_newest_by_date_not_the_backdated_tag(repo: Path) -> None:
    """A backdated release tag is NOT the reported release — the newest by date is.

    The gap is measured from the newest release DATE, and the reported tag is
    the release carrying that date. If the semver-newest tag carries an older
    date than another tag (a backdated or cherry-picked release), picking by
    semver would measure the gap from a release that is not the latest, and
    the dedupe key would name a release the gap was never measured from.
    """
    # v1.0.0 (20d ago) -> v1.2.3 (14d ago, the fixture) -> v1.3.0 (30d ago:
    # the semver-newest tag, but BACKDATED — older than v1.2.3).
    _tagged_commit(repo, "feat: one", _days_ago(20), "v1.0.0")
    _tagged_commit(repo, "feat: two", _days_ago(30), "v1.3.0")
    for i in range(6):
        _commit(repo, f"feat: unreleased work {i}")
    assert rs._last_release_tag(repo) == "v1.3.0", "the semver-newest tag must be v1.3.0 here"
    verdict = _gap(repo)
    assert verdict is not None, "the rule must still fire on the newest-by-date release"
    gap_days, bar, tag, count = verdict
    # The reported release is v1.2.3 (14d ago), NOT the backdated v1.3.0.
    assert tag == "v1.2.3", tag
    assert gap_days == 14, gap_days
    # The dates SORT to 30d, 20d, 14d, so the completed intervals are 10 and
    # 6, and the bar is 10. The backdated release still contributes a
    # completed interval (the bar is computed over the whole date-sorted
    # history, so an irregular history yields a longer bar).
    assert bar == 10, bar


def test_release_gap_divergent_release_stays_silent(repo: Path) -> None:
    """A release tag that is NOT on the checked-out branch must not be counted.

    `git log tag..branch` is a set difference over the commit DAG, not "the
    commits since the release": when the tag is not an ancestor of the branch
    the result includes the tag's own divergent history. The number the
    escalated line states as fact would then be the size of that difference,
    not the count of unreleased work. The rule stays silent instead.
    """
    # A release on a side branch: v2.0.0 is tagged on a commit that is not an
    # ancestor of the checked-out branch.
    _git(repo, "checkout", "-q", "-b", "side")
    _tagged_commit(repo, "feat: side", _days_ago(10), "v2.0.0")
    _git(repo, "checkout", "-q", "main")
    _tagged_commit(repo, "feat: one", _days_ago(12), "v1.0.0")
    for i in range(6):
        _commit(repo, f"feat: unreleased work {i}")
    assert not rs._is_ancestor(repo, "v2.0.0", "main"), "v2.0.0 must not be an ancestor of main"
    verdict = _gap(repo)
    assert verdict is None, f"a divergent release must not be reported, got {verdict}"


def test_release_gap_counts_the_release_branch_not_the_checked_out_one(repo: Path) -> None:
    """On a feature branch the count must still be the RELEASE branch's.

    The escalated line claims the running build is older than what a release
    would contain. On a feature branch, `git log tag..feature` counts work
    nobody intends to release, which would attribute a stale-install alarm to
    it. The count is therefore measured on the local default branch.
    """
    _tagged_commit(repo, "feat: one", _days_ago(12), "v1.0.0")
    _tagged_commit(repo, "feat: two", _days_ago(10), "v2.0.0")
    for i in range(5):
        _commit(repo, f"feat: unreleased work {i}")
    # A feature branch with its own commits, carrying the same tags.
    _git(repo, "checkout", "-q", "-b", "feature")
    for i in range(3):
        _commit(repo, f"feat: branch-only work {i}")
    verdict = _gap(repo)
    assert verdict is not None, "the rule must still fire from a feature branch checkout"
    gap_days, bar, tag, count = verdict
    assert tag == "v2.0.0", tag
    assert gap_days == 10, gap_days
    # 5 on main, NOT 8: the 3 branch-only commits are not counted.
    assert count == 5, count


def test_release_gap_line_carries_no_repo_controlled_prose(repo: Path, tmp_path: Path) -> None:
    """The escalated line carries measurement facts only — no prose, no branch name.

    The severity word must survive the quiet filter, and the line must not
    depend on repo-controlled text: a commit subject is arbitrary prose, and
    one containing a severity word would decide the line's fate for a reason
    unrelated to the measurement.
    """
    _tagged_commit(repo, "feat: one", _days_ago(12), "v1.0.0")
    _tagged_commit(repo, "feat: two", _days_ago(10), "v2.0.0")
    # A subject that WOULD trip the urgency filter if it leaked into the line.
    for i in range(5):
        _commit(repo, f"feat: FAIL unrelated prose {i}")
    out = _run(repo, tmp_path / "homeg6")
    assert "GAP ESCALATION" in out, out
    line = next(ln for ln in out.splitlines() if "GAP ESCALATION" in ln)
    assert "FAIL unrelated prose" not in line, line
    assert " on main " not in line, line
    assert "feature" not in line, line
    assert "HIGH" in line, line


# --------------------------------------------------------------------------- #
# the pure helpers, pinned directly
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "subject,expected",
    [
        ("chore: bump version to 3.6.3", True),
        ("chore: bump version to 10.20.30", True),
        ("chore: bump version to 1.2", False),  # not a full semver
        ("chore: bump version to 1.2.3 extra", False),  # trailing text = a human's commit
        ("feat: bump version to 1.2.3", False),  # wrong prefix
        ("docs(TRDD): a normal commit", False),
    ],
)
def test_bump_subject_regex(subject: str, expected: bool) -> None:
    assert bool(rs._BUMP_SUBJECT.match(subject)) is expected


def test_tag_regex_matches_semver_tags_only() -> None:
    assert rs._TAG_NAME.match("v1.2.3")
    assert not rs._TAG_NAME.match("v1.2.3-rc1")  # publish.py never creates these, stay conservative
    assert not rs._TAG_NAME.match("not-a-release")

# --------------------------------------------------------------------------- #
# the escalated line's two load-bearing claims
# --------------------------------------------------------------------------- #


def _load_dispatch():
    """scripts/dispatch.py, loaded under a synthetic module name.

    The quiet filter's regexes and its advisory-detector sets live in
    dispatch.py. A COPIED pattern can drift from the real one, and then the
    test proves nothing — so the test uses the real module.

    The synthetic name means dispatch.py's `if __name__ == "__main__"` guard
    does not fire, so importing it does not run a heartbeat.
    """
    spec = importlib.util.spec_from_file_location(
        "janitor_dispatch_under_test", DETECTOR.parent.parent / "dispatch.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["janitor_dispatch_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_release_gap_count_excludes_publish_bump_commits(repo: Path, tmp_path: Path) -> None:
    """A publish.py bump commit inside the range must NOT count as unreleased work.

    The escalated line states the count as a fact — "N commit(s) ... are
    unreleased (not made through publish.py)". If the count were the raw
    total, a bump commit would inflate it and the line would overstate the
    backlog. This pins the number the line prints.
    """
    _tagged_commit(repo, "feat: one", _days_ago(12), "v1.0.0")
    _tagged_commit(repo, "feat: two", _days_ago(10), "v2.0.0")
    for i in range(5):
        _commit(repo, f"feat: unreleased work {i}")
    # A bump commit INSIDE the range: publish.py's own signature, so it is
    # not unreleased work and must not be counted.
    _commit(repo, "chore: bump version to 9.9.9")
    verdict = _gap(repo)
    assert verdict is not None, "the rule must still fire"
    gap_days, bar, tag, count = verdict
    assert count == 5, f"the bump commit must not be counted, got {count}"
    out = _run(repo, tmp_path / "homeg7")
    line = next(ln for ln in out.splitlines() if "GAP ESCALATION" in ln)
    assert "5 commit(s)" in line, line
    assert "6 commit(s)" not in line, line


def test_release_gap_line_survives_the_real_quiet_filter(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The escalated line must survive dispatch's real quiet filter.

    repo-state is an advisory detector, so dispatch._quiet_filter drops its
    lines unless they match _URGENT_LINE_RE (and are not negated). The real
    filter is called here, not a reconstruction of it: a copied regex can
    drift, and a filter that gains a new disqualification path would still
    pass a test that only pokes at the old regexes.

    The same call drops the detector's own severity-free advisory line, which
    is the negative control: it proves the filter really engaged, so a
    passing assertion cannot be a short-circuit.
    """
    _tagged_commit(repo, "feat: one", _days_ago(12), "v1.0.0")
    _tagged_commit(repo, "feat: two", _days_ago(10), "v2.0.0")
    for i in range(5):
        _commit(repo, f"feat: unreleased work {i}")
    out = _run(repo, tmp_path / "homeg8")
    gap_line = next(ln for ln in out.splitlines() if "GAP ESCALATION" in ln)
    advisory_line = next(ln for ln in out.splitlines() if "NOT made through publish.py" in ln)

    dispatch = _load_dispatch()
    # _quiet_filter RECORDS every line it drops (sev=LOW, code=ADVISORY-<DETECTOR>)
    # into the findings ledger. The IN-PROCESS call below inherits THIS
    # PROCESS's environment, so state.project_root() resolves to the
    # developer's real project (the `_run` subprocess's own write lands in the
    # tmp repo instead). Without this patch the negative control below would
    # append a fabricated LOW finding to the developer's real
    # .janitor/state/findings-ledger.ndjsonl on every run — the
    # phantom-evidence leak this repo's conftest exists to prevent.
    # Neutralise the write; the filter's DECISION is what is under test.
    # The patch is on the shared MODULE object, so it holds for the duration
    # of this test; dispatch.py reaches `record` by attribute access, so the
    # patch covers it (a future `from findings_ledger import record` in
    # dispatch.py would keep its own binding and escape the patch).
    monkeypatch.setattr(dispatch.findings_ledger, "record", lambda **kw: None)

    assert "repo-state" in dispatch._ADVISORY_DETECTORS
    # Precondition: the advisory line the negative control depends on must be
    # in the detector's output, so a failure below is the filter's decision
    # and not the detector having stopped emitting it.
    assert advisory_line in out, out
    kept = dispatch._quiet_filter("repo-state", out)
    assert gap_line in kept, f"the escalated line was dropped by the quiet filter: {out!r}"
    # Negative control: the filter engaged, so the kept line was KEPT and not
    # merely passed through.
    assert advisory_line not in kept, f"the filter did not engage: {kept!r}"


def test_release_gap_line_states_the_consequence_and_the_bar(repo: Path, tmp_path: Path) -> None:
    """The escalated line must name the bar it measured against and the consequence.

    Acceptance clause (2) requires the line to name "how many commits, since
    which tag, how old" AND the consequence — that the running plugin is an
    OLDER build than the tree and cannot contain the tree's fixes. The count
    and the tag are pinned by the other tests; this one pins the two clauses
    that would otherwise be free to disappear unnoticed: the BAR (the repo's
    own historical maximum release interval, without which the age figure has
    nothing to be measured against) and the CONSEQUENCE (without which the
    finding is a bare number with no reason to act on it).
    """
    _tagged_commit(repo, "feat: one", _days_ago(12), "v1.0.0")
    _tagged_commit(repo, "feat: two", _days_ago(10), "v2.0.0")
    for i in range(5):
        _commit(repo, f"feat: unreleased work {i}")
    out = _run(repo, tmp_path / "homeg9")
    line = next(ln for ln in out.splitlines() if "GAP ESCALATION" in ln)

    # The BAR: the repo's own historical maximum release interval, in days.
    # The verdict is narrowed BEFORE it is unpacked, because _gap returns
    # None when the rule does not fire and unpacking that would be a type
    # error rather than a readable assertion failure.
    verdict = _gap(repo)
    assert verdict is not None, "the rule must fire on this repo"
    gap_days, bar, tag, count = verdict
    # The bar's VALUE, hard-coded: without this the assertion below would
    # compare the line against the detector's own verdict and could not catch
    # a wrong-but-consistent bar.
    assert bar == 2, bar
    assert f"historical maximum release interval of {bar} day(s)" in line, line
    assert f"{gap_days} day(s) old" in line, line
    # The CONSEQUENCE: the running build cannot contain the unreleased work.
    assert "it cannot contain them" in line, line
    assert "OLDER than the working tree" in line, line
    # The remedy the owner is asked to take.
    assert "scripts/publish.py" in line, line



# --------------------------------------------------------------------------- #
# the four surgical fixes: C1 (backdated tag), C2 (release line refusal),
# C3 (corrupt seen-file), N2 (the owner override reaches a young repo)
# --------------------------------------------------------------------------- #


def test_unreleased_count_excludes_commits_a_backdated_tag_already_shipped(
    repo: Path, tmp_path: Path
) -> None:
    """C1: a commit another release tag SHIPPED is not unreleased work.

    `git log tag..branch` is a SET DIFFERENCE, so a backdated semver-newer
    tag pointing at a NEWER commit than the reported one made the shipped
    commit look like a backlog. The count must be "since the reported
    release, and contained in NO release tag".
    """
    # The fixture's v1.2.3 (14d ago) is the oldest date here. v1.3.0 (10d
    # ago) is the NEWEST date, so it is the REPORTED release. v1.4.0 is
    # BACKDATED (20d ago — an earlier calendar date) but its commit is a
    # DESCENDANT of v1.3.0's, so it shipped a commit the reported release
    # does not contain.
    _tagged_commit(repo, "feat: reported release", _days_ago(10), "v1.3.0")
    _tagged_commit(repo, "feat: shipped by the backdated tag", _days_ago(20), "v1.4.0")
    for i in range(5):
        _commit(repo, f"feat: unreleased work {i}")

    verdict = _gap(repo)
    assert verdict is not None, "the rule must still fire"
    gap_days, bar, tag, count = verdict
    # The reported release is the newest BY DATE (v1.3.0), not the
    # semver-newest (v1.4.0).
    assert tag == "v1.3.0", tag
    # 5, not 6: the commit v1.4.0 shipped is inside the range but is
    # contained in a release tag, so it is not unreleased work. The EXACT
    # number is asserted — "smaller than 6" would also pass a count of 0.
    assert count == 5, count
    out = _run(repo, tmp_path / "homec1")
    line = next(ln for ln in out.splitlines() if "GAP ESCALATION" in ln)
    assert "5 commit(s)" in line, line

def test_release_gap_counts_work_a_side_branch_tag_happens_to_contain(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C1 (the hard half): a tag on a SIDE branch must not shrink the count.

    The subtraction that removes "commits a release already shipped" must be
    limited to the tags that were cut FROM THE RELEASE LINE. `git log A..B
    --not --tags` subtracts every tag, and a side-branch tag's history
    CONTAINS release-line commits (the side branch forked from the release
    line), so the naive form silently dropped genuine unreleased release-line
    work: on this fixture it reported 1 where the truth is 6.

    This is the test that distinguishes the two forms. The backdated-tag
    fixture cannot: on a repo whose only tags are release-line tags, both
    forms agree.

    The size floor is lowered to 1 so the COUNT is the discriminator: with
    the floor at its default 5 the naive form's count of 1 would make the
    rule silent, and the test would fail on "the rule must fire" rather than
    on the number the escalated line states as fact.
    """
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_RELEASE_GAP_MIN_COMMITS", "1")
    # The release line: TWO releases (so the bar exists). v1.0.0 (12d ago) ->
    # v1.1.0 (10d ago) gives a bar of 2 completed-interval days; the open gap
    # is measured from the newest release date, 10 days ago, so 10 > 2 fires.
    # (The fixture's own v1.2.3 is dated 14d ago, so it is not the newest.)
    _tagged_commit(repo, "feat: first release", _days_ago(12), "v1.0.0")
    _tagged_commit(repo, "feat: second release", _days_ago(10), "v1.1.0")
    # FIVE unreleased commits on the release line, made BEFORE the side branch
    # forks — so the side branch's history CONTAINS them.
    for i in range(5):
        _commit(repo, f"feat: unreleased on the release line {i}")
    # A SIDE branch forked from the release line, with its own tag. The tag is
    # DATED 11d ago: older than the newest release-line release, so it is not
    # the "newest release by date" the rule reports, and the rule still
    # measures the gap from v1.1.0.
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "feat: side branch work")
    old = os.environ.get("GIT_COMMITTER_DATE")
    os.environ["GIT_COMMITTER_DATE"] = _days_ago(11)
    try:
        _git(repo, "tag", "-a", "v9.9.9", "-m", "side hotfix")
    finally:
        if old is None:
            os.environ.pop("GIT_COMMITTER_DATE", None)
        else:
            os.environ["GIT_COMMITTER_DATE"] = old
    _git(repo, "checkout", "-q", "-")
    # One MORE unreleased commit on the release line, made AFTER the fork.
    _commit(repo, "feat: unreleased on the release line after the fork")

    verdict = _gap(repo)
    assert verdict is not None, "the rule must fire"
    gap_days, bar, tag, count = verdict
    # The reported release is the newest BY DATE on the release line. The
    # side-branch tag is semver-higher (v9.9.9) but it is not a release OF
    # THE RELEASE LINE, so it does not become the reported release either.
    assert tag == "v1.1.0", tag
    # SIX, not one: a tag cut on a side branch is not a release of the
    # release line, so the commits it happens to contain are still unreleased
    # on the line a release would be cut from. The naive `--not --tags` form
    # subtracts the side tag's whole history and reports 1.
    assert count == 6, f"a side-branch tag must not shrink the count, got {count}"


def test_unresolvable_release_line_refuses_loudly_instead_of_measuring_the_branch(
    repo: Path, tmp_path: Path
) -> None:
    """C2: no origin/HEAD + a feature branch ⇒ no escalation, but a refusal.

    The checked-out-branch fallback made the printed consequence a
    falsehood with no marker in the output: the count measured work nobody
    intends to release. The fallback is gone, so the rule must SAY it cannot
    evaluate the condition rather than measure something else.
    """
    _tagged_commit(repo, "feat: one", _days_ago(12), "v1.0.0")
    _tagged_commit(repo, "feat: two", _days_ago(10), "v2.0.0")
    for i in range(5):
        _commit(repo, f"feat: unreleased work {i}")
    # A feature branch with its own commits — the shape the fallback used
    # to measure, and the shape that made the consequence sentence false.
    _git(repo, "checkout", "-q", "-b", "feature")
    for i in range(3):
        _commit(repo, f"feat: branch-only work {i}")
    # No origin/HEAD: the release line cannot be resolved.
    _git(repo, "remote", "set-head", "origin", "--delete")
    assert rs._release_branch(repo) is None, "the release line must not resolve here"

    out = _run(repo, tmp_path / "homec2")
    # No escalation: nothing was measured, so nothing escalates.
    assert "GAP ESCALATION" not in out, out
    assert "HIGH" not in out, out
    # But the refusal is VISIBLE — a silent None is indistinguishable from a
    # healthy repo, which is the failure mode this feature exists to end.
    assert "release line could not be resolved" in out, out


def test_a_corrupt_surfaced_to_human_seen_file_does_not_repeat_the_finding(
    repo: Path, tmp_path: Path
) -> None:
    """C3: a corrupt seen-file must not un-latch the episode and repeat forever.

    `read_text()` raised UnicodeDecodeError on the non-UTF-8 seen-file, and
    the detector's `except Exception` un-latched the episode — so the finding
    re-fired on every fire and the ledger grew without bound.
    """
    _tagged_commit(repo, "feat: one", _days_ago(12), "v1.0.0")
    _tagged_commit(repo, "feat: two", _days_ago(10), "v2.0.0")
    for i in range(5):
        _commit(repo, f"feat: unreleased work {i}")

    # The detector's own state dir (CLAUDE_PROJECT_DIR is the repo itself).
    state_dir = repo / ".janitor" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    seen = state_dir / "surfaced-to-human.seen"
    seen.write_bytes(b"\xff\xfe garbage \x80 not utf8\n")

    home = tmp_path / "homec3"
    # The first fire must not raise, and must emit the escalation.
    first = _run(repo, home)
    assert "GAP ESCALATION" in first, first
    # The corrupt file was READ (as the wrong key set it holds) rather than
    # raising, so the episode is latched: the key was appended to it.
    assert "REPO-RELEASE-GAP" in seen.read_text(encoding="utf-8", errors="replace"), (
        seen.read_text(encoding="utf-8", errors="replace")
    )

    # The second fire must NOT re-emit. Without the fix, the first fire's
    # UnicodeDecodeError made the detector un-latch its episode, so the
    # second fire re-emitted the line and re-wrote the ledger entry — the
    # unbounded repeat + write-amplification loop.
    second = _run(repo, home)
    assert "GAP ESCALATION" not in second, second

    # And the ledger must hold exactly ONE entry for this finding, not one
    # per fire. (The ledger entry is written BEFORE the human-only marking
    # that used to raise, so the raise landed after the durable write.)
    ledger = state_dir / "findings-ledger.ndjsonl"
    gap_entries = [
        line
        for line in ledger.read_text(encoding="utf-8").splitlines()
        if "REPO-RELEASE-GAP" in line
    ]
    assert len(gap_entries) == 1, gap_entries


def test_dedupe_emit_once_survives_a_corrupt_seen_file(tmp_path: Path) -> None:
    """C3 (unit): `dedupe.emit_once` must not raise on a corrupt seen-file.

    Every caller treats an exception as "the write failed" and un-latches its
    episode, so a raise here turns one corrupt file into an unbounded
    repeat-and-write-amplification loop.
    """
    import importlib.util as _ilu  # noqa: PLC0415 — import kept local to the test

    lib = Path(__file__).resolve().parent.parent / "scripts" / "lib"
    spec = _ilu.spec_from_file_location("dedupe_under_test", lib / "dedupe.py")
    assert spec and spec.loader
    dedupe = _ilu.module_from_spec(spec)
    spec.loader.exec_module(dedupe)

    seen = tmp_path / "corrupt.seen"
    seen.write_bytes(b"\xff\xfe garbage \x80 not utf8\n")
    # First call: the file is (wrongly) read as holding no keys, so the
    # message comes back as if the file were empty.
    assert dedupe.emit_once(seen, "key-1", "the message") == "the message"
    # Second call: the key is now in the file, so the message is suppressed.
    assert dedupe.emit_once(seen, "key-1", "the message") is None


def test_the_owner_override_rescues_a_repo_with_a_single_release(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N2: the env override must be reachable when there is no measured bar.

    The override was read AFTER the "fewer than two releases" early return,
    so it could never rescue a repo with fewer than two release dates.
    """
    # The fixture has exactly ONE release tag (v1.2.3, 14d ago), so there is
    # no completed interval and no measured bar. The gap is 14 days.
    for i in range(5):
        _commit(repo, f"feat: unreleased work {i}")
    assert len(rs._release_dates(repo)) == 1, "this test needs exactly one release date"

    # Without the override there is NO bar, so the rule stays SILENT: nothing
    # is invented, because there is no evidence such a repo releases slowly.
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_RELEASE_GAP_MAX_DAYS", raising=False)
    assert rs._release_gap_bar(repo) is None
    out = _run(repo, tmp_path / "homen2a")
    assert "GAP ESCALATION" not in out, out

    # WITH the override the bar is the owner's value, and the gap (14d)
    # exceeds it, so the rule fires.
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_RELEASE_GAP_MAX_DAYS", "10")
    assert rs._release_gap_bar(repo) == 10
    verdict = _gap(repo)
    assert verdict is not None, "the owner-set bar must make the rule fire"
    gap_days, bar, tag, count = verdict
    assert bar == 10, bar
    assert gap_days == 14, gap_days
    out = _run(repo, tmp_path / "homen2b")
    assert "GAP ESCALATION" in out, out
