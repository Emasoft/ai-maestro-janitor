"""Tests for the report-to-trdd-drift detector.

The detector reminds (once per interval, until converted) when a DECISION /
synthesis-class report under reports/ is referenced by NO TRDD — enforcing
"reports are evidence; decisions become TRDDs". Real I/O, no mocks: each case
builds a temp project (design/tasks/ + reports/) and runs the detector as a
subprocess with CLAUDE_PROJECT_DIR pointed at it.
"""

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "report-to-trdd-drift.py"


def _trdd(status: str, title: str, body: str = "") -> str:
    return (
        f"---\ntrdd-id: 00000000-0000-0000-0000-000000000000\n"
        f"title: {title}\nstatus: {status}\n"
        f"created: 2026-05-30T10:00:00+0200\nupdated: 2026-05-30T10:00:00+0200\n---\n\n"
        f"# TRDD — {title}\n\n{body}\n## Problem\nx\n"
    )


def _aged(path: Path, secs: int = 300) -> None:
    """Backdate mtime past the detector's fresh-write grace window."""
    t = time.time() - secs
    os.utime(path, (t, t))


def _run(project: Path, session: str = "testsess") -> str:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_SESSION_ID"] = session
    # This test exercises the report→TRDD LOGIC, not the ai-maestro context gate
    # (TRDD-db169d9e R1) — the temp project isn't an ai-maestro-plugins member,
    # so force the gate ON. The gate is covered by test_context_gate_detectors.py.
    env["JANITOR_FORCE_AI_MAESTRO"] = "1"
    env.pop("CLAUDE_PLUGIN_OPTION_REPORT_TO_TRDD_INTERVAL", None)
    env.pop("CLAUDE_PLUGIN_OPTION_TRDD_PATH", None)
    res = subprocess.run(
        [sys.executable, str(DETECTOR)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    return res.stdout


class TestReportToTrddDrift(unittest.TestCase):
    def _proj(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "design" / "tasks").mkdir(parents=True)
        (root / "reports" / "audit").mkdir(parents=True)
        return root

    def test_unconverted_decision_report_flagged(self):
        """A decision report no TRDD references is flagged for conversion."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            (root / "design/tasks/TRDD-20260530_100000+0200-aaaaaaaa-x.md").write_text(
                _trdd("in-progress", "Active"))
            rep = root / "reports/audit/20260530_120000+0200-CONSOLIDATED.md"
            rep.write_text("# decision\nrecommended stack")
            _aged(rep)
            out = _run(root)
            self.assertIn("[report-to-trdd]", out)
            self.assertIn("CONSOLIDATED.md", out)

    def test_converted_decision_report_not_flagged(self):
        """A decision report cited by a TRDD body is treated as converted → silent."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            rep = root / "reports/audit/20260530_120000+0200-CONSOLIDATED.md"
            rep.write_text("# decision")
            _aged(rep)
            (root / "design/tasks/TRDD-20260530_100000+0200-bbbbbbbb-x.md").write_text(
                _trdd("in-progress", "Active",
                      body="Evidence: reports/audit/20260530_120000+0200-CONSOLIDATED.md"))
            out = _run(root)
            self.assertEqual(out.strip(), "")

    def test_data_report_ignored(self):
        """A non-decision-named report (e.g. lint output) is never flagged."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            (root / "design/tasks/TRDD-20260530_100000+0200-cccccccc-x.md").write_text(
                _trdd("in-progress", "Active"))
            rep = root / "reports/audit/20260530_120000+0200-lint-output.md"
            rep.write_text("ruff: all clean")
            _aged(rep)
            out = _run(root)
            self.assertEqual(out.strip(), "")

    def test_fresh_report_skipped(self):
        """A just-written decision report (within the grace window) is skipped."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            (root / "design/tasks/TRDD-20260530_100000+0200-dddddddd-x.md").write_text(
                _trdd("in-progress", "Active"))
            # NOT aged → mtime≈now → inside the fresh-write grace → skipped.
            (root / "reports/audit/20260530_120000+0200-synthesis.md").write_text("# d")
            out = _run(root)
            self.assertEqual(out.strip(), "")

    def test_no_design_tasks_silent(self):
        """A project without design/tasks/ (doesn't use TRDDs) is silent."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "reports" / "audit").mkdir(parents=True)
            rep = root / "reports/audit/20260530_120000+0200-CONSOLIDATED.md"
            rep.write_text("# d")
            _aged(rep)
            out = _run(root)
            self.assertEqual(out.strip(), "")

    def test_no_reports_silent(self):
        """A project without reports/ is silent."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "design" / "tasks").mkdir(parents=True)
            (root / "design/tasks/TRDD-20260530_100000+0200-eeeeeeee-x.md").write_text(
                _trdd("in-progress", "Active"))
            out = _run(root)
            self.assertEqual(out.strip(), "")

    def test_dedupe_once_per_interval(self):
        """The same unconverted set reminds once per interval (2nd run silent)."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            (root / "design/tasks/TRDD-20260530_100000+0200-ffffffff-x.md").write_text(
                _trdd("in-progress", "Active"))
            rep = root / "reports/audit/20260530_120000+0200-recommendation.md"
            rep.write_text("# d")
            _aged(rep)
            first = _run(root)
            second = _run(root)
            self.assertIn("[report-to-trdd]", first)
            self.assertEqual(second.strip(), "")

    def _mem_proj(self, tmp: str) -> Path:
        """A project whose reports/ also holds the memory-curator subdir."""
        root = Path(tmp)
        (root / "design" / "tasks").mkdir(parents=True)
        (root / "reports" / "memory-subconscious-agent").mkdir(parents=True)
        (root / "design/tasks/TRDD-20260530_100000+0200-aaaaaaaa-x.md").write_text(
            _trdd("in-progress", "Active"))
        return root

    def test_memory_abstain_report_not_flagged(self):
        """An ABSTAINED memory-subconscious pass report carries no decision → not flagged.

        Its filename matches the DECISION regex (substring 'consolidat'), but the
        body's `**Outcome:** ABSTAINED … nothing mutated` marks a no-op pass. Issue #63.
        """
        with TemporaryDirectory() as tmp:
            root = self._mem_proj(tmp)
            rep = root / "reports/memory-subconscious-agent/20260625_153512+0200-consolidate-abstain-no-candidates.md"
            rep.write_text(
                "# CONSOLIDATE pass — report\n\n"
                "- **Pass:** CONSOLIDATE (MERGE leg of the wikimem editor)\n"
                "- **Outcome:** **ABSTAINED — no merge performed, nothing mutated.** "
                "Zero same-subject aggregation candidates exist in any editable scope.\n")
            _aged(rep)
            out = _run(root)
            self.assertEqual(out.strip(), "")

    def test_memory_nothing_due_report_not_flagged(self):
        """A 'NOTHING DUE' memory-subconscious pass report is a no-op → not flagged."""
        with TemporaryDirectory() as tmp:
            root = self._mem_proj(tmp)
            # Filename matches DECISION regex via the '-plan' fragment in the slug.
            rep = root / "reports/memory-subconscious-agent/20260624_021706+0200-consolidate-no-merge-plan-due.md"
            rep.write_text(
                "# CONSOLIDATE pass — NOTHING DUE\n\n"
                "- **Pass:** CONSOLIDATE\n"
                "- **Outcome:** NOTHING DUE — no scope crossed its cadence boundary; "
                "mutated nothing, emitted nothing into any corpus.\n")
            _aged(rep)
            out = _run(root)
            self.assertEqual(out.strip(), "")

    # --- the format the curator ACTUALLY writes (measured correction 2026-07-29) ------
    #
    # The three tests above synthesize an inline `**Outcome:** …` label. Across the 51
    # real curator reports on disk, ZERO use that spelling — so they passed while the
    # exclusion never once fired in production, and every abstain was nagged forever.
    # That is the "a test that constructs its own precondition proves the reader is
    # correct GIVEN a writer, and says nothing about whether a writer exists" trap, which
    # this repo has already been bitten by once (disarmed.flag: four readers, no writer).
    # These use the shapes taken verbatim from real reports.

    def test_real_curator_outcome_heading_abstained_not_flagged(self):
        """The REAL no-op shape: a `## Outcome` heading with the verb on the next line.

        Copied from `20260729_051725+0200-consolidate-local.md`. This is the form that
        was nagged every cadence because the detector only looked for an inline label.
        """
        with TemporaryDirectory() as tmp:
            root = self._mem_proj(tmp)
            rep = root / "reports/memory-subconscious-agent/20260729_051725+0200-consolidate-local.md"
            rep.write_text(
                "# CONSOLIDATE pass — LOCAL scope\n\n"
                "Scope: LOCAL\n\n"
                "## Verdict\n\n"
                "NOT a duplicate by prior passes.\n\n"
                "## Outcome\n\n"
                "ABSTAINED — no aggregation candidates in LOCAL scope (librarian found none).\n")
            _aged(rep)
            out = _run(root)
            self.assertEqual(out.strip(), "")

    def test_real_curator_outcome_heading_nothing_due_not_flagged(self):
        """Same heading shape, `NOTHING DUE` verb — taken from a real harvest report."""
        with TemporaryDirectory() as tmp:
            root = self._mem_proj(tmp)
            rep = root / "reports/memory-subconscious-agent/20260708_224524+0200-harvest-local-nothing-due-plan.md"
            rep.write_text(
                "# HARVEST pass — LOCAL scope\n\n"
                "## Outcome\n\n"
                "NOTHING DUE — clean no-op. Buffer (`MEMORY.md`) left untouched.\n")
            _aged(rep)
            out = _run(root)
            self.assertEqual(out.strip(), "")

    def test_real_curator_h1_title_abstain_not_flagged(self):
        """Some passes declare the no-op only in the H1 title and carry no Outcome section.

        Copied from `20260727_100051+0200-consolidate-local-abstain.md`. An H1 is anchored,
        so it cannot be a passing mention of an abstained sub-candidate in prose.
        """
        with TemporaryDirectory() as tmp:
            root = self._mem_proj(tmp)
            rep = root / "reports/memory-subconscious-agent/20260727_100051+0200-consolidate-local-abstain.md"
            rep.write_text(
                "# CONSOLIDATE pass — LOCAL scope — abstained\n\n"
                "- **Scope**: LOCAL\n"
                "- **Editor enabled**: yes\n")
            _aged(rep)
            out = _run(root)
            self.assertEqual(out.strip(), "")

    def test_outcome_heading_with_a_MUTATING_verb_is_still_flagged(self):
        """THE SAFETY CONTROL. A `## Outcome` section whose verb is a real mutation must
        still be flagged — otherwise the widened pattern would silence genuine decisions,
        which is far worse than the over-nagging it fixes.

        The filename must itself trip `_DECISION_RE` ('consolidat'), or the report is
        skipped one gate earlier and the test proves nothing about the no-op pattern —
        which is exactly what the first cut of this test did.
        """
        with TemporaryDirectory() as tmp:
            root = self._mem_proj(tmp)
            rep = root / "reports/memory-subconscious-agent/20260728_160200+0200-consolidate-security-trio.md"
            rep.write_text(
                "# CONSOLIDATE pass — USER scope\n\n"
                "## Outcome\n\n"
                "MERGED the security-trio pages; recommend a follow-up TRDD.\n")
            _aged(rep)
            out = _run(root)
            self.assertIn("[report-to-trdd]", out)
            self.assertIn("consolidate-security-trio.md", out)

    def test_an_abstain_mentioned_in_PROSE_does_not_silence_a_decision(self):
        """Anchoring proof: a real decision report that merely MENTIONS an abstained
        sub-candidate mid-body is still flagged. This is the property the original
        inline-label pattern was protecting, and widening must not lose it.
        """
        with TemporaryDirectory() as tmp:
            root = self._mem_proj(tmp)
            rep = root / "reports/memory-subconscious-agent/20260729_120000+0200-consolidate-merged-plan.md"
            rep.write_text(
                "# CONSOLIDATE pass — USER scope\n\n"
                "Candidate A/B merged. A third candidate was abstained on for now, and\n"
                "nothing was due for the LOCAL scope this pass.\n\n"
                "## Outcome\n\n"
                "MERGED two pages; recommend a follow-up TRDD.\n")
            _aged(rep)
            out = _run(root)
            self.assertIn("[report-to-trdd]", out)
            self.assertIn("consolidate-merged-plan.md", out)

    def test_memory_decision_report_still_flagged(self):
        """A GENUINE decision report under the SAME curator dir is still flagged.

        Proves the fix keys on the no-op OUTCOME marker, not a blanket exclusion of
        the memory-subconscious-agent dir: a pass that actually merged + recommends
        follow-up has a real decision to convert.
        """
        with TemporaryDirectory() as tmp:
            root = self._mem_proj(tmp)
            rep = root / "reports/memory-subconscious-agent/20260625_160000+0200-security-trio-consolidation-plan.md"
            rep.write_text(
                "# CONSOLIDATE pass — report\n\n"
                "- **Pass:** CONSOLIDATE\n"
                "- **Outcome:** MERGED the security-trio pages; recommend a follow-up "
                "TRDD to wire the chosen option into the heartbeat.\n")
            _aged(rep)
            out = _run(root)
            self.assertIn("[report-to-trdd]", out)
            self.assertIn("security-trio-consolidation-plan.md", out)


if __name__ == "__main__":
    unittest.main()
