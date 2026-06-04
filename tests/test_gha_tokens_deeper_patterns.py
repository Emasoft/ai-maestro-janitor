"""Tests for scripts/lib/gha_tokens_deeper_patterns.py.

Pattern-coverage tests for the Wave-30 distill-round-16 GHA tokens /
permission scope catalogue (7 rules). Each rule has at least two tests:
one positive (canary that must fire) and one negative (carve-out / context
filter that must NOT fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import gha_tokens_deeper_patterns as gha  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(gha.RULES, tuple)
    rule_ids = {r.id for r in gha.RULES}
    expected = {
        "gha-prt-wrong-scope-write",
        "gha-pat-checkout-fork-ref",
        "gha-id-token-write-without-oidc-consumer",
        "gha-missing-permissions-default-write",
        "gha-third-party-action-token-no-sha-pin",
        "gha-checkout-persist-creds-git-push",
        "gha-workflow-dispatch-write-all-workflow-level",
    }
    assert expected == rule_ids
    assert len(gha.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity level."""
    for rule in gha.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding field shape."""
    f = gha.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-GHA-01",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-GHA-01"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert gha.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Findings must be ordered by (line, column, rule_id) for determinism."""
    # Two distinct hits: write-all at line 1, id-token at line 2.
    src = (
        "permissions: write-all\n"
        "  id-token: write\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
    )
    findings = gha.scan_text(src)
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[gha.Finding]:
    return [f for f in gha.scan_text(text) if f.rule_id == rule_id]


# ---------- G1 : gha-prt-wrong-scope-write ------------------------------


def test_g1_prt_with_narrow_scope_flags() -> None:
    """pull_request_target + issues:write only → HIGH finding."""
    src = """\
on:
  pull_request_target:
    types: [opened]

permissions:
  issues: write

jobs:
  comment:
    runs-on: ubuntu-latest
    steps:
      - run: echo done
"""
    hits = _hits("gha-prt-wrong-scope-write", src)
    assert hits, "Expected a finding for understated scope"
    assert hits[0].severity == "HIGH"


def test_g1_prt_with_pull_requests_scope_suppressed() -> None:
    """pull_request_target + pull-requests:write declared → no finding."""
    src = """\
on:
  pull_request_target:
    types: [opened]

permissions:
  pull-requests: write

jobs:
  comment:
    runs-on: ubuntu-latest
    steps:
      - run: echo done
"""
    hits = _hits("gha-prt-wrong-scope-write", src)
    assert not hits, "pull-requests: write scope should suppress the finding"


# ---------- G2 : gha-pat-checkout-fork-ref ------------------------------


def test_g2_pat_in_fork_exec_workflow_flags() -> None:
    """PAT token: in pull_request_target workflow → CRITICAL finding."""
    src = """\
on:
  pull_request_target:
    types: [opened]

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: JamesIves/github-sponsors-readme-action@v1.6.0
        with:
          token: ${{ secrets.SPONSORS_PAT }}
          file: README.md
"""
    hits = _hits("gha-pat-checkout-fork-ref", src)
    assert hits, "Expected CRITICAL finding for PAT in fork-exec workflow"
    assert hits[0].severity == "CRITICAL"


def test_g2_github_token_is_suppressed() -> None:
    """secrets.GITHUB_TOKEN as token: input → no finding (built-in token)."""
    src = """\
on:
  pull_request_target:
    types: [opened]

jobs:
  comment:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/github-script@v7
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
"""
    hits = _hits("gha-pat-checkout-fork-ref", src)
    assert not hits, "GITHUB_TOKEN should be suppressed"


def test_g2_pat_without_fork_trigger_suppressed() -> None:
    """PAT token: in a plain push workflow → no finding (not fork context)."""
    src = """\
on:
  push:
    branches: [main]

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: JamesIves/sponsors-action@v1.6.0
        with:
          token: ${{ secrets.SPONSORS_PAT }}
"""
    hits = _hits("gha-pat-checkout-fork-ref", src)
    assert not hits, "Without fork trigger context, PAT usage should not flag"


# ---------- G3 : gha-id-token-write-without-oidc-consumer --------------


def test_g3_id_token_write_without_consumer_flags() -> None:
    """id-token: write with no OIDC relying party step → HIGH finding."""
    src = """\
permissions:
  contents: write
  id-token: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: cargo build --release
      - uses: softprops/action-gh-release@v2
        with:
          files: target/release/mybinary
"""
    hits = _hits("gha-id-token-write-without-oidc-consumer", src)
    assert hits, "Expected finding: id-token:write with no OIDC consumer"
    assert hits[0].severity == "HIGH"


def test_g3_id_token_write_with_aws_credentials_suppressed() -> None:
    """id-token: write + aws-actions/configure-aws-credentials → no finding."""
    src = """\
permissions:
  id-token: write
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::123456789012:role/MyRole
          aws-region: us-east-1
"""
    hits = _hits("gha-id-token-write-without-oidc-consumer", src)
    assert not hits, "OIDC consumer present should suppress the finding"


def test_g3_id_token_write_with_npm_provenance_suppressed() -> None:
    """id-token: write + npm publish --provenance → no finding."""
    src = """\
permissions:
  id-token: write
  contents: read

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - run: npm publish --provenance
"""
    hits = _hits("gha-id-token-write-without-oidc-consumer", src)
    assert not hits, "npm publish --provenance is a valid OIDC consumer"


# ---------- G4 : gha-missing-permissions-default-write -----------------


def test_g4_workflow_without_permissions_flags() -> None:
    """Workflow with no permissions: block → HIGH finding at offset 0."""
    src = """\
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm test
"""
    hits = _hits("gha-missing-permissions-default-write", src)
    assert hits, "Expected finding: missing permissions block"
    assert hits[0].severity == "HIGH"
    assert hits[0].line == 1


def test_g4_workflow_with_permissions_block_suppressed() -> None:
    """Workflow with permissions: block present → no finding."""
    src = """\
name: CI

on:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: npm test
"""
    hits = _hits("gha-missing-permissions-default-write", src)
    assert not hits, "Permissions block present should suppress the finding"


def test_g4_non_workflow_file_not_flagged() -> None:
    """A plain Python or config file (no on:/jobs: marker) is not flagged."""
    src = """\
# not a workflow
def my_function():
    pass
"""
    hits = _hits("gha-missing-permissions-default-write", src)
    assert not hits, "Non-workflow file should not trigger the rule"


# ---------- G5 : gha-third-party-action-token-no-sha-pin ---------------


def test_g5_third_party_mutable_tag_with_token_flags() -> None:
    """Third-party action at semver tag + token: input → CRITICAL finding."""
    src = """\
jobs:
  update:
    steps:
      - uses: JamesIves/github-sponsors-readme-action@v1.6.0
        with:
          token: ${{ secrets.SPONSORS_PAT }}
          file: README.md
"""
    hits = _hits("gha-third-party-action-token-no-sha-pin", src)
    assert hits, "Expected CRITICAL finding for mutable-tag + token"
    assert hits[0].severity == "CRITICAL"


def test_g5_third_party_mutable_tag_without_token_suppressed() -> None:
    """Third-party action at semver tag with NO token input → no finding."""
    src = """\
jobs:
  update:
    steps:
      - uses: JamesIves/github-sponsors-readme-action@v1.6.0
        with:
          file: README.md
"""
    hits = _hits("gha-third-party-action-token-no-sha-pin", src)
    assert not hits, "Without token input, mutable-tag action should not flag"


def test_g5_first_party_action_suppressed() -> None:
    """actions/ org with mutable tag + token input → no finding."""
    src = """\
jobs:
  update:
    steps:
      - uses: actions/github-script@v7
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
"""
    hits = _hits("gha-third-party-action-token-no-sha-pin", src)
    assert not hits, "First-party actions/ org should be suppressed"


# ---------- G6 : gha-checkout-persist-creds-git-push -------------------


def test_g6_checkout_default_plus_git_push_flags() -> None:
    """Checkout without persist-credentials:false followed by git push → HIGH."""
    src = """\
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Bump and push
        run: |
          npm version patch
          git config user.email "bot@example.com"
          git config user.name "Release Bot"
          git add .
          git commit -m "chore: bump version"
          git push
"""
    hits = _hits("gha-checkout-persist-creds-git-push", src)
    assert hits, "Expected finding for implicit persist-credentials + git push"
    assert hits[0].severity == "HIGH"


def test_g6_checkout_persist_false_suppressed() -> None:
    """Checkout with explicit persist-credentials:false → no finding."""
    src = """\
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false

      - name: Push
        run: git push
"""
    hits = _hits("gha-checkout-persist-creds-git-push", src)
    assert not hits, "persist-credentials: false should suppress the finding"


def test_g6_checkout_without_git_push_suppressed() -> None:
    """Checkout followed by no git push → no finding."""
    src = """\
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm test
"""
    hits = _hits("gha-checkout-persist-creds-git-push", src)
    assert not hits, "No git push means no credential window issue"


# ---------- G7 : gha-workflow-dispatch-write-all-workflow-level ---------


def test_g7_write_all_in_standard_workflow_flags() -> None:
    """permissions: write-all in non-reusable workflow → CRITICAL finding."""
    src = """\
name: Release Drafter

on:
  push:
    branches: [main]
  pull_request:
    types: [opened, reopened, synchronize]

permissions: write-all

jobs:
  update_release_draft:
    runs-on: ubuntu-latest
    steps:
      - uses: release-drafter/release-drafter@v7
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
"""
    hits = _hits("gha-workflow-dispatch-write-all-workflow-level", src)
    assert hits, "Expected CRITICAL finding for permissions: write-all"
    assert hits[0].severity == "CRITICAL"


def test_g7_write_all_in_reusable_workflow_suppressed() -> None:
    """permissions: write-all in a workflow_call body → no finding (other rule)."""
    src = """\
on:
  workflow_call:
    inputs:
      environment:
        type: string

permissions: write-all

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: ./deploy.sh
"""
    hits = _hits("gha-workflow-dispatch-write-all-workflow-level", src)
    assert not hits, "workflow_call context should suppress G7 (covered by gha_reusable)"


def test_g7_minimal_scoped_permissions_no_flag() -> None:
    """Workflow with scoped (non write-all) permissions → no G7 finding."""
    src = """\
on:
  push:
    branches: [main]

permissions:
  contents: write
  pull-requests: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - run: echo done
"""
    hits = _hits("gha-workflow-dispatch-write-all-workflow-level", src)
    assert not hits, "Explicit scoped permissions should not trigger write-all rule"
