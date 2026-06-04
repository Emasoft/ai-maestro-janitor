"""CRDT / collaborative-sync engine anti-patterns library.

Wave-30 distillation round 16, angle CRDT-Sync.

Catalogue of 14 CRDT / collaborative real-time sync anti-patterns distilled
from Yjs, Automerge, Liveblocks, and Replicache usage patterns.

What is NOT here (handled by other modules — DO NOT duplicate):

  * Generic race-condition / concurrent-write hazards without CRDT context
    — `build_reproducibility_patterns.py`.
  * WebSocket credential leaks — `browser_cookies_patterns.py`.
  * Generic JWT / session token leaks — `auth_flow_patterns.py`.
  * Supply-chain attacks on npm packages — `cdn_supply_chain_patterns.py`.

What IS here (14 net-new rules, regex-only, all RE2-safe):

  * crdt-sync-ydoc-no-awareness-cleanup            (HIGH)
  * crdt-sync-ydoc-update-no-origin-guard          (HIGH)
  * crdt-sync-automerge-no-clone-before-mutate     (HIGH)
  * crdt-sync-liveblocks-presence-pii-broadcast    (CRITICAL)
  * crdt-sync-replicache-push-no-server-auth       (CRITICAL)
  * crdt-sync-replicache-pull-no-version-check     (HIGH)
  * crdt-sync-ydoc-xml-fragment-xss                (HIGH)
  * crdt-sync-conflict-resolution-last-write-wins  (MEDIUM)
  * crdt-sync-undomanager-no-scope                 (MEDIUM)
  * crdt-sync-liveblocks-room-id-user-controlled   (HIGH)
  * crdt-sync-replicache-client-id-predictable     (MEDIUM)
  * crdt-sync-yjs-provider-no-reconnect-limit      (MEDIUM)
  * crdt-sync-automerge-load-untrusted             (CRITICAL)
  * crdt-sync-ydoc-getarray-direct-splice          (LOW)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-02 — Secret / sensitive-data leak (presence PII broadcast)
  ASI-04 — Information leak (user-controlled room IDs, predictable client IDs)
  ASI-05 — Supply-chain / integrity (automerge load untrusted binary,
                                    XML-fragment XSS injection)
  ASI-07 — Authorisation gaps (push without server auth, pull without
                                version check, awareness cleanup missing)
  ASI-08 — Data-integrity / corruption (LWW without vector clock, undo
                                         scope missing, direct splice on
                                         shared array, update loops)
  ASI-09 — Availability / resource exhaustion (provider no reconnect
                                                limit, stale awareness)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module load.
Fail-fast: callers receive structured Finding tuples, never raised exceptions
on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model --------------------------------------------------------


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
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- C1 : crdt-sync-ydoc-no-awareness-cleanup --------------------------

# Yjs Awareness is created (new Awareness(doc)) but destroyed never
# (awareness.destroy() is absent from the file).
_YDOC_AWARENESS_CREATE = _re(
    r"\bnew\s+Awareness\s*\("
    r"|"
    r"\bwebsocketProvider\.awareness\b"
    r"|"
    r"\bwebRtcProvider\.awareness\b"
)

_YDOC_AWARENESS_DESTROY = _re(
    r"\bawareness\.destroy\s*\(\s*\)"
    r"|"
    r"\.off\s*\(\s*['\"`]change['\"`]\s*,\s*\w"
    r"|"
    r"\.removeUpdateListener\b"
)


# ---- C2 : crdt-sync-ydoc-update-no-origin-guard -----------------------

# Y.Doc.on('update', handler) loop that forwards the update back via
# applyUpdate without guarding the `origin` parameter.
_YDOC_ON_UPDATE = _re(
    r"\bdoc\s*\.\s*on\s*\(\s*['\"`]update['\"`]"
    r"|"
    r"\bydoc\s*\.\s*on\s*\(\s*['\"`]update['\"`]"
    r"|"
    r"\.on\s*\(\s*['\"`]update['\"`]\s*,\s*(?:async\s+)?\w"
)

_YDOC_APPLY_NO_ORIGIN = _re(
    r"\bY\.applyUpdate\s*\("
    r"|"
    r"\bapplyUpdate\s*\(\s*\w"
)

_YDOC_ORIGIN_GUARD = _re(
    r"\bif\s*\(\s*(?:!?\s*)?origin\b"
    r"|"
    r"\borigin\s*(?:===?|!==?|==)\s*"
    r"|"
    r"\borigin\s*!==?\s*"
    r"|"
    r"&&\s*origin\b"
    r"|"
    r"\|\|\s*origin\b"
    r"|"
    r"return\s+.*\borigin\b"
)


# ---- C3 : crdt-sync-automerge-no-clone-before-mutate ------------------

# Automerge.change() called directly on a ref stored in React state or
# a shared variable without Automerge.clone() first.
_AUTOMERGE_DIRECT_CHANGE = _re(
    r"\bAutomerge\.change\s*\(\s*(?:state|doc|document|currentDoc)\b"
    r"|"
    r"\bA\.change\s*\(\s*(?:state|doc|document|currentDoc)\b"
)

_AUTOMERGE_CLONE_GUARD = _re(
    r"\bAutomerge\.clone\s*\("
    r"|"
    r"\bA\.clone\s*\("
)


# ---- C4 : crdt-sync-liveblocks-presence-pii-broadcast ----------------

# updatePresence() called with a field that looks like personal data
# (email, userId, name, phone, ip).
_LIVEBLOCKS_UPDATE_PRESENCE = _re(
    r"\bupdatePresence\s*\(\s*\{"
    r"|"
    r"\broom\.updatePresence\s*\(\s*\{"
    r"|"
    r"\.updatePresence\s*\(\s*\{"
)

_PRESENCE_PII_FIELD = _re(
    r"\b(?:email|user_?email|phoneNumber|phone|ipAddress|ip_address"
    r"|ssn|passport|credit_?card)\s*:"
)


# ---- C5 : crdt-sync-replicache-push-no-server-auth -------------------

# Replicache POST /push (or custom pushURL) handler registered without
# authentication middleware or JWT/session check.
_REPLICACHE_PUSH_ROUTE = _re(
    r"\bpushURL\s*[=:]\s*['\"`][^'\"`]{1,120}push[^'\"`]{0,40}['\"`]"
    r"|"
    r"\b(?:app|router|server)\s*\.\s*post\s*\(\s*['\"`][^'\"`]{0,60}push['\"`]"
    r"|"
    r"\bpostMessage\s*\(\s*['\"`]push['\"`]"
)

_AUTH_MIDDLEWARE = _re(
    r"\b(?:authenticate|requireAuth|authMiddleware|verifyToken|checkSession"
    r"|isAuthenticated|authorize|bearerAuth|jwtMiddleware)\s*[,()\[]"
    r"|"
    r"Authorization\s*:"
    r"|"
    r"\breq\.user\b"
    r"|"
    r"\bctx\.user\b"
    r"|"
    r"\bsession\b"
)


# ---- C6 : crdt-sync-replicache-pull-no-version-check -----------------

# Replicache GET /pull handler that does not read or check
# `lastMutationID` / `cookie` / `fromVersion` before building the patch.
_REPLICACHE_PULL_ROUTE = _re(
    r"\bpullURL\s*[=:]\s*['\"`][^'\"`]{1,120}pull[^'\"`]{0,40}['\"`]"
    r"|"
    r"\b(?:app|router|server)\s*\.\s*(?:get|post)\s*\(\s*['\"`][^'\"`]{0,60}pull['\"`]"
    r"|"
    r"['\"`]/api/pull['\"`]"
)

_PULL_VERSION_CHECK = _re(
    r"\blastMutationID\b"
    r"|"
    r"\bfromVersion\b"
    r"|"
    r"\bcookie\b"
    r"|"
    r"\bsinceVersion\b"
)


# ---- C7 : crdt-sync-ydoc-xml-fragment-xss ----------------------------

# Y.XmlFragment content set from user-controlled string with innerHTML
# or insertAdjacentHTML, or via tiptap/prosemirror without sanitization.
_YDOC_XML_FRAGMENT = _re(
    r"\bnew\s+Y\.XmlFragment\s*\("
    r"|"
    r"\bnew\s+Y\.XmlText\s*\("
    r"|"
    r"\.insert\s*\(\s*0\s*,\s*\[?\s*new\s+Y\.Xml"
)

_XSS_SINK = _re(
    r"\binnerHTML\s*="
    r"|"
    r"\binsertAdjacentHTML\s*\("
    r"|"
    r"document\.write\s*\("
)

_SANITIZE_CALL = _re(
    r"\bDOMPurify\.sanitize\s*\("
    r"|"
    r"\bsanitize(?:Html|Svg)?\s*\("
    r"|"
    r"\bsanitized\b"
)


# ---- C8 : crdt-sync-conflict-resolution-last-write-wins --------------

# Explicit last-write-wins merge strategy without a vector clock or
# Lamport timestamp discriminator.
_LWW_ASSIGNMENT = _re(
    r"\bmerge\s*=\s*['\"`]lww['\"`]"
    r"|"
    r"\bconflictResolution\s*[=:]\s*['\"`](?:lww|last.write.wins)['\"`]"
    r"|"
    r"\bstrategy\s*[=:]\s*['\"`](?:lww|last.write.wins)['\"`]"
    r"|"
    r"\bmergeStrategy\s*[=:]\s*['\"`](?:lww|last.write.wins)['\"`]"
)

_VECTOR_CLOCK_OR_HLC = _re(
    r"\bvectorClock\b"
    r"|"
    r"\bhlcTimestamp\b"
    r"|"
    r"\bHybridLogicalClock\b"
    r"|"
    r"\bLamport\b"
    r"|"
    r"\bcounterClock\b"
)


# ---- C9 : crdt-sync-undomanager-no-scope ------------------------------

# Y.UndoManager created without a scope argument (tracks all types,
# potentially undoing remote edits from other clients).
_UNDOMANAGER_NO_SCOPE = _re(
    r"\bnew\s+Y\.UndoManager\s*\(\s*(?:doc|ydoc|document)\s*[,)]"
    r"|"
    r"\bnew\s+UndoManager\s*\(\s*(?:doc|ydoc|document)\s*[,)]"
)

_UNDOMANAGER_SCOPE_GUARD = _re(
    r"\bnew\s+Y\.UndoManager\s*\(\s*\["
    r"|"
    r"\bnew\s+Y\.UndoManager\s*\(\s*\w+\s*\.\s*(?:getText|getArray|getMap)\b"
    r"|"
    r"\bnew\s+UndoManager\s*\(\s*\["
)


# ---- C10 : crdt-sync-liveblocks-room-id-user-controlled ---------------

# Room ID passed to createRoom / enterRoom constructed from user-supplied
# URL params, query strings, or POST body without allowlist validation.
_LIVEBLOCKS_ENTER_ROOM = _re(
    r"\bcreateRoom\s*\("
    r"|"
    r"\benterRoom\s*\("
    r"|"
    r"\bclient\.enter\s*\("
    r"|"
    r"\b(?:room|roomId)\s*[=:]\s*req\."
    r"|"
    r"\b(?:room|roomId)\s*[=:]\s*params\."
    r"|"
    r"\b(?:room|roomId)\s*[=:]\s*query\."
)

_ROOM_ALLOWLIST_GUARD = _re(
    r"\bROOM_ALLOWLIST\b"
    r"|"
    r"\bALLOWED_ROOMS?\b"
    r"|"
    r"\broomAllowlist\b"
    r"|"
    r"\bvalidateRoom\b"
    r"|"
    r"\bisValidRoom\b"
)


# ---- C11 : crdt-sync-replicache-client-id-predictable -----------------

# clientID constructed from email address, username, or integer counter
# instead of a cryptographically random value.
_REPLICACHE_CLIENT_ID_WEAK = _re(
    r"\bclientID\s*[=:]\s*(?:user\.email|username|userId|user_?id|req\.user)"
    r"|"
    r"\bclientID\s*[=:]\s*String\s*\(\s*(?:Date\.now|new Date)\s*"
    r"|"
    r"\bclientID\s*[=:]\s*(?:counter|idx|index|i)\b"
    r"|"
    r"\bclientId\s*[=:]\s*(?:user\.email|username|userId|user_?id|req\.user)"
)

_REPLICACHE_CLIENT_ID_STRONG = _re(
    r"\bcrypto\.randomUUID\s*\(\s*\)"
    r"|"
    r"\buuid\s*\(\s*\)"
    r"|"
    r"\bv4\s*\(\s*\)"
    r"|"
    r"\bcrypto\.getRandomValues\b"
)


# ---- C12 : crdt-sync-yjs-provider-no-reconnect-limit ------------------

# WebsocketProvider / HocuspocusProvider without maxReconnectAttempts or
# reconnectTimeout cap, risking runaway reconnect storm.
_YJS_PROVIDER_CONSTRUCT = _re(
    r"\bnew\s+WebsocketProvider\s*\("
    r"|"
    r"\bnew\s+HocuspocusProvider\s*\("
    r"|"
    r"\bnew\s+WebrtcProvider\s*\("
)

_RECONNECT_LIMIT = _re(
    r"\bmaxReconnectAttempts\b"
    r"|"
    r"\breconnectTimeout\b"
    r"|"
    r"\bmaxRetries\b"
    r"|"
    r"\breconnectDelay\b"
)


# ---- C13 : crdt-sync-automerge-load-untrusted -------------------------

# Automerge.load() / Automerge.loadIncremental() called on data from
# network, user upload, or a query param without integrity check.
_AUTOMERGE_LOAD = _re(
    r"\bAutomerge\.load\s*\("
    r"|"
    r"\bA\.load\s*\("
    r"|"
    r"\bAutomerge\.loadIncremental\s*\("
    r"|"
    r"\bA\.loadIncremental\s*\("
)

_AUTOMERGE_LOAD_SAFE_SOURCE = _re(
    r"\bsignature\b"
    r"|"
    r"\bhmac\b"
    r"|"
    r"\bverify\b"
    r"|"
    r"\bchecksum\b"
    r"|"
    r"\bhash\b"
)

_AUTOMERGE_LOAD_UNTRUSTED_SOURCE = _re(
    r"\breq\.body\b"
    r"|"
    r"\breq\.file\b"
    r"|"
    r"\bformData\b"
    r"|"
    r"\bmultipart\b"
    r"|"
    r"\brequest\.body\b"
    r"|"
    r"\bupload\b"
)


# ---- C14 : crdt-sync-ydoc-getarray-direct-splice ----------------------

# Y.Array.toArray() result mutated with splice / push / pop directly
# instead of going through Y.Array transactional methods.
_YDOC_GETARRAY = _re(
    r"\b(?:doc|ydoc|yDoc)\s*\.\s*getArray\s*\("
    r"|"
    r"\byArray\b"
    r"|"
    r"\bydocArray\b"
)

_DIRECT_JS_SPLICE = _re(
    r"\.toArray\s*\(\s*\)\s*\.\s*(?:splice|push|pop|shift|unshift|fill|sort|reverse)\s*\("
    r"|"
    r"\bconst\s+\w+\s*=\s*\w+\.toArray\s*\(\s*\)"
)

_YJS_TRANSACTIONAL = _re(
    r"\.insert\s*\(\s*"
    r"|"
    r"\.delete\s*\(\s*"
    r"|"
    r"\.push\s*\(\s*\["
)


# ---- Build RULES tuple -------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="crdt-sync-ydoc-no-awareness-cleanup",
        name="Yjs Awareness leak — destroy() never called",
        severity="HIGH",
        description=(
            "Yjs Awareness objects accumulate stale presence entries and "
            "WebSocket message handlers when destroy() is never invoked on "
            "unmount, causing memory leaks and ghost presence indicators."
        ),
        pattern=_YDOC_AWARENESS_CREATE,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="crdt-sync-ydoc-update-no-origin-guard",
        name="Y.Doc update handler forwards updates without origin guard",
        severity="HIGH",
        description=(
            "Listening to 'update' and calling Y.applyUpdate() without "
            "checking the `origin` parameter causes an infinite broadcast "
            "loop: the re-applied update triggers the listener again."
        ),
        pattern=_YDOC_ON_UPDATE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crdt-sync-automerge-no-clone-before-mutate",
        name="Automerge.change() on shared doc reference without clone",
        severity="HIGH",
        description=(
            "Calling Automerge.change() on a reference stored in React state "
            "or a shared variable without cloning first causes the original "
            "document reference to be mutated, corrupting CRDT history."
        ),
        pattern=_AUTOMERGE_DIRECT_CHANGE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crdt-sync-liveblocks-presence-pii-broadcast",
        name="Liveblocks updatePresence() broadcasts PII to all room members",
        severity="CRITICAL",
        description=(
            "Presence fields such as email, phone, or IP address are "
            "broadcast to every participant in the Liveblocks room and "
            "persisted in room storage, constituting a PII data leak."
        ),
        pattern=_LIVEBLOCKS_UPDATE_PRESENCE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="crdt-sync-replicache-push-no-server-auth",
        name="Replicache push endpoint registered without authentication",
        severity="CRITICAL",
        description=(
            "A Replicache /push handler that processes mutations without "
            "verifying the caller's identity allows any unauthenticated "
            "client to apply arbitrary mutations to the shared dataset."
        ),
        pattern=_REPLICACHE_PUSH_ROUTE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="crdt-sync-replicache-pull-no-version-check",
        name="Replicache pull handler ignores lastMutationID / cookie",
        severity="HIGH",
        description=(
            "A /pull handler that does not read lastMutationID, fromVersion, "
            "or the sync cookie returns the full dataset on every pull instead "
            "of an incremental patch, causing data explosion and potential "
            "cross-client data leakage."
        ),
        pattern=_REPLICACHE_PULL_ROUTE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="crdt-sync-ydoc-xml-fragment-xss",
        name="Y.XmlFragment content written to innerHTML without sanitization",
        severity="HIGH",
        description=(
            "Y.XmlFragment and Y.XmlText allow arbitrary HTML; writing their "
            "content to innerHTML without DOMPurify or equivalent sanitization "
            "exposes all collaborative users to stored XSS via CRDT sync."
        ),
        pattern=_YDOC_XML_FRAGMENT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="crdt-sync-conflict-resolution-last-write-wins",
        name="Last-Write-Wins merge strategy without vector clock",
        severity="MEDIUM",
        description=(
            "LWW conflict resolution based on wall-clock time silently "
            "discards concurrent edits from clients with clock skew. "
            "A Hybrid Logical Clock or vector clock is required for "
            "causally consistent merges."
        ),
        pattern=_LWW_ASSIGNMENT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crdt-sync-undomanager-no-scope",
        name="Y.UndoManager created without type scope",
        severity="MEDIUM",
        description=(
            "Passing the Y.Doc root to UndoManager instead of a specific "
            "shared type (getText, getArray, getMap) causes the undo stack "
            "to capture remote peers' edits, breaking the undo/redo contract."
        ),
        pattern=_UNDOMANAGER_NO_SCOPE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="crdt-sync-liveblocks-room-id-user-controlled",
        name="Liveblocks room ID derived from untrusted user input",
        severity="HIGH",
        description=(
            "Constructing the room ID from URL params, query strings, or "
            "request body without allowlist validation lets any user join or "
            "create arbitrary rooms and access others' collaborative documents."
        ),
        pattern=_LIVEBLOCKS_ENTER_ROOM,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="crdt-sync-replicache-client-id-predictable",
        name="Replicache clientID derived from predictable user attribute",
        severity="MEDIUM",
        description=(
            "Using an email address, username, or sequential counter as the "
            "Replicache clientID allows an attacker to impersonate another "
            "client's mutation stream by guessing the ID."
        ),
        pattern=_REPLICACHE_CLIENT_ID_WEAK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="crdt-sync-yjs-provider-no-reconnect-limit",
        name="Yjs WebSocket provider created without reconnect cap",
        severity="MEDIUM",
        description=(
            "WebsocketProvider and HocuspocusProvider reconnect indefinitely "
            "by default. Without maxReconnectAttempts or a reconnectTimeout "
            "cap the client may generate a thundering-herd reconnect storm "
            "against a briefly unavailable server."
        ),
        pattern=_YJS_PROVIDER_CONSTRUCT,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="crdt-sync-automerge-load-untrusted",
        name="Automerge.load() called on untrusted network data",
        severity="CRITICAL",
        description=(
            "Automerge.load() and loadIncremental() execute arbitrary binary "
            "CRDT data. Passing attacker-controlled bytes (request body, file "
            "upload) without an HMAC or hash integrity check may trigger "
            "parser vulnerabilities or corrupt shared state."
        ),
        pattern=_AUTOMERGE_LOAD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="crdt-sync-ydoc-getarray-direct-splice",
        name="Y.Array.toArray() result mutated with native JS array methods",
        severity="LOW",
        description=(
            "Calling .splice(), .push(), or .pop() on the plain JavaScript "
            "array returned by Y.Array.toArray() mutates only the local copy "
            "and is not synced to other peers. Changes must go through "
            "Y.Array.insert() and Y.Array.delete()."
        ),
        pattern=_YDOC_GETARRAY,
        owasp_asi="ASI-08",
    ),
)


# ---- Internal helpers --------------------------------------------------


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


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * C1 (ydoc-no-awareness-cleanup) — Awareness created in file AND
        destroy() / off-listener absent from whole file.
      * C2 (ydoc-update-no-origin-guard) — update listener present AND
        applyUpdate called in next 20 lines AND no `origin` check.
      * C3 (automerge-no-clone-before-mutate) — direct Automerge.change()
        on named var AND Automerge.clone() absent from whole file.
      * C4 (liveblocks-presence-pii-broadcast) — updatePresence call AND
        PII field found within 10 lines.
      * C5 (replicache-push-no-server-auth) — push route AND no auth
        middleware anywhere in the file.
      * C6 (replicache-pull-no-version-check) — pull route AND no
        lastMutationID / cookie check in forward 20 lines.
      * C7 (ydoc-xml-fragment-xss) — XmlFragment creation AND innerHTML /
        insertAdjacentHTML sink in forward 15 lines AND no sanitize call.
      * C8 (conflict-resolution-lww) — LWW strategy AND no vector clock
        in whole file.
      * C9 (undomanager-no-scope) — pattern itself is high-precision; emit
        directly (scoped UndoManager already excluded by pattern shape).
      * C10 (liveblocks-room-id-user-controlled) — enterRoom / createRoom
        with user-input room ID AND no allowlist in forward 20 lines.
      * C11 (replicache-client-id-predictable) — weak clientID AND no
        strong random call in whole file.
      * C12 (yjs-provider-no-reconnect-limit) — provider construction AND
        no reconnect cap in forward 10 lines.
      * C13 (automerge-load-untrusted) — Automerge.load() AND untrusted
        source in forward 10 lines AND no integrity guard in whole file.
      * C14 (ydoc-getarray-direct-splice) — getArray call AND direct splice
        on toArray() result in forward 15 lines AND no transactional call.

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

    # ---- C1 : ydoc-no-awareness-cleanup ----
    rule_c1 = rule_by_id["crdt-sync-ydoc-no-awareness-cleanup"]
    if _file_contains(text, _YDOC_AWARENESS_CREATE) and not _file_contains(
        text, _YDOC_AWARENESS_DESTROY
    ):
        for m in _YDOC_AWARENESS_CREATE.finditer(text):
            _emit(rule_c1, m.start(), m.group(0))

    # ---- C2 : ydoc-update-no-origin-guard ----
    rule_c2 = rule_by_id["crdt-sync-ydoc-update-no-origin-guard"]
    for m in _YDOC_ON_UPDATE.finditer(text):
        window = _slice_forward(text, _line_col(text, m.start())[0], 20)
        if _file_contains(window, _YDOC_APPLY_NO_ORIGIN) and not _file_contains(
            window, _YDOC_ORIGIN_GUARD
        ):
            _emit(rule_c2, m.start(), m.group(0))

    # ---- C3 : automerge-no-clone-before-mutate ----
    rule_c3 = rule_by_id["crdt-sync-automerge-no-clone-before-mutate"]
    if not _file_contains(text, _AUTOMERGE_CLONE_GUARD):
        for m in _AUTOMERGE_DIRECT_CHANGE.finditer(text):
            _emit(rule_c3, m.start(), m.group(0))

    # ---- C4 : liveblocks-presence-pii-broadcast ----
    rule_c4 = rule_by_id["crdt-sync-liveblocks-presence-pii-broadcast"]
    for m in _LIVEBLOCKS_UPDATE_PRESENCE.finditer(text):
        window = _slice_forward(text, _line_col(text, m.start())[0], 10)
        if _file_contains(window, _PRESENCE_PII_FIELD):
            _emit(rule_c4, m.start(), m.group(0))

    # ---- C5 : replicache-push-no-server-auth ----
    rule_c5 = rule_by_id["crdt-sync-replicache-push-no-server-auth"]
    if not _file_contains(text, _AUTH_MIDDLEWARE):
        for m in _REPLICACHE_PUSH_ROUTE.finditer(text):
            _emit(rule_c5, m.start(), m.group(0))

    # ---- C6 : replicache-pull-no-version-check ----
    rule_c6 = rule_by_id["crdt-sync-replicache-pull-no-version-check"]
    for m in _REPLICACHE_PULL_ROUTE.finditer(text):
        window = _slice_forward(text, _line_col(text, m.start())[0], 20)
        if not _file_contains(window, _PULL_VERSION_CHECK):
            _emit(rule_c6, m.start(), m.group(0))

    # ---- C7 : ydoc-xml-fragment-xss ----
    rule_c7 = rule_by_id["crdt-sync-ydoc-xml-fragment-xss"]
    for m in _YDOC_XML_FRAGMENT.finditer(text):
        window = _slice_forward(text, _line_col(text, m.start())[0], 15)
        if _file_contains(window, _XSS_SINK) and not _file_contains(
            window, _SANITIZE_CALL
        ):
            _emit(rule_c7, m.start(), m.group(0))

    # ---- C8 : conflict-resolution-last-write-wins ----
    rule_c8 = rule_by_id["crdt-sync-conflict-resolution-last-write-wins"]
    if not _file_contains(text, _VECTOR_CLOCK_OR_HLC):
        for m in _LWW_ASSIGNMENT.finditer(text):
            _emit(rule_c8, m.start(), m.group(0))

    # ---- C9 : undomanager-no-scope ----
    rule_c9 = rule_by_id["crdt-sync-undomanager-no-scope"]
    if not _file_contains(text, _UNDOMANAGER_SCOPE_GUARD):
        for m in _UNDOMANAGER_NO_SCOPE.finditer(text):
            _emit(rule_c9, m.start(), m.group(0))

    # ---- C10 : liveblocks-room-id-user-controlled ----
    # Allowlist may appear before or after the enter call; check file-wide.
    rule_c10 = rule_by_id["crdt-sync-liveblocks-room-id-user-controlled"]
    if not _file_contains(text, _ROOM_ALLOWLIST_GUARD):
        for m in _LIVEBLOCKS_ENTER_ROOM.finditer(text):
            _emit(rule_c10, m.start(), m.group(0))

    # ---- C11 : replicache-client-id-predictable ----
    rule_c11 = rule_by_id["crdt-sync-replicache-client-id-predictable"]
    if not _file_contains(text, _REPLICACHE_CLIENT_ID_STRONG):
        for m in _REPLICACHE_CLIENT_ID_WEAK.finditer(text):
            _emit(rule_c11, m.start(), m.group(0))

    # ---- C12 : yjs-provider-no-reconnect-limit ----
    rule_c12 = rule_by_id["crdt-sync-yjs-provider-no-reconnect-limit"]
    for m in _YJS_PROVIDER_CONSTRUCT.finditer(text):
        window = _slice_forward(text, _line_col(text, m.start())[0], 10)
        if not _file_contains(window, _RECONNECT_LIMIT):
            _emit(rule_c12, m.start(), m.group(0))

    # ---- C13 : automerge-load-untrusted ----
    rule_c13 = rule_by_id["crdt-sync-automerge-load-untrusted"]
    if not _file_contains(text, _AUTOMERGE_LOAD_SAFE_SOURCE):
        for m in _AUTOMERGE_LOAD.finditer(text):
            window = _slice_forward(text, _line_col(text, m.start())[0], 10)
            if _file_contains(window, _AUTOMERGE_LOAD_UNTRUSTED_SOURCE):
                _emit(rule_c13, m.start(), m.group(0))

    # ---- C14 : ydoc-getarray-direct-splice ----
    rule_c14 = rule_by_id["crdt-sync-ydoc-getarray-direct-splice"]
    for m in _YDOC_GETARRAY.finditer(text):
        window = _slice_forward(text, _line_col(text, m.start())[0], 15)
        if _file_contains(window, _DIRECT_JS_SPLICE) and not _file_contains(
            window, _YJS_TRANSACTIONAL
        ):
            _emit(rule_c14, m.start(), m.group(0))

    return findings
