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
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from _fake_secrets import b62, secret  # noqa: E402
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
          echo "TITLE=${{ github.event.pull_request.title }}" >> "$GITHUB_ENV"
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

# --- Sentinel-port regex-tier fixtures -------------------------------------

HARDCODED_AWS_KEY_WORKFLOW = """\
name: bad-aws
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - run: |
          export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
"""

HARDCODED_GH_TOKEN_WORKFLOW = (
    "name: bad-token\n"
    "on: push\n"
    "jobs:\n"
    "  fail:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - run: |\n"
    f"          echo \"token={secret('ghp' + '_', 'zizmor-ghp-tok', 36)}\"\n"
)

HARDCODED_APIKEY_WORKFLOW = f"""\
name: bad-apikey
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - run: |
          api_key = "{b62('zizmor-apikey', 36)}"
"""

SECRET_VIA_SECRETS_CTX_WORKFLOW = """\
name: ok-secret
on: push
jobs:
  ok:
    runs-on: ubuntu-latest
    env:
      TOKEN: ${{ secrets.NPM_TOKEN }}
    steps:
      - run: echo done
"""

IDE_CONFIG_WRITE_WORKFLOW = """\
name: bad-ide
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo '{"allow": "*"}' > .claude/settings.json
"""

IDE_CONFIG_VSCODE_WORKFLOW = """\
name: bad-vscode
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - run: |
          cp tasks.json .vscode/tasks.json
"""

CURL_PIPE_SHELL_WORKFLOW = """\
name: bad-curl
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -sSL https://example.test/install.sh | sudo bash
"""

WGET_PIPE_SHELL_WORKFLOW = """\
name: bad-wget
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - run: |
          wget https://example.test/x.sh -O - | sh
"""

CURL_DOWNLOAD_THEN_VERIFY_WORKFLOW = """\
name: ok-curl
on: push
jobs:
  ok:
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -sSL https://example.test/install.sh -o install.sh
          sha256sum -c install.sh.sha256
          bash install.sh
"""

GIT_CONFIG_GLOBAL_WORKFLOW = """\
name: bad-gitconfig
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - run: |
          git config --global url."https://token@github.com/".insteadOf "https://github.com/"
"""

GIT_CONFIG_LOCAL_WORKFLOW = """\
name: ok-gitconfig
on: push
jobs:
  ok:
    runs-on: ubuntu-latest
    steps:
      - run: |
          git config --local user.name "ci-bot"
"""

GH_DEP_REF_WORKFLOW = """\
name: bad-dep
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - run: |
          npm install github:expressjs/express#abc1234
"""

GH_DEP_REF_GITPLUS_WORKFLOW = """\
name: bad-dep-git
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - run: |
          pnpm add git+https://github.com/lodash/lodash.git
"""

REGISTRY_INSTALL_WORKFLOW = """\
name: ok-dep
on: push
jobs:
  ok:
    runs-on: ubuntu-latest
    steps:
      - run: |
          npm install express@4.18.2
"""

JQ_ARG_ESCAPE_WORKFLOW = """\
name: bad-jq-escape
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo '{}' | jq --arg body "line1\\nline2" '.b = $body'
"""

DOCKER_LATEST_USES_WORKFLOW = """\
name: bad-docker-uses
on: push
jobs:
  fail:
    runs-on: ubuntu-latest
    steps:
      - uses: docker://alpine:latest
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
        """Container image on the mutable :latest tag fires unpinned-docker-image."""
        rules = self._find_rules(CONTAINER_LATEST_WORKFLOW)
        self.assertIn("unpinned-docker-image", rules)

    def test_docker_latest_uses_fires(self) -> None:
        """A docker:// uses pinned to :latest also fires unpinned-docker-image."""
        rules = self._find_rules(DOCKER_LATEST_USES_WORKFLOW)
        self.assertIn("unpinned-docker-image", rules)

    def test_hardcoded_aws_key_fires(self) -> None:
        """An inline AKIA AWS access key fires hardcoded-secrets."""
        rules = self._find_rules(HARDCODED_AWS_KEY_WORKFLOW)
        self.assertIn("hardcoded-secrets", rules)

    def test_hardcoded_gh_token_fires(self) -> None:
        """An inline ghp_ GitHub token fires hardcoded-secrets."""
        rules = self._find_rules(HARDCODED_GH_TOKEN_WORKFLOW)
        self.assertIn("hardcoded-secrets", rules)

    def test_hardcoded_apikey_assignment_fires(self) -> None:
        """A quoted api_key = "<30+ chars>" assignment fires hardcoded-secrets."""
        rules = self._find_rules(HARDCODED_APIKEY_WORKFLOW)
        self.assertIn("hardcoded-secrets", rules)

    def test_secret_via_secrets_context_does_not_fire(self) -> None:
        """A secret routed through ${{ secrets.* }} must NOT fire hardcoded-secrets."""
        rules = self._find_rules(SECRET_VIA_SECRETS_CTX_WORKFLOW)
        self.assertNotIn("hardcoded-secrets", rules)

    def test_ide_config_write_fires(self) -> None:
        """Redirecting output into .claude/ fires ide-config-injection."""
        rules = self._find_rules(IDE_CONFIG_WRITE_WORKFLOW)
        self.assertIn("ide-config-injection", rules)

    def test_ide_config_vscode_copy_fires(self) -> None:
        """Copying a file into .vscode/ fires ide-config-injection."""
        rules = self._find_rules(IDE_CONFIG_VSCODE_WORKFLOW)
        self.assertIn("ide-config-injection", rules)

    def test_curl_pipe_shell_fires(self) -> None:
        """curl ... | sudo bash fires curl-pipe-shell."""
        rules = self._find_rules(CURL_PIPE_SHELL_WORKFLOW)
        self.assertIn("curl-pipe-shell", rules)

    def test_wget_pipe_shell_fires(self) -> None:
        """wget ... -O - | sh fires curl-pipe-shell."""
        rules = self._find_rules(WGET_PIPE_SHELL_WORKFLOW)
        self.assertIn("curl-pipe-shell", rules)

    def test_curl_download_then_verify_does_not_fire(self) -> None:
        """Download-to-file, checksum, then run must NOT fire curl-pipe-shell."""
        rules = self._find_rules(CURL_DOWNLOAD_THEN_VERIFY_WORKFLOW)
        self.assertNotIn("curl-pipe-shell", rules)

    def test_git_config_global_fires(self) -> None:
        """git config --global ... insteadOf fires git-config-global."""
        rules = self._find_rules(GIT_CONFIG_GLOBAL_WORKFLOW)
        self.assertIn("git-config-global", rules)

    def test_git_config_local_does_not_fire(self) -> None:
        """git config --local must NOT fire git-config-global."""
        rules = self._find_rules(GIT_CONFIG_LOCAL_WORKFLOW)
        self.assertNotIn("git-config-global", rules)

    def test_github_dependency_ref_fires(self) -> None:
        """npm install github:owner/repo#ref fires github-dependency-refs."""
        rules = self._find_rules(GH_DEP_REF_WORKFLOW)
        self.assertIn("github-dependency-refs", rules)

    def test_github_dependency_gitplus_ref_fires(self) -> None:
        """pnpm add git+https://github.com/... fires github-dependency-refs."""
        rules = self._find_rules(GH_DEP_REF_GITPLUS_WORKFLOW)
        self.assertIn("github-dependency-refs", rules)

    def test_registry_install_does_not_fire(self) -> None:
        """npm install from the registry must NOT fire github-dependency-refs."""
        rules = self._find_rules(REGISTRY_INSTALL_WORKFLOW)
        self.assertNotIn("github-dependency-refs", rules)

    def test_jq_arg_escape_sequences_fires(self) -> None:
        """jq --arg with a literal \\n in the value fires jq-arg-escape-sequences."""
        rules = self._find_rules(JQ_ARG_ESCAPE_WORKFLOW)
        self.assertIn("jq-arg-escape-sequences", rules)

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

    # ---- Wave 14: ports from deep-workflow-security report ----

    def test_actions_allow_unsecure_commands_fires(self) -> None:
        wf = """\
on: push
env:
  ACTIONS_ALLOW_UNSECURE_COMMANDS: true
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo ok
"""
        rules = {f.rule_id for f in self.classifier.classify(wf)}
        self.assertIn("actions-allow-unsecure-commands", rules)

    def test_actions_allow_unsecure_quoted_fires(self) -> None:
        wf = """\
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    env:
      ACTIONS_ALLOW_UNSECURE_COMMANDS: "true"
    steps:
      - run: echo ok
"""
        rules = {f.rule_id for f in self.classifier.classify(wf)}
        self.assertIn("actions-allow-unsecure-commands", rules)

    def test_github_step_summary_injection_fires(self) -> None:
        wf = """\
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "PR: ${{ github.event.pull_request.title }}" >> $GITHUB_STEP_SUMMARY
"""
        rules = {f.rule_id for f in self.classifier.classify(wf)}
        self.assertIn("github-step-summary-injection", rules)

    def test_github_output_injection_fires(self) -> None:
        wf = """\
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - id: x
        run: |
          echo "branch=${{ github.head_ref }}" >> $GITHUB_OUTPUT
"""
        rules = {f.rule_id for f in self.classifier.classify(wf)}
        self.assertIn("github-output-injection", rules)

    def test_overprovisioned_secrets_tojson_fires(self) -> None:
        wf = """\
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    env:
      ALL_SECRETS: ${{ toJSON(secrets) }}
    steps:
      - run: echo "got"
"""
        rules = {f.rule_id for f in self.classifier.classify(wf)}
        self.assertIn("overprovisioned-secrets-tojson", rules)

    def test_clean_workflow_no_wave14_fps(self) -> None:
        """Hardened workflow must not fire any of the new rules."""
        wf = """\
on: push
permissions: {}
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@a1b2c3d4e5f6 # v4
        with:
          persist-credentials: false
      - run: echo ok
"""
        rules = {f.rule_id for f in self.classifier.classify(wf)}
        wave14_rules = {
            "actions-allow-unsecure-commands",
            "github-step-summary-injection",
            "github-output-injection",
            "overprovisioned-secrets-tojson",
        }
        self.assertEqual(rules & wave14_rules, set())


# --- PATTERNS_EXTRA wiring (audit HIGH-2 regression guard) ------------------
#
# The extension catalog scripts/lib/zizmor_patterns_extra.py was dead code:
# the classifier imported only PATTERNS, so 7 regex rules (incl. the CRITICAL
# workflow-run-pwn-checkout) never executed in production while their
# isolated unit tests passed and masked the gap. These tests fail if the
# union ever regresses — they go through the real Classifier(), not the
# raw PATTERNS_EXTRA dict.

WORKFLOW_RUN_PWN_CHECKOUT_WF = """\
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

INSTEADOF_SECRET_WF = """\
name: bad-insteadof
on: push
jobs:
  bad:
    runs-on: ubuntu-latest
    steps:
      - run: |
          git config url."https://x-access-token:${{ secrets.GH_PAT }}@github.com/".insteadOf "https://github.com/"
"""


class PatternsExtraWiringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = Classifier()

    def _find_rules(self, text: str) -> set[str]:
        return {f.rule_id for f in self.classifier.classify(text)}

    def test_every_extra_rule_is_reachable_through_classifier(self) -> None:
        """Each PATTERNS_EXTRA id must be wired into the classifier's dispatch
        (RE2 group names ∪ Python-re fallback), else it can never fire."""
        from lib.zizmor_patterns_extra import PATTERNS_EXTRA  # noqa: PLC0415

        reachable = set(self.classifier._re2_group_names.values())
        reachable |= {rid for rid, _ in self.classifier._fallback_compiled}
        missing = set(PATTERNS_EXTRA) - reachable
        self.assertEqual(missing, set(), f"PATTERNS_EXTRA ids not wired: {missing}")

    def test_workflow_run_pwn_checkout_fires_end_to_end(self) -> None:
        """The CRITICAL extra rule actually fires through classify() now that
        PATTERNS_EXTRA is merged (it was dead before the audit fix)."""
        rules = self._find_rules(WORKFLOW_RUN_PWN_CHECKOUT_WF)
        self.assertIn("workflow-run-pwn-checkout", rules)

    def test_insteadof_secret_fires_end_to_end(self) -> None:
        """A HIGH extra rule (insteadof-secret-in-url) fires through classify()."""
        rules = self._find_rules(INSTEADOF_SECRET_WF)
        self.assertIn("insteadof-secret-in-url", rules)

    def test_clean_workflow_fires_no_extra_rules(self) -> None:
        """A hardened workflow must not trip any extension-catalog rule."""
        from lib.zizmor_patterns_extra import PATTERNS_EXTRA  # noqa: PLC0415

        rules = self._find_rules(CLEAN_WORKFLOW)
        self.assertEqual(rules & set(PATTERNS_EXTRA), set())


if __name__ == "__main__":
    unittest.main()
