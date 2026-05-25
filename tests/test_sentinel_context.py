import sys, unittest  # noqa: E401
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from lib.sentinel.rules_context import RULES  # noqa: E402
from lib.sentinel.model import Workflow  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
