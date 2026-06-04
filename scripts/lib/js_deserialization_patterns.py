"""Browser/JS deserialization & message-event-trust patterns.

Wave-25 distillation round 11 — JS-side deserialization angle.

Catalogue of 6 net-new browser/JS-specific anti-patterns distilled in
`reports/distill-round-11/js-deserialization.md`. Targets `JSON.parse`,
`structuredClone`, `postMessage`, `WebSocket` / `EventSource` /
`BroadcastChannel` / `MessageChannel` listeners, and `localStorage` /
`sessionStorage` / `cookie` deserialization paths.

What is NOT here (already shipped — DO NOT duplicate):

  * Python pickle / Java ObjectInputStream / .NET BinaryFormatter
    deserialization gadgets — `cross_lang_deserialize_patterns.py`.
  * `Object.assign(target, JSON.parse(input))` direct prototype
    pollution — `frontend_patterns.py::prototype-pollution-object-
    assign-json-parse`.
  * `JSON.parse(raw, reviver)` where the reviver calls `eval` /
    `new Function` — `frontend_patterns.py::json-parse-reviver-with-
    eval` (CWE-95 RCE shape).
  * Browser-extension specific surfaces (manifest permissions,
    runtime.onMessageExternal, native messaging) —
    `browser_extension_patterns.py`.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * jsdes-ws-event-data-json-parse-no-schema                  (HIGH)
  * jsdes-storage-parse-into-state-spread                     (MEDIUM)
  * jsdes-window-message-listener-no-origin-check             (CRITICAL)
  * jsdes-postmessage-wildcard-target-origin                  (HIGH)
  * jsdes-structured-clone-untrusted-into-object-assign       (HIGH)
  * jsdes-json-parse-reviver-captured-state-write             (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-04 — Information leak (postMessage targetOrigin='*' leaks payload)
  ASI-06 — Untrusted-input execution / object materialisation
  ASI-07 — Authority / authorisation gaps (origin check missing)

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
    """Compile with MULTILINE+UNICODE — same flags family used by
    chat_bot_patterns / auth_flow_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind. IGNORECASE is OFF
    here because JS identifiers (`onmessage`, `JSON.parse`, etc.) are
    case-sensitive and we don't want to false-positive on `JSON.Parse`
    in C# code that happens to live in a mixed-language repo."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- J1 : jsdes-ws-event-data-json-parse-no-schema ----------------------


# Anchor on the listener registration shape. We support both the
# `socket.onmessage = ...` property-set form AND the
# `socket.addEventListener('message', ...)` form. The body is then
# checked with a Stage-B forward window for the JSON.parse(e.data) idiom
# and the absence of a schema-validator marker.
_WS_MESSAGE_LISTENER_TRIGGER = _re(
    # ws.onmessage = ... / es.onmessage = ... / port.onmessage = ...
    # / channel.onmessage = ... / sw.onmessage = ... / worker.onmessage = ...
    r"\b(?:ws|wss|es|eventSource|socket|sock|channel|bc|broadcastChannel"
    r"|worker|sharedWorker|port|mport|messagePort|sw|serviceWorker)"
    r"\.onmessage\s*="
    r"|"
    # .addEventListener('message', ...) on any object
    r"\.addEventListener\s*\(\s*['\"]message['\"]\s*,"
)

# Inside the listener body we expect JSON.parse(e.data) — any common
# event identifier. Capped at 600 chars from the trigger.
_JSON_PARSE_EVENT_DATA = _re(
    r"\bJSON\.parse\s*\(\s*"
    r"(?:e|ev|evt|event|msg|m|payload|message)\s*\.\s*data\b"
)

# Schema-validator markers that suppress the finding when present in the
# same window. Covers zod / ajv / io-ts / valibot / yup / superstruct /
# typia / runtypes / joi as well as the manual `typeof === 'object'` and
# `'kind' in data` shape-check forms.
_SCHEMA_VALIDATOR_MARKER = _re(
    r"\.safeParse\s*\("
    r"|"
    # XxxSchema.parse(...) — zod / arktype / typebox idiom. We require
    # the dotted prefix to END in "Schema" so we don't match the
    # untrusted-source idiom `JSON.parse(raw)` (which has prefix "JSON").
    r"[A-Za-z_$][\w$]*Schema\.parse\s*\("
    r"|"
    r"\bajv\.validate\s*\("
    r"|"
    r"\bvalidator\s*\.\s*validate\s*\("
    r"|"
    r"\bvalidate\s*\(\s*(?:data|parsed|payload)\b"
    r"|"
    r"\bz\.object\s*\("
    r"|"
    r"\bz\.union\s*\("
    r"|"
    r"\bz\.discriminatedUnion\s*\("
    r"|"
    r"\bdecode\s*\(\s*(?:data|parsed)\b"
    r"|"
    r"\bis(?:Right|Left)\s*\("
    r"|"
    r"\bSchema\.(?:safeParse|parse|decode)\s*\("
    r"|"
    r"\bguard\s*\(\s*(?:data|parsed)\b"
)


# ---- J2 : jsdes-storage-parse-into-state-spread -------------------------


# Anchor on the JSON.parse over a same-origin storage surface. The value
# read from storage is attacker-controllable by any prior XSS, malicious
# extension, sub-resource that escaped CSP, or sibling iframe with
# document.domain set.
_STORAGE_JSON_PARSE_TRIGGER = _re(
    r"\bJSON\.parse\s*\(\s*"
    r"(?:(?:window|globalThis|self)\.)?"
    r"(?:localStorage|sessionStorage)\s*"
    r"(?:\.\s*getItem\s*\(|\[)"
    r"|"
    # Cookie variants — document.cookie + helper functions
    r"\bJSON\.parse\s*\(\s*"
    r"(?:document\.cookie\b|getCookie\s*\(|Cookies\.get\s*\()"
    r"|"
    # The parsed-from-storage shape via temp variable
    r"\bJSON\.parse\s*\(\s*"
    r"(?:stored|cached|saved|raw|persisted)\s*\)"
)

# Sink: spread, Object.assign, lodash merge, jQuery deep-extend within
# ~15 lines of the parse. Required by Stage-B before we emit.
_STATE_SPREAD_SINK = _re(
    r"\bObject\.assign\s*\(\s*[A-Za-z_$][\w$]*\s*,"
    r"|"
    r"\.\.\.(?:parsed|stored|cached|saved|raw|persisted|prev)\b"
    r"|"
    r"\bset[A-Z][\w]*\s*\(\s*\([^)]*\)\s*=>\s*\(\s*\{\s*\.\.\.[A-Za-z_$]"
    r"|"
    r"\b_\.\s*(?:merge|defaultsDeep|set|mergeWith)\s*\("
    r"|"
    r"\blodash\.\s*(?:merge|defaultsDeep|mergeWith)\s*\("
    r"|"
    r"\$\.\s*extend\s*\(\s*true\s*,"
    r"|"
    r"\bjQuery\.\s*extend\s*\(\s*true\s*,"
    r"|"
    r"\bdeepMerge\s*\("
)

# Hardening guard markers — strip __proto__ / constructor before spread,
# OR run the parsed value through a schema validator. Either suppresses.
_STORAGE_GUARD_MARKER = _re(
    r"\bdelete\s+[A-Za-z_$][\w$]*\.__proto__\b"
    r"|"
    r"\bdelete\s+[A-Za-z_$][\w$]*\[\s*['\"]__proto__['\"]\s*\]"
    r"|"
    r"\bObject\.create\s*\(\s*null\s*\)"
    r"|"
    # Schema validator markers (subset of J1's set).
    r"\.safeParse\s*\("
    r"|"
    r"\.parse\s*\(\s*(?:parsed|stored|cached)\s*\)"
    r"|"
    r"\bz\.object\s*\("
)


# ---- J3 : jsdes-window-message-listener-no-origin-check -----------------


# Anchor on the listener registration shape on window / self / globalThis.
# We deliberately do NOT match `iframe.contentWindow.addEventListener` —
# that listener is on a different Window and not our scope.
_WINDOW_MESSAGE_LISTENER_TRIGGER = _re(
    r"\b(?:window|globalThis|self)\.addEventListener\s*\(\s*"
    r"['\"]message['\"]\s*,"
)

# Origin/source check markers that suppress the finding. Cover the
# common defensive idioms: `event.origin === EXPECTED`,
# `event.origin !== EXPECTED ... return`, `if (!ALLOWED.includes(...))`,
# `event.source === iframeRef.contentWindow`.
_MESSAGE_ORIGIN_CHECK_MARKER = _re(
    r"\b(?:e|ev|evt|event|m|msg|message)\.origin\s*(?:===|!==|==|!=)\s*"
    r"|"
    r"\b(?:e|ev|evt|event|m|msg|message)\.origin\s+(?:in|not\s+in)\s+"
    r"|"
    r"\bALLOWED_ORIGINS?\b"
    r"|"
    r"\bTRUSTED_ORIGINS?\b"
    r"|"
    r"\borigin(?:Allow|White|Allow)list\b"
    r"|"
    r"\.includes\s*\(\s*(?:e|ev|evt|event|m|msg|message)\.origin\s*\)"
    r"|"
    r"\.has\s*\(\s*(?:e|ev|evt|event|m|msg|message)\.origin\s*\)"
    r"|"
    r"\b(?:e|ev|evt|event|m|msg|message)\.source\s*(?:===|!==|==|!=)\s*"
)


# ---- J4 : jsdes-postmessage-wildcard-target-origin ----------------------


# `someWindow.postMessage(payload, '*')` — wildcard targetOrigin leaks
# the payload to whichever origin is loaded in `someWindow` at call
# time. An attacker can race the navigation of a popup to hijack the
# payload.
_POSTMESSAGE_WILDCARD = _re(
    r"\.postMessage\s*\("
    r"(?:[^,()]{0,200}|\{[^{}]{0,300}\}|\[[^\[\]]{0,200}\])"
    r"\s*,\s*['\"]\*['\"]\s*\)"
)


# ---- J5 : jsdes-structured-clone-untrusted-into-object-assign -----------


# Two trigger shapes:
#  (A) structuredClone(JSON.parse(...)) — explicit untrusted source.
#  (B) Object.assign(target, structuredClone(<anything>)) — directly
#      pipes a clone into the pollution sink.
#
# RE2-safe: bounded character classes, no nesting under repetition.
_STRUCTURED_CLONE_UNTRUSTED = _re(
    r"\bstructuredClone\s*\(\s*"
    r"(?:JSON\.parse\s*\([^()]{0,200}\)|"
    r"(?:event|e|ev|evt|msg|message|payload|data|incoming|raw|parsed)"
    r"(?:\.\s*data)?)\s*\)"
)

# The downstream pollution sink — Object.assign or recursive merge of a
# cloned value. Required within a 12-line forward window of the trigger.
# The RHS identifier must be one of the common "this came from a clone"
# names — `snap`, `snapshot`, `clone`, `cloned`, `incoming`, `parsed`,
# `prev`, `next`, or directly another `structuredClone(...)` call.
_CLONE_TO_ASSIGN_SINK = _re(
    r"\bObject\.assign\s*\(\s*[A-Za-z_$][\w$]*\s*,\s*"
    r"(?:structuredClone|snap|snapshot|clone|cloned|prev|next|incoming|parsed)\b"
    r"|"
    r"\b_\.\s*(?:merge|defaultsDeep|mergeWith)\s*\(\s*"
    r"[A-Za-z_$][\w$]*\s*,\s*"
    r"(?:structuredClone|snap|snapshot|clone|cloned|incoming|parsed)\b"
    r"|"
    r"\bdeepMerge\s*\(\s*[A-Za-z_$][\w$]*\s*,\s*"
    r"(?:structuredClone|snap|snapshot|clone|cloned|incoming|parsed)\b"
)

# The (B) shape: directly Object.assign(target, structuredClone(...)).
# This is high-precision — emit immediately without window scan.
_OBJECT_ASSIGN_OF_STRUCTURED_CLONE = _re(
    r"\bObject\.assign\s*\(\s*[A-Za-z_$][\w$]*\s*,\s*"
    r"structuredClone\s*\("
)


# ---- J6 : jsdes-json-parse-reviver-captured-state-write -----------------


# Reviver subform that mutates captured state via `X.Y = v` (or
# `X[k] = v`, `X.Y = v + ...`, etc.) inside the reviver body. The
# eval/Function shape is intentionally NOT covered — that's already
# handled by `frontend_patterns::json-parse-reviver-with-eval`. We catch
# the silent state-confusion variant.
#
# Anchor: `JSON.parse(<arg>, <fn>)` where <fn> is an arrow or function
# expression whose body contains an assignment to <ident>.<ident> or
# <ident>[<expr>] where <ident> looks captured (not `v` or `value` or
# the parser's own accumulator). Body bounded to 400 chars to avoid
# accidental cross-statement matches.
_JSON_PARSE_REVIVER_TRIGGER = _re(
    r"\bJSON\.parse\s*\(\s*"
    r"[^,()]{1,200},\s*"
    r"(?:function\s*\(\s*[A-Za-z_$][\w$]*\s*,\s*[A-Za-z_$][\w$]*\s*\)"
    r"|\(\s*[A-Za-z_$][\w$]*\s*,\s*[A-Za-z_$][\w$]*\s*\)\s*=>)"
    r"\s*\{"
)

# Captured-state assignment marker. RE2-safe: no lookbehind, no
# lookahead. We pin the LHS to a `<ident>.<ident> =` or
# `<ident>[<key>] =` shape followed by `v` / `value`. The scanner
# post-filters in Python to reject same-line `return …`, and to reject
# `v.<prop> = v` and `value.<prop> = v` (writes to the parser's own
# accumulator, which are benign).
_REVIVER_CAPTURED_WRITE = _re(
    r"\b[A-Za-z_$][\w$]*\s*\.\s*[A-Za-z_$][\w$]*\s*=\s*(?:v|value)\b"
    r"|"
    # Bracket-form: target[k] = v
    r"\b[A-Za-z_$][\w$]*\s*\[\s*[A-Za-z_$][\w$]*\s*\]\s*=\s*(?:v|value)\b"
)

# Identifier prefixes we must reject (the LHS belongs to the parser's
# own accumulator, NOT to a captured target). Applied after the regex
# match in Python.
_REVIVER_LHS_REJECT_PREFIXES = ("v.", "v[", "value.", "value[", "this.", "this[")


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="jsdes-ws-event-data-json-parse-no-schema",
        name=(
            "WebSocket / EventSource / Worker JSON.parse(event.data) "
            "without schema validation"
        ),
        severity="HIGH",
        description=(
            "A `WebSocket`, `EventSource`, `BroadcastChannel`, "
            "`MessageChannel`, `SharedWorker`, or `ServiceWorker` "
            "`onmessage` / `addEventListener('message', ...)` handler "
            "pipes the raw transport payload through `JSON.parse` and "
            "hands the resulting object to downstream UI/state "
            "machinery WITHOUT a schema validator (zod / ajv / io-ts / "
            "valibot / yup / superstruct) within ~30 lines. Because "
            "the parsed object's shape comes directly from the wire, "
            "any attacker who can compromise the origin endpoint, "
            "MITM a non-wss/non-https channel, or load a fake server "
            "URL into the client gets to dictate every dispatch key "
            "downstream code switches on. The JS analogue of trusting "
            "the deserialized object's class — except in JS the class "
            "IS the shape."
        ),
        pattern=_WS_MESSAGE_LISTENER_TRIGGER,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="jsdes-storage-parse-into-state-spread",
        name=(
            "JSON.parse of localStorage / sessionStorage / cookie "
            "spread into application state"
        ),
        severity="MEDIUM",
        description=(
            "`localStorage` / `sessionStorage` / `document.cookie` "
            "are writable by ANY same-origin script — a transient XSS, "
            "a sub-resource that escaped CSP, an iframe with "
            "`document.domain` set, or a malicious browser extension "
            "content-script. Code that reads such a value, "
            "`JSON.parse`s it, and either spreads it into state "
            "(`{ ...prev, ...parsed }`) or passes it through "
            "`Object.assign` / `_.merge` / `$.extend(true, ...)` "
            "walks `__proto__` and pollutes `Object.prototype` for "
            "the entire page. Suppressed when a schema validator or "
            "an explicit `__proto__` strip appears within ~15 lines."
        ),
        pattern=_STORAGE_JSON_PARSE_TRIGGER,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="jsdes-window-message-listener-no-origin-check",
        name=(
            "window.addEventListener('message') handler without "
            "event.origin check"
        ),
        severity="CRITICAL",
        description=(
            "The `message` event listener on `window` receives "
            "`MessageEvent` objects from ANY frame — same-origin and "
            "cross-origin iframes, popups opened by `window.open`, "
            "the parent frame in an embed scenario, Service Workers, "
            "Web Workers. The listener MUST verify `event.origin` "
            "against an allowlist AND ideally `event.source` against "
            "the expected `Window`. Failing either, the page "
            "implicitly trusts every cross-origin frame on the user's "
            "machine to dispatch privileged actions. Common downstream "
            "sinks (assignment to `location.href`, `eval`, `Function`, "
            "`document.write`, `innerHTML`, posting auth tokens via "
            "`fetch`) make this a one-message-to-XSS / token exfil "
            "chain."
        ),
        pattern=_WINDOW_MESSAGE_LISTENER_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="jsdes-postmessage-wildcard-target-origin",
        name="postMessage called with wildcard '*' targetOrigin",
        severity="HIGH",
        description=(
            "`window.postMessage(payload, '*')` (or any "
            "`<window-ref>.postMessage(payload, '*')`) broadcasts the "
            "payload to whichever origin happens to be loaded in the "
            "target window at the moment — which an attacker can race "
            "by navigating a popup or iframe just before the call. "
            "Payloads commonly observed in `postMessage(..., '*')` "
            "calls include session tokens, OAuth state, CSRF tokens, "
            "and PII. Use the actual expected origin (e.g. "
            "`'https://app.example.com'`) instead — if you don't know "
            "the target's origin at call time, the message almost "
            "certainly should not be cross-origin."
        ),
        pattern=_POSTMESSAGE_WILDCARD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="jsdes-structured-clone-untrusted-into-object-assign",
        name=(
            "structuredClone of untrusted JSON / event data passed to "
            "Object.assign or recursive merge"
        ),
        severity="HIGH",
        description=(
            "`structuredClone` was designed as a safe replacement for "
            "the `JSON.parse(JSON.stringify(x))` idiom, but per the "
            "HTML spec it does NOT strip `__proto__` as a special key. "
            "A `structuredClone(JSON.parse(untrusted))` followed by "
            "`Object.assign(target, clone)` — or by `_.merge`, "
            "`deepMerge`, `_.defaultsDeep` — DOES walk `__proto__` "
            "and pollutes `Object.prototype` process-wide. Authors "
            "commonly assume 'I cloned it, so I'm safe from "
            "prototype pollution' — this rule catches that assumption "
            "directly. Distinct from `prototype-pollution-object-"
            "assign-json-parse` (which catches "
            "`Object.assign(target, JSON.parse(...))` WITHOUT the "
            "structuredClone wash)."
        ),
        pattern=_STRUCTURED_CLONE_UNTRUSTED,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="jsdes-json-parse-reviver-captured-state-write",
        name=(
            "JSON.parse reviver writes to a captured target during "
            "parse (state-confusion subform)"
        ),
        severity="HIGH",
        description=(
            "The optional reviver argument to `JSON.parse` is invoked "
            "for every key during parsing, from leaves up to the root. "
            "A reviver that writes into a target captured from the "
            "closure (`(k, v) => { if (k === 'role') target.role = v; "
            "return v; }`) mutates application state DURING parse, "
            "bypassing every later validator that operates on the "
            "fully-parsed root object. Distinct from `json-parse-"
            "reviver-with-eval` (in `frontend_patterns.py`) which "
            "catches the CWE-95 eval / new Function subform — this "
            "rule catches the silent state-confusion subform where "
            "the reviver assigns to `<captured>.<prop> = v` inside "
            "its body."
        ),
        pattern=_JSON_PARSE_REVIVER_TRIGGER,
        owasp_asi="ASI-06",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


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


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * J1 (ws-event-data-json-parse-no-schema) — anchor on the
        listener trigger and require BOTH a `JSON.parse(e.data)`
        idiom AND NO schema-validator marker in a 30-line forward
        window.
      * J2 (storage-parse-into-state-spread) — anchor on the
        `JSON.parse(localStorage|...)` trigger and require a
        state-spread / Object.assign / merge sink within 15 lines AND
        NO __proto__-strip or schema-validator guard in the same
        window.
      * J3 (window-message-listener-no-origin-check) — anchor on
        the listener registration and require NO origin/source check
        in a 25-line forward window.
      * J4 (postmessage-wildcard-target-origin) — high-precision
        regex; emit on every match.
      * J5 (structured-clone-untrusted-into-object-assign) — two
        subshapes: (A) `structuredClone(JSON.parse|event.data)` plus a
        downstream `Object.assign(target, ...)` / merge sink within
        12 lines; (B) direct `Object.assign(target, structuredClone(...))`
        which is high-precision and emits immediately.
      * J6 (json-parse-reviver-captured-state-write) — anchor on
        `JSON.parse(arg, fn)` with an arrow/function-expression body
        and require a captured-state write (`<ident>.<ident> = v`) in
        the immediately-following 400 chars (≈ reviver body bounds).

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

    # ---- J1 : jsdes-ws-event-data-json-parse-no-schema ----
    rule_j1 = rule_by_id["jsdes-ws-event-data-json-parse-no-schema"]
    for m in _WS_MESSAGE_LISTENER_TRIGGER.finditer(text):
        line, _ = _line_col(text, m.start())
        # 30-line forward window — the handler body.
        window = _slice_forward(text, line, 30)
        # Must contain the JSON.parse(e.data) idiom to be meaningful.
        if _JSON_PARSE_EVENT_DATA.search(window) is None:
            continue
        # Suppress if a schema-validator marker is present.
        if _SCHEMA_VALIDATOR_MARKER.search(window) is not None:
            continue
        _emit(rule_j1, m.start(), m.group(0))

    # ---- J2 : jsdes-storage-parse-into-state-spread ----
    rule_j2 = rule_by_id["jsdes-storage-parse-into-state-spread"]
    for m in _STORAGE_JSON_PARSE_TRIGGER.finditer(text):
        line, _ = _line_col(text, m.start())
        # 15-line window centred on the parse — sinks usually appear
        # within the same useEffect / handler body.
        window = _slice_window(text, line, 2, 15)
        if _STATE_SPREAD_SINK.search(window) is None:
            continue
        # Suppress if a guard marker (proto strip / schema) is present.
        if _STORAGE_GUARD_MARKER.search(window) is not None:
            continue
        _emit(rule_j2, m.start(), m.group(0))

    # ---- J3 : jsdes-window-message-listener-no-origin-check ----
    rule_j3 = rule_by_id["jsdes-window-message-listener-no-origin-check"]
    for m in _WINDOW_MESSAGE_LISTENER_TRIGGER.finditer(text):
        line, _ = _line_col(text, m.start())
        # 25-line forward window — the handler body.
        window = _slice_forward(text, line, 25)
        if _MESSAGE_ORIGIN_CHECK_MARKER.search(window) is not None:
            continue
        _emit(rule_j3, m.start(), m.group(0))

    # ---- J4 : jsdes-postmessage-wildcard-target-origin ----
    rule_j4 = rule_by_id["jsdes-postmessage-wildcard-target-origin"]
    for m in _POSTMESSAGE_WILDCARD.finditer(text):
        _emit(rule_j4, m.start(), m.group(0))

    # ---- J5 : jsdes-structured-clone-untrusted-into-object-assign ----
    rule_j5 = rule_by_id["jsdes-structured-clone-untrusted-into-object-assign"]
    # Subshape (A): structuredClone(JSON.parse|event.data) + sink in window
    for m in _STRUCTURED_CLONE_UNTRUSTED.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 12)
        if _CLONE_TO_ASSIGN_SINK.search(window) is not None:
            _emit(rule_j5, m.start(), m.group(0))
    # Subshape (B): direct Object.assign(target, structuredClone(...))
    for m in _OBJECT_ASSIGN_OF_STRUCTURED_CLONE.finditer(text):
        _emit(rule_j5, m.start(), m.group(0))

    # ---- J6 : jsdes-json-parse-reviver-captured-state-write ----
    rule_j6 = rule_by_id["jsdes-json-parse-reviver-captured-state-write"]
    for m in _JSON_PARSE_REVIVER_TRIGGER.finditer(text):
        # Reviver body is on/after the matched `{` — take the next 400
        # chars as the reviver-body proxy.
        body_start = m.end()
        body_proxy = text[body_start : body_start + 400]
        for wm in _REVIVER_CAPTURED_WRITE.finditer(body_proxy):
            matched = wm.group(0).lstrip()
            # Reject writes to the parser's own accumulator
            # (`v.<prop>`, `value.<prop>`, `this.<prop>`).
            if matched.startswith(_REVIVER_LHS_REJECT_PREFIXES):
                continue
            # Reject `return X.Y = v` shape — check the 8 chars
            # preceding the captured-write match for a `return` token.
            lookback_start = max(0, wm.start() - 8)
            lookback = body_proxy[lookback_start : wm.start()]
            if "return " in lookback or "return\t" in lookback:
                continue
            _emit(rule_j6, m.start(), m.group(0))
            # One emission per JSON.parse — the trigger is the parse
            # site, not the write site.
            break

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
