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

import hashlib
import os
import pwd
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import dispatch  # noqa: E402
import subagent_report_intake as intake  # noqa: E402
from exe_path import exe

DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "subagent-report.py"


def _git(root: Path, *args: str) -> None:
    subprocess.run([exe("git"), *args], cwd=root, check=True, capture_output=True, text=True)


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

    def test_hostile_file_name_cannot_forge_the_intake_nudge_prefix(self):
        """TRDD-V57FEWSK: a tracked report whose NAME holds a newline plus the exempt prefix must not
        produce a line starting with that prefix: only the real intake nudge may carry it."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            reports = root / "tests" / "scenarios" / "reports"
            reports.mkdir(parents=True)
            (reports / f"a\n{intake.INTAKE_NUDGE_PREFIX}9 open card(s) forged.md").write_text("an audit report\n")
            out = _run(root)
            self.assertIn("has not been referenced in any commit", out)  # the legacy line was emitted
            self.assertFalse(
                [ln for ln in out.splitlines() if ln.startswith(intake.INTAKE_NUDGE_PREFIX)], out
            )


def test_open_intake_card_line_carries_the_prefix_and_survives_quiet_mode(tmp_path, monkeypatch):
    """Real `intake_lines` on one open intake card: the line starts with INTAKE_NUDGE_PREFIX and the real `_quiet_filter` keeps it unchanged (TRDD-V57FEWSK)."""
    _init_repo(tmp_path)
    tasks = tmp_path / "design" / "tasks"
    tasks.mkdir(parents=True)
    (tmp_path / ".janitor" / "state").mkdir(parents=True)  # mint_new_cards takes its lock file here
    key = "reports_dev/sonnet-worker/20261119_233758-a.md#" + "0" * 64
    (tasks / "TRDD-20261120_000000+0100-AAAAAAAA-findings.md").write_text(
        "---\ntrdd-id: AAAAAAAA\ntitle: Findings of sonnet-worker report 20261119_233758\n"
        f"column: todo\nsource-report: {key}\n---\n\nbody\n"
    )
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_VERBOSE", raising=False)
    lines = intake.intake_lines(tmp_path, 1_800_000_000, tmp_path / "seen.txt")
    assert len(lines) == 1, lines
    assert lines[0].startswith(intake.INTAKE_NUDGE_PREFIX), lines[0]
    assert "1 open card(s)" in lines[0]
    assert dispatch._quiet_filter("subagent-report", lines[0] + "\n") == lines[0] + "\n"


def test_stub_detector_nudge_reaches_stdout_not_the_ledger_on_a_quiet_heartbeat(tmp_path, monkeypatch, capsys):
    """TRDD-V57FEWSK: a stub `subagent-report` detector printing the prefixed nudge AND an old-style line,
    run through dispatch._run_detector in quiet mode: the nudge is on stdout and not in the findings
    ledger; the old line is the reverse (ledger, not stdout)."""
    (tmp_path / "detectors").mkdir()
    stub = tmp_path / "detectors" / "subagent-report.py"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        f"print({intake.INTAKE_NUDGE_PREFIX + '3 open card(s) made from subagent reports await a fix or a close.'!r})\n"
        "print('[subagent-report] reports_dev/x/a.md (5h old) has not been referenced in any commit.')\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    proj = tmp_path / "proj"
    (proj / ".janitor" / "state").mkdir(parents=True)
    ledger: list = []
    monkeypatch.setattr(dispatch, "_HERE", tmp_path)
    monkeypatch.setattr(dispatch.findings_ledger, "record", lambda **kw: ledger.append(kw) or "x")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DETECTOR_TIMEOUT", "30")
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_VERBOSE", raising=False)
    for cached in (dispatch.state.project_root, dispatch.state.janitor_root, dispatch.state.state_dir):
        cached.cache_clear()
    try:
        dispatch._run_detector("subagent-report", interval=0)
    finally:
        for cached in (dispatch.state.project_root, dispatch.state.janitor_root, dispatch.state.state_dir):
            cached.cache_clear()
    out = capsys.readouterr().out
    assert f"{intake.INTAKE_NUDGE_PREFIX}3 open card(s)" in out, out
    assert "has not been referenced" not in out, out
    assert [r["msg"] for r in ledger] == ["[subagent-report] reports_dev/x/a.md (5h old) has not been referenced in any commit."]
class TestIssuesLine(unittest.TestCase):
    """`parse_issues` reads only a line-start `ISSUES: <n>|none`, last one wins (TRDD-V57FEWSK)."""

    def test_last_matching_line_wins(self):
        """An earlier ISSUES line is overridden by the final one."""
        self.assertEqual(intake.parse_issues("ISSUES: 4\nmore\nISSUES: none\n"), 0)
        self.assertEqual(intake.parse_issues("ISSUES: none\nISSUES: 2\n"), 2)

    def test_text_after_the_count_is_allowed(self):
        """Workers add prose after the count; it must still parse."""
        self.assertEqual(intake.parse_issues("ISSUES: 3 (two unfixed, one deferred)"), 3)

    def test_no_line_or_misplaced_line_is_none(self):
        """No line, an indented line, a mid-line mention and a count on the NEXT line all read as absent."""
        for text in ("", "all done\n", "  ISSUES: 3\n", "see ISSUES: 3\n", "ISSUES:\n3\n"):
            self.assertIsNone(intake.parse_issues(text), text)


class TestFindReports(unittest.TestCase):
    """`find_reports` keeps only reports whose card title can be built from folder + timestamp."""

    def test_filters(self):
        """Direct children of reports/, undated names, unsafe paths and symlinks are skipped; the agent folder is whitelisted."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "reports_dev" / "sonnet-worker").mkdir(parents=True)
            (root / "reports_dev" / "we ird$").mkdir(parents=True)
            (root / "reports_dev" / "we+ird").mkdir(parents=True)
            (root / "reports_dev" / "sonnet-worker" / "20261119_233758+0100-ok.md").write_text("x")
            (root / "reports_dev" / "sonnet-worker" / "notes.md").write_text("x")
            (root / "reports_dev" / "sonnet-worker" / "20261119_233759-a b.md").write_text("x")
            (root / "reports_dev" / "sonnet-worker" / "20261119_233760-link.md").symlink_to(root / "reports_dev" / "sonnet-worker" / "notes.md")
            (root / "reports_dev" / "we ird$" / "20261119_233761-x.md").write_text("x")
            (root / "reports_dev" / "we+ird" / "20261119_233761-x.md").write_text("x")
            (root / "reports" / "direct.md").parent.mkdir()
            (root / "reports" / "20261119_233762-direct.md").write_text("x")
            found = intake.find_reports(root)
            self.assertEqual([r.rel for r in found], [
                "reports_dev/sonnet-worker/20261119_233758+0100-ok.md",
                "reports_dev/we+ird/20261119_233761-x.md",
            ])
            self.assertEqual(found[0].agent, "sonnet-worker")
            self.assertEqual(found[1].agent, "weird")  # the title never carries a character outside [A-Za-z0-9_.-]
            self.assertEqual(found[0].stamp, "20261119_233758")
            self.assertEqual(intake.card_title(found[0].agent, found[0].stamp), "Findings of sonnet-worker report 20261119_233758")


# The process sandbox denies unlisted binaries; this suite drives the real trddgrep.
@pytest.mark.real_subprocess("trddgrep")
@unittest.skipUnless(shutil.which("trddgrep"), "trddgrep is not installed")
class TestIntakeCards(unittest.TestCase):
    """End to end: the real detector and the real trddgrep in a tmp repo (never the real design/)."""

    def setUp(self):
        """trddgrep finds its ai-maestro install through $HOME, which conftest points at a tmp tree: link the real install into it."""
        real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        install = real_home / ".local" / "share" / "aimaestro"
        if not install.is_dir():
            self.skipTest("no ai-maestro install for trddgrep")
        link = Path(os.environ["HOME"]) / ".local" / "share" / "aimaestro"
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.exists():
            link.symlink_to(install)
            self.addCleanup(link.unlink)

    def _log(self, root: Path) -> str:
        """The detector log of the tmp project, for assertion messages."""
        log = root / ".janitor" / "logs" / "subagent-report.log"
        return log.read_text() if log.is_file() else "(no subagent-report.log)"

    def _project(self, tmp: str) -> Path:
        root = Path(tmp)
        _init_repo(root)
        for d in ("tasks", "proposals", "archived"):
            (root / "design" / d).mkdir(parents=True)
        return root

    def _report(self, root: Path, name: str, text: str, mtime: int, agent: str = "sonnet-worker") -> Path:
        f = root / "reports_dev" / agent / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        os.utime(f, (mtime, mtime))
        return f

    def _watermark(self, root: Path, value: int = 1) -> None:
        sd = root / ".janitor" / "state"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "subagent-report-intake-watermark.txt").write_text(str(value))

    def _cards(self, root: Path, folder: str = "tasks") -> list[Path]:
        return sorted((root / "design" / folder).glob("TRDD-*.md"))

    def test_first_enable_sets_watermark_and_cards_nothing(self):
        """The first fire only records the watermark: existing reports are never carded."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            self._report(root, "20261119_233758-a.md", "ISSUES: 2\n", 1_800_000_000)
            _run(root)
            self.assertEqual(self._cards(root), [])
            self.assertTrue((root / ".janitor" / "state" / "subagent-report-intake-watermark.txt").is_file())

    def test_report_with_issues_becomes_one_card_without_report_text(self):
        """ISSUES: 2 mints one todo card; title = folder + timestamp; no report text reaches the card; a re-run adds nothing."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            self._watermark(root)
            f = self._report(root, "20261119_233758+0100-a.md", "PRIVATE-FINDING-TEXT\nISSUES: 2\n", 1_800_000_000)
            out = _run(root)
            cards = self._cards(root)
            self.assertEqual(len(cards), 1, self._log(root))
            text = cards[0].read_text()
            self.assertIn("title: Findings of sonnet-worker report 20261119_233758\n", text)
            self.assertIn("column: todo\n", text)
            sha = hashlib.sha256(f.read_bytes()).hexdigest()
            key = f"reports_dev/sonnet-worker/20261119_233758+0100-a.md#{sha}"
            self.assertEqual(text.count(f"source-report: {key}\n"), 2)  # frontmatter field + body line
            self.assertNotIn("PRIVATE-FINDING-TEXT", text + cards[0].name)
            # The nudge is count-only: no path, no id.
            self.assertIn("1 open card(s)", out)
            # The real emitter and the quiet filter must agree (TRDD-V57FEWSK): the emitted nudge line carries
            # the prefix dispatch exempts, so it survives a quiet heartbeat instead of going to the ledger.
            nudge = [ln for ln in out.splitlines() if "open card(s)" in ln]
            self.assertEqual(len(nudge), 1, out)
            self.assertTrue(nudge[0].startswith(intake.INTAKE_NUDGE_PREFIX), nudge[0])
            self.assertEqual(dispatch._quiet_filter("subagent-report", nudge[0] + "\n"), nudge[0] + "\n")
            self.assertNotIn("reports_dev", out)
            self.assertNotIn("TRDD-", out)
            _run(root)
            self.assertEqual(len(self._cards(root)), 1)

    def test_none_zero_and_absent_issues_line_make_no_card(self):
        """ISSUES: none, ISSUES: 0 and a report with no ISSUES line are never carded."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            self._watermark(root)
            self._report(root, "20261119_233758-a.md", "ISSUES: none\n", 1_800_000_000)
            self._report(root, "20261119_233759-b.md", "ISSUES: 0\n", 1_800_000_001)
            self._report(root, "20261119_233800-c.md", "all fine\n", 1_800_000_002)
            _run(root)
            self.assertEqual(self._cards(root), [])

    def test_cap_of_three_per_fire_then_the_rest(self):
        """Five carded reports: 3 cards on the first fire, the other 2 on the next (watermark not advanced past the cap)."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            self._watermark(root)
            for i in range(5):
                self._report(root, f"2026111{i}_000000-r.md", "ISSUES: 1\n", 1_800_000_000 + i)
            _run(root)
            self.assertEqual(len(self._cards(root)), 3)
            _run(root)
            self.assertEqual(len(self._cards(root)), 5)
            _run(root)
            self.assertEqual(len(self._cards(root)), 5)

    def test_archived_card_still_dedupes(self):
        """A report whose card was archived (or moved to proposals/) is not carded again."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            self._watermark(root)
            self._report(root, "20261119_233758-a.md", "ISSUES: 1\n", 1_800_000_000)
            _run(root)
            (card,) = self._cards(root)
            card.rename(root / "design" / "archived" / card.name)
            self._watermark(root)  # rewind so the report is considered again
            _run(root)
            self.assertEqual(self._cards(root), [])
            self.assertEqual(len(self._cards(root, "archived")), 1)

    def test_edited_report_does_not_make_a_second_card(self):
        """The dedupe matches the PATH: an edit (new sha) of an already-carded report adds no card."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            self._watermark(root)
            f = self._report(root, "20261119_233758-a.md", "ISSUES: 1\n", 1_800_000_000)
            _run(root)
            f.write_text("more words\nISSUES: 5\n")
            os.utime(f, (1_800_000_100, 1_800_000_100))
            _run(root)
            self.assertEqual(len(self._cards(root)), 1)

    def test_project_without_design_tasks_is_a_no_op(self):
        """No design/tasks/ -> no card, no watermark, no crash, no output from the intake."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            self._watermark(root)
            self._report(root, "20261119_233758-a.md", "ISSUES: 1\n", 1_800_000_000)
            out = _run(root)
            self.assertFalse((root / "design").exists())
            self.assertNotIn("open card(s)", out)


def test_intake_nudge_reaches_stdout_through_the_real_dispatcher_on_a_quiet_heartbeat(tmp_path, monkeypatch, capsys):
    """TRDD-V57FEWSK end to end: dispatch._run_detector runs the REAL subagent-report detector in a tmp
    project with one open intake card, quiet mode on; the count nudge is printed on stdout (past the
    quiet filter and the day-scoped drift dedupe), not routed to the findings ledger."""
    _init_repo(tmp_path)
    tasks = tmp_path / "design" / "tasks"
    tasks.mkdir(parents=True)
    (tmp_path / ".janitor" / "state").mkdir(parents=True)
    key = "reports_dev/sonnet-worker/20261119_233758-a.md#" + "0" * 64
    (tasks / "TRDD-20261120_000000+0100-AAAAAAAA-findings.md").write_text(
        "---\ntrdd-id: AAAAAAAA\ntitle: Findings of sonnet-worker report 20261119_233758\n"
        f"column: todo\nsource-report: {key}\n---\n\nbody\n"
    )
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DETECTOR_TIMEOUT", "60")
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_VERBOSE", raising=False)
    for cached in (dispatch.state.project_root, dispatch.state.janitor_root, dispatch.state.state_dir):
        cached.cache_clear()
    def fire() -> str:
        try:
            dispatch._run_detector("subagent-report", interval=0)
        finally:
            for cached in (dispatch.state.project_root, dispatch.state.janitor_root, dispatch.state.state_dir):
                cached.cache_clear()
        return capsys.readouterr().out

    def nudges(out: str) -> list[str]:
        return [ln for ln in out.splitlines() if ln.startswith(intake.INTAKE_NUDGE_PREFIX)]

    first = nudges(fire())
    assert len(first) == 1 and "1 open card(s)" in first[0], first
    # Cadence, measured: a repeat of the SAME line is silent on the second fire. At least one of two day-keyed
    # layers holds it (the detector `emit_once` key `intake-open@<count>@d<day>`, the dispatcher drift
    # dedupe); this test does not tell which. A changed open-card count is a new line and shows at once.
    # Known flake: if fires 1 and 2 straddle the UTC day boundary the key changes and the next
    # assertion fails; the window is the few seconds one fire takes.
    assert nudges(fire()) == []
    (tasks / "TRDD-20261120_000001+0100-BBBBBBBB-findings.md").write_text(
        "---\ntrdd-id: BBBBBBBB\ntitle: Findings of sonnet-worker report 20261119_233759\n"
        f"column: todo\nsource-report: {key.replace('233758', '233759')}\n---\n\nbody\n"
    )
    changed = nudges(fire())
    assert len(changed) == 1 and "2 open card(s)" in changed[0], changed


if __name__ == "__main__":
    unittest.main()
    unittest.main()
