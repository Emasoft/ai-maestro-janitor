"""Tests for project-plugins-update.py's self-commit path (owner directive 2026-08-11).

Committing `.claude/settings.json` after the janitor's own worker updates
project-scope plugins is a zero-judgment mechanical action — the detector
must perform it itself instead of printing a command for the main Claude
turn to copy-paste-execute. This exercises the real detector against a real
temporary git repo (no mocked git): a clean repo commits silently, a
mid-rebase repo refuses and prints exactly one line, and nothing is ever
pushed to a remote.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "project-plugins-update.py"
SETTINGS_REL = ".claude/settings.json"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, timeout=30, check=False, env=env,
    )


def _init_repo(root: Path) -> None:
    """A real git repo with an initial commit carrying settings.json."""
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "Test User")
    _git(root, "config", "user.email", "test@example.com")
    settings_dir = root / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.json").write_text('{"enabledPlugins": {}}\n', encoding="utf-8")
    r = _git(root, "add", ".claude/settings.json")
    assert r.returncode == 0, r.stderr
    r = _git(root, "commit", "-q", "-m", "initial")
    assert r.returncode == 0, r.stderr


def _stage_pending_commit(root: Path, plugin_ids: list) -> None:
    """Dirty settings.json (as the worker would) and drop the sentinel + last-updated
    files the parent detector reads, so `main()` takes the commit-pending branch."""
    (root / ".claude" / "settings.json").write_text(
        '{"enabledPlugins": {"foo@mp": true}}\n', encoding="utf-8"
    )
    state_dir = root / ".janitor" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "project-plugins-update.commit-pending").write_text("1", encoding="utf-8")
    (state_dir / "project-plugins-update.last-updated.txt").write_text(
        "\n".join(plugin_ids) + "\n", encoding="utf-8"
    )


def _run_detector(root: Path) -> str:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    env["CLAUDE_SESSION_ID"] = "sess"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    # The detector gates on `shutil.which("claude")` and returns 0 silently when absent —
    # so on a runner without Claude Code (any CI box) every test here would "pass the
    # empty way" or fail before reaching the commit logic under test. A stub `claude`
    # makes the gate deterministic everywhere AND stops the macOS run from invoking the
    # real plugin manager against a throwaway repo. The commit logic these tests exercise
    # is the detector's own git, never `claude` itself.
    stub_bin = root / "stub-bin"
    stub_bin.mkdir(exist_ok=True)
    stub = stub_bin / "claude"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    env["PATH"] = f"{stub_bin}{os.pathsep}{env.get('PATH', '')}"
    res = subprocess.run(
        [sys.executable, str(DETECTOR)],
        capture_output=True, text=True, env=env, timeout=60, cwd=str(root),
    )
    assert res.returncode == 0, f"stdout={res.stdout!r} stderr={res.stderr!r}"
    return res.stdout


class TestProjectPluginsSelfCommit(unittest.TestCase):
    def test_clean_repo_commits_settings_and_prints_nothing(self):
        """A clean repo state: the detector commits settings.json itself, silently."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            _stage_pending_commit(root, ["foo@mp"])

            out = _run_detector(root)

            self.assertEqual(out.strip(), "", f"a successful commit must print nothing, got: {out!r}")

            # The commit actually landed, touching only settings.json.
            log = _git(root, "log", "-1", "--pretty=%s")
            self.assertIn("janitor chore: commit the updated plugins", log.stdout)

            changed = _git(root, "diff", "--name-only", "HEAD~1", "HEAD")
            self.assertEqual(changed.stdout.strip(), SETTINGS_REL)

            status = _git(root, "status", "--porcelain", "--", SETTINGS_REL)
            self.assertEqual(status.stdout.strip(), "", "settings.json must be clean after commit")

            sentinel = root / ".janitor" / "state" / "project-plugins-update.commit-pending"
            self.assertFalse(sentinel.exists(), "sentinel must be cleared after handling")

    def test_rebase_in_progress_refuses_and_prints_one_line(self):
        """Mid-rebase: the commit is refused, settings.json stays dirty, one drift line."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            _stage_pending_commit(root, ["foo@mp"])

            # Simulate an in-progress rebase without actually running one.
            (root / ".git" / "rebase-merge").mkdir()

            before_head = _git(root, "rev-parse", "HEAD").stdout.strip()
            out = _run_detector(root)

            lines = [line for line in out.splitlines() if line.strip()]
            self.assertEqual(len(lines), 1, f"expected exactly one drift line, got: {out!r}")
            self.assertTrue(lines[0].startswith("[project-plugins-commit-skipped]"), lines[0])
            self.assertIn("rebase", lines[0])

            after_head = _git(root, "rev-parse", "HEAD").stdout.strip()
            self.assertEqual(before_head, after_head, "no commit must land while rebase is in progress")

            status = _git(root, "status", "--porcelain", "--", SETTINGS_REL)
            self.assertNotEqual(status.stdout.strip(), "", "settings.json must remain uncommitted")

    def test_never_pushes_to_remote(self):
        """A successful self-commit never touches a configured remote."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = Path(tmp) / "remote.git"
            _git(Path(tmp), "init", "-q", "--bare", str(remote))

            _init_repo(root)
            _git(root, "remote", "add", "origin", str(remote))
            _git(root, "push", "-q", "-u", "origin", "main")
            remote_head_before = _git(remote, "rev-parse", "main").stdout.strip()

            _stage_pending_commit(root, ["foo@mp"])
            _run_detector(root)

            # The local commit landed...
            local_head = _git(root, "rev-parse", "HEAD").stdout.strip()
            self.assertNotEqual(local_head, remote_head_before, "sanity: a local commit must have happened")

            # ...but the remote was never touched.
            remote_head_after = _git(remote, "rev-parse", "main").stdout.strip()
            self.assertEqual(remote_head_before, remote_head_after, "the janitor must never push")


if __name__ == "__main__":
    unittest.main()
