"""stale-stash must key its dedupe and name its suggested commands by the stash commit, not by position.

A stash@{N} index shifts whenever a newer stash is pushed above it or one is dropped, so a dedupe key
or a suggested command built from that index can point at a different stash by the time it is used
(janitor#367). Real git repos in temp dirs and real git stash; no mocks.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from exe_path import exe

DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "stale-stash.py"


def _repo(tmp_path: Path) -> Path:
    """Create a real git repo with one committed file so that later edits can be stashed."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    subprocess.run([exe("git"), "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run([exe("git"), "config", "user.email", "t@t.t"], cwd=tmp_path, check=True)
    subprocess.run([exe("git"), "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run([exe("git"), "add", "seed.txt"], cwd=tmp_path, check=True)
    subprocess.run([exe("git"), "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    return tmp_path


def _stash(repo: Path, message: str, days_ago: int) -> None:
    """Stash a real edit to seed.txt, with the stash commit dated days_ago days in the past."""
    (repo / "seed.txt").write_text(f"{message}\n", encoding="utf-8")
    when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    env = dict(os.environ, GIT_COMMITTER_DATE=when)
    subprocess.run([exe("git"), "stash", "push", "-q", "-m", message], cwd=repo, check=True, env=env)


def _run(project: Path, home: Path) -> str:
    """Run the detector against the project with a 30-day threshold and return its stdout."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_PLUGIN_OPTION_STASH_STALE_DAYS"] = "30"
    res = subprocess.run(
        [sys.executable, str(DETECTOR)], capture_output=True, text=True, env=env, timeout=60
    )
    assert res.returncode == 0, res.stderr
    return res.stdout


def test_a_nudged_stash_is_not_re_emitted_after_a_newer_stash_is_pushed(tmp_path: Path) -> None:
    """The dedupe key is the stash commit, so pushing a newer stash above it does not re-emit it."""
    repo = _repo(tmp_path / "proj")
    home = tmp_path / "home"
    _stash(repo, "old work", days_ago=40)
    old_sha = subprocess.run(
        [exe("git"), "rev-parse", "stash@{0}"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    first = _run(repo, home)
    assert "old work" in first, f"the 40-day-old stash must be nudged once, got: {first!r}"

    _stash(repo, "newer work", days_ago=0)
    second = _run(repo, home)
    assert second == "", f"already-nudged stash re-emitted after a newer push: {second!r}"

    # The seen-file is the dedupe record: exactly one key, and it names the commit of the old stash.
    seen = (repo / ".janitor" / "state" / "stale-stash-seen.txt").read_text(encoding="utf-8").splitlines()
    assert len(seen) == 1 and old_sha in seen[0], f"expected one dedupe key for the old stash, got: {seen!r}"


def test_the_advisory_names_the_stash_commit_not_a_positional_index(tmp_path: Path) -> None:
    """The advisory names the stash commit sha and never a bare pop or drop, nor a concrete stash@{N} index."""
    repo = _repo(tmp_path / "proj")
    _stash(repo, "old work", days_ago=40)
    sha = subprocess.run(
        [exe("git"), "rev-parse", "stash@{0}"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    out = _run(repo, tmp_path / "home")

    assert f"git stash show -p {sha}" in out, f"inspect command must name the sha, got: {out!r}"
    assert "git stash list --format='%gd %H'" in out, f"the index lookup command is missing, got: {out!r}"
    assert "git stash pop <" in out and out.count("git stash pop") == out.count("git stash pop <"), f"a bare git stash pop is advised, got: {out!r}"
    assert "git stash drop <" in out and out.count("git stash drop") == out.count("git stash drop <"), f"a bare git stash drop is advised, got: {out!r}"
    for tail in out.split("stash@{")[1:]:
        assert tail.startswith("N}"), f"advisory names a concrete positional index: {out!r}"
