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
    # 7, not 6: the v1.0.0 commit is a DESCENDANT of the fixture's v1.2.3
    # commit (it was made later, with an older date), so it is itself
    # unreleased relative to the newest tag, plus the 6 work commits.
    assert count == 7, count
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
    gap_days, bar, tag, count = _gap(repo)
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
