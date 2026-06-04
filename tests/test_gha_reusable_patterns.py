"""Tests for scripts/lib/gha_reusable_patterns.py.

Wave 19 angle F implementation — 14 structural rules covering reusable
workflows, composite actions, workflow_dispatch / workflow_run chains,
step- and job-output taint, and node-action exec-arg-zero patterns.

Every rule has at least one positive case (fires) and one negative
case (does not fire). Total: ~30+ tests.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.gha_reusable_patterns import (  # noqa: E402
    RULE_CATALOG,
    CompositeAction,
    check_actions_toolkit_exec_arg_zero,
    scan_composite_action,
    scan_workflow,
)
from lib.sentinel.model import Workflow  # noqa: E402


def _wf(text: str) -> Workflow:
    return Workflow("t.yml", text)


def _fired_workflow(text: str, repo_owner: str | None = None) -> set[str]:
    return {f.rule_id for f in scan_workflow(_wf(text), repo_owner=repo_owner)}


def _fired_action(text: str) -> set[str]:
    return {f.rule_id for f in scan_composite_action(
        CompositeAction.parse("action.yml", text)
    )}


# =========================================================================
# Rule 1: reusable-workflow-mutable-ref
# =========================================================================

class ReusableWorkflowMutableRefTests(unittest.TestCase):
    def test_branch_pinned_reusable_fires(self):
        """Reusable workflow pinned to `main` fires CRITICAL."""
        wf = """
on: push
jobs:
  call:
    uses: org/devops/.github/workflows/release.yml@main
"""
        self.assertIn("reusable-workflow-mutable-ref", _fired_workflow(wf))

    def test_version_tag_pinned_reusable_fires(self):
        """Reusable workflow pinned to `v1.2` fires CRITICAL."""
        wf = """
on: push
jobs:
  call:
    uses: org/devops/.github/workflows/release.yml@v1.2
"""
        self.assertIn("reusable-workflow-mutable-ref", _fired_workflow(wf))

    def test_sha_pinned_reusable_does_not_fire(self):
        """SHA-pinned reusable workflow with trailing `# v1.2` comment is safe."""
        wf = """
on: push
jobs:
  call:
    uses: org/devops/.github/workflows/release.yml@a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e
"""
        self.assertNotIn("reusable-workflow-mutable-ref", _fired_workflow(wf))

    def test_third_party_action_does_not_fire_under_this_rule(self):
        """Third-party action (no .github/workflows/ in path) — not this rule's job."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
"""
        # Existing unpinned-uses-tag rule covers this; THIS rule must NOT fire.
        self.assertNotIn("reusable-workflow-mutable-ref", _fired_workflow(wf))

    def test_head_literal_fires(self):
        """`uses: org/repo/.github/workflows/x.yml@HEAD` fires."""
        wf = """
on: push
jobs:
  call:
    uses: org/devops/.github/workflows/release.yml@HEAD
"""
        self.assertIn("reusable-workflow-mutable-ref", _fired_workflow(wf))


# =========================================================================
# Rule 2: reusable-workflow-secrets-inherit-broad-scope
# =========================================================================

class SecretsInheritBroadScopeTests(unittest.TestCase):
    def test_cross_org_secrets_inherit_fires(self):
        """Cross-org `secrets: inherit` fires HIGH."""
        wf = """
on: push
jobs:
  release:
    uses: thirdparty/lib/.github/workflows/release.yml@a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e
    secrets: inherit
"""
        ids = _fired_workflow(wf, repo_owner="acme")
        self.assertIn("reusable-workflow-secrets-inherit-broad-scope", ids)

    def test_same_org_secrets_inherit_does_not_fire(self):
        """Same-org `secrets: inherit` does NOT fire (defer to MINOR mirror)."""
        wf = """
on: push
jobs:
  release:
    uses: acme/devops/.github/workflows/release.yml@a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e
    secrets: inherit
"""
        ids = _fired_workflow(wf, repo_owner="acme")
        self.assertNotIn(
            "reusable-workflow-secrets-inherit-broad-scope", ids,
        )

    def test_no_repo_owner_does_not_fire(self):
        """Without repo_owner, this rule defers to the MINOR mirror."""
        wf = """
on: push
jobs:
  release:
    uses: thirdparty/lib/.github/workflows/release.yml@a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e
    secrets: inherit
"""
        ids = _fired_workflow(wf, repo_owner=None)
        self.assertNotIn(
            "reusable-workflow-secrets-inherit-broad-scope", ids,
        )


# =========================================================================
# Rule 3: composite-action-input-shell-reflection
# =========================================================================

class CompositeActionInputShellReflectionTests(unittest.TestCase):
    def test_direct_input_in_run_fires(self):
        """`${{ inputs.X }}` in run: with no env-indirection fires CRITICAL."""
        action = """
name: Risky
runs:
  using: composite
  steps:
    - run: echo "Processing ${{ inputs.commit-message }}"
      shell: bash
"""
        self.assertIn(
            "composite-action-input-shell-reflection", _fired_action(action)
        )

    def test_env_indirected_does_not_fire(self):
        """env: indirection is the safe pattern."""
        action = """
name: Safe
runs:
  using: composite
  steps:
    - run: echo "Processing $COMMIT_MSG"
      env:
        COMMIT_MSG: ${{ inputs.commit-message }}
      shell: bash
"""
        self.assertNotIn(
            "composite-action-input-shell-reflection", _fired_action(action)
        )

    def test_non_composite_action_skipped(self):
        """A JavaScript action (runs.using: node20) is not in scope of this rule."""
        action = """
name: JS
runs:
  using: node20
  main: dist/index.js
"""
        self.assertNotIn(
            "composite-action-input-shell-reflection", _fired_action(action)
        )


# =========================================================================
# Rule 4: composite-action-local-path-from-pr
# =========================================================================

class CompositeActionLocalPathFromPRTests(unittest.TestCase):
    def test_pull_request_target_plus_local_path_fires(self):
        """pull_request_target + uses: ./local-action fires CRITICAL."""
        wf = """
on: pull_request_target
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e
      - uses: ./.github/actions/validate
"""
        self.assertIn(
            "composite-action-local-path-from-pr", _fired_workflow(wf)
        )

    def test_workflow_run_plus_local_path_fires(self):
        """workflow_run + uses: ./local-action also fires."""
        wf = """
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: ./.github/actions/deploy
"""
        self.assertIn(
            "composite-action-local-path-from-pr", _fired_workflow(wf)
        )

    def test_pull_request_plus_local_path_does_not_fire(self):
        """`pull_request` (not `_target`) + local path is fine — no privileged context."""
        wf = """
on: pull_request
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: ./.github/actions/validate
"""
        self.assertNotIn(
            "composite-action-local-path-from-pr", _fired_workflow(wf)
        )


# =========================================================================
# Rule 5: workflow-dispatch-input-in-git-push
# =========================================================================

class WorkflowDispatchInputInGitPushTests(unittest.TestCase):
    def test_input_in_git_push_fires(self):
        """`${{ inputs.X }}` interpolated into `git push` fires HIGH."""
        wf = """
on:
  workflow_dispatch:
    inputs:
      target_branch:
        type: string
jobs:
  push:
    runs-on: ubuntu-latest
    steps:
      - run: git push origin ${{ inputs.target_branch }}
"""
        self.assertIn(
            "workflow-dispatch-input-in-git-push", _fired_workflow(wf)
        )

    def test_input_in_gh_release_create_fires(self):
        """`${{ inputs.X }}` in `gh release create` also fires."""
        wf = """
on:
  workflow_dispatch:
    inputs:
      tag:
        type: string
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - run: gh release create ${{ inputs.tag }}
"""
        self.assertIn(
            "workflow-dispatch-input-in-git-push", _fired_workflow(wf)
        )

    def test_input_in_safe_command_does_not_fire(self):
        """`git config` is NOT destructive — does not fire."""
        wf = """
on:
  workflow_dispatch:
    inputs:
      username:
        type: string
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: git config user.name "${{ inputs.username }}"
"""
        self.assertNotIn(
            "workflow-dispatch-input-in-git-push", _fired_workflow(wf)
        )

    def test_env_routed_destructive_fires_major(self):
        """env-routed git push with input still flags MAJOR."""
        wf = """
on:
  workflow_dispatch:
    inputs:
      target:
        type: string
jobs:
  push:
    runs-on: ubuntu-latest
    steps:
      - env:
          TGT: ${{ inputs.target }}
        run: git push origin "$TGT"
"""
        findings = scan_workflow(_wf(wf))
        rule_findings = [
            f for f in findings
            if f.rule_id == "workflow-dispatch-input-in-git-push"
        ]
        self.assertTrue(rule_findings, "expected the env-routed case to fire")
        self.assertEqual(rule_findings[0].severity, "MAJOR")


# =========================================================================
# Rule 6: workflow-run-artifact-name-trust
# =========================================================================

class WorkflowRunArtifactNameTrustTests(unittest.TestCase):
    def test_run_id_workflow_run_no_actor_gate_fires(self):
        """run-id from workflow_run + no actor gate fires HIGH."""
        wf = """
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e
        with:
          name: build-output
          run-id: ${{ github.event.workflow_run.id }}
"""
        self.assertIn(
            "workflow-run-artifact-name-trust", _fired_workflow(wf)
        )

    def test_actor_allowlist_does_not_fire(self):
        """Actor allowlist gate is the mitigation — does NOT fire."""
        wf = """
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
jobs:
  publish:
    if: github.event.workflow_run.actor.login == 'release-bot'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e
        with:
          name: build-output
          run-id: ${{ github.event.workflow_run.id }}
"""
        self.assertNotIn(
            "workflow-run-artifact-name-trust", _fired_workflow(wf)
        )

    def test_no_workflow_run_trigger_does_not_fire(self):
        """`pull_request` + download-artifact does not fire."""
        wf = """
on: pull_request
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e
        with:
          name: build-output
"""
        self.assertNotIn(
            "workflow-run-artifact-name-trust", _fired_workflow(wf)
        )


# =========================================================================
# Rule 7: step-output-injection-via-github-output
# =========================================================================

class StepOutputInjectionTests(unittest.TestCase):
    def test_tainted_output_consumed_in_run_fires(self):
        """Tainted $GITHUB_OUTPUT + downstream interpolation fires HIGH."""
        wf = """
on: pull_request_target
jobs:
  process:
    runs-on: ubuntu-latest
    steps:
      - id: parse
        run: |
          echo "title=${{ github.event.pull_request.title }}" >> $GITHUB_OUTPUT
      - run: echo "Got title ${{ steps.parse.outputs.title }}"
"""
        self.assertIn(
            "step-output-injection-via-github-output", _fired_workflow(wf)
        )

    def test_sanitised_intermediate_does_not_fire(self):
        """env-routed sanitisation before $GITHUB_OUTPUT write is safe."""
        wf = """
on: pull_request_target
jobs:
  process:
    runs-on: ubuntu-latest
    steps:
      - id: parse
        env:
          RAW: ${{ github.event.pull_request.title }}
        run: |
          CLEAN=$(echo "$RAW" | tr -cd 'a-zA-Z0-9 _-')
          echo "title=$CLEAN" >> $GITHUB_OUTPUT
      - run: echo "Got title ${{ steps.parse.outputs.title }}"
"""
        # The first step writes to $GITHUB_OUTPUT but the value on the
        # same line is $CLEAN, not the untrusted ${{ ... }} — so NO fire.
        self.assertNotIn(
            "step-output-injection-via-github-output", _fired_workflow(wf)
        )

    def test_tainted_output_not_consumed_does_not_fire(self):
        """Tainted write but no downstream interpolation — does not fire."""
        wf = """
on: pull_request_target
jobs:
  process:
    runs-on: ubuntu-latest
    steps:
      - id: parse
        run: |
          echo "title=${{ github.event.pull_request.title }}" >> $GITHUB_OUTPUT
"""
        self.assertNotIn(
            "step-output-injection-via-github-output", _fired_workflow(wf)
        )


# =========================================================================
# Rule 8: job-output-cross-job-taint
# =========================================================================

class JobOutputCrossJobTaintTests(unittest.TestCase):
    def test_cross_job_taint_fires(self):
        """Job A tainted output → Job B consumes via needs.* fires HIGH."""
        wf = """
on: pull_request_target
jobs:
  parse:
    runs-on: ubuntu-latest
    outputs:
      msg: ${{ steps.s1.outputs.msg }}
    steps:
      - id: s1
        run: echo "msg=${{ github.event.issue.title }}" >> $GITHUB_OUTPUT
  deploy:
    needs: parse
    runs-on: ubuntu-latest
    steps:
      - run: ./deploy.sh "${{ needs.parse.outputs.msg }}"
"""
        self.assertIn("job-output-cross-job-taint", _fired_workflow(wf))

    def test_clean_cross_job_output_does_not_fire(self):
        """Clean job output (no taint) — does not fire."""
        wf = """
on: push
jobs:
  parse:
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.s1.outputs.version }}
    steps:
      - id: s1
        run: echo "version=1.2.3" >> $GITHUB_OUTPUT
  deploy:
    needs: parse
    runs-on: ubuntu-latest
    steps:
      - run: ./deploy.sh "${{ needs.parse.outputs.version }}"
"""
        self.assertNotIn("job-output-cross-job-taint", _fired_workflow(wf))

    def test_direct_untrusted_job_output_fires(self):
        """A job output that's literally `${{ github.event.issue.title }}` fires."""
        wf = """
on: pull_request_target
jobs:
  parse:
    runs-on: ubuntu-latest
    outputs:
      title: ${{ github.event.issue.title }}
    steps:
      - run: echo "hi"
  deploy:
    needs: parse
    runs-on: ubuntu-latest
    steps:
      - run: ./deploy.sh "${{ needs.parse.outputs.title }}"
"""
        self.assertIn("job-output-cross-job-taint", _fired_workflow(wf))


# =========================================================================
# Rule 9: workflow-dispatch-input-not-typed
# =========================================================================

class WorkflowDispatchInputNotTypedTests(unittest.TestCase):
    def test_untyped_input_used_in_run_fires(self):
        """Untyped input + used in run: fires MAJOR."""
        wf = """
on:
  workflow_dispatch:
    inputs:
      env_name:
        description: 'Target environment'
        required: true
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: ./deploy.sh ${{ inputs.env_name }}
"""
        self.assertIn(
            "workflow-dispatch-input-not-typed", _fired_workflow(wf)
        )

    def test_choice_typed_input_does_not_fire(self):
        """`type: choice` is the safe pattern."""
        wf = """
on:
  workflow_dispatch:
    inputs:
      env_name:
        type: choice
        options: [staging, prod]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: ./deploy.sh ${{ inputs.env_name }}
"""
        self.assertNotIn(
            "workflow-dispatch-input-not-typed", _fired_workflow(wf)
        )

    def test_boolean_typed_input_does_not_fire(self):
        """`type: boolean` is also safe."""
        wf = """
on:
  workflow_dispatch:
    inputs:
      dry_run:
        type: boolean
        default: true
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: echo "dry=${{ inputs.dry_run }}"
"""
        self.assertNotIn(
            "workflow-dispatch-input-not-typed", _fired_workflow(wf)
        )

    def test_unused_untyped_input_does_not_fire(self):
        """Untyped input but never referenced — does not fire."""
        wf = """
on:
  workflow_dispatch:
    inputs:
      env_name:
        description: 'unused'
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo "ok"
"""
        self.assertNotIn(
            "workflow-dispatch-input-not-typed", _fired_workflow(wf)
        )


# =========================================================================
# Rule 10: reusable-workflow-permissions-elevation
# =========================================================================

class ReusableWorkflowPermissionsElevationTests(unittest.TestCase):
    def test_write_all_on_workflow_call_fires_critical(self):
        """workflow_call body with `permissions: write-all` fires CRITICAL."""
        wf = """
on:
  workflow_call:
    inputs: {}
permissions: write-all
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - run: ./release.sh
"""
        findings = scan_workflow(_wf(wf))
        rule_findings = [
            f for f in findings
            if f.rule_id == "reusable-workflow-permissions-elevation"
        ]
        self.assertTrue(rule_findings)
        self.assertEqual(rule_findings[0].severity, "CRITICAL")

    def test_specific_write_scope_on_workflow_call_fires(self):
        """workflow_call body with specific write scope (no repo_owner) fires HIGH."""
        wf = """
on:
  workflow_call:
    inputs: {}
permissions:
  contents: write
  id-token: write
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - run: ./release.sh
"""
        findings = scan_workflow(_wf(wf))
        rule_findings = [
            f for f in findings
            if f.rule_id == "reusable-workflow-permissions-elevation"
        ]
        self.assertTrue(rule_findings)
        # No repo_owner → conservative HIGH.
        self.assertEqual(rule_findings[0].severity, "HIGH")

    def test_no_workflow_call_does_not_fire(self):
        """A workflow without `on.workflow_call` is not in scope."""
        wf = """
on: push
permissions: write-all
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo "ok"
"""
        self.assertNotIn(
            "reusable-workflow-permissions-elevation", _fired_workflow(wf)
        )

    def test_read_only_workflow_call_does_not_fire(self):
        """workflow_call with read-only permissions is safe."""
        wf = """
on:
  workflow_call:
    inputs: {}
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo "ok"
"""
        self.assertNotIn(
            "reusable-workflow-permissions-elevation", _fired_workflow(wf)
        )


# =========================================================================
# Rule 11: composite-action-uses-third-party-unsafe-chain
# =========================================================================

class CompositeActionUsesThirdPartyUnsafeChainTests(unittest.TestCase):
    def test_unpinned_third_party_in_composite_fires(self):
        """Composite action body using `third/party@v1` fires."""
        action = """
name: Wrapper
runs:
  using: composite
  steps:
    - uses: third/party-action@v1
      shell: bash
"""
        self.assertIn(
            "composite-action-uses-third-party-unsafe-chain",
            _fired_action(action),
        )

    def test_sha_pinned_third_party_in_composite_does_not_fire(self):
        """SHA-pinned third-party in composite is safe."""
        action = """
name: Wrapper
runs:
  using: composite
  steps:
    - uses: third/party-action@a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e
      shell: bash
"""
        self.assertNotIn(
            "composite-action-uses-third-party-unsafe-chain",
            _fired_action(action),
        )

    def test_local_path_in_composite_does_not_fire_here(self):
        """`uses: ./local` is a different rule — does not fire here."""
        action = """
name: Wrapper
runs:
  using: composite
  steps:
    - uses: ./sub-action
      shell: bash
"""
        self.assertNotIn(
            "composite-action-uses-third-party-unsafe-chain",
            _fired_action(action),
        )

    def test_security_sensitive_action_fires_high(self):
        """checkout / token / publish keywords elevate to HIGH."""
        action = """
name: Risky
runs:
  using: composite
  steps:
    - uses: third/checkout-action@v1
      shell: bash
"""
        findings = scan_composite_action(
            CompositeAction.parse("action.yml", action)
        )
        rule_findings = [
            f for f in findings
            if f.rule_id == "composite-action-uses-third-party-unsafe-chain"
        ]
        self.assertTrue(rule_findings)
        self.assertEqual(rule_findings[0].severity, "HIGH")


# =========================================================================
# Rule 12: artifact-name-attacker-controllable
# =========================================================================

class ArtifactNameAttackerControllableTests(unittest.TestCase):
    def test_pr_title_in_artifact_name_fires(self):
        """upload-artifact with name from PR title fires HIGH."""
        wf = """
on: pull_request_target
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e
        with:
          name: report-${{ github.event.pull_request.title }}
          path: ./out/
"""
        self.assertIn(
            "artifact-name-attacker-controllable", _fired_workflow(wf)
        )

    def test_sha_in_artifact_name_does_not_fire(self):
        """name: report-${{ github.sha }} is fine (sha is not in DANGEROUS_CONTEXTS)."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e
        with:
          name: report-${{ github.sha }}
          path: ./out/
"""
        self.assertNotIn(
            "artifact-name-attacker-controllable", _fired_workflow(wf)
        )

    def test_head_ref_in_artifact_name_fires(self):
        """github.head_ref IS in DANGEROUS_CONTEXTS — fires."""
        wf = """
on: pull_request_target
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e
        with:
          name: branch-${{ github.head_ref }}
          path: ./out/
"""
        self.assertIn(
            "artifact-name-attacker-controllable", _fired_workflow(wf)
        )


# =========================================================================
# Rule 13: environment-without-required-reviewers
# =========================================================================

class EnvironmentWithoutRequiredReviewersTests(unittest.TestCase):
    def test_production_environment_fires(self):
        """environment: production fires MAJOR."""
        wf = """
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    steps:
      - run: ./deploy.sh
"""
        self.assertIn(
            "environment-without-required-reviewers", _fired_workflow(wf)
        )

    def test_prod_environment_fires(self):
        """environment: prod also fires (alias)."""
        wf = """
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: prod
    steps:
      - run: ./deploy.sh
"""
        self.assertIn(
            "environment-without-required-reviewers", _fired_workflow(wf)
        )

    def test_staging_environment_does_not_fire(self):
        """environment: staging does NOT match prod patterns."""
        wf = """
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - run: ./deploy.sh
"""
        self.assertNotIn(
            "environment-without-required-reviewers", _fired_workflow(wf)
        )

    def test_no_environment_does_not_fire(self):
        """No `environment:` block — does not fire."""
        wf = """
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: ./deploy.sh
"""
        self.assertNotIn(
            "environment-without-required-reviewers", _fired_workflow(wf)
        )

    def test_mapping_form_environment_fires(self):
        """environment: { name: production, url: ... } — also fires on name."""
        wf = """
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: production
      url: https://prod.example.com
    steps:
      - run: ./deploy.sh
"""
        self.assertIn(
            "environment-without-required-reviewers", _fired_workflow(wf)
        )


# =========================================================================
# Rule 14: actions-toolkit-exec-arg-zero
# =========================================================================

class ActionsToolkitExecArgZeroTests(unittest.TestCase):
    def test_exec_get_input_fires(self):
        """exec(core.getInput('cmd')) fires MAJOR."""
        action = """
name: Risky JS
runs:
  using: node20
  main: dist/index.js
"""
        js = """
const core = require('@actions/core');
const exec = require('@actions/exec');
await exec.exec(core.getInput('cmd'));
"""
        findings = check_actions_toolkit_exec_arg_zero(
            CompositeAction.parse("action.yml", action), js, "index.js",
        )
        self.assertTrue(findings, "expected exec-arg-zero to fire")
        self.assertEqual(findings[0].rule_id, "actions-toolkit-exec-arg-zero")
        self.assertEqual(findings[0].severity, "MAJOR")

    def test_exec_with_args_array_does_not_fire(self):
        """exec('git', ['push', core.getInput('X')]) is safe."""
        action = """
name: Safe JS
runs:
  using: node20
  main: dist/index.js
"""
        js = """
const core = require('@actions/core');
const exec = require('@actions/exec');
await exec.exec('git', ['push', core.getInput('cmd')]);
"""
        findings = check_actions_toolkit_exec_arg_zero(
            CompositeAction.parse("action.yml", action), js, "index.js",
        )
        self.assertFalse(findings, "should not fire when args is an array")

    def test_non_javascript_action_does_not_fire(self):
        """Composite action with exec() in a separate file is out of scope."""
        action = """
name: Composite
runs:
  using: composite
  steps:
    - run: echo "ok"
      shell: bash
"""
        js = """
const exec = require('@actions/exec');
await exec.exec(core.getInput('cmd'));
"""
        findings = check_actions_toolkit_exec_arg_zero(
            CompositeAction.parse("action.yml", action), js, "main.js",
        )
        self.assertFalse(findings, "not a JS action — should not fire")

    def test_template_literal_interpolation_fires(self):
        """`exec(\\`${core.getInput('cmd')} args\\`)` fires."""
        action = """
name: Risky JS template
runs:
  using: node20
  main: dist/index.js
"""
        js = """
await exec(`${core.getInput('cmd')} --flag`);
"""
        findings = check_actions_toolkit_exec_arg_zero(
            CompositeAction.parse("action.yml", action), js, "index.js",
        )
        self.assertTrue(findings, "template-literal injection should fire")


# =========================================================================
# Module surface / catalog assertions
# =========================================================================

class ModuleSurfaceTests(unittest.TestCase):
    def test_rule_catalog_contains_all_14_rules(self):
        """RULE_CATALOG must list all 14 rule_ids the module ships."""
        expected = {
            "reusable-workflow-mutable-ref",
            "reusable-workflow-secrets-inherit-broad-scope",
            "composite-action-input-shell-reflection",
            "composite-action-local-path-from-pr",
            "workflow-dispatch-input-in-git-push",
            "workflow-run-artifact-name-trust",
            "step-output-injection-via-github-output",
            "job-output-cross-job-taint",
            "workflow-dispatch-input-not-typed",
            "reusable-workflow-permissions-elevation",
            "composite-action-uses-third-party-unsafe-chain",
            "artifact-name-attacker-controllable",
            "environment-without-required-reviewers",
            "actions-toolkit-exec-arg-zero",
        }
        self.assertEqual(set(RULE_CATALOG.keys()), expected)

    def test_every_rule_severity_is_canonical(self):
        """Each catalog entry uses CRITICAL/HIGH/MAJOR/MINOR severity."""
        for rule_id, (sev, _desc) in RULE_CATALOG.items():
            self.assertIn(
                sev, ("CRITICAL", "HIGH", "MAJOR", "MINOR"),
                f"{rule_id} has non-canonical severity {sev}",
            )

    def test_every_rule_has_non_empty_description(self):
        """Each catalog entry has a non-empty one-line description."""
        for rule_id, (_sev, desc) in RULE_CATALOG.items():
            self.assertTrue(desc, f"{rule_id} has empty description")
            self.assertLess(
                len(desc), 200,
                f"{rule_id} description should be one line, got: {desc}",
            )

    def test_finding_canonical_shape(self):
        """A fired finding has rule_id/line/col/matched_text/severity/description."""
        wf = """
on: push
jobs:
  call:
    uses: org/devops/.github/workflows/release.yml@main
"""
        findings = scan_workflow(_wf(wf))
        rule_findings = [
            f for f in findings if f.rule_id == "reusable-workflow-mutable-ref"
        ]
        self.assertEqual(len(rule_findings), 1)
        f = rule_findings[0]
        self.assertEqual(f.rule_id, "reusable-workflow-mutable-ref")
        self.assertGreaterEqual(f.line, 1)
        self.assertGreaterEqual(f.col, 1)
        self.assertEqual(f.severity, "CRITICAL")
        self.assertTrue(f.matched_text)
        self.assertTrue(f.description)

    def test_clean_workflow_emits_zero_findings(self):
        """A well-formed clean workflow fires zero rules in this module."""
        wf = """
on: push
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e
      - run: echo "ok"
"""
        self.assertEqual(scan_workflow(_wf(wf)), [])

    def test_clean_composite_action_emits_zero_findings(self):
        """A well-formed composite action emits zero findings."""
        action = """
name: Safe
runs:
  using: composite
  steps:
    - run: echo "$INPUT"
      env:
        INPUT: ${{ inputs.value }}
      shell: bash
"""
        self.assertEqual(
            scan_composite_action(
                CompositeAction.parse("action.yml", action)
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
