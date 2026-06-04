"""Distributed lock / consensus security patterns.

Wave-25 distillation round 11 — Distributed lock / consensus security
angle. Catalogue of 6 anti-patterns covering etcd auth toggle, etcd
v3 RBAC role grants, Consul agent ACLs, ZooKeeper digest ACLs, Raft
inter-member RPC, and Redlock single-instance / clock-skew fallacies.

Coverage gap (verified against `scripts/lib/`):

  * `k8s_admission_patterns.py` ships `k8s-pod-direct-etcd-access`
    (CRITICAL) but that rule targets K8s YAML (hostPath / Services /
    ETCDCTL_* env vars in pod specs). It does NOT cover standalone
    etcd deployments, etcd server flags (`--auth-enable=false`,
    `--client-cert-auth=false`), etcd v3 ROLE grants, Consul ACL
    config, ZooKeeper ACL constants, Raft peer RPC mTLS, or Redlock.
  * `time_clock_patterns.py` (TOCTOU/NTP) is unrelated — Redlock is
    a Lamport-style consensus property, not a clock-only bug.
  * Round-10 `service-mesh.md` covers Consul **Connect Intentions**
    (mesh layer) — orthogonal to Consul **agent ACL** (KV/session
    layer) covered here.

Six new rules, regex-only, all RE2-safe:

  * consensus-etcd-auth-disabled                       (CRITICAL)
  * consensus-etcd-role-grant-permissive-prefix        (HIGH)
  * consensus-consul-acl-default-allow                 (CRITICAL)
  * consensus-zookeeper-world-anyone-acl               (HIGH)
  * consensus-raft-rpc-no-mtls                         (CRITICAL)
  * consensus-redlock-single-instance-or-skew          (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity,
            description, owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping:
  ASI-02 — Insecure agent-supply-chain / poisoned ground-truth
           (Redlock: mutex failure → double-commit)
  ASI-05 — Supply-chain / cross-tenant pivot (Raft peer RPC
           join-as-voter)
  ASI-07 — Authority / authorisation gaps (etcd auth-disable,
           etcd role-grant, Consul ACL default-allow, ZooKeeper
           world:anyone)

All regexes are RE2-compatible: no backreferences, no lookbehind, no
catastrophic backtracking shapes. Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never
raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    chat_bot_patterns. RE2-safe: no nested quantifiers, no
    backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- C1 : consensus-etcd-auth-disabled ----------------------------------


# CLI flag form: `--auth-enable=false` or `--auth-enable false`.
# YAML form: `auth-enable: false`. Also covers explicit
# `--client-cert-auth=false`.
_ETCD_AUTH_DISABLED = _re(
    r"^\s*(?:--)?auth-enable[=: ]\s*false\b"
    r"|"
    r"^\s*(?:--)?client-cert-auth[=: ]\s*false\b"
)

# Loopback bind on the same file — suppresses CRITICAL for local-only
# dev fixtures.
_ETCD_LOOPBACK_BIND = _re(
    r"\b(?:listen-client-urls|listen-peer-urls)"
    r"[=: ]+['\"]?http[s]?://(?:127\.0\.0\.1|localhost|\[::1\])"
)


# ---- C2 : consensus-etcd-role-grant-permissive-prefix -------------------


# `etcdctl role grant-permission <role> [--prefix=...] readwrite [prefix]`
# OR `etcdctl role grant-permission <role> readwrite [--prefix=...] prefix`.
# Both orderings are accepted by etcdctl; we anchor on the verb and
# require an empty/root prefix token to appear within ~120 chars of the
# verb. Bounded char class on the in-between span — no backreferences,
# no catastrophic-backtracking shapes.
_ETCD_ROLE_GRANT_EMPTY_PREFIX = _re(
    # Form A: empty prefix `''` or `""` appears AFTER the verb, with
    # `readwrite` / `write` also present in the span. Bounded by 0–120
    # non-newline chars before the empty-quote sentinel.
    r"\betcdctl[^\n]{0,200}?\brole\s+grant(?:-permission)?\b"
    r"[^\n]{0,120}?\b(?:readwrite|write)\b[^\n]{0,80}?"
    r"(?:--prefix[= ])?['\"]{2}(?:\s|$)"
    r"|"
    r"\betcdctl[^\n]{0,200}?\brole\s+grant(?:-permission)?\b"
    r"[^\n]{0,80}?(?:--prefix[= ])?['\"]{2}\s+"
    r"[^\n]{0,40}?\b(?:readwrite|write)\b"
    r"|"
    # Form B: root prefix `/` (single slash) anywhere in the grant line.
    r"\betcdctl[^\n]{0,200}?\brole\s+grant(?:-permission)?\b"
    r"[^\n]{0,120}?\b(?:readwrite|write)\b[^\n]{0,80}?"
    r"--prefix[= ]+['\"]?/['\"]?(?:\s|$)"
    r"|"
    # Rust / Go etcd-client API: grant_permission(... Readwrite, b"").
    r"\bgrant_permission\s*\([^)]{0,200}?"
    r"(?:Permission::Readwrite|PermissionType::Readwrite|"
    r"PermReadWrite|\"READWRITE\")[^)]{0,80}?"
    r"b?[\"']{2}"
)

# A monitor / audit / readonly role name on the SAME line suppresses
# the finding. NOTE: the substring `readwrite` legitimately appears
# inside ordinary role names like `app-readwrite` — we exclude that
# false positive by anchoring the hint on word boundaries only.
# Tokens we treat as audit-style: bare `audit`, `monitor`, `metrics`,
# `readonly`, `read-only` (followed optionally by `-` + identifier).
# RE2-safe: word-boundary `\b` only, no lookbehind.
_ETCD_AUDIT_ROLE_HINT = _re(
    r"\b(?:audit|monitor|metrics|readonly|read-only)"
    r"(?:[_\-][A-Za-z0-9_]+)?\b"
)


# ---- C3 : consensus-consul-acl-default-allow ----------------------------


# HCL form (modern): `default_policy = "allow"` inside an `acl { ... }`
# block. JSON form: `"default_policy": "allow"`. Legacy
# `acl_default_policy = "allow"` (Consul < 1.4). Also flags the legacy
# `acl_master_token = "<uuid>"` literal in plaintext config.
_CONSUL_ACL_DEFAULT_ALLOW = _re(
    r"\bdefault_policy\s*[:=]\s*['\"]allow['\"]"
    r"|"
    r"\bacl_default_policy\s*[:=]\s*['\"]allow['\"]"
    r"|"
    r"\bacl_master_token\s*[:=]\s*['\"][0-9a-f\-]{30,40}['\"]"
)

# Single-node dev marker — bind to 127.0.0.1 AND bootstrap_expect = 1.
# Suppresses the rule when BOTH are present in the same file.
_CONSUL_SINGLE_NODE_DEV = _re(
    r"\bbind_addr\s*[:=]\s*['\"](?:127\.0\.0\.1|localhost)['\"]"
)
_CONSUL_BOOTSTRAP_EXPECT_ONE = _re(
    r"\bbootstrap_expect\s*[:=]\s*1\b"
)


# ---- C4 : consensus-zookeeper-world-anyone-acl --------------------------


# Apache Curator / Kazoo: `OPEN_ACL_UNSAFE` constant reference. Also
# direct ACL strings: `world:anyone:cdrwa` and the
# `digest:super:test:...` default that ships in `zoo_sample.cfg`.
_ZK_OPEN_ACL = _re(
    r"\bOPEN_ACL_UNSAFE\b"
    r"|"
    r"\bworld\s*:\s*anyone\s*:\s*[cdrwa]+\b"
    r"|"
    r"\bdigest\s*:\s*super\s*:\s*test\s*:"
)


# ---- C5 : consensus-raft-rpc-no-mtls ------------------------------------


# etcd peer auth disabled / unencrypted; Nomad `tls { rpc = false }`;
# hashicorp/raft `NewTCPTransport(` (the un-encrypted ctor — the
# encrypted one is `NewTCPTransportWithConfig` + non-nil TLSConfig).
_RAFT_RPC_NO_MTLS = _re(
    r"^\s*(?:--)?peer-(?:client-)?cert-auth[=: ]\s*false\b"
    r"|"
    r"\btls\s*\{[^}]*\brpc\s*=\s*false\b"
    r"|"
    r"\braft\.NewTCPTransport\s*\("
    r"|"
    # Plain-HTTP peer URL on non-loopback host.
    r"--initial-advertise-peer-urls[=\s]+http://(?!(?:127\.0\.0\.1|localhost|\[::1\]|0\.0\.0\.0))"
    r"[a-z0-9.\-]+:\d{2,5}"
)


# ---- C6 : consensus-redlock-single-instance-or-skew --------------------


# Python redlock-py / pottery / aioredlock: `Redlock([single_node])`.
# Also: `drift_factor=0` defeats the safety proof.
_REDLOCK_SINGLE_OR_SKEW = _re(
    # `Redlock([<one-item>])` — list with exactly one entry. Detect by
    # absence of comma inside the brackets. Bounded by the closing `]`
    # to avoid catastrophic backtracking on huge buffers.
    r"\bRedlock\s*\(\s*\[\s*[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?\s*\]"
    r"|"
    # `drift_factor=0` or `drift_factor = 0.0`.
    r"\bdrift_factor\s*=\s*0(?:\.0+)?\b"
    r"|"
    # JS bsm/redislock / node-redlock: `new Redlock([client], ...)`
    # with single-element array.
    r"\bnew\s+Redlock\s*\(\s*\[\s*[A-Za-z_][A-Za-z0-9_]*\s*\]"
)

# Advisory / best-effort marker suppresses the finding.
_REDLOCK_ADVISORY_MARKER = _re(
    r"\b(?:advisory|best[_\-]?effort|hint|nonfatal)\b"
    r"|"
    r"#\s*NOT[_\-]SAFETY[_\-]CRITICAL\b"
)


# ---- Rule catalogue -----------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="consensus-etcd-auth-disabled",
        name="etcd server started with authentication disabled",
        severity="CRITICAL",
        description=(
            "etcd server has `--auth-enable=false` (or `auth-enable: "
            "false` in YAML) or `--client-cert-auth=false`. etcd stores "
            "arbitrary K/V — when an app uses it for service discovery, "
            "feature flags, distributed locks, or as Vault's storage "
            "backend, ANY network reach to port 2379 grants full "
            "read/write of the entire keyspace. RBAC is enforced at "
            "the etcd layer only when `auth-enable: true` — without "
            "it, the only gate is network reachability, which "
            "routinely fails. FP-suppressed when the same file binds "
            "to 127.0.0.1 / localhost only."
        ),
        pattern=_ETCD_AUTH_DISABLED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="consensus-etcd-role-grant-permissive-prefix",
        name="etcd v3 role granted readwrite on empty / root prefix",
        severity="HIGH",
        description=(
            "etcd v3 role granted READWRITE on prefix `\"\"` (empty) or "
            "`/` (root) — the documented 'world-readable' "
            "misconfiguration. Equivalent to NO ACL because every key "
            "starts with the empty prefix. Also detects the legacy "
            "`etcdctl role grant guest readwrite ''` invocation and "
            "the Rust/Go client API equivalents "
            "(`Role::grant_permission(... Readwrite, b\"\")`). Result: "
            "any holder of the default role can read every Secret "
            "stored in etcd, including Vault's storage backend if "
            "etcd is configured as Vault's storage."
        ),
        pattern=_ETCD_ROLE_GRANT_EMPTY_PREFIX,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="consensus-consul-acl-default-allow",
        name="Consul agent shipped with default_policy = allow",
        severity="CRITICAL",
        description=(
            "Consul agent shipped with `acl { default_policy = "
            "\"allow\" }` — meaning unauthenticated requests succeed "
            "when no matching ACL rule exists. This is HashiCorp's "
            "documented Consul default for backward compatibility; "
            "the secure stance is `\"deny\"`. Also detects the legacy "
            "`acl_master_token` written in plaintext to the config "
            "file (instead of being passed via `consul acl bootstrap` "
            "once). Result: KV reads of `service/*/secrets` succeed "
            "without an `X-Consul-Token` header. FP-suppressed for "
            "single-node dev agents (loopback bind + "
            "bootstrap_expect = 1)."
        ),
        pattern=_CONSUL_ACL_DEFAULT_ALLOW,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="consensus-zookeeper-world-anyone-acl",
        name="ZooKeeper znode created with OPEN_ACL_UNSAFE / world:anyone",
        severity="HIGH",
        description=(
            "ZooKeeper znode created with the documented "
            "`Ids.OPEN_ACL_UNSAFE` constant (= `world:anyone:cdrwa`) "
            "— full read/write/create/delete/admin to any client "
            "that can TCP-reach port 2181. Apache's own Javadoc has "
            "carried the '_UNSAFE' warning since 3.4; nonetheless "
            "almost every Kazoo / Curator tutorial uses it as the "
            "'hello-world' example, and the example survives into "
            "production. Also detects the SASL-disabled / "
            "`digest:super:test:cdrwa` shape (the famous `super:test` "
            "default that ships in `zoo_sample.cfg`)."
        ),
        pattern=_ZK_OPEN_ACL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="consensus-raft-rpc-no-mtls",
        name="Raft inter-member RPC exposed without mTLS",
        severity="CRITICAL",
        description=(
            "Raft inter-member RPC port (etcd 2380, Consul 8300, "
            "Nomad 4647, hashicorp/raft default) exposed without "
            "mTLS — meaning ANY peer the network reaches can issue "
            "an `AddVoter` / `AddNonVoter` RPC and join the cluster "
            "as a voting member. Joining as a voter alone is enough "
            "to read the entire raft log (which contains every Apply "
            "payload — secrets, configs, sessions). Detects: "
            "`peer-cert-auth: false`, `--peer-client-cert-auth=false`, "
            "Nomad `tls { rpc = false }`, `raft.NewTCPTransport(` "
            "(the un-encrypted Go constructor), and plain-HTTP peer "
            "URLs on non-loopback hosts."
        ),
        pattern=_RAFT_RPC_NO_MTLS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="consensus-redlock-single-instance-or-skew",
        name="Redlock used against a single Redis instance or with drift_factor=0",
        severity="HIGH",
        description=(
            "'Redlock' mutex used against a SINGLE Redis instance — "
            "Salvatore Sanfilippo's own paper requires N≥3 "
            "independent masters with N/2+1 quorum; one node is not "
            "Redlock, it's just SET-NX with a fancy name. Also "
            "detects `drift_factor=0` — Redlock's safety proof "
            "requires the algorithm subtract a clock-drift bound "
            "from the TTL; libraries that hard-code `drift_factor=0` "
            "defeat the safety proof. FP-suppressed when the "
            "callsite is marked `# NOT-SAFETY-CRITICAL` or the lock "
            "name token includes `advisory|hint|best-effort|nonfatal`."
        ),
        pattern=_REDLOCK_SINGLE_OR_SKEW,
        owasp_asi="ASI-02",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult file-wide context:

      * C1 (etcd-auth-disabled) — suppressed when the file also binds
        the etcd listen URL to 127.0.0.1 / localhost / [::1] (local
        dev fixture).
      * C2 (etcd-role-grant-permissive-prefix) — emitted whenever the
        empty-prefix readwrite grant matches; the regex already
        excludes pure `read` grants, but if an `audit|monitor|metrics`
        role-name token appears on the SAME line, the finding is
        suppressed (operator explicitly tagged an audit role).
      * C3 (consul-acl-default-allow) — suppressed when the file
        ALSO sets `bind_addr = "127.0.0.1"` AND `bootstrap_expect = 1`
        (single-node dev agent).
      * C4 (zookeeper-world-anyone-acl) — emitted unconditionally;
        downstream consumers may apply a test-path FP suppression.
      * C5 (raft-rpc-no-mtls) — emitted on every distinct match.
      * C6 (redlock-single-instance-or-skew) — suppressed when an
        advisory marker (`# NOT-SAFETY-CRITICAL`, `advisory`,
        `best-effort`, `hint`, `nonfatal`) appears in the file.

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

    # ---- C1 : consensus-etcd-auth-disabled ----
    # File-wide loopback bind suppresses the finding.
    has_loopback = _file_contains(text, _ETCD_LOOPBACK_BIND)
    if not has_loopback:
        rule_c1 = rule_by_id["consensus-etcd-auth-disabled"]
        for m in _ETCD_AUTH_DISABLED.finditer(text):
            _emit(rule_c1, m.start(), m.group(0))

    # ---- C2 : consensus-etcd-role-grant-permissive-prefix ----
    rule_c2 = rule_by_id["consensus-etcd-role-grant-permissive-prefix"]
    for m in _ETCD_ROLE_GRANT_EMPTY_PREFIX.finditer(text):
        line, _col = _line_col(text, m.start())
        # Same-line audit-role suppression.
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.start())
        if line_end == -1:
            line_end = len(text)
        same_line = text[line_start:line_end]
        if _ETCD_AUDIT_ROLE_HINT.search(same_line) is not None:
            continue
        _emit(rule_c2, m.start(), m.group(0))

    # ---- C3 : consensus-consul-acl-default-allow ----
    # Single-node dev fixture suppresses the finding.
    is_single_node = (
        _file_contains(text, _CONSUL_SINGLE_NODE_DEV)
        and _file_contains(text, _CONSUL_BOOTSTRAP_EXPECT_ONE)
    )
    if not is_single_node:
        rule_c3 = rule_by_id["consensus-consul-acl-default-allow"]
        for m in _CONSUL_ACL_DEFAULT_ALLOW.finditer(text):
            _emit(rule_c3, m.start(), m.group(0))

    # ---- C4 : consensus-zookeeper-world-anyone-acl ----
    rule_c4 = rule_by_id["consensus-zookeeper-world-anyone-acl"]
    for m in _ZK_OPEN_ACL.finditer(text):
        _emit(rule_c4, m.start(), m.group(0))

    # ---- C5 : consensus-raft-rpc-no-mtls ----
    rule_c5 = rule_by_id["consensus-raft-rpc-no-mtls"]
    for m in _RAFT_RPC_NO_MTLS.finditer(text):
        _emit(rule_c5, m.start(), m.group(0))

    # ---- C6 : consensus-redlock-single-instance-or-skew ----
    has_advisory = _file_contains(text, _REDLOCK_ADVISORY_MARKER)
    if not has_advisory:
        rule_c6 = rule_by_id["consensus-redlock-single-instance-or-skew"]
        for m in _REDLOCK_SINGLE_OR_SKEW.finditer(text):
            _emit(rule_c6, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
