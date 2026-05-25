# Tests for scripts/lib/sentinel/rules_repo.py — the repo-level Sentinel
# rules (currently missing-zizmor) that run once over every workflow's text.

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.sentinel.rules_repo import REPO_RULES, missing_zizmor  # noqa: E402

WF_WITH_ZIZMOR_ACTION = """\
name: zizmor
on: pull_request
jobs:
  z:
    runs-on: ubuntu-latest
    steps:
      - uses: zizmorcore/zizmor-action@e673c3917a1aef3c65c972347ed84ccd013ecda4
"""

WF_WITH_ZIZMOR_RUN = """\
name: sec
on: push
jobs:
  z:
    runs-on: ubuntu-latest
    steps:
      - run: uvx zizmor .
"""

WF_PLAIN = """\
name: ci
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""


class MissingZizmorTest(unittest.TestCase):
    def _ids(self, texts: list[str]) -> set[str]:
        ids: set[str] = set()
        for rule in REPO_RULES:
            for finding in rule(texts):
                ids.add(finding.rule_id)
        return ids

    def test_fires_when_no_workflow_runs_zizmor(self) -> None:
        """missing-zizmor fires when none of the repo's workflows run zizmor."""
        self.assertIn("missing-zizmor", self._ids([WF_PLAIN]))

    def test_silent_when_a_workflow_uses_the_zizmor_action(self) -> None:
        """A zizmor action anywhere suppresses missing-zizmor."""
        self.assertEqual(self._ids([WF_PLAIN, WF_WITH_ZIZMOR_ACTION]), set())

    def test_silent_when_a_workflow_runs_zizmor_as_a_command(self) -> None:
        """A `run: zizmor` command anywhere suppresses missing-zizmor."""
        self.assertEqual(missing_zizmor([WF_PLAIN, WF_WITH_ZIZMOR_RUN]), [])

    def test_severity_is_minor(self) -> None:
        """missing-zizmor is a MINOR (low-severity) advisory."""
        findings = missing_zizmor([WF_PLAIN])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "MINOR")
        self.assertEqual(findings[0].rule_id, "missing-zizmor")


if __name__ == "__main__":
    unittest.main()
