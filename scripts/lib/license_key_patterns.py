"""License key runtime validation bypass patterns.

Wave-30 distillation round 16, license key validation angle.

Catalogue of 7 license-key-specific anti-patterns distilled in
`reports/distill-round-16/license-key-validation.md`. Covers client-side
clock reliance, fail-open exception handling, environment-injectable key
paths, hardcoded magic bypass strings, MAC address binding via spoofable
syscalls, TOTP secret exposure in token payloads, and non-strict boolean
equality on license gate return values.

What is NOT here (already shipped — DO NOT duplicate):

  * SPDX identifier mismatches, LICENSE file content vs. manifest drift —
    `license_conflict_patterns.py`.
  * Timing-unsafe `==` on HMAC/digest outputs —
    `crypto_misuse_patterns.py` Rule 3.
  * SHA-1 in security paths — `crypto_misuse_patterns.py` Rule 1.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * license-key-client-side-clock-expiry                    (MEDIUM)
  * license-key-fail-open-exception                         (HIGH)
  * license-key-path-env-injectable                         (HIGH)
  * license-key-hardcoded-bypass-literal                    (CRITICAL)
  * license-key-mac-address-binding                         (MEDIUM)
  * license-key-totp-secret-in-token-payload                (CRITICAL)
  * license-key-non-strict-boolean-equality                 (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (TOTP secret in JWS payload, hardcoded bypass key)
  ASI-03 — Injection (environment variable injection into trust boundary)
  ASI-06 — Insecure Design (client-side clock, MAC spoofing, boolean coercion)
  ASI-07 — Security Misconfiguration (hardcoded bypass string / backdoor)
  ASI-04 — Authorization bypass via error (fail-open exception handler)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


def _re_dot(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+DOTALL+UNICODE.

    Use for patterns that must match across line boundaries (e.g. multi-line
    except blocks). DOTALL makes `.` match `\\n` — still RE2-safe provided
    no nested quantifiers are used.
    """
    return re.compile(
        pattern, re.IGNORECASE | re.MULTILINE | re.DOTALL | re.UNICODE
    )


# ---- LKV-01 : license-key-client-side-clock-expiry ----------------------

# Matches a Date.now(), time.time(), or datetime.now() compared against an
# expiry-semantic identifier. The negative word-character suffix avoids
# generic session/request expiry that is not license-specific.
# RE2-safe: bounded alternation, no repetition under alternation.
_CLIENT_CLOCK_EXPIRY = _re(
    r"(?:Date\.now\(\)|time\.time\(\)|datetime\.now\(\))"
    r"\s*[<>][=]?\s*"
    r"(?:[a-zA-Z_][a-zA-Z0-9_]{0,40})?"
    r"(?:license[_\-]?expir|trial[_\-]?expir|license[_\-]?ttl"
    r"|valid_until|valid_through|licen[_\-]?expir)"
)

# ---- LKV-02 : license-key-fail-open-exception ---------------------------

# Python: except block that returns True.  The except clause and the
# return statement are typically on separate lines, so DOTALL is required.
# Bounded {0,200} avoids ReDoS. RE2-safe.
_FAIL_OPEN_EXCEPT_PY = _re_dot(
    r"except\b.{0,200}?\breturn\s+True\b"
)

# JavaScript/TypeScript: catch block that returns true.  Bounded {0,300}.
_FAIL_OPEN_CATCH_JS = _re_dot(
    r"catch\s*(?:\([^)]{0,80}\))?\s*\{[^}]{0,300}return\s+true\b"
)

# ---- LKV-03 : license-key-path-env-injectable ---------------------------

# Matches os.getenv / os.environ.get / process.env reads of
# LICENSE*, LIC*, ENTITLEMENT* env vars that feed a file path.
_LICENSE_PATH_FROM_ENV = _re(
    r"(?:os\.(?:getenv|environ\.get)|process\.env)"
    r"\s*[\[(]\s*['\"]"
    r"(?:LICENSE|LIC|ENTITLEMENT)(?:_FILE|_PATH|_KEY|_CERT)"
    r"['\"]"
)

# ---- LKV-04 : license-key-hardcoded-bypass-literal ----------------------

# Matches equality checks against common magic-bypass key strings.
_HARDCODED_BYPASS_KEY = _re(
    r"(?:==|!=|in\s+|===|!==)\s*['\"]"
    r"(?:FREEDOM|MASTER[_\-]KEY|admin[_\-]?(?:override|bypass|key)"
    r"|dev[_\-]bypass|UNLOCKED|TEST[_\-]KEY|BACKDOOR|SUPER[_\-]?ADMIN)"
    r"[^'\"]{0,40}['\"]"
)

# ---- LKV-05 : license-key-mac-address-binding ---------------------------

# uuid.getnode(), os.uname().nodename, /sys/class/net/*/address, or
# subprocess call to ifconfig/ip to read MAC address.
_MAC_BINDING = _re(
    r"uuid\.getnode\(\)"
    r"|os\.uname\(\)\.nodename"
    r"|/sys/class/net/[^/\s'\"]{1,40}/address"
    r"|subprocess\.(?:check_output|run|Popen)\s*\(\s*\[['\"](?:ifconfig|ip)['\"]"
)

# ---- LKV-06 : license-key-totp-secret-in-token-payload -----------------

# JWT sign/encode call that includes a totp_secret, license_key, or
# master_key field in the payload.  Multi-line calls need DOTALL.
# Bounded {0,500} avoids ReDoS.
_TOTP_SECRET_IN_TOKEN = _re_dot(
    r"jwt\.(?:sign|encode)\s*\(.{0,500}"
    r"['\"](?:totp[_\-]?secret|license[_\-]?key|master[_\-]?key|raw[_\-]?secret)['\"]"
)

# Also catch the dict-literal / object-literal form including unquoted JS keys:
#   Python:  "totp_secret": variable  or  'totp_secret': variable
#   JS:      totp_secret: variable   (unquoted object key)
_TOTP_SECRET_DICT_FIELD = _re(
    r"(?:['\"]totp[_\-]?secret['\"]|totp[_\-]?secret)"
    r"\s*:\s*"
    r"(?:[a-zA-Z_][a-zA-Z0-9_]{0,60})"
)

# ---- LKV-07 : license-key-non-strict-boolean-equality ------------------

# Matches != False / == True / != false / == true near a license-semantic
# identifier.  Bounded {0,80} avoids ReDoS.
_NON_STRICT_BOOL_EQUALITY = _re(
    r"(?:!=\s*False|==\s*True|!=\s*false\b|==\s*true\b)"
    r"\b.{0,80}?"
    r"(?:licen|valid|check|entitle|subscri)"
    r"|(?:licen|valid|check|entitle|subscri)"
    r".{0,80}?"
    r"(?:!=\s*False|==\s*True|!=\s*false\b|==\s*true\b)"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="license-key-client-side-clock-expiry",
        name="License expiry checked against client-side clock only",
        severity="MEDIUM",
        description=(
            "A license or trial-period gate reads the current time exclusively "
            "from Date.now() (JavaScript) or datetime.now() / time.time() (Python) "
            "on the client machine and compares it to an expiry identifier. Because "
            "the check runs on hardware controlled by the end user, the system clock "
            "can be set backward to defeat any trial countdown or expiry date. "
            "Server-side time binding is required for a tamper-resistant check."
        ),
        pattern=_CLIENT_CLOCK_EXPIRY,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="license-key-fail-open-exception",
        name="License validator returns True inside broad exception handler",
        severity="HIGH",
        description=(
            "A license or API-key validation function catches all (or broad) "
            "exceptions from the network call or file read that performs the "
            "actual check and returns True (or the permissive equivalent) to "
            "allow access. An attacker who can block the validation endpoint "
            "(DNS sinkhole, firewall rule, hosts-file override) always lands "
            "in this handler and receives full access."
        ),
        pattern=_FAIL_OPEN_EXCEPT_PY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="license-key-path-env-injectable",
        name="License file path resolved from injectable environment variable",
        severity="HIGH",
        description=(
            "A license validator reads the path to the license file from an "
            "environment variable (LICENSE_FILE, LICENSE_PATH, etc.) without "
            "pinning the path to a known safe directory. An attacker who can "
            "inject into the process environment can redirect the validator to "
            "a crafted license file that grants elevated entitlements or "
            "disables feature gates."
        ),
        pattern=_LICENSE_PATH_FROM_ENV,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="license-key-hardcoded-bypass-literal",
        name="Hardcoded magic bypass key literal in license/access-control check",
        severity="CRITICAL",
        description=(
            "A license or access-control check short-circuits to 'valid' when "
            "the supplied key matches a hardcoded string literal — a backdoor "
            "left by developers for testing or emergency override. These strings "
            "are invariably committed to source control, appear in git history "
            "even after being 'removed', and can be discovered by any party "
            "with access to the repository or the compiled binary."
        ),
        pattern=_HARDCODED_BYPASS_KEY,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="license-key-mac-address-binding",
        name="License bound to MAC address via spoofable syscall",
        severity="MEDIUM",
        description=(
            "A license check reads the machine's MAC address through a spoofable "
            "mechanism: uuid.getnode() (Python), os.uname().nodename, "
            "/sys/class/net/*/address, or subprocess call to ifconfig/ip. "
            "MAC addresses can be changed by any user with administrative access. "
            "A license tied to a MAC address is trivially transferable by setting "
            "the MAC on a second machine."
        ),
        pattern=_MAC_BINDING,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="license-key-totp-secret-in-token-payload",
        name="TOTP or license secret embedded in signed-but-not-encrypted token payload",
        severity="CRITICAL",
        description=(
            "A token-based license or authentication scheme stores a raw (or "
            "base64-encoded) shared secret directly inside a JWT/JWS payload. "
            "JWS tokens are signed, not encrypted: the payload is base64-encoded "
            "JSON visible to any party who possesses the token. When the TOTP "
            "secret or license key appears in the payload, every token issuance "
            "leaks the secret to any observer who can read the token."
        ),
        pattern=_TOTP_SECRET_IN_TOKEN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="license-key-non-strict-boolean-equality",
        name="Non-strict boolean equality on license gate return value",
        severity="MEDIUM",
        description=(
            "A license validation gate is called with '== True' or '!= False' "
            "(Python) or '== true' / '!= false' (JavaScript), making the gate "
            "bypassable by any function that returns a truthy non-boolean value "
            "(e.g. 1, a non-empty string, or an object). If the license function "
            "raises an exception caught by a generic handler that returns None, "
            "'None != False' evaluates to True — incorrectly granting access."
        ),
        pattern=_NON_STRICT_BOOL_EQUALITY,
        owasp_asi="ASI-06",
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


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B context filters:

      * LKV-02 (fail-open-exception) — Python ``except … return True``
        pattern is the primary anchor; the JS ``catch … return true`` form
        is additionally checked against the same file.  Both are emitted
        under the same rule ID.
      * LKV-06 (totp-secret-in-token-payload) — jwt.sign/encode literal
        plus the standalone dict-field form ``"totp_secret": variable``
        that appears outside a sign() call; both emitted under the same ID.

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

    # ---- LKV-01 : client-side-clock-expiry ----
    rule_lkv01 = rule_by_id["license-key-client-side-clock-expiry"]
    for m in _CLIENT_CLOCK_EXPIRY.finditer(text):
        _emit(rule_lkv01, m.start(), m.group(0))

    # ---- LKV-02 : fail-open-exception ----
    rule_lkv02 = rule_by_id["license-key-fail-open-exception"]
    for m in _FAIL_OPEN_EXCEPT_PY.finditer(text):
        _emit(rule_lkv02, m.start(), m.group(0))
    for m in _FAIL_OPEN_CATCH_JS.finditer(text):
        _emit(rule_lkv02, m.start(), m.group(0))

    # ---- LKV-03 : path-env-injectable ----
    rule_lkv03 = rule_by_id["license-key-path-env-injectable"]
    for m in _LICENSE_PATH_FROM_ENV.finditer(text):
        _emit(rule_lkv03, m.start(), m.group(0))

    # ---- LKV-04 : hardcoded-bypass-literal ----
    rule_lkv04 = rule_by_id["license-key-hardcoded-bypass-literal"]
    for m in _HARDCODED_BYPASS_KEY.finditer(text):
        _emit(rule_lkv04, m.start(), m.group(0))

    # ---- LKV-05 : mac-address-binding ----
    rule_lkv05 = rule_by_id["license-key-mac-address-binding"]
    for m in _MAC_BINDING.finditer(text):
        _emit(rule_lkv05, m.start(), m.group(0))

    # ---- LKV-06 : totp-secret-in-token-payload ----
    rule_lkv06 = rule_by_id["license-key-totp-secret-in-token-payload"]
    for m in _TOTP_SECRET_IN_TOKEN.finditer(text):
        _emit(rule_lkv06, m.start(), m.group(0))
    # Also catch the dict-field form outside a sign() call
    for m in _TOTP_SECRET_DICT_FIELD.finditer(text):
        _emit(rule_lkv06, m.start(), m.group(0))

    # ---- LKV-07 : non-strict-boolean-equality ----
    rule_lkv07 = rule_by_id["license-key-non-strict-boolean-equality"]
    for m in _NON_STRICT_BOOL_EQUALITY.finditer(text):
        _emit(rule_lkv07, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
