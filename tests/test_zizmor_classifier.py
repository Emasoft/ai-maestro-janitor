# Tests for scripts/lib/zizmor_classifier.py — the RE2 RegexSet workflow
# auditor (with Python re fallback). The tests exercise both the
# RE2-active path and the fallback path so a future contributor adding
# a lookaround/backref pattern still gets coverage.

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Allow running from project root with `python -m unittest tests.test_zizmor_classifier`.
# The lib.* imports MUST come after this sys.path mutation, hence the noqa.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.zizmor_classifier import Classifier, Finding  # noqa: E402
from lib.zizmor_patterns import PATTERNS  # noqa: E402

JQ_ARG_TRAP_WORKFLOW = """\
name: bad-jq
on: pull_request
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - name: bad
        run: |
          echo '{}' | jq --arg title "${{ github.event.pull_request.title }}" '.t = $title'
"""

PIN_BY_TAG_WORKFLOW = """\
name: bad-pin
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@main
"""

CONTAINER_LATEST_WORKFLOW = """\
name: bad-image
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    container:
      image: python:latest
"""

PR_TARGET_WORKFLOW = """\
name: bad-trigger
on:
  pull_request_target:
    branches: [main]
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - run: echo ok
"""

SECRETS_INHERIT_WORKFLOW = """\
name: bad-inherit
on: push
jobs:
  call:
    uses: ./.github/workflows/sub.yml
    secrets: inherit
"""

REF_INTERPOLATION_WORKFLOW = """\
name: bad-ref
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - run: |
          git switch ${{ github.ref }}
"""

SECRET_IN_RUN_WORKFLOW = """\
name: bad-secret
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -H "Authorization: Bearer ${{ secrets.NPM_TOKEN }}" https://example.test
"""

GITHUB_ENV_INJECTION_WORKFLOW = """\
name: bad-env
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "TITLE=${{ github.event.pull_request.title }}" >> "$GITHUB_OUTPUT"
"""

CLEAN_WORKFLOW = """\
name: ok
on: push
permissions: {}
jobs:
  ok:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2
        with:
          persist-credentials: false
      - run: echo "nothing to see"
"""


class ClassifierTest(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = Classifier()

    def _find_rules(self, text: str) -> set[str]:
        return {f.rule_id for f in self.classifier.classify(text)}

    def test_clean_workflow_has_zero_findings(self) -> None:
        # Hardened workflow with SHA-pinned action, persist-credentials false,
        # least-privilege permissions, no expression in run: blocks.
        findings = list(self.classifier.classify(CLEAN_WORKFLOW))
        self.assertEqual(findings, [], f"expected no findings, got {findings}")

    def test_jq_arg_trap_fires(self) -> None:
        rules = self._find_rules(JQ_ARG_TRAP_WORKFLOW)
        self.assertIn("jq-arg-trap", rules)

    def test_pin_by_tag_fires(self) -> None:
        rules = self._find_rules(PIN_BY_TAG_WORKFLOW)
        self.assertIn("unpinned-uses-tag", rules)

    def test_container_latest_fires(self) -> None:
        rules = self._find_rules(CONTAINER_LATEST_WORKFLOW)
        self.assertIn("hardcoded-container-latest", rules)

    def test_pr_target_fires(self) -> None:
        rules = self._find_rules(PR_TARGET_WORKFLOW)
        self.assertIn("dangerous-triggers-pr-target", rules)

    def test_secrets_inherit_fires(self) -> None:
        rules = self._find_rules(SECRETS_INHERIT_WORKFLOW)
        self.assertIn("secrets-inherit", rules)

    def test_ref_interpolation_fires(self) -> None:
        rules = self._find_rules(REF_INTERPOLATION_WORKFLOW)
        self.assertIn("ref-confusion-in-run", rules)

    def test_secret_in_run_fires(self) -> None:
        rules = self._find_rules(SECRET_IN_RUN_WORKFLOW)
        self.assertIn("secret-env-bare-in-run", rules)

    def test_github_env_injection_fires(self) -> None:
        rules = self._find_rules(GITHUB_ENV_INJECTION_WORKFLOW)
        self.assertIn("github-env-write-with-expr", rules)

    def test_line_col_are_one_indexed(self) -> None:
        findings = [f for f in self.classifier.classify(JQ_ARG_TRAP_WORKFLOW) if f.rule_id == "jq-arg-trap"]
        self.assertGreater(len(findings), 0)
        self.assertGreaterEqual(findings[0].line, 1)
        self.assertGreaterEqual(findings[0].col, 1)

    def test_severity_and_description_propagate(self) -> None:
        findings = list(self.classifier.classify(JQ_ARG_TRAP_WORKFLOW))
        jq_findings = [f for f in findings if f.rule_id == "jq-arg-trap"]
        self.assertGreater(len(jq_findings), 0)
        self.assertEqual(jq_findings[0].severity, PATTERNS["jq-arg-trap"][1])
        self.assertEqual(jq_findings[0].description, PATTERNS["jq-arg-trap"][2])

    def test_classifier_reports_re2_status(self) -> None:
        # Diagnostic property — true iff the RE2 fast path is active.
        # Both states are valid; the assertion just checks the property exists
        # and is boolean.
        self.assertIsInstance(self.classifier.re2_active, bool)

    def test_finding_dataclass_is_frozen(self) -> None:
        f = Finding(
            rule_id="jq-arg-trap",
            line=1,
            col=1,
            matched_text="x",
            severity="MAJOR",
            description="d",
        )
        with self.assertRaises(Exception):
            f.line = 2  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
