# Tests for scripts/lib/zizmor_patterns_extra.py — the EXTENSION catalog
# of workflow regex rules ported from the deep-workflow-security audit.
#
# These tests validate the regex patterns directly (no classifier
# dependency) so the module can be merged into the classifier later
# without changing this contract. Each test compiles the pattern, runs
# re.search() against a fixture workflow, and asserts on the match
# outcome — exercising both positive (fires) and negative (clean)
# behaviour.
#
# All patterns are RE2-safe by construction; the tests run against
# Python's built-in re module which is a superset.

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

# Allow running from project root with `python -m pytest tests/...`
# The lib.* imports MUST come after this sys.path mutation, hence the noqa.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.zizmor_patterns_extra import (  # noqa: E402
    PATTERN_FALLBACK_FLAGS_EXTRA,
    PATTERNS_EXTRA,
)

# ---------- Fixtures ----------

WORKFLOW_RUN_PWN_CHECKOUT = """\
name: bad-workflow-run
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
jobs:
  bad:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          ref: ${{ github.event.workflow_run.head_sha }}
"""

WORKFLOW_RUN_HEAD_BRANCH = """\
name: bad-workflow-run-branch
on:
  workflow_run:
    workflows: [CI]
jobs:
  bad:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          ref: ${{ github.event.workflow_run.head_branch }}
"""

WORKFLOW_RUN_SAFE_CHECKOUT = """\
name: ok-workflow-run
on:
  workflow_run:
    workflows: [CI]
jobs:
  ok:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
"""

MATRIX_FROMJSON_PR = """\
name: bad-matrix
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        target: ${{ fromJSON(${{ github.event.pull_request.body }}) }}
    steps:
      - run: echo ${{ matrix.target }}
"""

MATRIX_FROMJSON_HEAD_REF = """\
name: bad-matrix-headref
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        target: ${{ fromJSON(${{ github.head_ref }}) }}
    steps:
      - run: echo ${{ matrix.target }}
"""

MATRIX_STATIC_OK = """\
name: ok-matrix
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node: [18, 20, 22]
    steps:
      - run: node --version
"""

GH_APP_SKIP_REVOKE = """\
name: bad-app-token
on: push
jobs:
  bad:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/create-github-app-token@v1
        with:
          app-id: ${{ secrets.APP_ID }}
          private-key: ${{ secrets.APP_KEY }}
          skip-token-revoke: true
"""

GH_APP_REVOKE_FALSE = """\
name: bad-app-token-tibdex
on: push
jobs:
  bad:
    runs-on: ubuntu-latest
    steps:
      - uses: tibdex/github-app-token@v2
        with:
          app_id: ${{ secrets.APP_ID }}
          private_key: ${{ secrets.APP_KEY }}
          revoke-token: false
"""

GH_APP_DEFAULT_OK = """\
name: ok-app-token
on: push
jobs:
  ok:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/create-github-app-token@v1
        with:
          app-id: ${{ secrets.APP_ID }}
          private-key: ${{ secrets.APP_KEY }}
"""

ACTIONS_DEBUG_COMMITTED = """\
name: bad-debug
on: push
env:
  ACTIONS_STEP_DEBUG: true
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo ok
"""

ACTIONS_RUNNER_DEBUG_COMMITTED = """\
name: bad-runner-debug
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    env:
      ACTIONS_RUNNER_DEBUG: "1"
    steps:
      - run: echo ok
"""

ACTIONS_DEBUG_VIA_SECRET_OK = """\
name: ok-debug-via-secret
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    env:
      ACTIONS_STEP_DEBUG: ${{ secrets.DEBUG_FLAG }}
    steps:
      - run: echo ok
"""

DEPENDABOT_ACTOR_EQ = """\
name: bad-actor-eq
on: pull_request
jobs:
  check:
    if: github.actor == 'dependabot[bot]'
    runs-on: ubuntu-latest
    steps:
      - run: echo dependabot path
"""

DEPENDABOT_ACTOR_CONTAINS = """\
name: bad-actor-contains
on: pull_request
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - if: contains(github.actor, 'dependabot')
        run: echo bypassable
"""

DEPENDABOT_ACTOR_NEQ_OK = """\
name: ok-actor-exclusion
on: pull_request
jobs:
  check:
    if: github.actor != 'dependabot[bot]'
    runs-on: ubuntu-latest
    steps:
      - run: echo human only
"""

INSTEADOF_WITH_SECRET = """\
name: bad-insteadof
on: push
jobs:
  bad:
    runs-on: ubuntu-latest
    steps:
      - run: |
          git config url."https://x-access-token:${{ secrets.GH_PAT }}@github.com/".insteadOf "https://github.com/"
"""

INSTEADOF_WITH_GH_TOKEN = """\
name: bad-insteadof-ghtoken
on: push
jobs:
  bad:
    runs-on: ubuntu-latest
    steps:
      - run: |
          git config url."https://x-access-token:${{ github.token }}@github.com/".insteadOf "https://github.com/"
"""

INSTEADOF_STATIC_URL_OK = """\
name: ok-insteadof-static
on: push
jobs:
  ok:
    runs-on: ubuntu-latest
    steps:
      - run: |
          git config url."https://github.com/myorg/".insteadOf "git@github.com:myorg/"
"""

CONTINUE_ON_ERROR_SECURITY = """\
name: bad-coe-scan
on: push
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: some/security-scanner@v1
        continue-on-error: true  # scan failures shouldn't block merge
"""

CONTINUE_ON_ERROR_BENIGN_OK = """\
name: ok-coe-benign
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: flaky-network-step
        continue-on-error: true  # network is flaky on this runner
"""


# ---------- Helpers ----------

def _matches(rule_id: str, text: str) -> bool:
    """Return True iff the pattern for rule_id matches anywhere in text."""
    pattern, _severity, _desc = PATTERNS_EXTRA[rule_id]
    return re.search(pattern, text, flags=re.MULTILINE) is not None


# ---------- Tests ----------

class PatternsExtraStructureTest(unittest.TestCase):
    """Sanity checks on the dict shape and compile-ability."""

    def test_all_patterns_compile(self) -> None:
        """Every regex must compile under Python's re module."""
        for rule_id, (pattern, _sev, _desc) in PATTERNS_EXTRA.items():
            try:
                re.compile(pattern)
            except re.error as exc:
                self.fail(f"pattern {rule_id!r} failed to compile: {exc}")

    def test_severities_are_valid(self) -> None:
        """Severity must be one of CRITICAL / HIGH / MAJOR / MINOR."""
        valid = {"CRITICAL", "HIGH", "MAJOR", "MINOR"}
        for rule_id, (_pattern, severity, _desc) in PATTERNS_EXTRA.items():
            self.assertIn(
                severity,
                valid,
                f"rule {rule_id!r} has invalid severity {severity!r}",
            )

    def test_descriptions_nonempty(self) -> None:
        """Every rule must ship a non-empty description."""
        for rule_id, (_pattern, _sev, desc) in PATTERNS_EXTRA.items():
            self.assertTrue(
                desc and desc.strip(),
                f"rule {rule_id!r} has empty description",
            )

    def test_fallback_flags_cover_every_rule(self) -> None:
        """PATTERN_FALLBACK_FLAGS_EXTRA must list every rule id."""
        self.assertEqual(
            set(PATTERN_FALLBACK_FLAGS_EXTRA.keys()),
            set(PATTERNS_EXTRA.keys()),
        )

    def test_all_patterns_re2_safe(self) -> None:
        """No lookaround / backref tokens in any pattern (RE2 invariant)."""
        forbidden = ("(?=", "(?!", "(?<=", "(?<!", "\\1", "\\2", "\\3")
        for rule_id, (pattern, _sev, _desc) in PATTERNS_EXTRA.items():
            for token in forbidden:
                self.assertNotIn(
                    token,
                    pattern,
                    f"rule {rule_id!r} contains RE2-unsafe token {token!r}",
                )

    def test_no_collisions_with_base_patterns(self) -> None:
        """PATTERNS_EXTRA ids must not collide with the base PATTERNS dict."""
        from lib.zizmor_patterns import PATTERNS  # noqa: PLC0415

        collisions = set(PATTERNS.keys()) & set(PATTERNS_EXTRA.keys())
        self.assertEqual(
            collisions,
            set(),
            f"rule id collision with base PATTERNS: {collisions}",
        )


class WorkflowRunPwnCheckoutTest(unittest.TestCase):
    def test_head_sha_fires(self) -> None:
        self.assertTrue(_matches("workflow-run-pwn-checkout", WORKFLOW_RUN_PWN_CHECKOUT))

    def test_head_branch_fires(self) -> None:
        self.assertTrue(_matches("workflow-run-pwn-checkout", WORKFLOW_RUN_HEAD_BRANCH))

    def test_safe_workflow_run_does_not_fire(self) -> None:
        self.assertFalse(_matches("workflow-run-pwn-checkout", WORKFLOW_RUN_SAFE_CHECKOUT))


class MatrixFromJsonUntrustedTest(unittest.TestCase):
    def test_pr_body_fromjson_fires(self) -> None:
        self.assertTrue(_matches("matrix-fromjson-untrusted", MATRIX_FROMJSON_PR))

    def test_head_ref_fromjson_fires(self) -> None:
        self.assertTrue(_matches("matrix-fromjson-untrusted", MATRIX_FROMJSON_HEAD_REF))

    def test_static_matrix_does_not_fire(self) -> None:
        self.assertFalse(_matches("matrix-fromjson-untrusted", MATRIX_STATIC_OK))


class GitHubAppSkipTokenRevokeTest(unittest.TestCase):
    def test_skip_token_revoke_true_fires(self) -> None:
        self.assertTrue(_matches("github-app-skip-token-revoke", GH_APP_SKIP_REVOKE))

    def test_revoke_token_false_fires(self) -> None:
        self.assertTrue(_matches("github-app-skip-token-revoke", GH_APP_REVOKE_FALSE))

    def test_default_does_not_fire(self) -> None:
        self.assertFalse(_matches("github-app-skip-token-revoke", GH_APP_DEFAULT_OK))


class ActionsDebugEnvCommittedTest(unittest.TestCase):
    def test_step_debug_true_fires(self) -> None:
        self.assertTrue(_matches("actions-debug-env-committed", ACTIONS_DEBUG_COMMITTED))

    def test_runner_debug_quoted_one_fires(self) -> None:
        self.assertTrue(_matches("actions-debug-env-committed", ACTIONS_RUNNER_DEBUG_COMMITTED))

    def test_debug_via_secret_does_not_fire(self) -> None:
        """Routing the debug flag through a repo secret is the SAFE pattern."""
        self.assertFalse(_matches("actions-debug-env-committed", ACTIONS_DEBUG_VIA_SECRET_OK))


class DependabotActorSpoofableTest(unittest.TestCase):
    def test_actor_eq_dependabot_fires(self) -> None:
        self.assertTrue(_matches("dependabot-actor-spoofable", DEPENDABOT_ACTOR_EQ))

    def test_actor_contains_dependabot_fires(self) -> None:
        self.assertTrue(_matches("dependabot-actor-spoofable", DEPENDABOT_ACTOR_CONTAINS))

    def test_actor_neq_dependabot_does_not_fire(self) -> None:
        """`!= 'dependabot[bot]'` is an exclusion gate — safe, must not fire."""
        self.assertFalse(_matches("dependabot-actor-spoofable", DEPENDABOT_ACTOR_NEQ_OK))


class InsteadOfSecretInUrlTest(unittest.TestCase):
    def test_secret_in_insteadof_url_fires(self) -> None:
        self.assertTrue(_matches("insteadof-secret-in-url", INSTEADOF_WITH_SECRET))

    def test_github_token_in_insteadof_url_fires(self) -> None:
        self.assertTrue(_matches("insteadof-secret-in-url", INSTEADOF_WITH_GH_TOKEN))

    def test_static_insteadof_url_does_not_fire(self) -> None:
        self.assertFalse(_matches("insteadof-secret-in-url", INSTEADOF_STATIC_URL_OK))


class ContinueOnErrorOnSecurityStepTest(unittest.TestCase):
    def test_continue_on_error_security_comment_fires(self) -> None:
        self.assertTrue(_matches("continue-on-error-on-security-step", CONTINUE_ON_ERROR_SECURITY))

    def test_continue_on_error_benign_comment_does_not_fire(self) -> None:
        """continue-on-error with a non-security comment must not fire."""
        self.assertFalse(
            _matches("continue-on-error-on-security-step", CONTINUE_ON_ERROR_BENIGN_OK)
        )


if __name__ == "__main__":
    unittest.main()
