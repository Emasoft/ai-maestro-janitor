"""Tests for bitbucket_drone_patterns — 2 tests per rule (20 total).

Run with:
  uv run --with pytest --with pyyaml python -m pytest tests/test_bitbucket_drone_patterns.py -q
"""

from __future__ import annotations

import os
import sys

# Allow importing from scripts/lib without an installed package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))

import bitbucket_drone_patterns as bdp  # type: ignore  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has(findings: list, rule_id: str) -> bool:
    return any(f.rule_id == rule_id for f in findings)


# ---------------------------------------------------------------------------
# R1 — bdc-bitbucket-image-latest
# ---------------------------------------------------------------------------


def test_bitbucket_image_latest_fires_on_mutable_tag() -> None:
    """`:latest` tag in bitbucket-pipelines image key triggers rule."""
    yaml = "image: node:latest\n"
    findings = bdp.scan_text(yaml)
    assert _has(findings, "bdc-bitbucket-image-latest"), findings


def test_bitbucket_image_latest_no_fire_on_digest_pinned() -> None:
    """Digest-pinned image does not trigger rule."""
    yaml = "image: node:18@sha256:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890\n"
    findings = bdp.scan_text(yaml)
    assert not _has(findings, "bdc-bitbucket-image-latest"), findings


# ---------------------------------------------------------------------------
# R2 — bdc-bitbucket-oidc-wildcard
# ---------------------------------------------------------------------------


def test_bitbucket_oidc_wildcard_fires_on_oidc_plus_role_arn() -> None:
    """oidc: true with AWS_ROLE_ARN in same step triggers rule."""
    yaml = (
        "- step:\n"
        "    oidc: true\n"
        "    script:\n"
        "      - export AWS_ROLE_ARN=arn:aws:iam::123456789012:role/MyRole\n"
    )
    findings = bdp.scan_text(yaml)
    assert _has(findings, "bdc-bitbucket-oidc-wildcard"), findings


def test_bitbucket_oidc_wildcard_no_fire_without_oidc_flag() -> None:
    """AWS_ROLE_ARN without oidc: true does not trigger rule."""
    yaml = (
        "- step:\n"
        "    script:\n"
        "      - export AWS_ROLE_ARN=arn:aws:iam::123456789012:role/MyRole\n"
    )
    findings = bdp.scan_text(yaml)
    assert not _has(findings, "bdc-bitbucket-oidc-wildcard"), findings


# ---------------------------------------------------------------------------
# R3 — bdc-bitbucket-services-privileged
# ---------------------------------------------------------------------------


def test_bitbucket_services_privileged_fires_on_indented_privileged_true() -> None:
    """Indented `privileged: true` inside a services block triggers rule."""
    yaml = (
        "definitions:\n"
        "  services:\n"
        "    docker:\n"
        "      image: docker:dind\n"
        "      privileged: true\n"
    )
    findings = bdp.scan_text(yaml)
    assert _has(findings, "bdc-bitbucket-services-privileged"), findings


def test_bitbucket_services_privileged_no_fire_on_privileged_false() -> None:
    """`privileged: false` does not trigger rule."""
    yaml = (
        "definitions:\n"
        "  services:\n"
        "    docker:\n"
        "      image: docker:dind\n"
        "      privileged: false\n"
    )
    findings = bdp.scan_text(yaml)
    assert not _has(findings, "bdc-bitbucket-services-privileged"), findings


# ---------------------------------------------------------------------------
# R4 — bdc-drone-image-pull-secrets-committed
# ---------------------------------------------------------------------------


def test_drone_image_pull_secrets_fires_on_inline_password() -> None:
    """Literal `password:` inside image_pull_secrets triggers rule."""
    yaml = (
        "image_pull_secrets:\n"
        "  - registry: registry.example.com\n"
        "    username: myuser\n"
        "    password: s3cr3tP@ssword\n"
    )
    findings = bdp.scan_text(yaml)
    assert _has(findings, "bdc-drone-image-pull-secrets-committed"), findings


def test_drone_image_pull_secrets_no_fire_on_from_secret_reference() -> None:
    """A `from_secret:` reference (no literal credential) does not trigger rule."""
    yaml = (
        "image_pull_secrets:\n"
        "  - registry: registry.example.com\n"
        "    username:\n"
        "      from_secret: registry_user\n"
    )
    findings = bdp.scan_text(yaml)
    assert not _has(findings, "bdc-drone-image-pull-secrets-committed"), findings


# ---------------------------------------------------------------------------
# R5 — bdc-drone-build-on-fork-branch
# ---------------------------------------------------------------------------


def test_drone_build_on_fork_branch_fires_on_inline_list_main() -> None:
    """Branch filter `[main, develop]` triggers rule."""
    yaml = (
        "trigger:\n"
        "  branches: [main, develop]\n"
    )
    findings = bdp.scan_text(yaml)
    assert _has(findings, "bdc-drone-build-on-fork-branch"), findings


def test_drone_build_on_fork_branch_fires_on_block_list_master() -> None:
    """Block-list branch filter with `- master` triggers rule."""
    yaml = (
        "trigger:\n"
        "  branches:\n"
        "    - master\n"
        "    - release\n"
    )
    findings = bdp.scan_text(yaml)
    assert _has(findings, "bdc-drone-build-on-fork-branch"), findings


# ---------------------------------------------------------------------------
# R6 — bdc-drone-commit-message-shell-injection
# ---------------------------------------------------------------------------


def test_drone_commit_message_injection_fires_on_drone_commit_message() -> None:
    """`$DRONE_COMMIT_MESSAGE` unquoted in commands triggers rule."""
    yaml = (
        "steps:\n"
        "  - name: notify\n"
        "    image: alpine\n"
        "    commands:\n"
        "      - echo Build message: $DRONE_COMMIT_MESSAGE\n"
    )
    findings = bdp.scan_text(yaml)
    assert _has(findings, "bdc-drone-commit-message-shell-injection"), findings


def test_drone_commit_message_injection_no_fire_on_safe_env_var() -> None:
    """`$DRONE_BUILD_NUMBER` (not in the blocked list) does not trigger rule."""
    yaml = (
        "steps:\n"
        "  - name: deploy\n"
        "    commands:\n"
        "      - echo Build: $DRONE_BUILD_NUMBER\n"
    )
    findings = bdp.scan_text(yaml)
    assert not _has(findings, "bdc-drone-commit-message-shell-injection"), findings


# ---------------------------------------------------------------------------
# R7 — bdc-drone-plugin-image-unpinned
# ---------------------------------------------------------------------------


def test_drone_plugin_image_unpinned_fires_on_latest_tag() -> None:
    """`image: plugins/docker:latest` triggers rule."""
    yaml = "    image: plugins/docker:latest\n"
    findings = bdp.scan_text(yaml)
    assert _has(findings, "bdc-drone-plugin-image-unpinned"), findings


def test_drone_plugin_image_unpinned_no_fire_on_digest_pinned() -> None:
    """`image: plugins/docker:20.10@sha256:<digest>` does not trigger rule."""
    yaml = (
        "    image: plugins/docker:20.10.21@sha256:"
        "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890\n"
    )
    findings = bdp.scan_text(yaml)
    assert not _has(findings, "bdc-drone-plugin-image-unpinned"), findings


# ---------------------------------------------------------------------------
# R8 — bdc-woodpecker-clone-disabled
# ---------------------------------------------------------------------------


def test_woodpecker_clone_disabled_fires_on_block_form() -> None:
    """`clone:\\n  disable: true` triggers rule."""
    yaml = (
        "clone:\n"
        "  disable: true\n"
        "steps:\n"
        "  - name: build\n"
    )
    findings = bdp.scan_text(yaml)
    assert _has(findings, "bdc-woodpecker-clone-disabled"), findings


def test_woodpecker_clone_disabled_no_fire_when_disable_absent() -> None:
    """Clone block without `disable: true` does not trigger rule."""
    yaml = (
        "clone:\n"
        "  depth: 1\n"
        "steps:\n"
        "  - name: build\n"
    )
    findings = bdp.scan_text(yaml)
    assert not _has(findings, "bdc-woodpecker-clone-disabled"), findings


# ---------------------------------------------------------------------------
# R9 — bdc-woodpecker-runtime-user-controlled
# ---------------------------------------------------------------------------


def test_woodpecker_backend_local_fires() -> None:
    """`backend: local` triggers rule."""
    yaml = (
        "steps:\n"
        "  - name: test\n"
        "    backend: local\n"
        "    commands:\n"
        "      - go test ./...\n"
    )
    findings = bdp.scan_text(yaml)
    assert _has(findings, "bdc-woodpecker-runtime-user-controlled"), findings


def test_woodpecker_backend_docker_no_fire() -> None:
    """`backend: docker` does not trigger rule."""
    yaml = (
        "steps:\n"
        "  - name: test\n"
        "    backend: docker\n"
        "    image: golang:1.22\n"
        "    commands:\n"
        "      - go test ./...\n"
    )
    findings = bdp.scan_text(yaml)
    assert not _has(findings, "bdc-woodpecker-runtime-user-controlled"), findings


# ---------------------------------------------------------------------------
# R10 — bdc-bitbucket-cache-key-predictable
# ---------------------------------------------------------------------------


def test_bitbucket_cache_key_static_fires() -> None:
    """Static cache key without checksum/hash reference triggers rule."""
    yaml = (
        "definitions:\n"
        "  caches:\n"
        "    node-modules:\n"
        "      key: node-cache-main\n"
        "      path: node_modules\n"
    )
    findings = bdp.scan_text(yaml)
    assert _has(findings, "bdc-bitbucket-cache-key-predictable"), findings


def test_bitbucket_cache_key_with_checksum_no_fire() -> None:
    """Cache key containing `checksum` does not trigger rule."""
    yaml = (
        "definitions:\n"
        "  caches:\n"
        "    node-modules:\n"
        "      key: checksum-node-cache\n"
        "      path: node_modules\n"
    )
    findings = bdp.scan_text(yaml)
    assert not _has(findings, "bdc-bitbucket-cache-key-predictable"), findings


# ---------------------------------------------------------------------------
# Meta: verify all 10 rules have at least one test each
# ---------------------------------------------------------------------------


def test_all_rules_have_ids() -> None:
    """RULES tuple exposes exactly 10 rules and all IDs are bdc-prefixed."""
    ids = [r.id for r in bdp.RULES]
    assert len(ids) == 10, f"Expected 10 rules, got {len(ids)}: {ids}"
    for rid in ids:
        assert rid.startswith("bdc-"), f"Rule ID missing bdc- prefix: {rid}"
