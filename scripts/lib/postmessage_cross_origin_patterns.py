"""postMessage / window.postMessage cross-origin abuse patterns.

Wave-32 distillation round 18, angle postmessage-cross-origin.

Catalogue of 9 postMessage-specific anti-patterns distilled in
`reports/distill-round-18/postmessage-cross-origin.md`. Targets
browser messaging APIs: window.postMessage, BroadcastChannel,
MessageChannel/MessagePort, ServiceWorker client.postMessage, and
extension content-script postMessage bridges.

What is NOT here (already shipped — DO NOT duplicate):

  * `window.addEventListener('message')` without origin check —
    `js_deserialization_patterns.py` rule `jsdes-window-message-listener-no-origin-check`
  * `.postMessage(payload, '*')` wildcard target —
    `js_deserialization_patterns.py` rule `jsdes-postmessage-wildcard-target-origin`
  * WS/BC/MC onmessage JSON.parse no schema —
    `js_deserialization_patterns.py` rule `jsdes-ws-event-data-json-parse-no-schema`
  * `.includes()` substring origin check bypass —
    `iframe_csp_frames_patterns.py` rule `iframe-csp-postmessage-origin-includes-bypass`
  * Wildcard target via iframe angles —
    `iframe_csp_frames_patterns.py` rule `iframe-csp-postmessage-wildcard-target`

What IS here (9 net-new rules, regex-only, all RE2-safe):

  * pmsg-onmessage-property-no-origin-guard                    (CRITICAL)
  * pmsg-broadcastchannel-handler-no-type-allowlist            (HIGH)
  * pmsg-origin-startswith-endswith-bypass                     (HIGH)
  * pmsg-messagechannel-port-wildcard-transfer                 (CRITICAL)
  * pmsg-data-relay-to-wildcard                                (CRITICAL)
  * pmsg-sw-clients-matchall-broadcast                         (HIGH)
  * pmsg-extension-postmessage-bridge-no-nonce                 (HIGH)
  * pmsg-source-reply-wildcard-target                          (HIGH)
  * pmsg-broadcastchannel-user-input-name                      (MAJOR)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-04 — Information leak / cross-origin data exfiltration
  ASI-07 — Authority / authorisation gaps (origin validation, sender auth)

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
    """A single rule match."""

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
    """Compile with IGNORECASE+MULTILINE+UNICODE. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- P1 : pmsg-onmessage-property-no-origin-guard -----------------------

# Trigger: assigning a handler to window.onmessage (property-set form).
# The existing jsdes-window-message-listener-no-origin-check rule anchors
# on window.addEventListener; the property-set form is a detection gap.
# FP risk: Low. Rare legitimate handlers whose origin check is >20 lines
# away from the assignment; reviewers should inspect the full handler body.
_ONMESSAGE_PROPERTY_ASSIGN = _re(
    r"\b(?:window|globalThis|self)\.onmessage\s*="
)

# ---- P2 : pmsg-broadcastchannel-handler-no-type-allowlist ---------------

# Trigger: constructing a new BroadcastChannel.
# BroadcastChannel has no origin concept — all senders are same-origin.
# A compromised same-origin page (XSS, rogue extension) can inject messages
# to trigger privileged actions without any origin gate. Handlers that act
# on event.data without checking event.data.type against a closed allowlist
# are vulnerable. FP risk: Medium — benign inter-tab state sync is common.
_BROADCASTCHANNEL_NEW = _re(
    r"\bnew\s+BroadcastChannel\s*\("
)

# ---- P3 : pmsg-origin-startswith-endswith-bypass ------------------------

# Trigger: calling .startsWith() or .endsWith() on event.origin.
# startsWith('https://trusted.com') is bypassed by 'https://trusted.com.evil.com'.
# endsWith('trusted.com') is bypassed by 'https://evil-trusted.com'.
# The .includes() bypass is already covered; these are distinct bypass shapes.
# FP risk: Low — strict equality or Set.has() is the correct idiom.
_ORIGIN_STARTSWITH_ENDSWITH = _re(
    r"\b(?:e|ev|evt|event|m|msg|message)\.origin\.(?:startsWith|endsWith)\s*\("
)

# ---- P4 : pmsg-messagechannel-port-wildcard-transfer --------------------

# Trigger: new MessageChannel() immediately followed (within ~400 chars)
# by a .postMessage call that uses the wildcard '*' as targetOrigin.
# Transferring a MessagePort to an unknown origin gives the attacker a
# private authenticated-free pipe bypassing all future origin checks.
# FP risk: Low-medium — MessageChannel is niche; cross-origin port-transfer
# with wildcard is very rarely intentional.
_MESSAGECHANNEL_PORT_WILDCARD = _re(
    r"new\s+MessageChannel\s*\([\s\S]{0,400}\.postMessage\s*\([^)]{0,200}['\"][*]['\"]"
)

# ---- P5 : pmsg-data-relay-to-wildcard -----------------------------------

# Trigger: relaying event.data verbatim to a wildcard postMessage target.
# A listener re-posts e.data (or direct derivative) with targetOrigin='*',
# turning the relay page into an open proxy enabling cross-origin exfiltration.
# FP risk: Low — relaying e.data verbatim to '*' has very few legitimate uses.
_DATA_RELAY_TO_WILDCARD = _re(
    r"\.postMessage\s*\(\s*(?:e|ev|evt|event|m|msg|message)\.data\b[^)]{0,100}['\"][*]['\"]\s*\)"
)

# ---- P6 : pmsg-sw-clients-matchall-broadcast ----------------------------

# Trigger: ServiceWorker clients.matchAll() followed (within ~300 chars)
# by client.postMessage — broadcasting a fetch response to every tab
# regardless of auth context. Without checking the client URL, the SW
# becomes a cross-tab broadcast amplifier leaking sensitive response data.
# FP risk: Medium — clients.matchAll + postMessage is used legitimately
# for push-notification UX.
_SW_CLIENTS_MATCHALL_BROADCAST = _re(
    r"self\.clients\.matchAll\s*\([\s\S]{0,300}\.postMessage\s*\("
)

# ---- P7 : pmsg-extension-postmessage-bridge-no-nonce --------------------

# Trigger: window.addEventListener('message') with chrome.runtime.sendMessage
# or browser.runtime.sendMessage within ~400 chars (content-script bridge).
# Without a shared secret or nonce, any same-origin web page can craft a
# matching message and trigger privileged extension background actions.
# FP risk: Medium — fires on any extension using the page↔extension bridge.
# True positives lack a nonce/secret check before the sendMessage call.
_EXTENSION_POSTMESSAGE_BRIDGE = _re(
    r"window\.addEventListener\s*\(\s*['\"]message['\"]\s*,[\s\S]{0,400}"
    r"(?:chrome|browser)\.runtime\.sendMessage\s*\("
)

# ---- P8 : pmsg-source-reply-wildcard-target -----------------------------

# Trigger: event.source.postMessage(result, '*') — replying to the sender
# window using the wildcard targetOrigin. If the sender's window navigates
# between receiving the message and receiving the reply, an attacker who
# races the navigation can intercept the reply (tokens, credentials).
# FP risk: Low — event.source.postMessage(..., '*') is explicitly called out
# in OWASP HTML5 as insecure.
_SOURCE_REPLY_WILDCARD = _re(
    r"\b(?:e|ev|evt|event|m|msg|message)\.source\.postMessage\s*\([^)]{0,200}['\"][*]['\"]\s*\)"
)

# ---- P9 : pmsg-broadcastchannel-user-input-name -------------------------

# Trigger: new BroadcastChannel() with a template-literal (indicating the
# channel name is dynamic / potentially attacker-influenced). An attacker
# who knows or can guess the channel name (e.g. user-${userId}) can
# subscribe from another tab to eavesdrop or inject messages.
# FP risk: Medium — template-literal channel names are common in multi-tenant
# apps. True positive when the variable component is not a crypto-random secret.
_BROADCASTCHANNEL_TEMPLATE_NAME = _re(
    r"new\s+BroadcastChannel\s*\(\s*`[^`]{0,100}\$\{"
)


# ---- Rule catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="pmsg-onmessage-property-no-origin-guard",
        name="window.onmessage property assignment without origin guard",
        severity="CRITICAL",
        description=(
            "Assigning a handler to window.onmessage (property-set form) without "
            "verifying event.origin lets any cross-origin frame, popup, or "
            "ServiceWorker inject an arbitrary payload. "
            "The addEventListener form is covered by a separate rule."
        ),
        pattern=_ONMESSAGE_PROPERTY_ASSIGN,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pmsg-broadcastchannel-handler-no-type-allowlist",
        name="BroadcastChannel handler with no message-type allowlist",
        severity="HIGH",
        description=(
            "BroadcastChannel delivers messages to all same-origin contexts "
            "with no origin concept. Any compromised same-origin page (XSS, "
            "rogue extension) can inject channel messages that trigger privileged "
            "actions unless handlers check event.data.type against a closed allowlist."
        ),
        pattern=_BROADCASTCHANNEL_NEW,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pmsg-origin-startswith-endswith-bypass",
        name="Weak event.origin check using startsWith or endsWith",
        severity="HIGH",
        description=(
            "event.origin.startsWith('https://trusted.com') is bypassed by "
            "'https://trusted.com.evil.com'; endsWith('trusted.com') is bypassed "
            "by 'https://evil-trusted.com'. Use strict equality or Set.has() instead."
        ),
        pattern=_ORIGIN_STARTSWITH_ENDSWITH,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pmsg-messagechannel-port-wildcard-transfer",
        name="MessageChannel port transferred via postMessage to wildcard target",
        severity="CRITICAL",
        description=(
            "Transferring a MessagePort to a wildcard '*' targetOrigin gives an "
            "attacker who owns the other window a private, authentication-free pipe "
            "back into the original page, bypassing all future origin checks."
        ),
        pattern=_MESSAGECHANNEL_PORT_WILDCARD,
        owasp_asi="ASI-04 + ASI-07",
    ),
    Rule(
        id="pmsg-data-relay-to-wildcard",
        name="postMessage data relay — forwarding event.data to wildcard target",
        severity="CRITICAL",
        description=(
            "Relaying event.data verbatim to a wildcard postMessage target turns "
            "the relay page into an open proxy, enabling cross-origin data "
            "exfiltration or privilege escalation through a trusted intermediary."
        ),
        pattern=_DATA_RELAY_TO_WILDCARD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="pmsg-sw-clients-matchall-broadcast",
        name="ServiceWorker clients.matchAll + client.postMessage without auth context",
        severity="HIGH",
        description=(
            "A ServiceWorker that broadcasts fetch response data to all controlled "
            "clients via clients.matchAll() + client.postMessage() without checking "
            "the client URL leaks sensitive data to unauthenticated tabs."
        ),
        pattern=_SW_CLIENTS_MATCHALL_BROADCAST,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="pmsg-extension-postmessage-bridge-no-nonce",
        name="Extension content-script window.postMessage bridge without shared secret",
        severity="HIGH",
        description=(
            "A content script that listens for window.postMessage and forwards to "
            "chrome.runtime.sendMessage or browser.runtime.sendMessage without a "
            "shared secret or nonce allows any same-origin web page to trigger "
            "privileged extension background actions."
        ),
        pattern=_EXTENSION_POSTMESSAGE_BRIDGE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pmsg-source-reply-wildcard-target",
        name="event.source.postMessage reply sent to wildcard target origin",
        severity="HIGH",
        description=(
            "Replying via event.source.postMessage(result, '*') leaks the response "
            "to whatever origin the sender window navigates to between message "
            "receipt and reply, enabling token/credential interception via a race."
        ),
        pattern=_SOURCE_REPLY_WILDCARD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="pmsg-broadcastchannel-user-input-name",
        name="BroadcastChannel name derived from user input (template literal)",
        severity="MAJOR",
        description=(
            "A BroadcastChannel whose name is built from a template literal "
            "(indicating dynamic, potentially attacker-influenced input) allows "
            "an attacker who knows or guesses the channel name to subscribe from "
            "another tab and eavesdrop or inject messages."
        ),
        pattern=_BROADCASTCHANNEL_TEMPLATE_NAME,
        owasp_asi="ASI-04",
    ),
)


# ---- Helpers -------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - before.rfind("\n")
    return line, col


# ---- Public API ----------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return sorted findings.

    Findings are deduped by (rule_id, line, col) and sorted by
    (line, column, rule_id).
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

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
