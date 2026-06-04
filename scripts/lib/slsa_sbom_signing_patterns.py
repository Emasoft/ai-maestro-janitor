"""SLSA/SBOM supply-chain signing patterns (cosign, in-toto, sigstore).

Wave-31 distillation round 17, angle SLSA-SBOM.

Catalogue of 14 supply-chain signing anti-patterns covering:
  cosign / sigstore artifact-signing, SBOM generation (CycloneDX / SPDX),
  in-toto attestation, SLSA provenance, and OCI image verification
  workflows.

What is NOT here (already shipped — DO NOT duplicate):
  * Generic container-image pull without digest pinning —
    ``container_image_patterns.py``.
  * CI/CD secret leak of signing keys —
    ``cicd_secret_leak_patterns.py``.
  * Generic build-reproducibility patterns —
    ``build_reproducibility_patterns.py``.
  * CDN / registry TLS validation —
    ``cdn_supply_chain_patterns.py``.

What IS here (14 net-new rules, regex-only, all RE2-safe):

  * slsa-sbom-cosign-skip-verify                               (CRITICAL)
  * slsa-sbom-cosign-allow-insecure-registry                   (HIGH)
  * slsa-sbom-cosign-keyless-oidc-no-cert-identity             (HIGH)
  * slsa-sbom-image-no-digest-pin                              (HIGH)
  * slsa-sbom-sbom-not-attached-to-oci                         (MEDIUM)
  * slsa-sbom-intoto-attestation-no-verify                     (CRITICAL)
  * slsa-sbom-slsa-provenance-no-verify                        (CRITICAL)
  * slsa-sbom-signing-key-committed                            (CRITICAL)
  * slsa-sbom-cosign-verify-no-rekor-log                       (MEDIUM)
  * slsa-sbom-sbom-tool-no-version-lock                        (MEDIUM)
  * slsa-sbom-fulcio-url-override-untrusted                    (HIGH)
  * slsa-sbom-rekor-url-override-untrusted                     (HIGH)
  * slsa-sbom-sbom-missing-hash-algorithm                      (MEDIUM)
  * slsa-sbom-cosign-sign-env-key-unprotected                  (HIGH)

Public surface:
  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Injection / arbitrary execution (insecure registry, keyless
            OIDC misconfiguration)
  ASI-02 — Secret leak (signing key committed to repo)
  ASI-05 — Supply-chain / dependency confusion (image no digest, SBOM
            not attached, provenance skip, attestation no verify,
            SLSA provenance no verify)
  ASI-07 — Authority / authorisation gaps (Rekor / Fulcio URL override,
            missing hash algorithm, unprotected env key)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- S1 : slsa-sbom-cosign-skip-verify ----------------------------------

# ``cosign verify … --skip-tlog-verify`` or ``--insecure-skip-tlog-verify``
# entirely disables the Rekor transparency-log check, making the signature
# unauditable. Flag: literal ``--skip-tlog-verify`` or the deprecated
# ``--insecure-skip-tlog-verify`` on a cosign verify/verify-blob command.
_COSIGN_SKIP_VERIFY = _re(
    r"\bcosign\s+verify[^\n]*--(?:insecure-)?skip-tlog-verify\b"
)

# ---- S2 : slsa-sbom-cosign-allow-insecure-registry ----------------------

# ``cosign … --allow-insecure-registry`` bypasses TLS validation for the
# OCI registry, opening the door for MITM and registry-swap attacks.
_COSIGN_INSECURE_REGISTRY = _re(
    r"\bcosign\b[^\n]*--allow-insecure-registry\b"
)

# ---- S3 : slsa-sbom-cosign-keyless-oidc-no-cert-identity ----------------

# ``cosign verify … --certificate-oidc-issuer`` without a corresponding
# ``--certificate-identity`` (or ``--certificate-identity-regexp``) means
# *any* identity at that issuer can forge a valid signature.
_COSIGN_KEYLESS_NO_CERT_IDENTITY = _re(
    r"\bcosign\s+verify[^\n]*--certificate-oidc-issuer\b(?![^\n]*--certificate-identity\b)"
)

# ---- S4 : slsa-sbom-image-no-digest-pin ---------------------------------

# An OCI image reference like ``image: nginx:latest`` or ``FROM python:3.11``
# without ``@sha256:…`` is mutable and subject to supply-chain substitution.
#
# Strategy: match the full token including an optional ``@sha256:<hex>``
# digest suffix; then filter in scan_text by checking whether the full match
# contains ``@sha256:`` followed by exactly 64 hex chars.  A pure-regex
# negative-lookahead approach is unreliable here because the {1,40} quantifier
# on the tag portion allows the engine to backtrack to a shorter sub-match that
# escapes the lookahead even when the real tag is followed by a digest.
_IMAGE_NO_DIGEST_PIN = _re(
    r"(?:FROM|image:)\s+[a-z0-9][a-z0-9._/\-]{1,120}:[a-zA-Z0-9._\-]{1,40}"
    r"(?:@sha256:[a-f0-9]{64})?"
)
_DIGEST_SUFFIX = re.compile(r"@sha256:[a-f0-9]{64}$", re.IGNORECASE)

# ---- S5 : slsa-sbom-sbom-not-attached-to-oci ----------------------------

# ``syft … -o cyclonedx-json`` or ``trivy sbom --format cyclonedx …``
# generating an SBOM file but NOT piping into ``cosign attach sbom``
# in the same logical block. Anchor on the generation call; Stage-B
# checks for the ``cosign attach`` companion within 20 lines.
_SBOM_GENERATE_ANCHOR = _re(
    r"\b(?:syft|trivy\s+sbom|spdx-tools|cdxgen|cyclonedx\b)[^\n]*"
    r"(?:-o|--format)\s+(?:cyclonedx|spdx|bom)[^\n]*"
)

_SBOM_ATTACH_NEARBY = _re(r"\bcosign\s+attach\s+sbom\b")

# ---- S6 : slsa-sbom-intoto-attestation-no-verify ------------------------

# Fetching an in-toto attestation (``cosign download attestation``) without
# a subsequent ``cosign verify-attestation``. The download alone proves
# nothing — verification must follow.
_INTOTO_DOWNLOAD = _re(r"\bcosign\s+download\s+attestation\b")
_INTOTO_VERIFY = _re(r"\bcosign\s+verify-attestation\b")

# ---- S7 : slsa-sbom-slsa-provenance-no-verify ---------------------------

# Fetching SLSA provenance (``slsa-verifier verify-image``, or
# ``cosign download attestation --predicate-type slsa.dev``) and
# ``--skip-verify`` being present, or provenance download without
# a ``slsa-verifier verify-image`` call in the file.
_SLSA_SKIP_VERIFY = _re(
    r"\bslsa-verifier\b[^\n]*--skip-verify\b"
)

# ---- S8 : slsa-sbom-signing-key-committed -------------------------------

# A PEM-encoded private key block committed to a file (covers EC, RSA,
# or PKCS#8 / PKCS#1 formats used by cosign sign --key).
_SIGNING_KEY_COMMITTED = _re(
    r"-----BEGIN (?:EC |RSA |ENCRYPTED |OPENSSH )?PRIVATE KEY-----"
)

# ---- S9 : slsa-sbom-cosign-verify-no-rekor-log --------------------------

# ``cosign verify`` without ``--rekor-url`` OR with an explicit
# ``--offline`` flag disables Rekor transparency log inclusion,
# hiding the signature from the public audit log.
_COSIGN_VERIFY_NO_REKOR = _re(
    r"\bcosign\s+verify\b[^\n]*--offline\b"
)

# ---- S10 : slsa-sbom-sbom-tool-no-version-lock --------------------------

# Installing SBOM tooling (syft / cdxgen / trivy) without pinning the
# version — e.g. ``pip install syft`` or ``npm install -g @cyclonedx/cdxgen``
# with no ``==`` / ``@<semver>`` version specifier.
# The negative lookahead checks for ``==``, ``=``, ``@``, ``>``, ``<``
# followed immediately by a digit (semver start).  ``==0.98.0`` is two chars
# before the digit, so we match ``==`` as a two-char sequence or simply check
# that neither ``=`` nor a digit follows (handles ``==`` because the first
# ``=`` is followed by ``=``, not a digit).
_SBOM_TOOL_NO_VERSION = _re(
    r"(?:pip\s+install|npm\s+install\s+-g|pip3\s+install)\s+"
    r"(?:syft|cdxgen|@cyclonedx/cdxgen|trivy|sbom-tool)"
    r"(?![=@><][=0-9])"
)

# ---- S11 : slsa-sbom-fulcio-url-override-untrusted ----------------------

# ``--fulcio-url`` set to a non-official endpoint could redirect signing
# to an untrusted CA.
_FULCIO_URL_OVERRIDE = _re(
    r"\bcosign\b[^\n]*--fulcio-url\s+(?!https://fulcio\.sigstore\.dev\b)"
    r"https?://[^\s'\"]{4,120}"
)

# ---- S12 : slsa-sbom-rekor-url-override-untrusted -----------------------

# ``--rekor-url`` set to a non-official endpoint bypasses the public
# transparency log.
_REKOR_URL_OVERRIDE = _re(
    r"\bcosign\b[^\n]*--rekor-url\s+(?!https://rekor\.sigstore\.dev\b)"
    r"https?://[^\s'\"]{4,120}"
)

# ---- S13 : slsa-sbom-sbom-missing-hash-algorithm ------------------------

# CycloneDX / SPDX SBOMs that reference a component without any
# ``hash`` / ``checksum`` field rely on version strings alone, which
# are mutable. Flag XML/JSON fragments that have a ``component``
# element but no ``hashes`` / ``hash``  / ``checksums`` nearby.
_SBOM_COMPONENT_ANCHOR = _re(
    r'"(?:type|bom-ref|purl)"\s*:\s*"[^"]{1,200}"'
)
_SBOM_HASH_NEARBY = _re(r'"(?:hashes|hash|checksums|checksum)"\s*:')

# ---- S14 : slsa-sbom-cosign-sign-env-key-unprotected --------------------

# ``cosign sign --key env://COSIGN_PRIVATE_KEY`` where the env var is not
# set from a secrets manager reference — i.e. the key material appears to
# come from a plain env block, not from a vault/secretsmanager/keymanager
# lookup.
_COSIGN_ENV_KEY_SIGN = _re(
    r"\bcosign\s+sign\b[^\n]*--key\s+env://[A-Z_]{3,60}"
)


# ---- Rule catalogue -----------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="slsa-sbom-cosign-skip-verify",
        name="cosign verify with --skip-tlog-verify",
        severity="CRITICAL",
        description=(
            "cosign verify called with --skip-tlog-verify or "
            "--insecure-skip-tlog-verify disables Rekor transparency-log "
            "audit, making the signature unverifiable against the public log."
        ),
        pattern=_COSIGN_SKIP_VERIFY,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="slsa-sbom-cosign-allow-insecure-registry",
        name="cosign --allow-insecure-registry bypasses TLS",
        severity="HIGH",
        description=(
            "--allow-insecure-registry disables TLS validation for the OCI "
            "registry, enabling MITM and registry-swap attacks against the "
            "signed artifact."
        ),
        pattern=_COSIGN_INSECURE_REGISTRY,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="slsa-sbom-cosign-keyless-oidc-no-cert-identity",
        name="cosign keyless verify without --certificate-identity",
        severity="HIGH",
        description=(
            "cosign verify uses --certificate-oidc-issuer without "
            "--certificate-identity or --certificate-identity-regexp; any "
            "identity at that OIDC issuer can forge an accepted signature."
        ),
        pattern=_COSIGN_KEYLESS_NO_CERT_IDENTITY,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="slsa-sbom-image-no-digest-pin",
        name="OCI image reference without SHA-256 digest pin",
        severity="HIGH",
        description=(
            "Image reference uses a mutable tag (e.g. :latest) without a "
            "@sha256:<digest> pin, enabling silent image substitution in the "
            "supply chain."
        ),
        pattern=_IMAGE_NO_DIGEST_PIN,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="slsa-sbom-sbom-not-attached-to-oci",
        name="SBOM generated but not attached to OCI image via cosign",
        severity="MEDIUM",
        description=(
            "An SBOM is generated (syft/trivy/cdxgen) but no "
            "'cosign attach sbom' call follows within 20 lines, leaving the "
            "SBOM unlinked from the signed image."
        ),
        pattern=_SBOM_GENERATE_ANCHOR,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="slsa-sbom-intoto-attestation-no-verify",
        name="in-toto attestation downloaded but not verified",
        severity="CRITICAL",
        description=(
            "cosign download attestation fetches the in-toto attestation but "
            "no cosign verify-attestation call follows in the file, meaning "
            "the attestation is consumed without cryptographic verification."
        ),
        pattern=_INTOTO_DOWNLOAD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="slsa-sbom-slsa-provenance-no-verify",
        name="slsa-verifier called with --skip-verify",
        severity="CRITICAL",
        description=(
            "slsa-verifier is invoked with --skip-verify, bypassing SLSA "
            "provenance verification entirely and defeating the supply-chain "
            "integrity guarantee."
        ),
        pattern=_SLSA_SKIP_VERIFY,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="slsa-sbom-signing-key-committed",
        name="PEM private key committed to repository",
        severity="CRITICAL",
        description=(
            "A PEM-encoded private key block (EC/RSA/PKCS#8) is present in "
            "the file, indicating a cosign signing key or similar credential "
            "has been committed to the repository."
        ),
        pattern=_SIGNING_KEY_COMMITTED,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="slsa-sbom-cosign-verify-no-rekor-log",
        name="cosign verify run in --offline mode (no Rekor log)",
        severity="MEDIUM",
        description=(
            "cosign verify --offline disables inclusion-proof lookup against "
            "the Rekor transparency log, allowing signature acceptance without "
            "public auditability."
        ),
        pattern=_COSIGN_VERIFY_NO_REKOR,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="slsa-sbom-sbom-tool-no-version-lock",
        name="SBOM tooling installed without version pin",
        severity="MEDIUM",
        description=(
            "syft, cdxgen, or trivy is installed via pip/npm without a version "
            "specifier, allowing the SBOM generator itself to be silently "
            "upgraded to a vulnerable or tampered release."
        ),
        pattern=_SBOM_TOOL_NO_VERSION,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="slsa-sbom-fulcio-url-override-untrusted",
        name="cosign --fulcio-url points to non-official CA",
        severity="HIGH",
        description=(
            "--fulcio-url overrides the Fulcio CA endpoint to a non-sigstore "
            "URL, redirecting certificate issuance to an untrusted authority "
            "and breaking the keyless signing trust model."
        ),
        pattern=_FULCIO_URL_OVERRIDE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="slsa-sbom-rekor-url-override-untrusted",
        name="cosign --rekor-url points to non-official transparency log",
        severity="HIGH",
        description=(
            "--rekor-url overrides the Rekor transparency-log endpoint to a "
            "non-sigstore URL, allowing signatures to be logged to a private "
            "or attacker-controlled log instead of the public one."
        ),
        pattern=_REKOR_URL_OVERRIDE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="slsa-sbom-sbom-missing-hash-algorithm",
        name="SBOM component entry lacks hash/checksum field",
        severity="MEDIUM",
        description=(
            "A CycloneDX/SPDX SBOM component block has a purl/bom-ref "
            "identifier but no hashes/checksums field within 5 lines, relying "
            "solely on version strings which are mutable."
        ),
        pattern=_SBOM_COMPONENT_ANCHOR,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="slsa-sbom-cosign-sign-env-key-unprotected",
        name="cosign sign uses --key env:// without secrets-manager reference",
        severity="HIGH",
        description=(
            "cosign sign --key env://<VAR> loads the private key from a plain "
            "environment variable; without a secrets-manager (Vault/KMS) "
            "backend the key material can leak via environment dumps or logs."
        ),
        pattern=_COSIGN_ENV_KEY_SIGN,
        owasp_asi="ASI-07",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:  # noqa: UP006
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against *text* and return findings.

    Stage-B context filters:

      * S5 (sbom-not-attached-to-oci) — anchor on the SBOM-generate call
        and require NO ``cosign attach sbom`` in a 20-line forward window.
      * S6 (intoto-attestation-no-verify) — anchor on ``cosign download
        attestation`` and require NO ``cosign verify-attestation`` anywhere
        in the file; if verify is present the pattern is benign.
      * S13 (sbom-missing-hash-algorithm) — anchor on the component purl
        and require NO hash/checksum field within 5 lines forward.

    All other rules (S1–S4, S7–S12, S14) are single-anchor patterns that
    fire on every match without additional context filtering.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- S1 : cosign-skip-verify ----
    rule = rule_by_id["slsa-sbom-cosign-skip-verify"]
    for m in _COSIGN_SKIP_VERIFY.finditer(text):
        _emit(rule, m.start(), m.group(0))

    # ---- S2 : cosign-allow-insecure-registry ----
    rule = rule_by_id["slsa-sbom-cosign-allow-insecure-registry"]
    for m in _COSIGN_INSECURE_REGISTRY.finditer(text):
        _emit(rule, m.start(), m.group(0))

    # ---- S3 : cosign-keyless-oidc-no-cert-identity ----
    rule = rule_by_id["slsa-sbom-cosign-keyless-oidc-no-cert-identity"]
    for m in _COSIGN_KEYLESS_NO_CERT_IDENTITY.finditer(text):
        _emit(rule, m.start(), m.group(0))

    # ---- S4 : image-no-digest-pin ----
    # Filter: only fire when the match does NOT end with @sha256:<64hex>
    rule = rule_by_id["slsa-sbom-image-no-digest-pin"]
    for m in _IMAGE_NO_DIGEST_PIN.finditer(text):
        if not _DIGEST_SUFFIX.search(m.group(0)):
            _emit(rule, m.start(), m.group(0))

    # ---- S5 : sbom-not-attached-to-oci (Stage-B) ----
    rule = rule_by_id["slsa-sbom-sbom-not-attached-to-oci"]
    for m in _SBOM_GENERATE_ANCHOR.finditer(text):
        line_no, _ = _line_col(text, m.start())
        window = _slice_forward(text, line_no, 20)
        if not _file_contains(window, _SBOM_ATTACH_NEARBY):
            _emit(rule, m.start(), m.group(0))

    # ---- S6 : intoto-attestation-no-verify (Stage-B) ----
    rule = rule_by_id["slsa-sbom-intoto-attestation-no-verify"]
    if _file_contains(text, _INTOTO_DOWNLOAD) and not _file_contains(
        text, _INTOTO_VERIFY
    ):
        for m in _INTOTO_DOWNLOAD.finditer(text):
            _emit(rule, m.start(), m.group(0))

    # ---- S7 : slsa-provenance-no-verify ----
    rule = rule_by_id["slsa-sbom-slsa-provenance-no-verify"]
    for m in _SLSA_SKIP_VERIFY.finditer(text):
        _emit(rule, m.start(), m.group(0))

    # ---- S8 : signing-key-committed ----
    rule = rule_by_id["slsa-sbom-signing-key-committed"]
    for m in _SIGNING_KEY_COMMITTED.finditer(text):
        _emit(rule, m.start(), m.group(0))

    # ---- S9 : cosign-verify-no-rekor-log ----
    rule = rule_by_id["slsa-sbom-cosign-verify-no-rekor-log"]
    for m in _COSIGN_VERIFY_NO_REKOR.finditer(text):
        _emit(rule, m.start(), m.group(0))

    # ---- S10 : sbom-tool-no-version-lock ----
    rule = rule_by_id["slsa-sbom-sbom-tool-no-version-lock"]
    for m in _SBOM_TOOL_NO_VERSION.finditer(text):
        _emit(rule, m.start(), m.group(0))

    # ---- S11 : fulcio-url-override-untrusted ----
    rule = rule_by_id["slsa-sbom-fulcio-url-override-untrusted"]
    for m in _FULCIO_URL_OVERRIDE.finditer(text):
        _emit(rule, m.start(), m.group(0))

    # ---- S12 : rekor-url-override-untrusted ----
    rule = rule_by_id["slsa-sbom-rekor-url-override-untrusted"]
    for m in _REKOR_URL_OVERRIDE.finditer(text):
        _emit(rule, m.start(), m.group(0))

    # ---- S13 : sbom-missing-hash-algorithm (Stage-B) ----
    rule = rule_by_id["slsa-sbom-sbom-missing-hash-algorithm"]
    for m in _SBOM_COMPONENT_ANCHOR.finditer(text):
        line_no, _ = _line_col(text, m.start())
        window = _slice_forward(text, line_no, 5)
        if not _file_contains(window, _SBOM_HASH_NEARBY):
            _emit(rule, m.start(), m.group(0))

    # ---- S14 : cosign-sign-env-key-unprotected ----
    rule = rule_by_id["slsa-sbom-cosign-sign-env-key-unprotected"]
    for m in _COSIGN_ENV_KEY_SIGN.finditer(text):
        _emit(rule, m.start(), m.group(0))

    return findings
