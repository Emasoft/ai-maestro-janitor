"""Tests for scripts/lib/slsa_sbom_signing_patterns.py.

Pattern-coverage tests for the Wave-31 distill-round-17 SLSA/SBOM signing
catalogue (14 supply-chain signing anti-patterns covering cosign / in-toto /
sigstore / SLSA provenance / SBOM generation). Each rule has at least two
tests: one positive (canary fires) and one negative (carve-out / benign
variant does NOT fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import slsa_sbom_signing_patterns as ssp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Synthetic secret-shaped fixtures -----------------------------
# PEM markers split at runtime so no contiguous private-key header exists
# at rest in this file. The detector still receives the fully-assembled
# string; only the at-rest bytes change.
_EC_PEM_BEGIN = "-----BEGIN EC " + "PRIVATE KEY-----"
_EC_PEM_END = "-----END EC " + "PRIVATE KEY-----"
_RSA_PEM_BEGIN = "-----BEGIN RSA " + "PRIVATE KEY-----"
_RSA_PEM_END = "-----END RSA " + "PRIVATE KEY-----"

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 14 documented rule IDs."""
    assert isinstance(ssp.RULES, tuple)
    rule_ids = {r.id for r in ssp.RULES}
    expected = {
        "slsa-sbom-cosign-skip-verify",
        "slsa-sbom-cosign-allow-insecure-registry",
        "slsa-sbom-cosign-keyless-oidc-no-cert-identity",
        "slsa-sbom-image-no-digest-pin",
        "slsa-sbom-sbom-not-attached-to-oci",
        "slsa-sbom-intoto-attestation-no-verify",
        "slsa-sbom-slsa-provenance-no-verify",
        "slsa-sbom-signing-key-committed",
        "slsa-sbom-cosign-verify-no-rekor-log",
        "slsa-sbom-sbom-tool-no-version-lock",
        "slsa-sbom-fulcio-url-override-untrusted",
        "slsa-sbom-rekor-url-override-untrusted",
        "slsa-sbom-sbom-missing-hash-algorithm",
        "slsa-sbom-cosign-sign-env-key-unprotected",
    }
    assert expected == rule_ids
    assert len(ssp.RULES) == 14


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in ssp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = ssp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-05",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-05"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert ssp.scan_text("") == []


# ---------- S1 : slsa-sbom-cosign-skip-verify ----------------------------


def test_s1_positive_skip_tlog_verify() -> None:
    """cosign verify with --skip-tlog-verify fires S1."""
    src = "cosign verify --key cosign.pub --skip-tlog-verify ghcr.io/acme/app:v1.2\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-cosign-skip-verify" in ids


def test_s1_positive_insecure_skip_tlog_verify() -> None:
    """cosign verify with deprecated --insecure-skip-tlog-verify also fires S1."""
    src = "cosign verify --insecure-skip-tlog-verify --key k.pub myimage:tag\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-cosign-skip-verify" in ids


def test_s1_negative_no_skip_flag() -> None:
    """cosign verify without skip flag does not fire S1."""
    src = "cosign verify --key cosign.pub ghcr.io/acme/app@sha256:" + "a" * 64 + "\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-cosign-skip-verify" not in ids


# ---------- S2 : slsa-sbom-cosign-allow-insecure-registry ----------------


def test_s2_positive_allow_insecure_registry() -> None:
    """cosign with --allow-insecure-registry fires S2."""
    src = "cosign sign --key key.pem --allow-insecure-registry localhost:5000/img:v1\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-cosign-allow-insecure-registry" in ids


def test_s2_negative_no_insecure_flag() -> None:
    """cosign sign without --allow-insecure-registry does not fire S2."""
    src = "cosign sign --key key.pem ghcr.io/acme/img:v2\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-cosign-allow-insecure-registry" not in ids


# ---------- S3 : slsa-sbom-cosign-keyless-oidc-no-cert-identity ----------


def test_s3_positive_oidc_issuer_without_identity() -> None:
    """cosign verify with --certificate-oidc-issuer but no --certificate-identity fires S3."""
    src = (
        "cosign verify "
        "--certificate-oidc-issuer https://token.actions.githubusercontent.com "
        "myrepo/myimage:latest\n"
    )
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-cosign-keyless-oidc-no-cert-identity" in ids


def test_s3_negative_oidc_issuer_with_identity() -> None:
    """cosign verify with both --certificate-oidc-issuer and --certificate-identity is safe."""
    src = (
        "cosign verify "
        "--certificate-oidc-issuer https://token.actions.githubusercontent.com "
        "--certificate-identity https://github.com/acme/repo/.github/workflows/release.yml@refs/heads/main "
        "myrepo/myimage:latest\n"
    )
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-cosign-keyless-oidc-no-cert-identity" not in ids


# ---------- S4 : slsa-sbom-image-no-digest-pin ---------------------------


def test_s4_positive_dockerfile_from_mutable_tag() -> None:
    """Dockerfile FROM with mutable tag and no digest fires S4."""
    src = "FROM python:3.11-slim\nRUN pip install -r requirements.txt\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-image-no-digest-pin" in ids


def test_s4_positive_yaml_image_no_digest() -> None:
    """Kubernetes pod spec with mutable tag fires S4."""
    src = "image: nginx:latest\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-image-no-digest-pin" in ids


def test_s4_negative_image_with_digest() -> None:
    """Image reference with @sha256: digest pin does not fire S4."""
    src = "FROM python:3.11-slim@sha256:" + "a" * 64 + "\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-image-no-digest-pin" not in ids


# ---------- S5 : slsa-sbom-sbom-not-attached-to-oci ----------------------


def test_s5_positive_sbom_generated_not_attached() -> None:
    """syft generating SBOM without cosign attach sbom fires S5."""
    src = (
        "syft packages -o cyclonedx-json /path/to/image > sbom.json\n"
        "echo done\n"
    )
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-sbom-not-attached-to-oci" in ids


def test_s5_negative_sbom_generated_and_attached() -> None:
    """syft SBOM followed by cosign attach sbom within 20 lines does not fire S5."""
    lines = [
        "syft packages -o cyclonedx-json ghcr.io/acme/app:v1 > sbom.json\n",
        "cosign attach sbom --sbom sbom.json ghcr.io/acme/app:v1\n",
    ]
    src = "".join(lines)
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-sbom-not-attached-to-oci" not in ids


# ---------- S6 : slsa-sbom-intoto-attestation-no-verify ------------------


def test_s6_positive_download_attestation_no_verify() -> None:
    """cosign download attestation without verify-attestation fires S6."""
    src = (
        "cosign download attestation ghcr.io/acme/app:v1 > att.json\n"
        "cat att.json | jq .\n"
    )
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-intoto-attestation-no-verify" in ids


def test_s6_negative_download_with_verify() -> None:
    """cosign download attestation followed by verify-attestation does not fire S6."""
    src = (
        "cosign download attestation ghcr.io/acme/app:v1 > att.json\n"
        "cosign verify-attestation --type slsaprovenance ghcr.io/acme/app:v1\n"
    )
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-intoto-attestation-no-verify" not in ids


# ---------- S7 : slsa-sbom-slsa-provenance-no-verify ---------------------


def test_s7_positive_slsa_verifier_skip_verify() -> None:
    """slsa-verifier with --skip-verify fires S7."""
    src = "slsa-verifier verify-image --skip-verify --source-uri github.com/acme/app ghcr.io/acme/app:v1\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-slsa-provenance-no-verify" in ids


def test_s7_negative_slsa_verifier_without_skip() -> None:
    """slsa-verifier without --skip-verify does not fire S7."""
    src = "slsa-verifier verify-image --source-uri github.com/acme/app ghcr.io/acme/app:v1\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-slsa-provenance-no-verify" not in ids


# ---------- S8 : slsa-sbom-signing-key-committed -------------------------


def test_s8_positive_ec_private_key_pem() -> None:
    """PEM EC private key block fires S8."""
    src = f"{_EC_PEM_BEGIN}\nMHQCAQEEIPf...\n{_EC_PEM_END}\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-signing-key-committed" in ids


def test_s8_positive_rsa_private_key_pem() -> None:
    """PEM RSA private key block fires S8."""
    src = f"{_RSA_PEM_BEGIN}\nMIIEowIBAAKCAQEA...\n{_RSA_PEM_END}\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-signing-key-committed" in ids


def test_s8_negative_public_key_only() -> None:
    """PEM public key block does not fire S8."""
    src = "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkq...\n-----END PUBLIC KEY-----\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-signing-key-committed" not in ids


# ---------- S9 : slsa-sbom-cosign-verify-no-rekor-log --------------------


def test_s9_positive_cosign_verify_offline() -> None:
    """cosign verify --offline fires S9."""
    src = "cosign verify --offline --key cosign.pub ghcr.io/acme/app:v1\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-cosign-verify-no-rekor-log" in ids


def test_s9_negative_cosign_verify_online() -> None:
    """cosign verify without --offline does not fire S9."""
    src = "cosign verify --key cosign.pub ghcr.io/acme/app:v1\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-cosign-verify-no-rekor-log" not in ids


# ---------- S10 : slsa-sbom-sbom-tool-no-version-lock --------------------


def test_s10_positive_pip_install_syft_no_version() -> None:
    """pip install syft without version pin fires S10."""
    src = "pip install syft\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-sbom-tool-no-version-lock" in ids


def test_s10_positive_npm_install_cdxgen_no_version() -> None:
    """npm install -g @cyclonedx/cdxgen without version fires S10."""
    src = "npm install -g @cyclonedx/cdxgen\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-sbom-tool-no-version-lock" in ids


def test_s10_negative_pip_install_syft_with_version() -> None:
    """pip install syft==0.98.0 does not fire S10."""
    src = "pip install syft==0.98.0\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-sbom-tool-no-version-lock" not in ids


# ---------- S11 : slsa-sbom-fulcio-url-override-untrusted ----------------


def test_s11_positive_custom_fulcio_url() -> None:
    """cosign with --fulcio-url pointing to non-official host fires S11."""
    src = "cosign sign --fulcio-url https://fulcio.internal.example.com --identity-token $TOKEN myimg:v1\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-fulcio-url-override-untrusted" in ids


def test_s11_negative_official_fulcio_url() -> None:
    """cosign with official --fulcio-url does not fire S11."""
    src = "cosign sign --fulcio-url https://fulcio.sigstore.dev --identity-token $TOKEN myimg:v1\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-fulcio-url-override-untrusted" not in ids


# ---------- S12 : slsa-sbom-rekor-url-override-untrusted -----------------


def test_s12_positive_custom_rekor_url() -> None:
    """cosign with --rekor-url pointing to non-official host fires S12."""
    src = "cosign sign --rekor-url https://rekor.internal.example.com --key k.pem myimg:v1\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-rekor-url-override-untrusted" in ids


def test_s12_negative_official_rekor_url() -> None:
    """cosign with official --rekor-url does not fire S12."""
    src = "cosign sign --rekor-url https://rekor.sigstore.dev --key k.pem myimg:v1\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-rekor-url-override-untrusted" not in ids


# ---------- S13 : slsa-sbom-sbom-missing-hash-algorithm ------------------


def test_s13_positive_component_without_hash() -> None:
    """CycloneDX component block without hashes field fires S13."""
    src = (
        '  "type": "library",\n'
        '  "bom-ref": "pkg:npm/lodash@4.17.21",\n'
        '  "name": "lodash",\n'
        '  "version": "4.17.21"\n'
    )
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-sbom-missing-hash-algorithm" in ids


def test_s13_negative_component_with_hashes() -> None:
    """CycloneDX component block with hashes field does not fire S13."""
    src = (
        '  "type": "library",\n'
        '  "bom-ref": "pkg:npm/lodash@4.17.21",\n'
        '  "hashes": [{"alg": "SHA-256", "content": "abc123"}],\n'
        '  "name": "lodash"\n'
    )
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-sbom-missing-hash-algorithm" not in ids


# ---------- S14 : slsa-sbom-cosign-sign-env-key-unprotected --------------


def test_s14_positive_cosign_sign_env_key() -> None:
    """cosign sign --key env://COSIGN_PRIVATE_KEY fires S14."""
    src = "cosign sign --key env://COSIGN_PRIVATE_KEY ghcr.io/acme/app:v1\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-cosign-sign-env-key-unprotected" in ids


def test_s14_negative_cosign_sign_with_kms_key() -> None:
    """cosign sign with a KMS key path does not fire S14."""
    src = "cosign sign --key gcpkms://projects/my-project/locations/global/keyRings/my-ring/cryptoKeys/my-key ghcr.io/acme/app:v1\n"
    findings = ssp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "slsa-sbom-cosign-sign-env-key-unprotected" not in ids
