"""SPIFFE / SPIRE workload-identity misuse patterns.

Wave-37 distillation round 23 — workload-identity / Apple group.

Targets SPIRE Server / Agent HCL/JSON configs and workload entry
definitions for misconfigurations that allow identity spoofing, CA
compromise, lateral movement, or workload impersonation. The corpus is
SPIRE `*.hcl` / `*.conf` / `*.json` (e.g. `server.conf`, `agent.conf`,
`entries.json`, federation config).

Reference proposal: `reports/distill-round-23/spiffe-spire.md`.

Rule inventory (10 rules):

  1.  spiffe-jwt-svid-wildcard-audience        (CRITICAL)
  2.  spiffe-x509-svid-ttl-excessive           (HIGH)
  3.  spiffe-agent-socket-world-readable        (HIGH)
  4.  spiffe-trust-domain-public-dns            (HIGH)
  5.  spiffe-federation-bundle-endpoint-unpinned (HIGH)
  6.  spiffe-node-attestor-join-token-long-ttl  (HIGH)
  7.  spiffe-unix-attestor-no-sha256            (MEDIUM)
  8.  spiffe-upstream-authority-disk-cleartext  (CRITICAL)
  9.  spiffe-parent-id-chain-too-deep           (MEDIUM)
  10. spiffe-oidc-discovery-provider-block       (MEDIUM)

Public surface mirrors `scripts/lib/cloud_credential_patterns.py`:

  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.
  * Rule(id, name, severity, description, pattern, owasp_asi) — frozen
            NamedTuple; the regex is PRE-COMPILED at module load.
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]

Every regex is RE2-safe: no lookahead / lookbehind / backreferences.
The proposal's lookahead-based "absence of sibling key" variants are
deliberately replaced with the simpler positive-match alternatives the
proposal itself offers — these are advisory flags ("verify pinning /
verify single-use") rather than precise absence assertions, which is
how an RE2 engine must treat them.

OWASP ASI mapping:
  ASI-05 — Supply-chain / cross-tenant pivot (federation bundle MITM,
                                              deep delegation chains).
  ASI-07 — Authority / authorisation gaps    (wildcard audience, CA in
                                              cleartext, long-lived join
                                              token, world-readable
                                              Workload API socket, weak
                                              unix attestation).
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    `scripts/lib/cloud_credential_patterns.Finding` so heartbeat
    detectors render either kind uniformly."""

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
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE.

    SPIRE HCL is ASCII-by-convention. Every alternation branch is
    bounded — RE2 safe (no backreferences, no lookarounds).
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


# ---- Rule 1: JWT-SVID wildcard audience ---------------------------------
# `audience = ["*"]` is accepted by any relying party — token-relay.
_JWT_WILDCARD_AUDIENCE = _re(r'audience\s*=\s*\[\s*"\*"\s*\]')


# ---- Rule 2: X.509-SVID TTL exceeding 24h on workload entries -----------
# A long TTL means a compromised cert stays valid long past detection.
# The simpler "any value >= 24h expressed in hours" form (>= 20h here so
# the two-digit branch covers the 24h boundary cleanly): a two-digit hour
# value 20-99 or any 3+-digit hour value. RE2-safe — bounded alternation.
_X509_TTL_EXCESSIVE = _re(r'x509_svid_ttl\s*=\s*"(?:[2-9][0-9]|[1-9][0-9]{2,})h"')


# ---- Rule 3: SPIRE Agent socket in world-writable /tmp ------------------
# A socket under /tmp is the canonical insecure default — any local
# process can call the Workload API and impersonate registered workloads.
_AGENT_SOCKET_TMP = _re(r'socket_path\s*=\s*"/tmp/[^"]+"')


# ---- Rule 4: trust_domain matching attacker-controllable public DNS -----
# Public multi-label hostname (not an internal `.cluster.local` / `.internal`
# zone): if an adversary gains DNS control they can stand up a rogue SPIRE
# Server for that trust domain and mint SVIDs every agent accepts.
_TRUST_DOMAIN_PUBLIC = _re(
    r'trust_domain\s*=\s*"[a-z0-9-]+\.[a-z0-9-]+\.'
    r'(?:com|net|org|io|dev|cloud|app)"'
)


# ---- Rule 5: federation bundle endpoint with no cert pinning ------------
# Any federation block referencing a remote bundle_endpoint_url over the
# network must pin the endpoint (endpoint_spiffe_id / bundle_endpoint_profile
# / use_web_pki). RE2 cannot assert "sibling key absent", so every
# bundle_endpoint_url is flagged for manual pinning verification.
_FEDERATION_BUNDLE_ENDPOINT = _re(
    r'bundle_endpoint_url\s*=\s*"https?://[^"]+"'
)


# ---- Rule 6: node attestor join_token with long-lived / reusable TTL ----
# join_token attestation is bootstrap-only; a long-lived TTL lets any node
# that obtains the (leaked) token attest and register arbitrary workloads.
# Flag a ttl of 1000+ seconds/minutes/hours, or any value in days/weeks.
_JOIN_TOKEN_LONG_TTL = _re(
    r'ttl\s*=\s*"(?:[1-9][0-9]{3,}[smh]|[1-9][0-9]*[dw])"'
)


# ---- Rule 7: unix workload attestor without sha256 binary check ---------
# The unix attestor identifies workloads by UID/GID/PID; without a
# sha256 binary hash selector any process running as the target UID can
# claim the SVID (process substitution / LD_PRELOAD). We flag the plugin
# declaration; the operator confirms a `unix:sha256:` selector exists.
# SPIRE configs declare the plugin two ways: the HCL block-label form
# `WorkloadAttestor "unix" {` and the JSON/keyed form `plugin_name = "unix"`.
_UNIX_ATTESTOR = _re(
    r'WorkloadAttestor\s+"unix"\s*\{|plugin_name\s*=\s*"unix"'
)


# ---- Rule 8: UpstreamAuthority "disk" stores CA key in cleartext --------
# When UpstreamAuthority "disk" is configured, the CA private key lives in
# a plaintext PEM on disk — read access == sign-anything for the whole
# trust domain.
_UPSTREAM_AUTHORITY_DISK = _re(r'UpstreamAuthority\s+"disk"\s*\{')


# ---- Rule 9: parent_id delegation chain deeper than 3 levels ------------
# parent_id forms a delegation chain; chains deeper than 3 levels mean a
# single compromised node can register entries for a large subtree,
# amplifying lateral movement. 4+ path segments after spiffe://domain.
_PARENT_ID_DEEP_CHAIN = _re(
    r'parent_id\s*=\s*"spiffe://[^/]+(?:/[^/"]+){4,}"'
)


# ---- Rule 10: OIDC discovery provider block present ---------------------
# An OIDCProvider / oidc_discovery_provider block is what lets external
# relying parties validate JWT-SVIDs with standard OIDC tooling. RE2
# cannot assert its ABSENCE, so we surface every OIDCProvider stanza for
# review of its issuer + JWKS configuration.
_OIDC_PROVIDER_BLOCK = _re(r'OIDCProvider\s*\{')


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="spiffe-jwt-svid-wildcard-audience",
        name="JWT-SVID wildcard audience",
        severity="CRITICAL",
        description=(
            "JWT-SVID configured with `audience = [\"*\"]` is accepted by "
            "any relying party in the mesh, eliminating audience binding "
            "and enabling token-relay attacks: a JWT intercepted from one "
            "service can be replayed against every other. Set an explicit "
            "audience list per relying party."
        ),
        pattern=_JWT_WILDCARD_AUDIENCE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="spiffe-x509-svid-ttl-excessive",
        name="X.509-SVID TTL exceeding 24 hours",
        severity="HIGH",
        description=(
            "Workload `x509_svid_ttl` is >= 24h. A long TTL means a "
            "compromised workload certificate stays valid long after the "
            "compromise is detected. SPIRE guidance is 1h or less for "
            "workload SVIDs."
        ),
        pattern=_X509_TTL_EXCESSIVE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="spiffe-agent-socket-world-readable",
        name="SPIRE Agent Workload-API socket under /tmp",
        severity="HIGH",
        description=(
            "SPIRE Agent `socket_path` points into world-writable `/tmp`. "
            "Any local process can then call the Workload API, obtain SVIDs "
            "for any registered selector, and impersonate services. Place "
            "the socket in a directory with restrictive permissions and set "
            "`socket_permission` / a hardening umask."
        ),
        pattern=_AGENT_SOCKET_TMP,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="spiffe-trust-domain-public-dns",
        name="trust_domain set to attacker-controllable public DNS",
        severity="HIGH",
        description=(
            "`trust_domain` is a public multi-label hostname (e.g. a "
            "`.com`/`.io`/`.cloud` zone) rather than an internal zone "
            "(`.cluster.local` / `.internal`). An adversary who gains DNS "
            "control over that name can stand up a rogue SPIRE Server for "
            "the trust domain and issue SVIDs every agent will accept. "
            "Manual review required."
        ),
        pattern=_TRUST_DOMAIN_PUBLIC,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="spiffe-federation-bundle-endpoint-unpinned",
        name="Federation bundle endpoint without cert pinning",
        severity="HIGH",
        description=(
            "Federation references a remote `bundle_endpoint_url` over the "
            "network. Without pinning (`endpoint_spiffe_id` / "
            "`bundle_endpoint_profile` / `use_web_pki`), MITM or DNS "
            "hijacking can substitute a malicious trust bundle, expanding "
            "the trust domain to attacker-controlled workloads. Verify the "
            "pinning stanza is present."
        ),
        pattern=_FEDERATION_BUNDLE_ENDPOINT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="spiffe-node-attestor-join-token-long-ttl",
        name="join_token node attestation with long-lived / reusable TTL",
        severity="HIGH",
        description=(
            "A `join_token` TTL measured in days/weeks (or 1000+ "
            "seconds/minutes/hours) makes the bootstrap token long-lived "
            "and effectively reusable. Anything that obtains it (a leaked "
            "CI secret, a compromised node) can attest, receive a node "
            "SVID, and register arbitrary workload entries. Keep join "
            "tokens single-use with a short TTL."
        ),
        pattern=_JOIN_TOKEN_LONG_TTL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="spiffe-unix-attestor-no-sha256",
        name="unix workload attestor without sha256 binary check",
        severity="MEDIUM",
        description=(
            "The `unix` workload attestor identifies workloads by "
            "UID/GID/PID. Without a `unix:sha256:` binary-hash selector, "
            "any process running as the target UID can claim the workload's "
            "SVID (process substitution / LD_PRELOAD). Add a sha256 "
            "selector to the workload entry."
        ),
        pattern=_UNIX_ATTESTOR,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="spiffe-upstream-authority-disk-cleartext",
        name="UpstreamAuthority disk storing CA key in cleartext",
        severity="CRITICAL",
        description=(
            "`UpstreamAuthority \"disk\"` keeps the CA private key in a "
            "plaintext PEM file on disk. Any process with read access to "
            "that file can sign arbitrary SVIDs for the entire trust "
            "domain. Prefer an HSM / KMS-backed upstream authority and "
            "restrict the key file's permissions."
        ),
        pattern=_UPSTREAM_AUTHORITY_DISK,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="spiffe-parent-id-chain-too-deep",
        name="Workload parent_id delegation chain deeper than 3 levels",
        severity="MEDIUM",
        description=(
            "A workload entry `parent_id` with 4+ path segments forms a "
            "deep delegation chain. A single compromised node/workload high "
            "in the chain can register entries for a large downstream "
            "subtree, amplifying lateral movement. Flatten the delegation "
            "hierarchy."
        ),
        pattern=_PARENT_ID_DEEP_CHAIN,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="spiffe-oidc-discovery-provider-block",
        name="OIDC discovery provider block (verify issuer / JWKS)",
        severity="MEDIUM",
        description=(
            "An `OIDCProvider` stanza configures how external relying "
            "parties validate JWT-SVIDs. Verify its issuer and JWKS "
            "settings: a missing or misconfigured discovery provider drives "
            "operators toward accepting unverified JWTs or disabling "
            "audience checks, creating implicit trust-escalation paths."
        ),
        pattern=_OIDC_PROVIDER_BLOCK,
        owasp_asi="ASI-07",
    ),
)


# ---- The composed scanner -----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return findings.

    Findings are deduped by (rule_id, line, col) and sorted by
    (line, column, rule_id).
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line,
                    column=col,
                    matched_text=matched,
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
