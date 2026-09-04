"""Interrupted-publish recovery must never ship a tag that names a stale commit.

TRDD-S7FIQTCO. Release 3.4.14 was tagged 4 commits behind the head it shipped
with: a previous run created the local `v3.4.14` tag and died before pushing,
the recovery path re-bumped to the SAME version (a second bump commit), and the
tag step saw "tag already exists locally" and skipped — leaving the tag on the
FIRST bump commit. `Verified on remote` only asked whether the tag EXISTED, so
the publish reported green.

These tests use REAL git repositories (a working repo plus a bare origin), not
mocks: the defect lives in what `git rev-parse` resolves an annotated tag to,
and a mock of git cannot have that bug.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import publish  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True,
        check=True, timeout=30,
    )
    return r.stdout.strip()


def _plan_and_apply(repo: Path, tag: str, message: str) -> list[str]:
    """Drive `_stale_tag_plan` exactly as `stage_commit_and_push` does, and return its lines.

    The production call site decides for EVERY tag before mutating ANY, then
    applies. `_stale_tag_plan` is therefore pure — it neither exits nor moves a
    ref — so these tests reproduce the three-line applier rather than calling a
    wrapper that no longer exists.

    THIS IS DUPLICATED LOGIC AND NOTHING KEEPS IT IN SYNC. Do not read it as a
    coupling: a change to the call site's semantics would leave these tests
    passing against the old ones. It is still the right trade, because the part
    that can be WRONG is the pure decision function, and that is tested
    directly — the applier is three lines of `git tag -f`. The consequence to
    remember is that the call site's own wiring (which tag ends up in `_retag`,
    when it exits) has no coverage here.
    """
    verdict, lines = publish._stale_tag_plan(repo, tag)
    # The call site prints EVERY plan's lines and only then exits if any refused,
    # so printing unconditionally here is the faithful mirror — and it is what
    # makes the operator-facing wording observable to these tests at all.
    for line in lines:
        print(line)
    if verdict == "refuse":
        raise SystemExit(1)
    if verdict == "retag":
        subprocess.run(["git", "tag", "-f", "-a", tag, "-m", message],
                       cwd=str(repo), capture_output=True, check=True, timeout=30)
    return lines


def _commit(repo: Path, name: str, body: str) -> str:
    (repo / name).write_text(body, encoding="utf-8")
    _git(repo, "add", "--", name)
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo_with_origin(tmp_path: Path) -> tuple[Path, Path]:
    """A working repo with one commit, wired to a bare `origin` it has pushed to."""
    origin = tmp_path / "origin.git"
    # `cwd` is inside tmp_path deliberately: tests/sandbox_guard.py refuses any
    # mutating git verb whose cwd resolves to the real repository, and a bare
    # `subprocess.run(["git", "init", ...])` inherits this repo as its cwd.
    subprocess.run(["git", "init", "-q", "--bare", str(origin)],
                   cwd=str(tmp_path), check=True, timeout=30)
    repo = tmp_path / "work"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    _commit(repo, "a.txt", "first\n")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "main")
    return repo, origin


def test_rev_parse_commit_peels_an_annotated_tag_to_its_commit(repo_with_origin) -> None:
    """`_rev_parse_commit` must return the COMMIT an annotated tag points at, not the tag object's own sha."""
    repo, _ = repo_with_origin
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "-a", "v1.0.0", "-m", "Release v1.0.0")
    # The annotated tag's OWN sha is a different object from the commit's.
    tag_object_sha = _git(repo, "rev-parse", "v1.0.0")
    assert tag_object_sha != head, "fixture is wrong: this tag is not annotated"
    assert publish._rev_parse_commit(repo, "v1.0.0") == head


def test_rev_parse_commit_returns_none_for_an_unknown_rev(repo_with_origin) -> None:
    """A rev that does not resolve yields None rather than a bogus sha or an exception."""
    repo, _ = repo_with_origin
    assert publish._rev_parse_commit(repo, "v9.9.9-does-not-exist") is None


def test_stale_unpushed_tag_is_repointed_at_head(repo_with_origin, capsys) -> None:
    """The 3.4.14 defect: a leftover local tag one commit behind HEAD is moved onto HEAD."""
    repo, _ = repo_with_origin
    first = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "-a", "v1.0.0", "-m", "Release v1.0.0")  # the interrupted run's tag
    second = _commit(repo, "b.txt", "the commit that would have been lost\n")
    assert publish._rev_parse_commit(repo, "v1.0.0") == first

    _plan_and_apply(repo, "v1.0.0", "Release v1.0.0")

    assert publish._rev_parse_commit(repo, "v1.0.0") == second
    assert "re-pointing it" in capsys.readouterr().out


def test_tag_already_on_head_is_left_untouched(repo_with_origin, capsys) -> None:
    """A tag that already names HEAD is a genuine no-op — it must not be rewritten."""
    repo, _ = repo_with_origin
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "-a", "v1.0.0", "-m", "Release v1.0.0")
    before = _git(repo, "rev-parse", "v1.0.0")  # the tag OBJECT sha

    _plan_and_apply(repo, "v1.0.0", "Release v1.0.0")

    assert publish._rev_parse_commit(repo, "v1.0.0") == head
    assert _git(repo, "rev-parse", "v1.0.0") == before, "the tag object was rewritten"
    assert "points at HEAD" in capsys.readouterr().out


def test_stale_tag_already_on_origin_blocks_the_publish(repo_with_origin, capsys) -> None:
    """A PUBLISHED tag is history: refuse rather than silently redefine what other clones fetched."""
    repo, _ = repo_with_origin
    first = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "-a", "v1.0.0", "-m", "Release v1.0.0")
    _git(repo, "push", "-q", "origin", "v1.0.0")
    _commit(repo, "b.txt", "later work\n")

    with pytest.raises(SystemExit) as exc:
        _plan_and_apply(repo, "v1.0.0", "Release v1.0.0")

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "BLOCKED" in out
    assert "published history" in out
    # And it really did leave the tag alone.
    assert publish._rev_parse_commit(repo, "v1.0.0") == first


def test_unreachable_remote_refuses_to_move_the_tag(repo_with_origin, monkeypatch, capsys) -> None:
    """"Cannot ask origin" must refuse like "yes": False-on-network-error would license moving a PUBLISHED tag."""
    repo, _ = repo_with_origin
    first = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "-a", "v1.0.0", "-m", "Release v1.0.0")
    _commit(repo, "b.txt", "later work\n")
    # The tag is NOT on origin here — so a False answer would authorize the move.
    # None (cannot ask) must not.
    monkeypatch.setattr(publish, "_remote_tag_state", lambda *_a, **_kw: None)

    with pytest.raises(SystemExit) as exc:
        _plan_and_apply(repo, "v1.0.0", "Release v1.0.0")

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "could not be queried on origin" in out
    assert "cannot be PROVEN unpublished" in out
    assert publish._rev_parse_commit(repo, "v1.0.0") == first


def test_remote_tag_state_is_tristate_and_exists_folds_none_to_false(
    repo_with_origin, tmp_path: Path,
) -> None:
    """`_remote_tag_state` answers True/False/None; `_remote_tag_exists` is that with None folded to False."""
    repo, _ = repo_with_origin
    _git(repo, "tag", "-a", "v1.0.0", "-m", "Release v1.0.0")
    assert publish._remote_tag_state(repo, "v1.0.0") is False  # local only
    assert publish._remote_tag_exists(repo, "v1.0.0") is False
    _git(repo, "push", "-q", "origin", "v1.0.0")
    assert publish._remote_tag_state(repo, "v1.0.0") is True
    assert publish._remote_tag_exists(repo, "v1.0.0") is True
    # The None branch, produced for real rather than monkeypatched — an
    # unreachable origin. Without this the test's NAME promised a fold it never
    # exercised, and that fold is the whole safety property of
    # `_remote_tag_exists`'s "never a false green" docstring claim.
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "nope.git"))
    assert publish._remote_tag_state(repo, "v1.0.0") is None
    assert publish._remote_tag_exists(repo, "v1.0.0") is False


def test_remote_tag_commit_peels_the_annotated_tag_on_the_REMOTE_side(repo_with_origin) -> None:
    """`_remote_tag_commit` must return origin's COMMIT, not the tag object sha `ls-remote` prints first."""
    repo, _ = repo_with_origin
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "-a", "v1.0.0", "-m", "Release v1.0.0")
    _git(repo, "push", "-q", "origin", "v1.0.0")
    tag_object_sha = _git(repo, "rev-parse", "v1.0.0")
    assert tag_object_sha != head, "fixture is wrong: this tag is not annotated"
    # Comparing the tag OBJECT sha against a rev-parse ^{commit} sha would
    # mismatch on every annotated tag — a false alarm on every publish.
    assert publish._remote_tag_commit(repo, "v1.0.0") == head


def test_remote_tag_commit_catches_a_stale_remote_tag_that_local_hides(repo_with_origin) -> None:
    """The exact case the post-push check exists for: origin's tag is behind while the LOCAL tag equals HEAD."""
    repo, _ = repo_with_origin
    first = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "-a", "v1.0.0", "-m", "Release v1.0.0")
    _git(repo, "push", "-q", "origin", "v1.0.0")
    second = _commit(repo, "b.txt", "the push that silently failed its ref-update\n")
    _git(repo, "tag", "-f", "-a", "v1.0.0", "-m", "Release v1.0.0")  # local moves, remote does not

    # Resolving LOCALLY says everything is fine — this is the false green.
    assert publish._rev_parse_commit(repo, "v1.0.0") == second
    # Asking origin catches it.
    assert publish._remote_tag_commit(repo, "v1.0.0") == first


def test_post_push_verdict_reports_unverified_when_the_remote_commit_is_unknown() -> None:
    """CANNOT-CHECK IS NEVER A PASS: an unresolvable remote commit must not print `Verified on remote`."""
    for tagged, head in (("abc123", None), (None, "abc123"), (None, None)):
        lines = publish._remote_tag_verdict("v1.0.0", tagged, head)
        joined = "\n".join(lines)
        assert "UNVERIFIED, not a pass" in joined, (tagged, head)
        assert "Verified on remote" not in joined, (tagged, head)
        assert "WRONG COMMIT" not in joined, (tagged, head)


def test_post_push_verdict_flags_a_remote_tag_on_the_wrong_commit() -> None:
    """A remote tag naming anything but the pushed head is reported WRONG COMMIT, not verified."""
    lines = publish._remote_tag_verdict("v1.0.0", "a" * 40, "b" * 40)
    joined = "\n".join(lines)
    assert "WRONG COMMIT" in joined
    assert "Verified on remote" not in joined
    # BOTH shas must appear, and they are distinguishable on purpose: the `[:8]`
    # slicing is where a wrong-variable bug lives (printing the pushed head
    # twice, say), and asserting only on the message text would not see it.
    assert "aaaaaaaa" in joined, "the remote tag's commit is missing from the report"
    assert "bbbbbbbb" in joined, "the pushed head is missing from the report"


def test_post_push_verdict_passes_only_on_an_exact_match() -> None:
    """The single green path requires the remote commit to equal the pushed head exactly."""
    lines = publish._remote_tag_verdict("v1.0.0", "c" * 40, "c" * 40)
    joined = "\n".join(lines)
    assert "Verified on remote" in joined
    assert "UNVERIFIED" not in joined
    assert "WRONG COMMIT" not in joined


def test_remote_tag_commit_returns_none_when_origin_cannot_be_reached(
    repo_with_origin, tmp_path: Path,
) -> None:
    """An unreachable origin yields None, so the caller reports UNVERIFIED rather than a false WRONG COMMIT."""
    repo, _ = repo_with_origin
    _git(repo, "tag", "-a", "v1.0.0", "-m", "Release v1.0.0")
    _git(repo, "push", "-q", "origin", "v1.0.0")
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "nope.git"))
    assert publish._remote_tag_commit(repo, "v1.0.0") is None


def test_unreadable_comparison_leaves_the_tag_alone(repo_with_origin, monkeypatch, capsys) -> None:
    """Cannot answer is never a force-move: an unresolvable HEAD leaves the tag exactly as found."""
    repo, _ = repo_with_origin
    first = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "-a", "v1.0.0", "-m", "Release v1.0.0")
    _commit(repo, "b.txt", "later work\n")
    monkeypatch.setattr(publish, "_rev_parse_commit", lambda *_a, **_kw: None)

    _plan_and_apply(repo, "v1.0.0", "Release v1.0.0")

    assert "leaving it untouched" in capsys.readouterr().out
    # Restored implementation confirms nothing moved.
    monkeypatch.undo()
    assert publish._rev_parse_commit(repo, "v1.0.0") == first
