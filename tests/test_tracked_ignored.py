"""Tests for the tracked-ignored detector.

The bug fixed here: the staleness cache_key mixes HEAD + ignore-file mtimes
(so a NEW uncommitted .gitignore rule re-triggers the scan), but the
`emit_once` dedupe key was `trackedignored@{head_sha}` — HEAD only. A second
newly-ignored tracked file added at the SAME HEAD recomputed the scan but its
finding was suppressed by the already-seen HEAD key. The fix keys the emit on
the full cache_key so each distinct offender-set at a fixed HEAD emits once.

Real I/O, no mocks: each case builds a real git repo, commits files, then
mutates .gitignore between runs.
"""

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "tracked-ignored.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")


def _bump_mtime(path: Path, *, offset_secs: int) -> None:
    """Force a distinct integer-second mtime so the detector's cache_key
    (which reads `int(stat().st_mtime)`) actually changes between runs."""
    t = time.time() + offset_secs
    os.utime(path, (t, t))


def _run(repo: Path) -> str:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    res = subprocess.run(
        [sys.executable, str(DETECTOR)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    return res.stdout


class TestTrackedIgnored(unittest.TestCase):
    def _repo(self, tmp: str) -> Path:
        repo = Path(tmp)
        _init_repo(repo)
        return repo

    def test_first_offender_emitted(self):
        """A tracked file newly matched by .gitignore is surfaced."""
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            (repo / "foo.log").write_text("x")
            _git(repo, "add", "foo.log")
            _git(repo, "commit", "-q", "-m", "add foo")
            (repo / ".gitignore").write_text("*.log\n")
            out = _run(repo)
            self.assertIn("[tracked-ignored]", out)
            self.assertIn("foo.log", out)

    def test_second_offender_same_head_emitted(self):
        """A SECOND newly-ignored tracked file at the SAME HEAD still emits —
        the regression the fix addresses (HEAD-only key would drop it)."""
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            (repo / "foo.log").write_text("x")
            (repo / "bar.tmp").write_text("y")
            _git(repo, "add", "foo.log", "bar.tmp")
            _git(repo, "commit", "-q", "-m", "add both")

            gi = repo / ".gitignore"
            # First rule → first offender set {foo.log}.
            gi.write_text("*.log\n")
            _bump_mtime(gi, offset_secs=-10)
            first = _run(repo)
            self.assertIn("foo.log", first)
            self.assertNotIn("bar.tmp", first)

            # Second rule at the SAME HEAD → offender set grows to
            # {bar.tmp, foo.log}. cache_key changes (mtime bumped), the scan
            # re-runs, and the new finding must NOT be suppressed.
            gi.write_text("*.log\n*.tmp\n")
            _bump_mtime(gi, offset_secs=0)
            second = _run(repo)
            self.assertIn("[tracked-ignored]", second)
            self.assertIn("bar.tmp", second)

    def test_unchanged_key_deduped(self):
        """Re-running with no HEAD/ignore change emits nothing the 2nd time."""
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            (repo / "foo.log").write_text("x")
            _git(repo, "add", "foo.log")
            _git(repo, "commit", "-q", "-m", "add foo")
            gi = repo / ".gitignore"
            gi.write_text("*.log\n")
            _bump_mtime(gi, offset_secs=-5)
            first = _run(repo)
            self.assertIn("foo.log", first)
            # No change at all → staleness gate short-circuits → silent.
            second = _run(repo)
            self.assertEqual(second.strip(), "")

    def test_clean_repo_silent(self):
        """A repo with no tracked-yet-ignored files emits nothing."""
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            (repo / "keep.txt").write_text("x")
            _git(repo, "add", "keep.txt")
            _git(repo, "commit", "-q", "-m", "keep")
            (repo / ".gitignore").write_text("*.log\n")
            out = _run(repo)
            self.assertEqual(out.strip(), "")


if __name__ == "__main__":
    unittest.main()
