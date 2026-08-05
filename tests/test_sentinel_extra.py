"""Tests for the extended Sentinel structural rules.

Mirrors the layout of tests/test_sentinel_context.py: each rule has a
positive case (the attack shape fires) and one or more negative cases
(safe variants do not fire). All workflows are real GitHub Actions YAML
to keep the parse path honest.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.sentinel.model import Workflow  # noqa: E402
from lib.sentinel.rules_extra import RULES  # noqa: E402


def fired(text):
    """Return the set of rule_ids that fire on the given workflow YAML."""
    wf = Workflow("t.yml", text)
    ids = set()
    for r in RULES:
        for f in r.check(wf):
            ids.add(f.rule_id)
    return ids


def findings_for(rule_name, text):
    """Return the list of Finding objects emitted by `rule_name` on `text`."""
    wf = Workflow("t.yml", text)
    for r in RULES:
        if r.name == rule_name:
            return r.check(wf)
    return []


# --- workflow-run-pwn-checkout --------------------------------------------


class WorkflowRunPwnCheckoutTests(unittest.TestCase):
    def test_workflow_run_with_head_sha_checkout_fires(self):
        """workflow_run trigger + checkout ref=head_sha fires CRITICAL."""
        wf = """
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
jobs:
  privileged:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.workflow_run.head_sha }}
      - run: ./deploy.sh
"""
        ids = fired(wf)
        self.assertIn("workflow-run-pwn-checkout", ids)

    def test_workflow_run_with_head_branch_checkout_fires(self):
        """workflow_run + checkout ref=head_branch also fires."""
        wf = """
on:
  workflow_run:
    workflows: [Build]
    types: [completed]
jobs:
  pwn:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.workflow_run.head_branch }}
"""
        self.assertIn("workflow-run-pwn-checkout", fired(wf))

    def test_workflow_run_without_dangerous_ref_does_not_fire(self):
        """workflow_run + checkout of the base (no ref:) does not fire."""
        wf = """
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
jobs:
  safe:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
"""
        self.assertNotIn("workflow-run-pwn-checkout", fired(wf))

    def test_dangerous_ref_without_workflow_run_does_not_fire(self):
        """workflow_dispatch + same ref does not fire (no trust boundary)."""
        wf = """
on: workflow_dispatch
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.workflow_run.head_sha }}
"""
        # workflow_run trigger is absent → no CRITICAL fire.
        self.assertNotIn("workflow-run-pwn-checkout", fired(wf))


# --- matrix-strategy-injection --------------------------------------------


class MatrixStrategyInjectionTests(unittest.TestCase):
    def test_matrix_from_pr_title_and_run_consumes_it_fires(self):
        """Matrix populated from PR title + run consumes ${{ matrix.* }} fires."""
        wf = """
on: pull_request_target
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        target:
          - ${{ github.event.pull_request.title }}
    steps:
      - run: echo "Building ${{ matrix.target }}"
"""
        self.assertIn("matrix-strategy-injection", fired(wf))

    def test_matrix_with_include_pr_body_fires(self):
        """Tainted axis under include[] is caught by the recursive walker."""
        wf = """
on: pull_request_target
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        include:
          - name: stable
            value: ${{ github.event.pull_request.body }}
    steps:
      - run: ./build.sh ${{ matrix.value }}
"""
        self.assertIn("matrix-strategy-injection", fired(wf))

    def test_matrix_clean_axis_but_run_uses_matrix_does_not_fire(self):
        """Hard-coded matrix consumed by run: is fine — no tainted source."""
        wf = """
on: pull_request
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node: [18, 20, 22]
    steps:
      - run: node --version ${{ matrix.node }}
"""
        self.assertNotIn("matrix-strategy-injection", fired(wf))

    def test_tainted_matrix_without_run_consumer_does_not_fire(self):
        """Tainted axis consumed only via with: (no run: sink) does not fire."""
        wf = """
on: pull_request_target
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        ref:
          - ${{ github.head_ref }}
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ matrix.ref }}
"""
        # No run: block with ${{ matrix.* }} → no shell sink → no fire.
        # (The dangerous checkout itself would be a separate rule.)
        self.assertNotIn("matrix-strategy-injection", fired(wf))


# --- github-app-skip-token-revoke -----------------------------------------


class GithubAppSkipTokenRevokeTests(unittest.TestCase):
    def test_skip_token_revoke_true_fires(self):
        """create-github-app-token with skip-token-revoke: true fires."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/create-github-app-token@v1
        with:
          app-id: ${{ vars.APP_ID }}
          private-key: ${{ secrets.APP_KEY }}
          skip-token-revoke: true
"""
        self.assertIn("github-app-skip-token-revoke", fired(wf))

    def test_skip_token_revoke_string_true_fires(self):
        """skip-token-revoke: \"true\" (string) also fires."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/create-github-app-token@v1
        with:
          app-id: ${{ vars.APP_ID }}
          private-key: ${{ secrets.APP_KEY }}
          skip-token-revoke: "true"
"""
        self.assertIn("github-app-skip-token-revoke", fired(wf))

    def test_tibdex_revoke_token_false_fires(self):
        """tibdex/github-app-token with revoke-token: false fires."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: tibdex/github-app-token@v2
        with:
          app_id: ${{ vars.APP_ID }}
          private_key: ${{ secrets.APP_KEY }}
          revoke-token: false
"""
        self.assertIn("github-app-skip-token-revoke", fired(wf))

    def test_default_revocation_does_not_fire(self):
        """create-github-app-token with no skip-token-revoke is safe."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/create-github-app-token@v1
        with:
          app-id: ${{ vars.APP_ID }}
          private-key: ${{ secrets.APP_KEY }}
"""
        self.assertNotIn("github-app-skip-token-revoke", fired(wf))

    def test_skip_token_revoke_false_does_not_fire(self):
        """Explicit skip-token-revoke: false is correct, does not fire."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/create-github-app-token@v1
        with:
          app-id: ${{ vars.APP_ID }}
          private-key: ${{ secrets.APP_KEY }}
          skip-token-revoke: false
"""
        self.assertNotIn("github-app-skip-token-revoke", fired(wf))


# --- actions-allow-unsecure-commands --------------------------------------


class ActionsAllowUnsecureCommandsTests(unittest.TestCase):
    def test_workflow_level_truthy_fires(self):
        """workflow.env.ACTIONS_ALLOW_UNSECURE_COMMANDS=true fires CRITICAL."""
        wf = """
on: push
env:
  ACTIONS_ALLOW_UNSECURE_COMMANDS: true
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo "::set-env name=FOO::bar"
"""
        self.assertIn("actions-allow-unsecure-commands", fired(wf))

    def test_job_level_string_one_fires(self):
        """job.env.ACTIONS_ALLOW_UNSECURE_COMMANDS=\"1\" fires."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    env:
      ACTIONS_ALLOW_UNSECURE_COMMANDS: "1"
    steps:
      - run: echo "hello"
"""
        self.assertIn("actions-allow-unsecure-commands", fired(wf))

    def test_step_level_string_true_fires(self):
        """step.env.ACTIONS_ALLOW_UNSECURE_COMMANDS=\"true\" fires."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: legacy
        env:
          ACTIONS_ALLOW_UNSECURE_COMMANDS: "true"
        run: echo "hi"
"""
        self.assertIn("actions-allow-unsecure-commands", fired(wf))

    def test_falsy_value_does_not_fire(self):
        """ACTIONS_ALLOW_UNSECURE_COMMANDS=false is safe — does not fire."""
        wf = """
on: push
env:
  ACTIONS_ALLOW_UNSECURE_COMMANDS: false
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo "ok"
"""
        self.assertNotIn("actions-allow-unsecure-commands", fired(wf))

    def test_absent_var_does_not_fire(self):
        """No env block at all — does not fire."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo "clean"
"""
        self.assertNotIn("actions-allow-unsecure-commands", fired(wf))


# --- id-token-write-unscoped ----------------------------------------------


class IdTokenWriteUnscopedTests(unittest.TestCase):
    def test_workflow_level_id_token_no_environment_fires(self):
        """workflow.permissions.id-token=write + job without environment fires."""
        wf = """
on: push
permissions:
  id-token: write
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::1234:role/ci
"""
        self.assertIn("id-token-write-unscoped", fired(wf))

    def test_job_level_id_token_no_environment_fires(self):
        """job.permissions.id-token=write without job.environment fires."""
        wf = """
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::1234:role/ci
"""
        self.assertIn("id-token-write-unscoped", fired(wf))

    def test_write_all_no_environment_fires(self):
        """workflow.permissions: write-all (string) without environment fires."""
        wf = """
on: push
permissions: write-all
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: echo "doom"
"""
        self.assertIn("id-token-write-unscoped", fired(wf))

    def test_id_token_with_environment_does_not_fire(self):
        """id-token: write WITH environment: production is the mitigation."""
        wf = """
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::1234:role/ci
"""
        self.assertNotIn("id-token-write-unscoped", fired(wf))

    def test_id_token_with_environment_mapping_does_not_fire(self):
        """environment: as a mapping with name: is also a valid gate."""
        wf = """
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: production
      url: https://prod.example.com
    permissions:
      id-token: write
    steps:
      - run: ./deploy.sh
"""
        self.assertNotIn("id-token-write-unscoped", fired(wf))

    def test_attestation_job_id_token_does_not_fire(self):
        """#30: id-token: write for actions/attest-build-provenance mints a
        sigstore SIGNING token, not cloud creds — the environment: gate is
        inapplicable, so a job-scoped attestation grant must NOT fire."""
        wf = """
on: push
jobs:
  build-memgrep:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      id-token: write
      attestations: write
    steps:
      - run: cargo build --release
      - uses: actions/attest-build-provenance@v1
        with:
          subject-path: target/release/memgrep
"""
        self.assertNotIn("id-token-write-unscoped", fired(wf))

    def test_attestation_plus_cloud_auth_still_fires(self):
        """A job that does attestation AND cloud auth without an environment gate
        is still a real unscoped-OIDC risk — suppression must not hide it."""
        wf = """
on: push
jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: write
    steps:
      - uses: actions/attest-build-provenance@v1
        with:
          subject-path: dist/app
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::1234:role/ci
"""
        self.assertIn("id-token-write-unscoped", fired(wf))

    def test_no_id_token_perm_does_not_fire(self):
        """contents: read only — no OIDC trust, no fire."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - run: echo "ok"
"""
        self.assertNotIn("id-token-write-unscoped", fired(wf))

    def test_npm_trusted_publishing_job_does_not_fire(self):
        """#99: `npm publish` mints its OWN registry OIDC token (npm CLI
        trusted publishing) — no cloud IAM trust policy exists for an
        environment: gate to narrow, so a job-scoped grant beside a bare
        `npm publish` step must NOT fire (the exact `publish-npm` shape
        reported: workflow-level contents: read, job-level id-token: write,
        no environment)."""
        wf = """
on: push
permissions:
  contents: read
jobs:
  publish-npm:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/setup-node@v4
      - run: npm publish
"""
        self.assertNotIn("id-token-write-unscoped", fired(wf))

    def test_npm_publish_plus_cloud_auth_still_fires(self):
        """A job that runs `npm publish` AND also authenticates to a cloud
        provider without an environment gate is still a real unscoped-OIDC
        risk for the cloud credential — the npm-publish exemption must not
        hide it."""
        wf = """
on: push
jobs:
  publish-and-deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - run: npm publish
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::1234:role/ci
"""
        self.assertIn("id-token-write-unscoped", fired(wf))


# --- module-level coverage assertions -------------------------------------


class ModuleSurfaceTests(unittest.TestCase):
    def test_rules_export_is_non_empty(self):
        """rules_extra.RULES must export at least one Rule instance."""
        self.assertTrue(len(RULES) >= 5)

    def test_every_rule_has_name_severity_description(self):
        """Every Rule subclass must set the canonical metadata trio."""
        for r in RULES:
            self.assertTrue(r.name, f"empty name on {type(r).__name__}")
            self.assertIn(r.severity, ("CRITICAL", "HIGH", "MAJOR", "MINOR"))
            self.assertTrue(r.description)

    def test_rule_ids_are_unique(self):
        """No two rules share a name (would collide in dispatch)."""
        names = [r.name for r in RULES]
        self.assertEqual(len(names), len(set(names)))

    def test_findings_have_canonical_shape(self):
        """A fired finding has rule_id, line >= 1, col, matched_text, severity."""
        wf = """
on: push
env:
  ACTIONS_ALLOW_UNSECURE_COMMANDS: true
jobs:
  x:
    runs-on: ubuntu-latest
    steps:
      - run: echo "hi"
"""
        results = findings_for("actions-allow-unsecure-commands", wf)
        self.assertEqual(len(results), 1)
        f = results[0]
        self.assertEqual(f.rule_id, "actions-allow-unsecure-commands")
        self.assertGreaterEqual(f.line, 1)
        self.assertGreaterEqual(f.col, 1)
        self.assertEqual(f.severity, "CRITICAL")
        self.assertIn("ACTIONS_ALLOW_UNSECURE_COMMANDS", f.matched_text)


if __name__ == "__main__":
    unittest.main()
