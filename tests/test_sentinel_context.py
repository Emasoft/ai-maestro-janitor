import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.sentinel.model import Workflow  # noqa: E402
from lib.sentinel.rules_context import RULES  # noqa: E402


def fired(text):
    wf = Workflow("t.yml", text)
    ids = set()
    for r in RULES:
        for f in r.check(wf):
            ids.add(f.rule_id)
    return ids


class StaticAwsCredentialsTests(unittest.TestCase):
    def test_static_keys_fire(self):
        """configure-aws-credentials with static keys and no OIDC role fires."""
        wf = """
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
"""
        self.assertIn("static-aws-credentials", fired(wf))

    def test_oidc_role_does_not_fire(self):
        """configure-aws-credentials via OIDC role-to-assume does not fire."""
        wf = """
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::1234:role/ci
          aws-region: us-east-1
"""
        self.assertNotIn("static-aws-credentials", fired(wf))


class UnscopedAppTokenTests(unittest.TestCase):
    def test_unscoped_token_fires(self):
        """create-github-app-token without permission-* inputs fires."""
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
        self.assertIn("unscoped-app-token", fired(wf))

    def test_scoped_token_does_not_fire(self):
        """create-github-app-token with a permission-* input does not fire."""
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
          permission-contents: write
"""
        self.assertNotIn("unscoped-app-token", fired(wf))


class DockerBuildArgSecretsTests(unittest.TestCase):
    def test_secret_build_arg_fires(self):
        """A secrets.* reference inside a build-args block fires."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: docker/build-push-action@v5
        with:
          build-args: |
            NPM_TOKEN=${{ secrets.NPM_TOKEN }}
            FOO=bar
"""
        self.assertIn("docker-build-arg-secrets", fired(wf))

    def test_plain_build_arg_does_not_fire(self):
        """A build-args block with no secrets reference does not fire."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: docker/build-push-action@v5
        with:
          build-args: |
            NODE_ENV=production
            FOO=bar
"""
        self.assertNotIn("docker-build-arg-secrets", fired(wf))


class UnpinnedArtifactTests(unittest.TestCase):
    def test_download_without_name_fires(self):
        """download-artifact without a name input fires."""
        wf = """
on: push
jobs:
  use:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
"""
        self.assertIn("unpinned-artifact", fired(wf))

    def test_download_with_name_does_not_fire(self):
        """download-artifact with a non-empty name input does not fire."""
        wf = """
on: push
jobs:
  use:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: build-output
"""
        self.assertNotIn("unpinned-artifact", fired(wf))


class SelfHostedRunnerForkTests(unittest.TestCase):
    def test_self_hosted_on_pr_fires(self):
        """Self-hosted runner under a pull_request trigger fires."""
        wf = """
on: pull_request
jobs:
  build:
    runs-on: self-hosted
    steps:
      - run: make
"""
        self.assertIn("self-hosted-runner-fork", fired(wf))

    def test_label_gated_does_not_fire(self):
        """Self-hosted runner gated to label-only PR types does not fire."""
        wf = """
on:
  pull_request:
    types: [labeled]
jobs:
  build:
    runs-on: self-hosted
    steps:
      - run: make
"""
        self.assertNotIn("self-hosted-runner-fork", fired(wf))


class BuildPublishSameJobTests(unittest.TestCase):
    def test_install_and_publish_same_job_fires(self):
        """Install + publish in one job with a publish secret in env fires."""
        wf = """
on: push
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - run: npm ci
      - run: npm publish
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
"""
        self.assertIn("build-publish-same-job", fired(wf))

    def test_split_jobs_does_not_fire(self):
        """Install and publish split across separate jobs does not fire."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: npm ci
  publish:
    runs-on: ubuntu-latest
    needs: build
    steps:
      - run: npm publish
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
"""
        self.assertNotIn("build-publish-same-job", fired(wf))


class AllowForksArtifactTests(unittest.TestCase):
    def test_allow_forks_true_fires(self):
        """An allow_forks: true input fires."""
        wf = """
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
jobs:
  use:
    runs-on: ubuntu-latest
    steps:
      - uses: dawidd6/action-download-artifact@v6
        with:
          allow_forks: true
"""
        self.assertIn("allow-forks-artifact", fired(wf))

    def test_allow_forks_false_does_not_fire(self):
        """An allow_forks: false input does not fire."""
        wf = """
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
jobs:
  use:
    runs-on: ubuntu-latest
    steps:
      - uses: dawidd6/action-download-artifact@v6
        with:
          allow_forks: false
"""
        self.assertNotIn("allow-forks-artifact", fired(wf))


class DangerousLifecycleScriptsTests(unittest.TestCase):
    def test_npm_install_with_secrets_fires(self):
        """npm install without --ignore-scripts in a secrets workflow fires."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: npm install
      - run: npm publish
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
"""
        self.assertIn("dangerous-lifecycle-scripts", fired(wf))

    def test_ignore_scripts_does_not_fire(self):
        """npm install with --ignore-scripts in a secrets workflow does not fire."""
        wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: npm install --ignore-scripts
      - run: echo ${{ secrets.NPM_TOKEN }}
"""
        self.assertNotIn("dangerous-lifecycle-scripts", fired(wf))


class TestIfAlwaysTrue(unittest.TestCase):
    def test_positive_always(self):
        """`if: ${{ always() }}` always evaluates true → fires."""
        wf = """\
on: [push]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - if: ${{ always() }}
        run: ./publish.sh
"""
        self.assertIn("if-always-true", fired(wf))

    def test_positive_success_or_failure(self):
        """`success() || failure()` is a disguised always(). Fires."""
        wf = """\
on: [push]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - if: success() || failure()
        run: ./publish.sh
"""
        self.assertIn("if-always-true", fired(wf))

    def test_positive_bare_true(self):
        wf = """\
on: [push]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - if: true
        run: ./publish.sh
"""
        self.assertIn("if-always-true", fired(wf))

    def test_negative_meaningful_condition(self):
        wf = """\
on: [push]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - if: github.ref == 'refs/heads/main'
        run: ./publish.sh
"""
        self.assertNotIn("if-always-true", fired(wf))


class TestAiConfigInjection(unittest.TestCase):
    def test_positive_pr_title_to_cursor_config(self):
        """Dangerous expression written into a .cursorrules file fires."""
        wf = """\
on: pull_request
jobs:
  ai:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "${{ github.event.pull_request.title }}" > .cursorrules
"""
        self.assertIn("ai-config-injection", fired(wf))

    def test_positive_pr_body_to_claude_md(self):
        wf = """\
on: pull_request
jobs:
  ai:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "${{ github.event.pull_request.body }}" >> CLAUDE.md
"""
        self.assertIn("ai-config-injection", fired(wf))

    def test_negative_safe_trigger_only(self):
        """A push-only workflow has no attacker-controlled context to inject."""
        wf = """\
on: [push]
jobs:
  ai:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "${{ github.event.pull_request.title }}" > .cursorrules
"""
        self.assertNotIn("ai-config-injection", fired(wf))

    def test_negative_ai_mention_with_safe_context(self):
        """An AI tool mention with a SAFE context (pull_request.number) does
        not fire."""
        wf = """\
on: pull_request
jobs:
  ai:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "PR ${{ github.event.pull_request.number }}" > .cursorrules
"""
        self.assertNotIn("ai-config-injection", fired(wf))


class TestCachePoisoningPrTrigger(unittest.TestCase):
    def test_positive_pull_request_target_with_cache(self):
        wf = """\
on: pull_request_target
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/cache@v4
        with:
          path: ~/.cache
          key: deps-${{ hashFiles('**/lock') }}
"""
        self.assertIn("cache-poisoning-pr-trigger", fired(wf))

    def test_positive_workflow_run_with_cache(self):
        wf = """\
on:
  workflow_run:
    workflows: [CI]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/cache@v4
        with:
          path: ~/.cache
          key: x
"""
        self.assertIn("cache-poisoning-pr-trigger", fired(wf))

    def test_negative_pull_request_with_cache(self):
        """Plain pull_request trigger is safe — fork PRs don't have access
        to the base repo's cache writes anyway."""
        wf = """\
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/cache@v4
        with:
          path: ~/.cache
          key: x
"""
        self.assertNotIn("cache-poisoning-pr-trigger", fired(wf))

    def test_negative_pull_request_target_no_cache(self):
        """A pull_request_target workflow without actions/cache is fine."""
        wf = """\
on: pull_request_target
jobs:
  approve:
    runs-on: ubuntu-latest
    steps:
      - run: echo ok
"""
        self.assertNotIn("cache-poisoning-pr-trigger", fired(wf))


class TestArtipackedUpload(unittest.TestCase):
    def test_positive_pull_request_target_with_upload(self):
        wf = """\
on: pull_request_target
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@v4
        with:
          path: ./build/
"""
        self.assertIn("artipacked-upload", fired(wf))

    def test_positive_workflow_run_with_upload(self):
        wf = """\
on:
  workflow_run:
    workflows: [CI]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@v4
        with:
          path: ./build/
"""
        self.assertIn("artipacked-upload", fired(wf))

    def test_negative_pull_request_with_upload(self):
        """Plain pull_request workflow uploading is fine — fork PRs don't
        have artifact-write access to base repo."""
        wf = """\
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@v4
        with:
          path: ./build/
"""
        self.assertNotIn("artipacked-upload", fired(wf))


if __name__ == "__main__":
    unittest.main()
