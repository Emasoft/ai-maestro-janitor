"""Tests for scripts/lib/jenkins_groovy_patterns.py.

Pattern-coverage tests for the Wave-36 distill-round-22 Jenkins Groovy
catalogue (10 Jenkins-specific anti-patterns covering Jenkinsfile, shared
library Groovy, and Jenkins CasC YAML). Each rule has 2 tests: one
positive (canary triggers) and one negative (safe variant does NOT fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import jenkins_groovy_patterns as jkn  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs with jkn- prefix."""
    assert isinstance(jkn.RULES, tuple)
    rule_ids = {r.id for r in jkn.RULES}
    expected = {
        "jkn-gstring-shell-injection",
        "jkn-evaluate-user-input",
        "jkn-shared-lib-mutable-ref",
        "jkn-withcredentials-echo",
        "jkn-lightweight-false",
        "jkn-unpinned-docker-image",
        "jkn-docker-run-as-root",
        "jkn-noncps-privileged",
        "jkn-casc-plaintext-secret",
        "jkn-cron-with-credentials",
    }
    assert expected == rule_ids
    assert len(jkn.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity level."""
    for rule in jkn.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding NamedTuple has all required fields in the right positions."""
    f = jkn.Finding(
        rule_id="jkn-test",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-07",
    )
    assert f.rule_id == "jkn-test"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must return an empty findings list without error."""
    assert jkn.scan_text("") == []


# ---------- jkn-gstring-shell-injection ----------------------------------


def test_gstring_shell_injection_double_quoted_positive() -> None:
    """sh with double-quoted GString params interpolation must be flagged."""
    src = 'sh "git clone ${params.REPO_URL} /workspace"'
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-gstring-shell-injection" in ids


def test_gstring_shell_injection_safe_env_step_negative() -> None:
    """sh using plain env var reference (no GString) must NOT be flagged."""
    # $REPO_URL is a shell variable expansion, not a Groovy GString
    src = "sh 'git clone $REPO_URL /workspace'"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-gstring-shell-injection" not in ids


# ---------- jkn-evaluate-user-input --------------------------------------


def test_evaluate_readfile_positive() -> None:
    """evaluate(readFile('...')) must be flagged as arbitrary code execution."""
    src = "evaluate(readFile('scripts/deploy.groovy'))"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-evaluate-user-input" in ids


def test_evaluate_params_positive() -> None:
    """evaluate(params.SCRIPT_BODY) must be flagged."""
    src = "def result = evaluate(params.SCRIPT_BODY)"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-evaluate-user-input" in ids


# ---------- jkn-shared-lib-mutable-ref -----------------------------------


def test_shared_lib_main_ref_positive() -> None:
    """library identifier pinned to @main must be flagged as mutable ref."""
    src = "library identifier: 'my-shared-lib@main', retriever: modernSCM(...)"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-shared-lib-mutable-ref" in ids


def test_shared_lib_sha_ref_negative() -> None:
    """library identifier pinned to a commit SHA must NOT be flagged."""
    src = "library identifier: 'my-shared-lib@a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2'"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-shared-lib-mutable-ref" not in ids


# ---------- jkn-withcredentials-echo -------------------------------------


def test_withcredentials_echo_password_positive() -> None:
    """echo expanding a PASSWORD variable inside withCredentials must be flagged."""
    src = 'echo "Deploying with ${PASSWORD}"'
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-withcredentials-echo" in ids


def test_withcredentials_echo_safe_negative() -> None:
    """echo of a non-secret variable name must NOT be flagged."""
    src = 'echo "Build number ${BUILD_NUMBER} complete"'
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-withcredentials-echo" not in ids


# ---------- jkn-lightweight-false ----------------------------------------


def test_lightweight_false_positive() -> None:
    """checkout block with lightweight: false must be flagged."""
    src = "checkout(scm: scm, lightweight: false)"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-lightweight-false" in ids


def test_lightweight_true_negative() -> None:
    """checkout block with lightweight: true must NOT be flagged."""
    src = "checkout(scm: scm, lightweight: true)"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-lightweight-false" not in ids


# ---------- jkn-unpinned-docker-image ------------------------------------


def test_unpinned_docker_latest_positive() -> None:
    """Docker image pinned to :latest must be flagged as mutable supply-chain."""
    src = "agent { docker { image 'node:latest' } }"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-unpinned-docker-image" in ids


def test_pinned_docker_version_negative() -> None:
    """Docker image pinned to a specific version must NOT be flagged."""
    src = "agent { docker { image 'node:20.12.0' } }"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-unpinned-docker-image" not in ids


# ---------- jkn-docker-run-as-root ---------------------------------------


def test_docker_args_root_positive() -> None:
    """agent docker args containing -u root must be flagged."""
    src = "agent { docker { image 'myimage:1.0' args '-u root --privileged' } }"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-docker-run-as-root" in ids


def test_docker_args_nonroot_negative() -> None:
    """agent docker args without root user flag must NOT be flagged."""
    src = "agent { docker { image 'myimage:1.0' args '-u 1000' } }"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-docker-run-as-root" not in ids


# ---------- jkn-noncps-privileged ----------------------------------------


def test_noncps_with_withcredentials_positive() -> None:
    """@NonCPS followed by withCredentials within 80 chars must be flagged."""
    src = "@NonCPS\ndef deploySecrets() {\n  withCredentials([]) { sh 'deploy.sh' }\n}"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-noncps-privileged" in ids


def test_noncps_pure_util_negative() -> None:
    """@NonCPS on a pure utility function (no credentials/shell) must NOT be flagged."""
    src = "@NonCPS\ndef formatDate(String d) { return d.replace('-', '/') }"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-noncps-privileged" not in ids


# ---------- jkn-casc-plaintext-secret ------------------------------------


def test_casc_plaintext_password_positive() -> None:
    """CasC YAML with literal password value must be flagged as secret leak."""
    src = "password: mysecretpassword123"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-casc-plaintext-secret" in ids


def test_casc_env_var_reference_negative() -> None:
    """CasC YAML using ${SECRET_VAR} reference must NOT be flagged."""
    src = "password: ${JENKINS_ADMIN_PASSWORD}"
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-casc-plaintext-secret" not in ids


# ---------- jkn-cron-with-credentials ------------------------------------


def test_cron_with_credentials_positive() -> None:
    """Cron trigger followed by withCredentials in the same pipeline must be flagged."""
    src = (
        "pipeline {\n"
        "  triggers { cron('H 2 * * *') }\n"
        "  stages {\n"
        "    stage('deploy') {\n"
        "      steps {\n"
        "        withCredentials([usernamePassword(credentialsId: 'prod')]) {\n"
        "          sh './deploy.sh'\n"
        "        }\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-cron-with-credentials" in ids


def test_cron_without_credentials_negative() -> None:
    """Cron trigger without withCredentials must NOT trigger the combined rule."""
    src = (
        "pipeline {\n"
        "  triggers { cron('H 2 * * *') }\n"
        "  stages {\n"
        "    stage('report') {\n"
        "      steps { sh 'echo hello' }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    findings = jkn.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "jkn-cron-with-credentials" not in ids
