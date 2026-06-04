"""Browser ServiceWorker / SharedWorker / Web Worker security patterns.

Wave-31 distillation round 17, angle service-worker.

Catalogue of 6 ServiceWorker-specific anti-patterns distilled in
`reports/distill-round-17/service-worker.md`. Targets Service Workers,
Shared Workers, and Dedicated Workers in browser JavaScript / TypeScript.

What is NOT here (already shipped — DO NOT duplicate):

  * IndexedDB / Cache API storage patterns — `browser_storage_patterns.py`
    (Wave 30).
  * iframe postMessage origin checks — `js_deserialization_patterns.py`.
  * Browser extension content-script patterns —
    `browser_extension_patterns.py`.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * sw-scope-no-scope-arg                     (HIGH)
  * sw-import-scripts-dynamic-url             (CRITICAL)
  * sw-push-handler-exfil                     (HIGH)
  * sw-clients-claim-no-guard                 (HIGH)
  * sw-worker-from-variable-url               (HIGH)
  * sw-cache-put-no-status-check              (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret / credential leak (push endpoint exfiltration)
  ASI-05 — Supply-chain / cross-tenant pivot (scope hijack, importScripts
                                               supply chain, worker URL
                                               injection)
  ASI-07 — Authority / authorisation gaps (clients.claim race, unchecked
                                            cache.put locking user out)

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


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- SW-001 : sw-scope-no-scope-arg ------------------------------------

# Matches navigator.serviceWorker.register('...') or ("...") with NO
# second argument (no comma after the URL).  Stops at the closing
# parenthesis to avoid false matches when a scope option IS supplied.
_SW_REGISTER_NO_SCOPE = _re(
    r"navigator\.serviceWorker\.register\s*\(\s*[\"'][^\"']*[\"']\s*\)"
)

# ---- SW-002 : sw-import-scripts-dynamic-url ----------------------------

# Matches importScripts(...) where the argument uses string concatenation.
_SW_IMPORT_SCRIPTS_CONCAT = _re(
    r"importScripts\s*\(\s*[^)]*\+[^)]*\)"
)

# Matches importScripts(`...${...`) — template literal with interpolation.
_SW_IMPORT_SCRIPTS_TEMPLATE = _re(
    r"importScripts\s*\(\s*`[^`]*\$\{"
)

# ---- SW-003 : sw-push-handler-exfil ------------------------------------

# Matches addEventListener('pushsubscriptionchange', ...) — the subscription
# rotation event that is under-reviewed and commonly leaks the new endpoint.
_SW_PUSHSUBSCRIPTIONCHANGE = _re(
    r"addEventListener\s*\(\s*[\"']pushsubscriptionchange[\"']"
)

# ---- SW-004 : sw-clients-claim-no-guard --------------------------------

# Matches self.clients.claim() — direct form.
_SW_CLIENTS_CLAIM = _re(
    r"self\.clients\.claim\s*\(\s*\)"
)

# Matches the Workbox helper form clientsClaim().
_SW_WORKBOX_CLIENTS_CLAIM = _re(
    r"\bclientsClaim\s*\(\s*\)"
)

# ---- SW-005 : sw-worker-from-variable-url ------------------------------

# Matches new Worker(variable) or new SharedWorker(variable) where the
# first argument is a JavaScript identifier (variable), not a string
# literal or import.meta.url.  The negative case (string literal) is
# excluded by the character class: identifiers start with [a-zA-Z_$]
# which doesn't match quotes.
_SW_WORKER_VAR_URL = _re(
    r"new\s+(?:Shared)?Worker\s*\(\s*[a-zA-Z_$][a-zA-Z0-9_$.]*"
)

# Blob-URL worker: new Worker(URL.createObjectURL(...))
_SW_WORKER_BLOB = _re(
    r"new\s+Worker\s*\(\s*URL\.createObjectURL\s*\("
)

# ---- SW-006 : sw-cache-put-no-status-check ----------------------------

# Matches cache.put(req, response) or cache.put(req, res.clone()) without
# an explicit .ok or .status check visible in the same expression.
_SW_CACHE_PUT = _re(
    r"cache\.put\s*\([^,]+,\s*(?:res|response|r)(?:\.clone\(\))?\s*\)"
)

# Positive sentinel for the guarded pattern (res.ok / response.status /
# response.ok check in same line). Used to suppress FPs at scan time.
_SW_CACHE_PUT_STATUS_GUARD = _re(
    r"(?:\.ok\b|\.status\b)"
)


# ---- Rule catalogue -----------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="sw-scope-no-scope-arg",
        name="SW registration without explicit scope",
        severity="HIGH",
        description=(
            "navigator.serviceWorker.register() called without a scope option "
            "defaults to the directory of the SW script. A SW served from '/' "
            "gains control of the entire origin, enabling cross-tenant "
            "interception in multi-tenant SaaS."
        ),
        pattern=_SW_REGISTER_NO_SCOPE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sw-import-scripts-dynamic-url",
        name="importScripts from dynamic or untrusted URL",
        severity="CRITICAL",
        description=(
            "importScripts() inside a Service Worker executes synchronously in "
            "the worker's global scope. If the URL is constructed from runtime "
            "data (config response, postMessage payload, template literal with "
            "interpolation), an attacker who can influence that value achieves "
            "arbitrary code execution in the SW context with full fetch "
            "interception of the origin."
        ),
        pattern=_SW_IMPORT_SCRIPTS_CONCAT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sw-push-handler-exfil",
        name="pushsubscriptionchange handler — potential endpoint leak",
        severity="HIGH",
        description=(
            "addEventListener('pushsubscriptionchange') handlers that POST the "
            "new subscription endpoint to a remote URL without validating that "
            "the target is the app's own backend can leak push endpoints to "
            "third-party analytics or an attacker who has compromised the "
            "analytics service."
        ),
        pattern=_SW_PUSHSUBSCRIPTIONCHANGE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="sw-clients-claim-no-guard",
        name="self.clients.claim() — immediate client takeover",
        severity="HIGH",
        description=(
            "self.clients.claim() or Workbox clientsClaim() makes a newly "
            "installed SW immediately take control of all in-scope pages. "
            "Combined with a broad scope (e.g. '/'), this creates a race "
            "condition where auth callback URLs or CSRF state pages are "
            "intercepted before they finish processing."
        ),
        pattern=_SW_CLIENTS_CLAIM,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="sw-worker-from-variable-url",
        name="new Worker / SharedWorker from variable URL",
        severity="HIGH",
        description=(
            "new Worker(variable) or new SharedWorker(variable) where the URL "
            "comes from a runtime variable rather than a static string literal "
            "enables URL injection. Blob URLs constructed from attacker-"
            "influenced content (XSS, JSONP sink) run arbitrary code in the "
            "worker context. SharedWorkers without origin validation on incoming "
            "postMessage calls accumulate state accessible to any same-origin page."
        ),
        pattern=_SW_WORKER_VAR_URL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sw-cache-put-no-status-check",
        name="cache.put without HTTP status check",
        severity="HIGH",
        description=(
            "cache.put(request, response) without verifying response.ok or "
            "response.status before storing can cache a 401, 403, or 5xx "
            "response, permanently locking the user out of a resource until "
            "the SW is unregistered or the cache is manually cleared."
        ),
        pattern=_SW_CACHE_PUT,
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


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- Scanner ------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters:

      * SW-002 — two distinct anchors: concatenation form and template-literal
        form. Both are checked; findings are deduped.
      * SW-004 — two anchors: self.clients.claim() and Workbox clientsClaim().
        Both are checked; findings are deduped under a single rule ID.
      * SW-005 — two anchors: variable-URL form and blob-URL form. Both
        checked; deduped under a single rule ID.
      * SW-006 — requires that the matching line does NOT already contain a
        `.ok` or `.status` guard in the same line (simple same-line filter).

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

    # ---- SW-001 : sw-scope-no-scope-arg ----
    rule_sw001 = rule_by_id["sw-scope-no-scope-arg"]
    for m in _SW_REGISTER_NO_SCOPE.finditer(text):
        _emit(rule_sw001, m.start(), m.group(0))

    # ---- SW-002 : sw-import-scripts-dynamic-url ----
    rule_sw002 = rule_by_id["sw-import-scripts-dynamic-url"]
    for m in _SW_IMPORT_SCRIPTS_CONCAT.finditer(text):
        _emit(rule_sw002, m.start(), m.group(0))
    for m in _SW_IMPORT_SCRIPTS_TEMPLATE.finditer(text):
        _emit(rule_sw002, m.start(), m.group(0))

    # ---- SW-003 : sw-push-handler-exfil ----
    rule_sw003 = rule_by_id["sw-push-handler-exfil"]
    for m in _SW_PUSHSUBSCRIPTIONCHANGE.finditer(text):
        _emit(rule_sw003, m.start(), m.group(0))

    # ---- SW-004 : sw-clients-claim-no-guard ----
    rule_sw004 = rule_by_id["sw-clients-claim-no-guard"]
    for m in _SW_CLIENTS_CLAIM.finditer(text):
        _emit(rule_sw004, m.start(), m.group(0))
    for m in _SW_WORKBOX_CLIENTS_CLAIM.finditer(text):
        _emit(rule_sw004, m.start(), m.group(0))

    # ---- SW-005 : sw-worker-from-variable-url ----
    rule_sw005 = rule_by_id["sw-worker-from-variable-url"]
    for m in _SW_WORKER_VAR_URL.finditer(text):
        _emit(rule_sw005, m.start(), m.group(0))
    for m in _SW_WORKER_BLOB.finditer(text):
        _emit(rule_sw005, m.start(), m.group(0))

    # ---- SW-006 : sw-cache-put-no-status-check ----
    rule_sw006 = rule_by_id["sw-cache-put-no-status-check"]
    lines_text = text.split("\n")
    for m in _SW_CACHE_PUT.finditer(text):
        line_no, _ = _line_col(text, m.start())
        # Suppress if the matched line itself contains a .ok or .status guard.
        line_content = lines_text[line_no - 1] if line_no <= len(lines_text) else ""
        if _SW_CACHE_PUT_STATUS_GUARD.search(line_content) is not None:
            continue
        _emit(rule_sw006, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
