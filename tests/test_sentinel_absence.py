"""Unit tests for the Sentinel "absence / context" structural rule tier.

Each of the seven rules in lib.sentinel.rules_absence gets a POSITIVE test
(a workflow that SHOULD trip it) and a NEGATIVE test (a hardened workflow
that must NOT). A final test asserts a fully-hardened workflow fires ZERO
rules — the no-false-positive guarantee.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.sentinel.model import Workflow  # noqa: E402
from lib.sentinel.rules_absence import RULES, MissingPersistCredentials  # noqa: E402


def fired(text: str) -> set:
    """Run every absence rule over a workflow string; return fired rule_ids."""
    wf = Workflow("t.yml", text)
    ids = set()
    for rule in RULES:
        for finding in rule.check(wf):
            ids.add(finding.rule_id)
    return ids


# A workflow hardened against all seven rules — used by the negative tests
# and the no-false-positive guarantee. Push has a branch filter, the only job
# has a timeout, no write permission, checkout pins persist-credentials:false,
# no publish/OIDC, and no unpinned installs.
HARDENED = """\
name: CI
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - run: npm ci
"""


class TestMissingPermissions(unittest.TestCase):
    def test_positive_no_top_level_permissions(self):
        """Workflow with no top-level permissions block trips the rule."""
        wf = """\
on:
  push:
    branches: [main]
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - run: echo hi
"""
        self.assertIn("missing-permissions", fired(wf))

    def test_negative_has_top_level_permissions(self):
        """Workflow with a top-level permissions block does not trip the rule."""
        self.assertNotIn("missing-permissions", fired(HARDENED))


class TestMissingTimeouts(unittest.TestCase):
    def test_positive_job_without_timeout(self):
        """A job missing timeout-minutes trips the rule."""
        wf = """\
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""
        self.assertIn("missing-timeouts", fired(wf))

    def test_negative_job_with_timeout(self):
        """A job that sets timeout-minutes does not trip the rule."""
        self.assertNotIn("missing-timeouts", fired(HARDENED))


class TestExcessivePermissions(unittest.TestCase):
    def test_positive_write_without_write_steps(self):
        """contents: write with no write-performing steps trips the rule."""
        wf = """\
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: write
    steps:
      - run: echo just reading
"""
        self.assertIn("excessive-permissions", fired(wf))

    def test_negative_write_with_git_push(self):
        """contents: write justified by a git push step does not trip the rule."""
        wf = """\
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - run: git push origin HEAD
"""
        self.assertNotIn("excessive-permissions", fired(wf))


class TestMissingPersistCredentials(unittest.TestCase):
    def test_positive_checkout_without_flag(self):
        """A checkout WITHOUT persist-credentials:false in a job that PUSHES
        trips the rule — the persisted token has a real in-job abuse path."""
        wf = """\
on:
  push:
    branches: [main]
permissions:
  contents: write
jobs:
  release:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - run: git push origin HEAD:release
"""
        self.assertIn("missing-persist-credentials", fired(wf))

    def test_negative_checkout_with_flag(self):
        """A checkout step with persist-credentials: false does not trip the rule."""
        self.assertNotIn("missing-persist-credentials", fired(HARDENED))

    def test_negative_readonly_job_checkout(self):
        """A checkout in a READ-ONLY job (no push / PR-create path) does NOT
        fire. The persist-credentials threat is a token left in .git/config
        being abused by a later step to push/mutate the repo; a read-only job
        has no such path, so flagging its checkout HIGH was a false positive
        (FP-test round 2, surf-cli: 6 FPs on read-only CI checkouts)."""
        wf = """\
on:
  pull_request:
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm test
"""
        self.assertNotIn("missing-persist-credentials", fired(wf))

    def test_the_finding_cites_the_offending_job_not_an_innocent_one(self):
        """The reported LINE must be the pushing job's own checkout.

        janitor#157: the rule kept its own per-`uses` occurrence counter and
        advanced it only for AUDITED steps — i.e. inside the job_pushes gate — so
        the Nth audited checkout was reported at the Nth TEXTUAL checkout. With
        two hardened non-pushing build jobs ahead of the offender, a correct
        finding was cited against `build-linux`'s checkout, which sets
        persist-credentials three lines below. It was filed as a false positive;
        it was a true finding wearing the wrong line number.

        A true finding pointed at innocent code is worse than a false one: it
        costs the same investigation AND teaches the reader to distrust the HIGH
        banner, which is the one banner that has to stay trustworthy.
        """
        wf = """\
on: [push]
jobs:
  build-linux:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - run: cargo build
  build-macos:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - run: cargo build
  commit-binaries:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - run: git push origin HEAD
"""
        findings = MissingPersistCredentials().check(Workflow("t.yml", wf))
        self.assertEqual(len(findings), 1, "only the pushing job is at fault")
        # Line 20 is commit-binaries' own checkout; line 6 is build-linux's — the
        # line the pre-fix rule reported, and the one that looks innocent.
        self.assertEqual(
            findings[0].line,
            20,
            "must cite the pushing job's checkout, not the first one in the file",
        )


class TestMissingEnvProtection(unittest.TestCase):
    def test_positive_publish_without_environment(self):
        """A job that runs npm publish without an environment trips the rule."""
        wf = """\
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  release:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - run: npm publish
"""
        self.assertIn("missing-env-protection", fired(wf))

    def test_positive_oidc_without_environment(self):
        """A job granted id-token: write without an environment trips the rule."""
        wf = """\
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      id-token: write
    steps:
      - run: echo deploy
"""
        self.assertIn("missing-env-protection", fired(wf))

    def test_negative_publish_with_environment(self):
        """A publish job that declares an environment does not trip the rule."""
        wf = """\
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  release:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    environment: pypi
    steps:
      - run: uv publish
"""
        self.assertNotIn("missing-env-protection", fired(wf))

    def test_positive_write_all_oidc_without_environment(self):
        """Audit MEDIUM-2: `permissions: write-all` is a STRING that implicitly
        grants id-token: write. A dict-only check missed it; the OIDC branch
        must now fire for a write-all workflow with no environment: gate."""
        wf = """\
on:
  push:
    branches: [main]
permissions: write-all
jobs:
  deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - run: echo deploy
"""
        self.assertIn("missing-env-protection", fired(wf))

    def test_negative_write_all_oidc_with_environment(self):
        """write-all but the job is gated by an environment: → no finding
        (the environment is the mitigation)."""
        wf = """\
on:
  push:
    branches: [main]
permissions: write-all
jobs:
  deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    environment: production
    steps:
      - run: echo deploy
"""
        self.assertNotIn("missing-env-protection", fired(wf))

    def test_negative_attestation_only_oidc_does_not_need_an_environment(self):
        """janitor#164: a job that mints id-token: write ONLY to sign a Sigstore
        build-provenance attestation has no deployment trust policy for an
        environment: gate to narrow — the same false positive
        IdTokenWriteUnscoped had before janitor#99, on the SAME job shape
        (the janitor's own memgrep-release.yml `release` job)."""
        wf = """\
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  release:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: write
      id-token: write
      attestations: write
    steps:
      - uses: actions/attest-build-provenance@v1
        with:
          subject-path: 'out/memgrep-*'
      - run: gh release upload "$TAG" out/memgrep-*
"""
        self.assertNotIn("missing-env-protection", fired(wf))

    def test_positive_attestation_plus_cloud_auth_still_needs_an_environment(self):
        """A job that ALSO authenticates to a cloud provider is a real
        unscoped-OIDC deploy risk — the attestation exemption must not hide it."""
        wf = """\
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  release:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      id-token: write
      contents: write
    steps:
      - uses: actions/attest-build-provenance@v1
        with:
          subject-path: 'out/memgrep-*'
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::1234:role/ci
"""
        self.assertIn("missing-env-protection", fired(wf))

    def test_positive_npm_trusted_publishing_oidc_still_needs_an_environment(self):
        """Unlike attestation, registry-OIDC publishing (npm trusted publishing)
        IS a publish action — "should a human approve before this runs" is a
        genuine, separate concern from the OIDC-SCOPE question
        IdTokenWriteUnscoped answers (janitor#99). The attestation exemption
        above must not spill over into exempting an actual publish step; this
        also already trips on `has_publish` alone via `npm publish`, so this
        pins that neither path was weakened."""
        wf = """\
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  publish-npm:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      id-token: write
      contents: read
    steps:
      - run: npm publish
"""
        self.assertIn("missing-env-protection", fired(wf))


class TestOverlyBroadTriggers(unittest.TestCase):
    def test_positive_push_without_branch_filter(self):
        """A push trigger with no branch/tag/path filter trips the rule."""
        wf = """\
on:
  push:
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - run: npm ci
"""
        self.assertIn("overly-broad-triggers", fired(wf))

    def test_negative_push_with_branch_filter(self):
        """A push trigger scoped with branches: does not trip the rule."""
        self.assertNotIn("overly-broad-triggers", fired(HARDENED))


class TestMissingFrozenLockfile(unittest.TestCase):
    def test_positive_npm_install_unpinned(self):
        """A bare npm install (no lockfile enforcement) trips the rule."""
        wf = """\
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - run: npm install
"""
        self.assertIn("missing-frozen-lockfile", fired(wf))

    def test_negative_npm_ci(self):
        """Using npm ci instead of npm install does not trip the rule."""
        self.assertNotIn("missing-frozen-lockfile", fired(HARDENED))

    def test_no_fp_on_webpack_bundle_flag(self):
        """`webpack --bundle` / `bundle.js` are not Ruby bundler — must not fire."""
        wf = """\
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - run: webpack --bundle && node bundle.js
"""
        self.assertNotIn("missing-frozen-lockfile", fired(wf))

    def test_fires_on_real_bundle_install(self):
        """A real `bundle install` (no --frozen) still trips the rule."""
        wf = """\
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - run: bundle install
"""
        self.assertIn("missing-frozen-lockfile", fired(wf))


class TestNoFalsePositives(unittest.TestCase):
    def test_hardened_workflow_fires_nothing(self):
        """A fully-hardened workflow fires zero absence rules."""
        self.assertEqual(fired(HARDENED), set())


if __name__ == "__main__":
    unittest.main()
