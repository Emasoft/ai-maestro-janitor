"""Tests for the memory-scope-leak detector (TRDD-c77dae09, ranks 2+6).

The PROJECT memory scope (`<git-root>/memory/`) is git-tracked and PUSHED, so it
MUST NOT carry machine/user-private material. This detector scans those pages
with the private-path lib + privacy PII shapes + credential libs + entropy and
surfaces `[memory-scope-leak] <file>: <class> — demote to LOCAL scope` findings.
It also guards the gitignore invariants: PROJECT `memory/` must be TRACKED (not
ignored), and a LOCAL-shaped store must not be committed into the repo.

Real I/O, no mocks: each case builds a tmp git repo with a `memory/` dir and
runs the detector as a subprocess with CLAUDE_PROJECT_DIR + HOME pointed at the
fixture. The detector is project-scoped and a graceful no-op when there is no
`memory/` dir, no git repo, or an unchanged finding set.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

DETECTOR = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "detectors" / "memory-scope-leak.py"
)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "t")
    env.setdefault("GIT_AUTHOR_EMAIL", "t@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "t")
    env.setdefault("GIT_COMMITTER_EMAIL", "t@example.com")
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env, check=False,
    )


def _init_repo(root: Path) -> None:
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "t"], root)


def _run(home: Path, project: Path, *, extra_env: dict | None = None) -> str:
    """Run the detector with HOME + CLAUDE_PROJECT_DIR pointed at the fixture.
    Returns stdout; raises if the detector exits non-zero (heartbeat must be
    crash-free)."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_SESSION_ID"] = "testsess"
    # Force scanning even though the fixture isn't the janitor's own repo; and
    # make the per-run cadence irrelevant (the detector self-checks last-run).
    env["CLAUDE_PLUGIN_ALLOW_SELF_SCAN"] = "1"
    env.pop("CLAUDE_PLUGIN_OPTION_MEMORY_SCOPE_LEAK_INTERVAL", None)
    if extra_env:
        env.update(extra_env)
    res = subprocess.run(
        [sys.executable, str(DETECTOR)],
        capture_output=True, text=True, env=env, timeout=60, check=False,
    )
    if res.returncode != 0:
        raise AssertionError(f"detector exited {res.returncode}; stderr:\n{res.stderr}")
    return res.stdout


def _write_project_memory(root: Path, name: str, content: str) -> Path:
    mem = root / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    page = mem / name
    page.write_text(content, encoding="utf-8")
    return page


def _proposal(root: Path) -> str:
    """The detector's proposal file content (the per-page leak detail lives here;
    the heartbeat line is intentionally terse, like the librarian's)."""
    p = root / "memory" / "memory-scope-leak-proposed.md"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


class TestMemoryScopeLeak(unittest.TestCase):
    # ----- graceful no-ops -----------------------------------------------

    def test_no_git_repo_is_noop(self) -> None:
        """Not a git repo → silent no-op (project-scoped, needs a repo)."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _write_project_memory(root, "a.md", "clean project fact.\n")
            out = _run(Path(td) / "home", root)
            self.assertEqual(out.strip(), "")

    def test_absent_memory_dir_is_noop(self) -> None:
        """A git repo with NO `memory/` dir → silent no-op."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            out = _run(Path(td) / "home", root)
            self.assertEqual(out.strip(), "")

    def test_clean_pages_yield_nothing(self) -> None:
        """A tracked memory/ with only portable, non-private content → no leak."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "arch.md",
                "The parser retries 3× then fails. See [[other]] for the table.\n",
            )
            _git(["add", "memory/arch.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)

    # ----- leak classes ---------------------------------------------------

    def test_local_path_leak_flagged(self) -> None:
        """A /Users/<name>/ absolute home path in a pushed page is a leak."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "paths.md",
                "the script lives at /Users/emanuele/Code/run.sh on my box.\n",
            )
            _git(["add", "memory/paths.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            self.assertIn("demote to LOCAL", out)
            # The per-page detail (filename + class) lives in the proposal file.
            prop = _proposal(root)
            self.assertIn("paths.md", prop)
            self.assertIn("local-path", prop)

    def test_email_pii_leak_flagged(self) -> None:
        """An email address (PII via privacy_patterns) in a pushed page is a leak."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "contact.md",
                "ping the maintainer at someone.private@gmail.com when stuck.\n",
            )
            _git(["add", "memory/contact.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            prop = _proposal(root)
            self.assertIn("contact.md", prop)
            self.assertIn("pii:email", prop)

    def test_high_entropy_secret_leak_flagged(self) -> None:
        """A long high-entropy base64-ish blob (an unrecognised secret) is a leak."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            secret = "Zk9hQm*c2VjUmV0X3Rva2VuX3hQ8wLm5vdF9hX3JlYWxfb25lX2J1dF9yYW5kb20"
            _write_project_memory(
                root, "token.md",
                f"the api key was {secret} but it has been rotated since.\n",
            )
            _git(["add", "memory/token.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            prop = _proposal(root)
            self.assertIn("token.md", prop)
            self.assertIn("high-entropy secret", prop)

    def test_allowlist_no_false_positive(self) -> None:
        """Generic/shared paths + documentation hosts must NOT be flagged as leaks."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "ok.md",
                "CI runs in /home/runner/work; cache under /Users/Shared/x; "
                "docs at example.com and localhost; bare ~/bin is fine.\n",
            )
            _git(["add", "memory/ok.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)

    def test_memgrep_dir_skipped(self) -> None:
        """The tool's `.memgrep/` index sidecar inside memory/ is never scanned."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            mem = root / "memory"
            mem.mkdir(parents=True)
            (mem / "arch.md").write_text("clean fact.\n", encoding="utf-8")
            idx = mem / ".memgrep"
            idx.mkdir()
            # A would-be leak INSIDE the index dir must be ignored (not a note).
            (idx / "cache.md").write_text(
                "/Users/secretuser/leak/path/here.sh\n", encoding="utf-8",
            )
            _git(["add", "memory/arch.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)

    # ----- gitignore guards ----------------------------------------------

    def test_ignored_project_memory_flagged(self) -> None:
        """PROJECT memory/ must be TRACKED. If a .gitignore swallows it, surface
        a guard finding (the shared scope would silently never be pushed)."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            (root / ".gitignore").write_text("memory/\n", encoding="utf-8")
            _write_project_memory(root, "arch.md", "clean fact.\n")
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            self.assertIn("gitignore guard", out.lower())
            # The guard detail (the word "gitignored" + the fix) is in the proposal.
            self.assertIn("gitignored", _proposal(root).lower())

    # ----- dedupe ---------------------------------------------------------

    def test_unchanged_findings_are_silent_on_rerun(self) -> None:
        """A second run over an unchanged corpus emits nothing (fingerprint
        dedupe — idempotent like the other detectors)."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "paths.md", "see /Users/emanuele/x.sh on disk.\n",
            )
            _git(["add", "memory/paths.md"], root)
            _git(["commit", "-qm", "x"], root)
            home = Path(td) / "home"
            first = _run(home, root)
            self.assertIn("[memory-scope-leak]", first)
            # last-run gating would suppress the 2nd run; bypass it by forcing
            # the interval to 0 so cadence never blocks, leaving ONLY the
            # content-fingerprint dedupe as the silencer.
            second = _run(home, root, extra_env={"CLAUDE_PLUGIN_OPTION_MEMORY_SCOPE_LEAK_INTERVAL": "0"})
            self.assertEqual(second.strip(), "")


if __name__ == "__main__":
    unittest.main()
