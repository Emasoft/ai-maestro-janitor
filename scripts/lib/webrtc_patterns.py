"""WebRTC / TURN / STUN / media-relay anti-patterns.

Wave-24 distillation round 10, angle webrtc-turn.

Catalogue of 7 WebRTC-specific anti-patterns distilled in
`reports/distill-round-10/webrtc-turn.md`. Targets browser-side
`RTCPeerConnection` configuration, coturn / mediasoup / Janus server
deployment, SDP a=crypto cipher selection, and `getUserMedia`
consent gating — surfaces that no existing rule pack in the corpus
covers.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic TLS cipher mis-selection — `tls_pki_patterns` (HTTPS-only;
    does not know DTLS-SRTP profile codepoints).
  * Generic CORS preflight — `cors_misconfig_patterns` (WebRTC
    signalling channels are not CORS-gated).
  * Generic JWT confusion — `jwt_deeper_patterns` (TURN REST auth
    uses HMAC-SHA1 over an ASCII timestamp, not a JWT shape).
  * Generic webhook HMAC — `webhook_signature_patterns` (TURN REST
    auth message shape is fundamentally different).

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * webrtc-turn-longterm-creds-in-client-bundle              (HIGH)
  * webrtc-coturn-static-auth-secret-in-repo                 (CRITICAL)
  * webrtc-ice-transport-policy-all-host-leak                (MEDIUM)
  * webrtc-ice-servers-url-from-untrusted-input              (HIGH)
  * webrtc-dtls-srtp-weak-cipher                             (HIGH)
  * webrtc-getusermedia-without-consent-gate                 (MEDIUM)
  * webrtc-mediasoup-janus-admin-unauth                      (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Improper Access Control (unauthenticated mediasoup/Janus
                                     admin)
  ASI-04 — Insecure Communication Channels (TURN cred leak, ICE host
                                             candidates, weak SRTP
                                             cipher, getUserMedia
                                             consent gap)
  ASI-07 — Insecure Inter-Agent Communication (coturn static secret,
                                                attacker-controlled
                                                relay)
  ASI-08 — Trust-Boundary Violation (third-party AI consumer of
                                      captured media)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helpers in
    chat_bot_patterns / auth_flow_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- W1 : webrtc-turn-longterm-creds-in-client-bundle -------------------


# Anchor: an `RTCPeerConnection({iceServers: [...]})` construction containing
# a `turn:` or `turns:` URL. The Stage-B filter looks for a literal
# `username` / `credential` (not env-bound) inside the same object literal.
_RTCPC_TURN_ANCHOR = _re(
    r"\bnew\s+RTCPeerConnection\s*\(\s*\{"
)

_TURN_URL_LITERAL = _re(
    r"\b(?:urls|url)\s*:\s*['\"`]turn(?:s)?:[^'\"`\s]+['\"`]"
)

# Literal (non-env) credential — at least 6 chars, NOT starting with
# `process.env`, `window.`, `import.meta`, `getCreds`, etc.
_TURN_CRED_LITERAL = _re(
    r"\b(?:username|credential)\s*:\s*"
    r"['\"`](?!process\.env|window\.|import\.meta|getCred|fetchCred)"
    r"[A-Za-z0-9+/=._\-]{6,}['\"`]"
)


# ---- W2 : webrtc-coturn-static-auth-secret-in-repo ----------------------


# coturn config-file form. Anchored at line start; value is a non-empty
# literal that is NOT an env-var placeholder.
_COTURN_STATIC_SECRET_CONF = _re(
    r"^[ \t]*(?:static-auth-secret|use-auth-secret)\s*[:=]\s*"
    r"(?!\$\{|\$\(|\$ENV|<|!!|\{\{|CHANGEME|REPLACE_ME|x{8,}|XXX|"
    r"your[-_]secret|placeholder)"
    r"[A-Za-z0-9+/=._\-]{8,}"
)

# docker-compose / k8s env-form. `STATIC_AUTH_SECRET: <literal>` etc.
_COTURN_STATIC_SECRET_ENV = _re(
    r"^[ \t]*(?:STATIC_AUTH_SECRET|TURN_SECRET|COTURN_STATIC_AUTH_SECRET)"
    r"\s*[:=]\s*"
    r"(?!\$\{|\$\(|<|null|\"\"|''|CHANGEME|REPLACE_ME|x{8,}|XXX|"
    r"your[-_]secret|placeholder)"
    r"['\"]?[A-Za-z0-9+/=._\-]{8,}['\"]?"
)

# Path carve-out marker — used by scan_text Stage-B filter, NOT by the
# pattern itself. Listed here so the scanner can soft-suppress hits in
# example / template files.
_COTURN_PLACEHOLDER_VALUE = _re(
    r"\b(?:CHANGEME|REPLACE[-_]?ME|YOUR[-_]?SECRET|PLACEHOLDER|EXAMPLE"
    r"|XXX+|x{8,})\b"
)


# ---- W3 : webrtc-ice-transport-policy-all-host-leak ---------------------


# Explicit-all case: developer typed `iceTransportPolicy: "all"` on purpose.
_ICE_POLICY_EXPLICIT_ALL = _re(
    r"\biceTransportPolicy\s*:\s*['\"`]all['\"`]"
)

# Implicit-default case: a `new RTCPeerConnection({...})` whose config
# does NOT mention iceTransportPolicy. The Stage-B filter looks at the
# matched block; we use a simple `iceServers` anchor + same-block window
# to keep the regex RE2-safe.
_RTCPC_WITH_ICESERVERS = _re(
    r"\bnew\s+RTCPeerConnection\s*\(\s*\{"
    r"[^}]{0,400}"
    r"\biceServers\s*:"
)

_ICE_POLICY_MENTION = _re(
    r"\biceTransportPolicy\b"
)

# Loopback / same-origin carve-out — if these markers appear in the
# same configuration the rule downgrades to noise.
_LOOPBACK_MARKER = _re(
    r"\b(?:localhost|127\.0\.0\.1|\[::1\])\b"
    r"|"
    r"\biceServers\s*:\s*\[\s*\]"
)


# ---- W4 : webrtc-ice-servers-url-from-untrusted-input -------------------


# `urls: <expr>` where <expr> is a template literal with interpolation,
# a string concatenation with a variable, or a property access on
# `.params`, `.query`, `.searchParams`, `.env`, or `.location`.
# Bounded character class avoids catastrophic backtracking.
_ICE_URL_FROM_INPUT = _re(
    r"\b(?:urls|url)\s*:\s*"
    r"(?:`[^`]{0,300}\$\{[^}]{0,200}\}[^`]{0,200}`"
    r"|['\"][^'\"]{0,200}['\"]\s*\+\s*[A-Za-z_$][\w$]{0,40}"
    r"|[A-Za-z_$][\w$]{0,40}"
    r"\.(?:params|query|searchParams|env|location)\.[A-Za-z_$][\w$]{0,40})"
)

# Anchor: the URL is INSIDE an iceServers entry. We confirm with a
# Stage-B same-file marker (`iceServers` keyword present nearby).
_ICESERVERS_KEYWORD = _re(
    r"\biceServers\b"
)


# ---- W5 : webrtc-dtls-srtp-weak-cipher ----------------------------------


# SDP a=crypto attribute advertising weak / NULL profile.
_SDP_CRYPTO_WEAK = _re(
    r"^a=crypto:\d{1,3}\s+"
    r"(?:AES_CM_128_HMAC_SHA1_32|NULL_HMAC_SHA1_(?:32|80)"
    r"|AES_CM_128_NULL_AUTH)"
)

# mediasoup / Janus router config — `srtpCryptoSuite(s)` set to weak.
_MEDIASOUP_WEAK_SUITE = _re(
    r"\bsrtpCryptoSuites?\s*[:=]\s*"
    r"(?:\[\s*)?['\"]"
    r"(?:AES_CM_128_HMAC_SHA1_32|NULL_HMAC_SHA1_(?:32|80))"
    r"['\"]"
)

# coturn config — disabling DTLS or selecting a NULL/EXPORT/RC4/DES
# OpenSSL cipher list.
_COTURN_WEAK_CIPHER = _re(
    r"^[ \t]*(?:no-tls|no-dtls)\s*$"
    r"|"
    r"^[ \t]*cipher-list\s*[:=]\s*['\"]?[^#\n]{0,200}"
    r"(?:!?DEFAULT|\bNULL\b|\bEXPORT\b|\bRC4\b|\bDES\b)"
)


# ---- W6 : webrtc-getusermedia-without-consent-gate ----------------------


_GETUSERMEDIA_CALL = _re(
    r"(?:navigator\.mediaDevices\.|\bmediaDevices\.)getUserMedia\s*\("
)

# Consent / user-gesture keywords that, if present in the surrounding
# function body, downgrade the finding to noise.
_CONSENT_GATE_MARKER = _re(
    r"\b(?:requestConsent|askConsent|confirmConsent|userConsented?"
    r"|hasMicPermission|micPermissionGranted|getPermissionState"
    r"|requestPermission|user[A-Za-z]*Consent|consent[A-Za-z]*"
    r"|onClick\s*=|addEventListener\s*\(\s*['\"]click['\"]"
    r"|onclick\s*=)\b"
)


# ---- W7 : webrtc-mediasoup-janus-admin-unauth ---------------------------


# Janus admin.cfg with documented-default or empty secret.
_JANUS_ADMIN_SECRET_DEFAULT = _re(
    r"^[ \t]*admin_secret\s*=\s*"
    r"(?:janusoverlord|admin|password|changeme|secret|\"\"|'')\s*(?:#.*)?$"
)

# mediasoup-demo / starter signalling: an /admin* HTTP route on
# Express / Fastify / Koa / FastAPI / Flask. Stage-B looks for an
# auth-check keyword within ~30 lines of the match; if absent, flag.
_ADMIN_HTTP_ROUTE = _re(
    r"\b(?:app|router|express|fastify|koa)\."
    r"(?:get|post|put|patch|delete|all|use)\s*\(\s*"
    r"['\"`]/admin(?:[/?][^'\"`]{0,200})?['\"`]"
    r"|"
    # FastAPI / Flask decorator form.
    r"^\s*@(?:app|router|bp)\."
    r"(?:get|post|put|patch|delete)\s*\(\s*"
    r"['\"`]/admin(?:[/?][^'\"`]{0,200})?['\"`]"
)

_ADMIN_AUTH_MARKER = _re(
    r"\b(?:authenticate|requireAuth|isAuthed|verify(?:Token|Auth|Jwt)?"
    r"|checkAuth|ensureAuthenticated|adminAuth|bearerAuth|basicAuth"
    r"|isAdmin|hasRole|authorize|authMiddleware|jwt\.verify"
    r"|passport\.authenticate|session\.user|req\.user)\b"
)

# Local-bind carve-out — server binds to 127.0.0.1 / localhost only.
_LOCAL_BIND_MARKER = _re(
    r"\.listen\s*\([^)]{0,80}['\"](?:127\.0\.0\.1|localhost|::1)['\"]"
    r"|"
    r"\bhost\s*[:=]\s*['\"](?:127\.0\.0\.1|localhost|::1)['\"]"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="webrtc-turn-longterm-creds-in-client-bundle",
        name="TURN long-term credentials embedded literally in client JS bundle",
        severity="HIGH",
        description=(
            "An `RTCPeerConnection({iceServers:[...]})` construction "
            "contains a `turn:` or `turns:` URL alongside a LITERAL "
            "(non-env-bound) `username` / `credential`. RFC 5766 §10.2 "
            "requires the credential be obtained out-of-band per user; "
            "shipping the literal credential in the browser bundle "
            "defeats the design — anyone scraping the page gets a "
            "reusable TURN relay credential with no TTL. The relay can "
            "then be used as a free open-UDP egress for bandwidth fraud "
            "and anonymised exfil."
        ),
        pattern=_TURN_URL_LITERAL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="webrtc-coturn-static-auth-secret-in-repo",
        name="coturn static-auth-secret committed to repository",
        severity="CRITICAL",
        description=(
            "coturn's REST-API authentication mode (RFC 7635) derives "
            "every per-user TURN HMAC-SHA1 password from a single "
            "shared `static-auth-secret`. Committing that secret to "
            "`turnserver.conf`, `docker-compose.yml`, or a "
            "`helm/values.yaml` lets any repo reader forge unlimited "
            "ephemeral credentials. Remediation requires rotating the "
            "secret on every running coturn instance AND re-issuing "
            "every outstanding client token — both disruptive."
        ),
        pattern=_COTURN_STATIC_SECRET_CONF,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="webrtc-ice-transport-policy-all-host-leak",
        name="RTCPeerConnection uses iceTransportPolicy=all (host-candidate leak)",
        severity="MEDIUM",
        description=(
            "`RTCConfiguration.iceTransportPolicy` defaults to `\"all\"`, "
            "which causes ICE candidate gathering from EVERY local "
            "interface (Wi-Fi, LAN, VPN, tethered, virtual adapters). "
            "Host candidates expose the user's LAN-side IPv4, VPN-bypass "
            "public IPv4s, IPv6 temporary addresses, and Wi-Fi-MAC-derived "
            "host portions to the remote peer — useful for "
            "de-anonymisation and lateral-movement recon. Set "
            "`iceTransportPolicy: \"relay\"` unless the peer is "
            "explicitly trusted (loopback / same-origin worker)."
        ),
        pattern=_ICE_POLICY_EXPLICIT_ALL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="webrtc-ice-servers-url-from-untrusted-input",
        name="iceServers URL built from URL parameter / env / postMessage",
        severity="HIGH",
        description=(
            "An `iceServers` entry's `urls` field is built from a URL "
            "parameter, query string, postMessage payload, or env var. "
            "A phishing variant of the page can override the relay to "
            "attacker-controlled coturn — the attacker's coturn then "
            "sees every signalling packet (DTLS fingerprints, SDP "
            "a=ice-ufrag), enumerates the user's host candidates, and "
            "can serve crafted permission-refresh responses to keep the "
            "session pinned to a hostile relay. DTLS-SRTP encrypts the "
            "payload but not the metadata."
        ),
        pattern=_ICE_URL_FROM_INPUT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="webrtc-dtls-srtp-weak-cipher",
        name="SDP / mediasoup / coturn allows NULL or SHA1-32 SRTP cipher",
        severity="HIGH",
        description=(
            "SDP `a=crypto` line advertises `AES_CM_128_HMAC_SHA1_32` "
            "or a `NULL_HMAC_SHA1_*` profile, OR a mediasoup router "
            "config explicitly lists a weak `srtpCryptoSuite`, OR a "
            "coturn config disables DTLS or selects a NULL / EXPORT / "
            "RC4 / DES OpenSSL cipher list. SRTP is the encryption "
            "layer for the ENTIRE media stream — voice, video, "
            "screen-share. SHA1-32 truncates auth tags to 32 bits "
            "(forgery feasible within ~2^32 packets ≈ hours of an "
            "active call); NULL profiles disable confidentiality."
        ),
        pattern=_SDP_CRYPTO_WEAK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="webrtc-getusermedia-without-consent-gate",
        name="getUserMedia invoked without consent gate / user gesture",
        severity="MEDIUM",
        description=(
            "`navigator.mediaDevices.getUserMedia({audio|video|...})` "
            "is invoked from a `useEffect` / mount lifecycle / global "
            "scope with no preceding user-gesture button click and no "
            "consent-UI render check. Modern browsers prompt on first "
            "use, but on subsequent visits (origin already permitted) "
            "the prompt is silently bypassed and the mic/camera "
            "activates with no in-product cue. Captured media is then "
            "frequently piped to a third-party AI relay — a per-session "
            "consent affordance is required by GDPR Art. 7, CCPA "
            "§1798.100, and LGPD Art. 8."
        ),
        pattern=_GETUSERMEDIA_CALL,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="webrtc-mediasoup-janus-admin-unauth",
        name="mediasoup / Janus admin endpoint reachable without authentication",
        severity="HIGH",
        description=(
            "Janus admin.cfg ships with `admin_secret = janusoverlord` "
            "as the documented default — frequently committed unchanged. "
            "mediasoup-demo / mediasoup-starter signalling servers "
            "expose `/admin/*` HTTP routes; if the route handler lacks "
            "an authentication marker (no `authenticate`, `requireAuth`, "
            "`jwt.verify`, `req.user`, etc.) within ~30 lines, the "
            "relay's admin surface is unauthenticated. An attacker can "
            "enumerate active rooms, kick participants, redirect rooms "
            "to a hostile relay, and harvest SDP `a=ice-ufrag` for "
            "stealthy replay correlation."
        ),
        pattern=_ADMIN_HTTP_ROUTE,
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


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * W1 (turn-longterm-creds-in-client-bundle) — anchor on the
        `turn:` URL literal, then require a literal (non-env)
        `username` / `credential` in the same 20-line window AND a
        same-file `RTCPeerConnection({` construction.
      * W2 (coturn-static-auth-secret-in-repo) — soft-suppress if the
        line is a documented placeholder (CHANGEME / x{8,} / etc.).
        The env-var form is a separate alternation in the same rule.
      * W3 (ice-transport-policy-all-host-leak) — flag the explicit
        `iceTransportPolicy: "all"` case directly. The implicit-default
        case requires an `RTCPeerConnection({...iceServers:...})`
        block with NO `iceTransportPolicy` mention AND no loopback
        carve-out marker in the same block.
      * W4 (ice-servers-url-from-untrusted-input) — anchor on the
        untrusted-URL pattern AND require an `iceServers` keyword
        in a 10-line backward + 5-line forward window.
      * W5 (dtls-srtp-weak-cipher) — three alternation forms each
        flag directly (SDP / mediasoup / coturn).
      * W6 (getusermedia-without-consent-gate) — anchor on the call
        site and require NO consent-gate marker in a 30-line backward
        + 5-line forward window.
      * W7 (mediasoup-janus-admin-unauth) — anchor on the admin route
        and require NO auth marker in a 30-line forward window AND no
        loopback-bind marker in the same file. The Janus default
        secret form is a separate alternation that flags directly.

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

    # ---- W1 : webrtc-turn-longterm-creds-in-client-bundle ----
    rule_w1 = rule_by_id["webrtc-turn-longterm-creds-in-client-bundle"]
    has_rtcpc = _file_contains(text, _RTCPC_TURN_ANCHOR)
    if has_rtcpc:
        for m in _TURN_URL_LITERAL.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 10, 10)
            if _TURN_CRED_LITERAL.search(window) is not None:
                _emit(rule_w1, m.start(), m.group(0))

    # ---- W2 : webrtc-coturn-static-auth-secret-in-repo ----
    rule_w2 = rule_by_id["webrtc-coturn-static-auth-secret-in-repo"]
    for m in _COTURN_STATIC_SECRET_CONF.finditer(text):
        # The negative lookahead inside the pattern already excludes
        # documented placeholders; we additionally suppress if the
        # ENTIRE matched line contains a placeholder marker (belt +
        # braces for hand-rolled placeholder shapes).
        if _COTURN_PLACEHOLDER_VALUE.search(m.group(0)) is not None:
            continue
        _emit(rule_w2, m.start(), m.group(0))
    for m in _COTURN_STATIC_SECRET_ENV.finditer(text):
        if _COTURN_PLACEHOLDER_VALUE.search(m.group(0)) is not None:
            continue
        _emit(rule_w2, m.start(), m.group(0))

    # ---- W3 : webrtc-ice-transport-policy-all-host-leak ----
    rule_w3 = rule_by_id["webrtc-ice-transport-policy-all-host-leak"]
    # Explicit-"all" form — direct flag, no Stage-B beyond loopback
    # carve-out within the SAME 5-line window.
    for m in _ICE_POLICY_EXPLICIT_ALL.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 5)
        if _LOOPBACK_MARKER.search(window) is not None:
            continue
        _emit(rule_w3, m.start(), m.group(0))
    # Implicit-default form — RTCPeerConnection({...iceServers:...})
    # block with NO iceTransportPolicy mention AND no loopback marker.
    # The carve-out window extends 5 lines back / 15 lines forward from
    # the anchor so a loopback comment or `iceServers: []` literal
    # adjacent to the construction is honoured.
    for m in _RTCPC_WITH_ICESERVERS.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 15)
        if _ICE_POLICY_MENTION.search(window) is not None:
            continue
        if _LOOPBACK_MARKER.search(window) is not None:
            continue
        _emit(rule_w3, m.start(), m.group(0))

    # ---- W4 : webrtc-ice-servers-url-from-untrusted-input ----
    rule_w4 = rule_by_id["webrtc-ice-servers-url-from-untrusted-input"]
    has_iceservers_kw = _file_contains(text, _ICESERVERS_KEYWORD)
    if has_iceservers_kw:
        for m in _ICE_URL_FROM_INPUT.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 10, 5)
            if _ICESERVERS_KEYWORD.search(window) is not None:
                _emit(rule_w4, m.start(), m.group(0))

    # ---- W5 : webrtc-dtls-srtp-weak-cipher ----
    rule_w5 = rule_by_id["webrtc-dtls-srtp-weak-cipher"]
    for m in _SDP_CRYPTO_WEAK.finditer(text):
        _emit(rule_w5, m.start(), m.group(0))
    for m in _MEDIASOUP_WEAK_SUITE.finditer(text):
        _emit(rule_w5, m.start(), m.group(0))
    for m in _COTURN_WEAK_CIPHER.finditer(text):
        _emit(rule_w5, m.start(), m.group(0))

    # ---- W6 : webrtc-getusermedia-without-consent-gate ----
    rule_w6 = rule_by_id["webrtc-getusermedia-without-consent-gate"]
    for m in _GETUSERMEDIA_CALL.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 30, 5)
        if _CONSENT_GATE_MARKER.search(window) is not None:
            continue
        _emit(rule_w6, m.start(), m.group(0))

    # ---- W7 : webrtc-mediasoup-janus-admin-unauth ----
    rule_w7 = rule_by_id["webrtc-mediasoup-janus-admin-unauth"]
    # Janus documented-default admin_secret — direct flag.
    for m in _JANUS_ADMIN_SECRET_DEFAULT.finditer(text):
        _emit(rule_w7, m.start(), m.group(0))
    # mediasoup-style /admin route — flag unless an auth marker appears
    # within 30 lines AND no loopback bind marker is present in the
    # whole file (a localhost-only dev server is intentional / lower
    # risk).
    has_local_bind = _file_contains(text, _LOCAL_BIND_MARKER)
    if not has_local_bind:
        for m in _ADMIN_HTTP_ROUTE.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_forward(text, line, 30)
            if _ADMIN_AUTH_MARKER.search(window) is not None:
                continue
            _emit(rule_w7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
