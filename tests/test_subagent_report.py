"""Tests for the subagent-report detector's gitignored-scratch handling (#32).

The detector nudges Claude to act on recent report files under docs_dev/,
tests/scenarios/reports/, scripts_dev/ that aren't referenced in any commit.
The bug: docs_dev/ and scripts_dev/ are gitignored `_dev` scratch (RULE 0.2),
so their files can NEVER be committed — the per-file "not referenced in any
commit" nag was un-actionable noise that cycled through every scratch file
(212 in the reporter's case) every heartbeat. The fix folds gitignored-scratch
files into ONE daily summary line, while keeping per-file nags for tracked
report dirs (where "commit it / commit a note" is actually possible).

Real I/O, no mocks: each case builds a temp git repo with a real .gitignore,
writes recent .md files, and runs the detector as a subprocess.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "subagent-report.py"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    """A real git repo with docs_dev/ + scripts_dev/ gitignored, one commit."""
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    (root / ".gitignore").write_text("docs_dev/\nscripts_dev/\n")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-q", "-m", "init")


def _run(project: Path) -> str:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_SESSION_ID"] = "sess"
    # Files are fresh (< 24h); clear the lookback knob so a host env value can't
    # widen/narrow the window under the test.
    env.pop("CLAUDE_PLUGIN_OPTION_SUBAGENT_REPORT_LOOKBACK", None)
    res = subprocess.run(
        [sys.executable, str(DETECTOR)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    return res.stdout


class TestSubagentReportScratch(unittest.TestCase):
    def test_gitignored_scratch_summarized_not_per_file(self):
        """docs_dev/ (gitignored) recent reports → ONE summary, zero per-file nags (#32)."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            scratch = root / "docs_dev"
            scratch.mkdir()
            for i in range(3):
                (scratch / f"report-{i}.md").write_text(f"scratch report {i}\n")

            out = _run(root)

            # No per-file line names any of the scratch files.
            for i in range(3):
                self.assertNotIn(f"report-{i}.md", out)
            # Exactly one summary line, naming the gitignored-scratch bucket.
            summary_lines = [ln for ln in out.splitlines() if "[subagent-report]" in ln]
            self.assertEqual(len(summary_lines), 1, f"expected one summary, got: {summary_lines}")
            self.assertIn("gitignored scratch", summary_lines[0])
            self.assertIn("3 recent report file(s)", summary_lines[0])

    def test_tracked_report_dir_still_per_file_nagged(self):
        """tests/scenarios/reports/ (tracked, committable) keeps its per-file nag."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            reports = root / "tests" / "scenarios" / "reports"
            reports.mkdir(parents=True)
            (reports / "audit.md").write_text("an audit report\n")

            out = _run(root)

            self.assertIn("[subagent-report]", out)
            self.assertIn("tests/scenarios/reports/audit.md", out)
            self.assertIn("not been referenced in any commit", out)

    def test_referenced_tracked_file_not_nagged(self):
        """A tracked report whose path is in a commit message is not nagged."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            reports = root / "tests" / "scenarios" / "reports"
            reports.mkdir(parents=True)
            f = reports / "done.md"
            f.write_text("acted-upon report\n")
            _git(root, "add", "-f", "tests/scenarios/reports/done.md")
            _git(root, "commit", "-q", "-m", "act on tests/scenarios/reports/done.md")

            out = _run(root)

            self.assertNotIn("done.md", out)

    def test_no_scratch_no_summary(self):
        """No gitignored-scratch reports → no summary line at all."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            out = _run(root)
            self.assertNotIn("gitignored scratch", out)


if __name__ == "__main__":
    unittest.main()
