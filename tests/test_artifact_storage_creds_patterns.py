"""Tests for scripts/lib/artifact_storage_creds_patterns.py.

Pattern-coverage tests for the Wave-27 distill-round-13 angle catalogue
(7 anti-patterns covering credentials embedded in committed
package-registry configuration files). Each rule has at least one
positive test exercising the canary AND at least one negative test
exercising the safe-form carve-out.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import artifact_storage_creds_patterns as ascp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import dsn, secret  # noqa: E402

_docker_auth = base64.b64encode(("deployer:" + secret("ghp_", "artif-docker", 30)).encode()).decode()

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(ascp.RULES, tuple)
    rule_ids = {r.id for r in ascp.RULES}
    expected = {
        "artifact-npmrc-literal-authtoken",
        "artifact-maven-settings-literal-password",
        "artifact-url-inline-user-password",
        "artifact-docker-config-auth-b64",
        "artifact-gradle-properties-literal-credential",
        "artifact-netrc-machine-password-block",
        "artifact-aws-codeartifact-token-assignment",
    }
    assert expected == rule_ids
    assert len(ascp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in ascp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = ascp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-02",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert ascp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — npmrc literal token
        f"//registry.npmjs.org/:_authToken={secret('npm' + '_', 'ascp-sort-npm1', 36)}\n"
        # Line 2 — Maven password literal
        "<password>LiteralP@ssword2026</password>\n"
    )
    findings = ascp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[ascp.Finding]:
    return [f for f in ascp.scan_text(text) if f.rule_id == rule_id]


# ---------- A1 : artifact-npmrc-literal-authtoken ------------------------


def test_a1_npmrc_literal_authtoken_flags() -> None:
    """Literal `.npmrc` _authToken pinned to a real-shaped value → CRITICAL hit."""
    src = f"//registry.npmjs.org/:_authToken={secret('npm' + '_', 'ascp-a1-npm1', 36)}\n"
    hits = _hits("artifact-npmrc-literal-authtoken", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_a1_npmrc_env_reference_silent() -> None:
    """`_authToken=${NPM_TOKEN}` is the safe form → no hit."""
    src = "//registry.npmjs.org/:_authToken=${NPM_TOKEN}\n"
    assert not _hits("artifact-npmrc-literal-authtoken", src)


# ---------- A2 : artifact-maven-settings-literal-password ----------------


def test_a2_maven_literal_password_flags() -> None:
    """`<password>literal</password>` in settings.xml → CRITICAL hit."""
    src = (
        "<server><id>nexus-snapshots</id>"
        "<username>deployer</username>"
        "<password>P@ssw0rdLiteral123</password>"
        "</server>\n"
    )
    hits = _hits("artifact-maven-settings-literal-password", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_a2_maven_encrypted_or_env_password_silent() -> None:
    """Maven master-encrypted `{xxx==}` and `${env.X}` forms → no hit."""
    encrypted = "<password>{COQLCE6DU6GtcS5PoAfM/2RPpQADC3Y=}</password>\n"
    env_ref = "<password>${env.NEXUS_PASS}</password>\n"
    empty_placeholder = "<password></password>\n"
    assert not _hits("artifact-maven-settings-literal-password", encrypted)
    assert not _hits("artifact-maven-settings-literal-password", env_ref)
    assert not _hits("artifact-maven-settings-literal-password", empty_placeholder)


# ---------- A3 : artifact-url-inline-user-password -----------------------


def test_a3_url_inline_user_password_flags() -> None:
    """Inline credentials embedded in a package-registry URL → HIGH hit."""
    # URL with embedded user:pass is generated at runtime; no credential literal in source.
    _url = dsn("https", "a3-nexus-url", host="nexus.corp.local", port=None, db="repository/pypi-internal/simple", user_prefix="deployer_")
    src = f"pip install --extra-index-url {_url} mypkg\n"
    hits = _hits("artifact-url-inline-user-password", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_a3_url_env_interpolated_userinfo_silent() -> None:
    """`https://${USER}:${PASS}@…` is the safe form → no hit; SSH-shape user@host → no hit."""
    env_form = (
        "index-url = \"https://${USER}:${PASS}@artifactory.corp/api/pypi/pypi-local/simple\"\n"
    )
    ssh_form = "git+ssh://git@github.com/org/repo.git\n"
    assert not _hits("artifact-url-inline-user-password", env_form)
    assert not _hits("artifact-url-inline-user-password", ssh_form)


# ---------- A4 : artifact-docker-config-auth-b64 -------------------------


def test_a4_docker_config_auth_b64_flags() -> None:
    """Docker config.json `auths.<host>.auth` base64 value → CRITICAL hit."""
    src = '{"auths":{"ghcr.io":{"auth":"' + _docker_auth + '"}}}'
    hits = _hits("artifact-docker-config-auth-b64", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_a4_docker_config_no_auths_context_silent() -> None:
    """An `"auth"` field outside an `"auths"` block (e.g. unrelated JSON) → no hit."""
    src = '{"unrelated":{"auth":"YWRtaW46cGFzc3dvcmQ="}}\n'  # gitleaks:allow  pragma: allowlist secret
    assert not _hits("artifact-docker-config-auth-b64", src)


# ---------- A5 : artifact-gradle-properties-literal-credential -----------


def test_a5_gradle_literal_credential_flags() -> None:
    """`gradle.properties` literal token/password on a publishing key → CRITICAL hit."""
    src = (
        "ossrhUsername=mavendeploy\n"
        "ossrhPassword=My$onatypeP@ss2026Live\n"
    )
    hits = _hits("artifact-gradle-properties-literal-credential", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_a5_gradle_env_interpolation_or_signing_keyid_silent() -> None:
    """`${VAR}` interpolation and `signing.keyId` (non-secret) → no hit."""
    env_form = "ossrhPassword=${OSSRH_PASSWORD}\n"
    signing_keyid = "signing.keyId=12345678\n"
    assert not _hits("artifact-gradle-properties-literal-credential", env_form)
    assert not _hits("artifact-gradle-properties-literal-credential", signing_keyid)


# ---------- A6 : artifact-netrc-machine-password-block -------------------


def test_a6_netrc_artifact_host_literal_flags() -> None:
    """`.netrc` entry on artifact host with literal password → CRITICAL hit."""
    src = (
        "machine maven.pkg.github.com login octocat password "
        f"{secret('ghp' + '_', 'ascp-a6-ghp1', 26)}\n"
    )
    hits = _hits("artifact-netrc-machine-password-block", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_a6_netrc_non_artifact_host_silent() -> None:
    """`.netrc` for a generic host → no hit (different detector handles those)."""
    src = "machine example.com login alice password mypass1234567890\n"
    assert not _hits("artifact-netrc-machine-password-block", src)


# ---------- A7 : artifact-aws-codeartifact-token-assignment --------------


def test_a7_codeartifact_token_literal_flags() -> None:
    """`CODEARTIFACT_AUTH_TOKEN=<literal>` JWT-shape → CRITICAL hit."""
    # 22-char header.payload.body (each segment ≥ 20 chars per regex bound)
    token = (
        "eyJ2ZXIiOiIxIiwiYWxnIjoiZGlyIiwiZW5jIjoiQTI1NkdDTSJ9"
        ".AAAAAAAAAAAAAAAAAAAAAAAA"
        ".AAAAAAAAAAAAAAAAAAAAAAAA"
    )
    src = f"export CODEARTIFACT_AUTH_TOKEN={token}\n"
    hits = _hits("artifact-aws-codeartifact-token-assignment", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_a7_codeartifact_token_runtime_substitution_silent() -> None:
    """`${VAR}` and `$(aws codeartifact …)` are the safe forms → no hit."""
    env_ref = "export CODEARTIFACT_AUTH_TOKEN=${CODEARTIFACT_TOKEN}\n"
    cmd_subst = (
        "export CODEARTIFACT_AUTH_TOKEN="
        "$(aws codeartifact get-authorization-token --query authorizationToken "
        "--output text)\n"
    )
    assert not _hits("artifact-aws-codeartifact-token-assignment", env_ref)
    assert not _hits("artifact-aws-codeartifact-token-assignment", cmd_subst)
