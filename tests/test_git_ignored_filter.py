"""The shared gitignore filter for detector walks (janitor#99).

Two scanners — `typosquat-watcher` and `repo-trust-score` — walked the working tree with a
bare `rglob` and no ignore filtering, so they scored a DOWNLOADED RESEARCH CORPUS under
gitignored `*_dev/` dirs as if it were the project's own supply chain. Measured downstream
on AgentlensPro: 313 of 313 binaries in the tree were gitignored, all under `downloads_dev/`,
and `repo-trust-score` reported 393 ("dropper-shape") on a repo whose TRACKED surface is
clean.

The filter is batched on purpose: one `git check-ignore --stdin` call for the whole walk,
not one subprocess per path. A heartbeat detector that forks 300+ times is its own defect.

It fails OPEN everywhere — no git, not a repo, a git error — because suppressing findings on
an unreadable signal is the one direction a security scanner must never take.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS / "lib"))

import git_utils  # type: ignore[import-not-found]  # noqa: E402


def _repo(tmp: Path) -> Path:
    root = tmp / "repo"
    (root / "downloads_dev" / "nested").mkdir(parents=True)
    (root / "src").mkdir()
    (root / ".gitignore").write_text("/downloads_dev/\n", encoding="utf-8")
    (root / "downloads_dev" / "nested" / "package-lock.json").write_text("{}", encoding="utf-8")
    (root / "src" / "package-lock.json").write_text("{}", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", ".gitignore", "src/package-lock.json"], cwd=root, check=True)
    return root


def test_ignored_paths_are_dropped_and_tracked_ones_kept(tmp_path: Path) -> None:
    """THE issue-#99 case: a lockfile inside a gitignored corpus dir is filtered out, and
    the project's own lockfile survives."""
    root = _repo(tmp_path)
    corpus = root / "downloads_dev" / "nested" / "package-lock.json"
    own = root / "src" / "package-lock.json"

    kept = git_utils.drop_gitignored([corpus, own], root=root)

    assert own in kept, "a tracked, non-ignored path must never be filtered"
    assert corpus not in kept, "a path under a gitignored dir must be dropped"


def test_filter_is_one_subprocess_for_the_whole_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Batched, not per-path: a heartbeat detector must not fork once per file. Measured
    downstream at 313 paths in one walk."""
    root = _repo(tmp_path)
    paths = [root / "downloads_dev" / "nested" / "package-lock.json"] * 50 + [
        root / "src" / "package-lock.json"
    ]
    calls: list[tuple[str, ...]] = []
    real = git_utils._git

    def _counting(*args: str, **kw: object):
        calls.append(args)
        return real(*args, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(git_utils, "_git", _counting)
    git_utils.drop_gitignored(paths, root=root)
    assert len(calls) == 1, f"expected ONE batched git call, got {len(calls)}: {calls}"


def test_fails_open_outside_a_git_repo(tmp_path: Path) -> None:
    """Not a repo ⇒ return the input UNCHANGED. Suppressing findings on an unreadable
    signal is the one direction a security scanner must never take."""
    plain = tmp_path / "plain"
    (plain / "sub").mkdir(parents=True)
    p = plain / "sub" / "package-lock.json"
    p.write_text("{}", encoding="utf-8")
    assert git_utils.drop_gitignored([p], root=plain) == [p]


def test_fails_open_when_git_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A git failure (exit >= 2) must also fail OPEN, not silently drop everything."""
    root = _repo(tmp_path)
    paths = [root / "downloads_dev" / "nested" / "package-lock.json"]

    def _boom(*_a: str, **_k: object):
        raise OSError("git exploded")

    monkeypatch.setattr(git_utils, "_git", _boom)
    assert git_utils.drop_gitignored(paths, root=root) == paths


def test_empty_input_makes_no_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No paths ⇒ no fork. The common case on a clean tree must cost nothing."""
    root = _repo(tmp_path)

    def _boom(*_a: str, **_k: object):
        raise AssertionError("must not shell out for an empty batch")

    monkeypatch.setattr(git_utils, "_git", _boom)
    assert git_utils.drop_gitignored([], root=root) == []


def test_order_is_preserved(tmp_path: Path) -> None:
    """Callers sort their walks for stable output; the filter must not reshuffle them."""
    root = _repo(tmp_path)
    a = root / "src" / "package-lock.json"
    (root / "src" / "b.json").write_text("{}", encoding="utf-8")
    b = root / "src" / "b.json"
    assert git_utils.drop_gitignored([a, b], root=root) == [a, b]
