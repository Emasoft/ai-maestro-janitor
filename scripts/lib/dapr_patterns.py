"""Dapr sidecar / Distributed Application Runtime misconfig patterns.

Wave-37 distillation round 23 — k8s/service-mesh group.

Targets Dapr Component, Configuration, and Subscription YAML plus Dapr
sidecar pod annotations / env blocks. Distinct attack surface from the
Istio/k8s-RBAC siblings: this catches Dapr's own access-control,
app-channel TLS, secret-store, pubsub-scope, tracing, API-token, input
binding, and actor-placement defaults.

Reference proposal: `reports/distill-round-23/dapr-sidecar.md`.

Several rules are two-pass (anchor regex + plain-string absence check on
the captured block — RE2-safe, no negative lookahead): pattern 2
(appPort without appProtocol https/grpcs) and pattern 7 (input binding
without a sender restriction).

Rule inventory (8 rules):

  1.  dapr-access-control-default-allow       (HIGH)
  2.  dapr-app-channel-no-tls                  (MEDIUM)
  3.  dapr-secrets-file-baked-path            (MEDIUM)
  4.  dapr-pubsub-subscription-no-scope       (MEDIUM)
  5.  dapr-tracing-full-sampling              (LOW)
  6.  dapr-api-token-static                    (HIGH)
  7.  dapr-input-binding-no-sender-restriction (HIGH)
  8.  dapr-placement-non-loopback             (HIGH)

Public surface mirrors sibling modules:

  * Finding / Rule NamedTuples, RULES tuple,
    scan_text(text, *, file_kind="auto", file_path="") -> list[Finding],
    scan_dapr(text, *, file_path="") -> list[Finding].

OWASP ASI mapping:
  ASI-05 — Cross-tenant pivot / exposure (placement on routable iface,
                                          secrets baked into image).
  ASI-07 — Authority / authorisation gaps (default-allow access control,
                                           static API token, open input
                                           binding, unscoped pubsub).
  ASI-08 — Sensitive-data exposure        (plaintext app channel, full
                                           trace sampling).
"""

from __future__ import annotations

import re
from typing import Callable, NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as the sibling pattern modules."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """Static rule metadata."""

    id: str
    name: str
    severity: str
    description: str
    owasp_asi: str


def _re(pattern: str) -> re.Pattern[str]:
    """Compile a pattern with IGNORECASE.

    RE2-safe: bounded quantifiers, no backreferences, no lookaround.
    `(?s)` dot-all and `(?m)` multiline are applied inline per-pattern.
    """
    return re.compile(pattern, re.IGNORECASE)


# ---- Rule metadata ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="dapr-access-control-default-allow",
        name="accessControl defaultAction: allow",
        severity="HIGH",
        description=(
            "Dapr's default-deny access-control model is the safe "
            "baseline. defaultAction: allow lets any compromised sidecar "
            "in the namespace invoke privileged operations without being "
            "listed in any policy block."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="dapr-app-channel-no-tls",
        name="appPort without appProtocol https/grpcs",
        severity="MEDIUM",
        description=(
            "The sidecar-to-app channel is the last hop before secret "
            "values and event payloads reach application code. Without "
            "appProtocol https/grpcs it travels plaintext and any process "
            "on the pod network can intercept or inject."
        ),
        owasp_asi="ASI-08",
    ),
    Rule(
        id="dapr-secrets-file-baked-path",
        name="secretsFile path baked into component YAML",
        severity="MEDIUM",
        description=(
            "A static secretsFile path points at a file baked into the "
            "image layer or committed to the repo — visible in docker "
            "history / image manifests and shipped with the image."
        ),
        owasp_asi="ASI-05",
    ),
    Rule(
        id="dapr-pubsub-subscription-no-scope",
        name="pubsub Subscription without subscriptionScopes",
        severity="MEDIUM",
        description=(
            "Without subscriptionScopes any app in the namespace can "
            "publish to or consume from the topic — a rogue app can "
            "inject into a privileged topic or drain a specific "
            "consumer's messages."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="dapr-tracing-full-sampling",
        name="tracing samplingRate \"1\" (100%)",
        severity="LOW",
        description=(
            "samplingRate \"1\" forwards every request body, header, and "
            "correlation id to the tracing exporter. In GDPR/HIPAA "
            "environments this is a data leak by default."
        ),
        owasp_asi="ASI-08",
    ),
    Rule(
        id="dapr-api-token-static",
        name="static Dapr API token (env or annotation)",
        severity="HIGH",
        description=(
            "API-token auth is a long-lived bearer credential with full "
            "sidecar API access. In env/annotation form a single "
            "`kubectl describe pod` leaks it to anyone with namespace "
            "read access; mTLS is the preferred mechanism."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="dapr-input-binding-no-sender-restriction",
        name="input binding without sender restriction",
        severity="HIGH",
        description=(
            "An input binding invokes the app's /binding/<name> endpoint. "
            "Without allowedOrigins / verifyPayload an attacker who can "
            "reach the sidecar HTTP port (3500) can trigger arbitrary "
            "binding invocations."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="dapr-placement-non-loopback",
        name="placementHostAddress on a non-loopback address",
        severity="HIGH",
        description=(
            "The placement service controls which host owns a given actor "
            "id. Reachable from outside the node, an attacker can register "
            "a rogue host for an actor id and hijack its state and method "
            "calls."
        ),
        owasp_asi="ASI-05",
    ),
)


# ---- Regex constants (RE2-safe, bounded) --------------------------------
#
# Line-anchored patterns carry an inline `(?m)` because the module `_re`
# does NOT force MULTILINE (it leaves flags per-pattern so `(?s)` dot-all
# rules and `^`-anchored line rules can coexist). Without `(?m)` the `^`
# would only match the very start of the file.


# Rule 1 — accessControl defaultAction: allow.
_DEFAULT_ACTION_ALLOW = _re(
    r"(?m)^\s*defaultAction:\s+allow\b"
)

# Rule 2 — appPort declared (absence of appProtocol https/grpcs checked
# separately, per-block, two-pass).
_APP_PORT = _re(
    r"(?m)^\s*appPort:\s+\d{1,5}\b"
)
_APP_PROTOCOL_TLS = _re(
    r"(?m)^\s*appProtocol:\s+(?:https|grpcs)\b"
)

# Rule 3 — secretsFile path baked in.
_SECRETS_FILE = _re(
    r"(?m)^\s*secretsFile:\s+\S[^\n]{0,300}"
)

# Rule 4 — pubsub Subscription with a topic (scope absence two-pass).
_SUBSCRIPTION_TOPIC = _re(
    r"(?s)kind:\s+Subscription\b.{0,400}?topic:\s+\S+"
)

# Rule 5 — full trace sampling.
_FULL_SAMPLING = _re(
    r"(?m)^\s*samplingRate:\s+\"1\"\s*$"
)

# Rule 6 — static API token (env var name or annotation form).
_API_TOKEN_ENV = _re(
    r"\bDAPR_API_TOKEN\b"
)
_API_TOKEN_ANNOTATION = _re(
    r"dapr\.io/(?:api-token-secret|app-token-secret):\s+\S+"
)

# Rule 7 — input binding (sender-restriction absence two-pass).
_INPUT_DIRECTION = _re(
    r"(?m)^\s*direction:\s+input\b"
)

# Rule 8 — placementHostAddress on a non-loopback host. Anchor on the key
# then exclude loopback in code (RE2-safe; no negative lookahead).
_PLACEMENT_HOST = _re(
    r"(?m)^\s*placementHostAddress:\s+(\S+)"
)

_DOC_SPLIT = re.compile(r"^---\s*$", re.MULTILINE)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert string offset → (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _trunc(s: str, n: int = 200) -> str:
    """Truncate matched_text for reporting."""
    return s if len(s) <= n else s[:n] + "…"


def _rule(rule_id: str) -> Rule:
    """Lookup a Rule by id. Raises KeyError if missing (programmer error)."""
    for r in RULES:
        if r.id == rule_id:
            return r
    raise KeyError(rule_id)


def _emit(
    rule_id: str,
    text: str,
    match: re.Match[str],
    findings: list[Finding],
    *,
    severity: str | None = None,
) -> None:
    """Append a Finding for `match` using `rule_id`'s metadata."""
    rule = _rule(rule_id)
    line, col = _line_col(text, match.start())
    findings.append(
        Finding(
            rule_id=rule_id,
            line=line,
            column=col,
            matched_text=_trunc(match.group(0).strip()),
            severity=severity or rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        )
    )


_LOOPBACK_HOSTS: tuple[str, ...] = ("127.0.0.1", "localhost", "::1", "[::1]")


def _is_loopback(host: str) -> bool:
    """True when `host` (possibly `host:port`) is a loopback address."""
    bare = host.strip().strip("\"'")
    # Strip a trailing :port (but keep IPv6 brackets handled above).
    if bare.startswith("[") and "]" in bare:
        bare = bare[: bare.index("]") + 1]
    elif bare.count(":") == 1:
        bare = bare.split(":", 1)[0]
    return bare in _LOOPBACK_HOSTS


# ---- Scanners -----------------------------------------------------------


def _scan_simple(
    text: str,
    findings: list[Finding],
    rule_id: str,
    pattern: re.Pattern[str],
) -> None:
    """Emit one Finding per non-overlapping match of `pattern`."""
    for m in pattern.finditer(text):
        _emit(rule_id, text, m, findings)


def _scan_default_action_allow(text: str, findings: list[Finding]) -> None:
    """Rule 1 — accessControl defaultAction: allow."""
    _scan_simple(text, findings, "dapr-access-control-default-allow", _DEFAULT_ACTION_ALLOW)


def _scan_app_channel_no_tls(text: str, findings: list[Finding]) -> None:
    """Rule 2 — appPort with no appProtocol https/grpcs (file-wide absence)."""
    if _APP_PROTOCOL_TLS.search(text) is not None:
        return
    _scan_simple(text, findings, "dapr-app-channel-no-tls", _APP_PORT)


def _scan_secrets_file(text: str, findings: list[Finding]) -> None:
    """Rule 3 — secretsFile path baked into component YAML."""
    _scan_simple(text, findings, "dapr-secrets-file-baked-path", _SECRETS_FILE)


def _scan_subscription_no_scope(text: str, findings: list[Finding]) -> None:
    """Rule 4 — Subscription topic without subscriptionScopes (per-doc)."""
    for m in _SUBSCRIPTION_TOPIC.finditer(text):
        # The non-greedy anchor regex stops at the first `topic:`, so the
        # `subscriptionScopes:` key (which may appear before OR after the
        # topic) must be checked against the whole enclosing document.
        if "subscriptionScopes" in _doc_for_offset(text, m.start()):
            continue
        _emit("dapr-pubsub-subscription-no-scope", text, m, findings)


def _scan_full_sampling(text: str, findings: list[Finding]) -> None:
    """Rule 5 — samplingRate \"1\"."""
    _scan_simple(text, findings, "dapr-tracing-full-sampling", _FULL_SAMPLING)


def _scan_api_token(text: str, findings: list[Finding]) -> None:
    """Rule 6 — static Dapr API token (env or annotation)."""
    for m in _API_TOKEN_ENV.finditer(text):
        _emit("dapr-api-token-static", text, m, findings)
    for m in _API_TOKEN_ANNOTATION.finditer(text):
        _emit("dapr-api-token-static", text, m, findings)


def _scan_input_binding(text: str, findings: list[Finding]) -> None:
    """Rule 7 — input binding without a sender restriction (per-doc absence)."""
    restriction_keys = ("allowedOrigins", "verifyPayload", "allowedSenders")
    for offset, doc in _docs_with_offsets(text):
        m = _INPUT_DIRECTION.search(doc)
        if m is None:
            continue
        if any(key in doc for key in restriction_keys):
            continue
        _emit(
            "dapr-input-binding-no-sender-restriction",
            text,
            _shift_match(text, offset, _INPUT_DIRECTION, m),
            findings,
        )


def _scan_placement(text: str, findings: list[Finding]) -> None:
    """Rule 8 — placementHostAddress on a non-loopback host."""
    for m in _PLACEMENT_HOST.finditer(text):
        if _is_loopback(m.group(1)):
            continue
        _emit("dapr-placement-non-loopback", text, m, findings)


def _docs_with_offsets(text: str) -> list[tuple[int, str]]:
    """Split a multi-doc YAML stream into (absolute_offset, doc_text)."""
    docs: list[tuple[int, str]] = []
    last = 0
    for m in _DOC_SPLIT.finditer(text):
        docs.append((last, text[last : m.start()]))
        last = m.end()
    docs.append((last, text[last:]))
    return docs


def _doc_for_offset(text: str, offset: int) -> str:
    """Return the single YAML document containing `offset`."""
    for start, doc in _docs_with_offsets(text):
        if start <= offset < start + len(doc) + 1:
            return doc
    return text


def _shift_match(
    text: str,
    offset: int,
    pattern: re.Pattern[str],
    fallback: re.Match[str],
) -> re.Match[str]:
    """Re-find `pattern` in full `text` at/after `offset` for true coords."""
    abs_match = pattern.search(text, offset)
    return abs_match if abs_match is not None else fallback


_SCANNERS: tuple[Callable[[str, list[Finding]], None], ...] = (
    _scan_default_action_allow,
    _scan_app_channel_no_tls,
    _scan_secrets_file,
    _scan_subscription_no_scope,
    _scan_full_sampling,
    _scan_api_token,
    _scan_input_binding,
    _scan_placement,
)


def scan_dapr(text: str, *, file_path: str = "") -> list[Finding]:
    """Apply every Dapr rule to a Dapr YAML / sidecar-annotation file."""
    _ = file_path
    findings: list[Finding] = []
    for scan in _SCANNERS:
        scan(text, findings)
    return findings


def scan_text(
    text: str,
    *,
    file_kind: str = "auto",
    file_path: str = "",
) -> list[Finding]:
    """Top-level dispatcher.

    file_kind: "auto" or "dapr". Findings come out sorted by
    (line, column, rule_id) and deduped on
    (rule_id, line, column, matched_text).
    """
    if not text:
        return []
    _ = file_kind
    findings = scan_dapr(text, file_path=file_path)

    seen: set[tuple[str, int, int, str]] = set()
    deduped: list[Finding] = []
    for f in findings:
        key = (f.rule_id, f.line, f.column, f.matched_text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    deduped.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return deduped
