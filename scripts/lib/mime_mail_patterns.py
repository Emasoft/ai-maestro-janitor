"""MIME / mail body-parser, attachment, S/MIME and calendar-invite patterns.

Wave-24 distillation round 10 — MIME / mail deeper parsing & content
attack patterns.

Catalogue of 8 mail-content-specific anti-patterns distilled in
`reports/distill-round-10/mime-mail-deeper.md`. This wave drills into
the *body parser*, *attachment-handling*, *S/MIME signature trust*, and
*calendar-invite* layers — the surfaces that turn a delivered message
into code execution, data exfiltration, or social-engineering payload.

What is NOT here (already shipped — DO NOT duplicate):

  * DKIM / SPF / DMARC, SMTP AUTH, address-header injection — those
    live in `email_smtp_patterns.py` (Wave 21). This wave protects the
    *content* (body parse, attachment, signature semantics, calendar
    method, embedded deserialization).
  * Generic DNS/email transport patterns — `dns_email_patterns.py`.

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * mime-boundary-attacker-controlled                  (HIGH)
  * mime-attachment-double-extension-rce               (CRITICAL)
  * mime-smime-chain-only-no-signature-verify          (CRITICAL)
  * mime-parser-no-strict-policy                       (MEDIUM)
  * mime-attachment-filename-rtlo-bidi                 (HIGH)
  * mime-ics-method-request-no-sender-verify           (HIGH)
  * mime-custom-header-crlf-injection                  (HIGH)
  * mime-attachment-payload-insecure-deserialize       (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-03 — Trust Boundary Violation (boundary smuggling, ICS sender,
                                     custom-header CRLF)
  ASI-04 — Input Validation Failures (parser policy, RTLO bidi,
                                       custom-header CRLF)
  ASI-05 — Lack of Authentication (S/MIME signature, ICS sender)
  ASI-06 — Lack of Resource Limits (attachment double-extension)
  ASI-07 — Output Encoding & Escaping (boundary, double-extension,
                                        RTLO, custom-header CRLF)
  ASI-09 — Insecure Cryptography (S/MIME chain-only)
  ASI-11 — Insecure Deserialization (attachment pickle/msgpack,
                                      double-extension)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    chat_bot_patterns / auth_flow_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- M1 : mime-boundary-attacker-controlled -----------------------------


# Python: msg.set_boundary(<untrusted>) or MIMEMultipart(..., boundary=<untrusted>)
# Node: nodemailer transporter.sendMail({ boundary: <untrusted>, ... })
_MIME_BOUNDARY_FROM_UNTRUSTED = _re(
    # Python set_boundary call reading from a request-shape variable
    r"\.set_boundary\s*\(\s*"
    r"(?:request|req|body|payload|data|input|user|json|form|params|kwargs|args)"
    r"[\.\[]"
    r"|"
    # Python MIMEMultipart(..., boundary=request.json[...])
    r"\bMIMEMultipart\s*\([^)]*\bboundary\s*=\s*"
    r"(?:request|req|body|payload|data|input|user|json|form|params|kwargs|args)"
    r"[\.\[]"
    r"|"
    # Node: boundary: req.body... / boundary: request.X / boundary: ctx.body...
    r"\bboundary\s*:\s*"
    r"(?:req\.body|req\.query|req\.params|request\.body|request\.json"
    r"|ctx\.body|ctx\.request|user(?:Input)?|payload|input)\.[A-Za-z_$][A-Za-z0-9_$]*"
    r"|"
    # Direct assignment: boundary = req.body.foo
    r"\bboundary\s*=\s*"
    r"(?:req\.body|req\.query|req\.params|request\.body|request\.json"
    r"|ctx\.body|ctx\.request|user(?:Input)?|payload|input)\.[A-Za-z_$][A-Za-z0-9_$]*"
)


# ---- M2 : mime-attachment-double-extension-rce --------------------------


# Filename literal with safe-looking ext followed by executable ext.
# RE2-safe: bounded char class for the "safe" part, fixed alternation
# for the "dangerous" part. The optional `[\"']?` between `filename`
# and the `[=:]` covers JSON/dict shapes like `{"filename": "..."}`
# where the key is quoted.
_MIME_DOUBLE_EXTENSION_LITERAL = _re(
    r"filename['\"]?\s*[=:]\s*['\"][^'\"<>\r\n]{1,200}"
    r"\.(?:pdf|doc|docx|xls|xlsx|ppt|pptx|txt|jpg|jpeg|png|gif|csv|rtf|odt|zip)"
    r"\.(?:exe|scr|bat|cmd|com|pif|js|vbs|ps1|jar|msi|lnk|hta|cpl|gadget|app|deb|rpm)"
    r"['\"]"
)

# Python: part.get_filename() output written to disk without sanitization.
# Stage-B: same file must contain a write call (open(...).write / fs.writeFile).
_MIME_GET_FILENAME_CALL = _re(
    r"\.get_filename\s*\(\s*\)"
    r"|"
    r"\bparams\[\s*['\"]filename['\"]\s*\]"
    r"|"
    r"\bparameters\.filename\b"
)

_MIME_WRITE_TO_DISK = _re(
    # open(..., 'wb') / open(..., "w+b"). Bounded `.{0,200}?` lets the
    # call args cross balanced parens (e.g. os.path.join(...)). The
    # non-greedy quantifier with a hard cap is RE2-safe.
    r"\bopen\s*\(.{0,200}?['\"]w[bx+]{0,2}['\"]"
    r"|"
    r"\bfs\.(?:writeFile|writeFileSync|createWriteStream)\s*\("
    r"|"
    r"\bPath\s*\([^)]{0,200}\)\.write_(?:bytes|text)\s*\("
    r"|"
    r"\.write_bytes\s*\("
    r"|"
    r"\.write\s*\(\s*part\."
)


# ---- M3 : mime-smime-chain-only-no-signature-verify ---------------------


# Trigger: certificate-chain verification call WITHOUT a signed-data
# verify call in the same code region.
_SMIME_CHAIN_VERIFY = _re(
    r"\bverify_chain\s*\("
    r"|"
    r"\bverify_certificate(?:_chain)?\s*\("
    r"|"
    r"\bx509\.verification\."
    r"|"
    r"\bload_(?:der|pem)_pkcs7_certificates\s*\("
    r"|"
    # Node: forge.pkcs7.messageFromAsn1(...)
    r"\bpkcs7\.messageFromAsn1\s*\("
    r"|"
    # cryptography: pkcs7.load_der_pkcs7_certificates(...)
    r"\bpkcs7\.load_(?:der|pem)_pkcs7_certificates\s*\("
)

_SMIME_SIGNED_DATA_VERIFY = _re(
    # Python cryptography signed-data verification surfaces
    r"\bverify_signed_data\s*\("
    r"|"
    r"\bverify_signature\s*\("
    r"|"
    # forge / node-forge signed data verify
    r"\bp7\.verify\s*\("
    r"|"
    r"\bpkcs7\.verify\s*\("
    r"|"
    # explicit signed-message verify call shapes
    r"\.verify\s*\(\s*(?:body|payload|data|content|message|msg|raw)"
)


# ---- M4 : mime-parser-no-strict-policy ----------------------------------


# Python email.parser used WITHOUT policy= keyword. Matches:
#   BytesParser()                       — compat32 (default)
#   Parser()                            — compat32
#   message_from_bytes(raw)             — compat32 (single positional arg)
#   message_from_string(raw)            — compat32
#   message_from_file(f)                — compat32
# Safe versions pass policy=... explicitly.
_EMAIL_PARSER_NO_POLICY = _re(
    # Parser-class constructor without policy=
    r"\b(?:BytesParser|FeedParser|HeaderParser|BytesHeaderParser|Parser)"
    r"\s*\(\s*\)"
    r"|"
    # message_from_* helper with single positional argument, no kw
    r"\bmessage_from_(?:bytes|string|file)\s*\(\s*"
    r"[A-Za-z_][A-Za-z0-9_\.\[\]]*"
    r"\s*\)"
)

# Same-file marker that proves policy is in scope (suppresses FP).
_EMAIL_POLICY_USED = _re(
    r"\bpolicy\s*=\s*(?:email\.)?policy\.(?:default|strict|SMTP|HTTP|compat32)"
    r"|"
    r"\bfrom\s+email\s+import\s+policy\b"
    r"|"
    r"\bfrom\s+email\.policy\s+import\s+"
)


# ---- M5 : mime-attachment-filename-rtlo-bidi ----------------------------


# Bidi-control codepoints in a filename literal — direct attack signal.
# U+202A LRE, U+202B RLE, U+202C PDF, U+202D LRO, U+202E RLO,
# U+2066 LRI, U+2067 RLI, U+2068 FSI, U+2069 PDI,
# U+200E LRM, U+200F RLM
_MIME_FILENAME_BIDI_LITERAL = _re(
    # Optional closing quote on the key (`"filename":`) before the
    # delimiter — covers JSON/dict shapes as well as MIME header forms.
    r"filename['\"]?\s*[=:]\s*['\"][^'\"\r\n]{0,300}"
    r"[‪‫‬‭‮⁦⁧⁨⁩‎‏]"  # nosec B613 -- this pattern carries bidi control chars as its detection data
    r"[^'\"\r\n]{0,300}['\"]"
)

# Trigger: get_filename() / parameters.filename without sanitization in
# the surrounding window. Stage-B: SANITIZATION_MARKER must be ABSENT.
_MIME_FILENAME_USE = _re(
    r"\.get_filename\s*\(\s*\)"
    r"|"
    r"\bparameters\.filename\b"
    r"|"
    r"\bparams\[\s*['\"]filename['\"]\s*\]"
)

_MIME_FILENAME_SANITIZATION = _re(
    r"\bunicodedata\.normalize\s*\("
    r"|"
    r"\bnormalize\s*\(\s*['\"]NF[KC]?[CD]?['\"]"
    r"|"
    r"\b(?:sanitize|sanitise)_?filename\s*\("
    r"|"
    r"\bsecure_filename\s*\("
    r"|"
    r"\bU\+202[A-E]\b"
    r"|"
    r"\b0x202[A-E]\b"
    r"|"
    r"\bBIDI_CONTROLS?\b"
    r"|"
    r"\bencode\s*\(\s*['\"]ascii['\"]\s*,\s*['\"]ignore['\"]"
)


# ---- M6 : mime-ics-method-request-no-sender-verify ----------------------


# Trigger: ICS parse call from a request body / untrusted source.
_ICS_PARSE_FROM_UNTRUSTED = _re(
    # Python icalendar.Calendar.from_ical(<src>)
    r"\bCalendar\.from_ical\s*\("
    r"|"
    # Node node-ical / ical-generator parse helpers
    r"\bical\.parseICS\s*\("
    r"|"
    r"\bical\.parseFile\s*\("
    r"|"
    r"\bnode-?ical\.parseICS\s*\("
    r"|"
    # Outlook-style: ICAL.parse / ical.js
    r"\bICAL\.parse\s*\("
)

# A METHOD:REQUEST / CANCEL / REPLY / COUNTER property in the source —
# bare text shape inside .ics content embedded in a fixture.
_ICS_METHOD_REQUEST = _re(
    r"^\s*METHOD\s*:\s*(?:REQUEST|CANCEL|REPLY|COUNTER|PUBLISH|ADD)\b"
    r"|"
    r"\bev\.method\s*===?\s*['\"]REQUEST['\"]"
    r"|"
    r"\bcal\s*\[\s*['\"]method['\"]\s*\]\s*==\s*['\"]REQUEST['\"]"
    r"|"
    r"\bcalendar\s*\[\s*['\"]method['\"]\s*\]\s*==\s*['\"]REQUEST['\"]"
)

# Stage-B: sender-trust marker — if present, suppress.
_ICS_SENDER_TRUST_MARKER = _re(
    r"\bverify_sender\s*\("
    r"|"
    r"\btrusted_(?:sender|org|domain)s?\b"
    r"|"
    r"\bsender_allowlist\b"
    r"|"
    r"\bcheck_org\s*\("
    r"|"
    r"\bauthorize_sender\s*\("
    r"|"
    r"\bALLOWED_(?:SENDERS?|ORGS?|ORGANIZERS?)\b"
    r"|"
    r"\bsender\s*(?:==|===|!=|!==|in|not in)\s*"
)


# ---- M7 : mime-custom-header-crlf-injection -----------------------------


# Node nodemailer: headers: { "X-..." : req.body.X } / etc.
_MAIL_CUSTOM_HEADER_FROM_UNTRUSTED_NODE = _re(
    # headers: { "X-Foo": req.body.bar }  (one matching pair)
    r"['\"]X-[A-Za-z][A-Za-z0-9\-]{0,40}['\"]\s*:\s*"
    r"(?:req\.body|req\.query|req\.params|request\.body|request\.query"
    r"|ctx\.body|ctx\.request|payload|input|userdata|user\.)"
    r"\.?[A-Za-z_$][A-Za-z0-9_$]*"
)

# Python email: msg["X-..."] = request.X
_MAIL_CUSTOM_HEADER_FROM_UNTRUSTED_PY = _re(
    r"\bmsg\s*\[\s*['\"]X-[A-Za-z][A-Za-z0-9\-]{0,40}['\"]\s*\]\s*=\s*"
    r"(?:request|req|body|payload|user|input|form|args|kwargs|params|data|json)"
    r"\.[A-Za-z_$][A-Za-z0-9_$]*"
    r"|"
    # msg.add_header("X-...", request.foo)
    r"\.add_header\s*\(\s*['\"]X-[A-Za-z][A-Za-z0-9\-]{0,40}['\"]\s*,\s*"
    r"(?:request|req|body|payload|user|input|form|args|kwargs|params|data|json)"
    r"\.[A-Za-z_$][A-Za-z0-9_$]*"
)

# Stage-B: if same line/region runs an explicit CRLF sanitizer, suppress.
_MAIL_HEADER_SANITIZER = _re(
    r"\breplace\s*\(\s*['\"][\\][rn]"
    r"|"
    r"\bre\.sub\s*\(\s*[r]?['\"][\\][rn]"
    r"|"
    r"\bencode_header\s*\("
    r"|"
    r"\bemail\.utils\.formataddr\s*\("
    r"|"
    r"\bquopri\.encodestring\s*\("
    r"|"
    r"\bencode_quoted_printable\s*\("
)


# ---- M8 : mime-attachment-payload-insecure-deserialize -----------------


# Deserialize call whose input expression mentions an email/MIME part shape.
_MAIL_DESERIALIZE_FROM_PART = _re(
    r"\b(?:pickle|cPickle|dill|cloudpickle|marshal|msgpack)"
    r"\.(?:loads?|unpackb?|load)\s*\(\s*"
    # bounded chunk that must include an email/MIME variable name
    r"[^)\n]{0,200}"
    r"\b(?:part|msg|payload|body|attachment|email|message|raw_email|mail)\b"
)

# Python: yaml.load(<part>...) without SafeLoader (yaml.load defaults to
# arbitrary tag instantiation pre-yaml-6.0 default-safe; legacy and many
# pinned versions remain unsafe).
_MAIL_YAML_UNSAFE_FROM_PART = _re(
    r"\byaml\.load\s*\(\s*"
    r"[^)\n]{0,200}"
    r"\b(?:part|msg|payload|body|attachment|email|message|raw_email|mail)\b"
    r"[^)\n]{0,200}\)"
)

# Stage-B: A SafeLoader / safe_load marker on the same call disqualifies it.
_MAIL_YAML_SAFE_MARKER = _re(
    r"\byaml\.safe_load\s*\("
    r"|"
    r"\bLoader\s*=\s*(?:yaml\.)?SafeLoader\b"
    r"|"
    r"\bLoader\s*=\s*(?:yaml\.)?CSafeLoader\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="mime-boundary-attacker-controlled",
        name="Multipart MIME boundary derived from untrusted input",
        severity="HIGH",
        description=(
            "The `boundary=` parameter of a multipart MIME message is "
            "derived from an attacker-controllable source (request body, "
            "query string, webhook payload). An attacker can choose a "
            "boundary string that ALSO appears inside the body content "
            "of a downstream part — receivers split on the boundary, so "
            "the smuggled-content part vanishes or a new fake part "
            "appears with attacker-chosen `Content-Type` / "
            "`Content-Disposition` that the recipient parses as a "
            "legitimate attachment."
        ),
        pattern=_MIME_BOUNDARY_FROM_UNTRUSTED,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="mime-attachment-double-extension-rce",
        name="Attachment filename with safe-looking + executable double extension",
        severity="CRITICAL",
        description=(
            "Filename literal exposes a double-extension RCE bait "
            "(e.g. `invoice.pdf.exe`, `quarterly.txt.scr`). Most OSes "
            "and email clients display only the FIRST extension; the "
            "second is the one actually executed. Code that writes the "
            "attachment to disk using the raw filename — and code that "
            "pipes the `Content-Disposition` through to a UI that lets "
            "the user 'Open' the file — creates a one-click RCE."
        ),
        pattern=_MIME_DOUBLE_EXTENSION_LITERAL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="mime-smime-chain-only-no-signature-verify",
        name="S/MIME chain validated but signed-data signature never verified",
        severity="CRITICAL",
        description=(
            "Code calls `verify_chain()` / `verify_certificate()` / "
            "`pkcs7.messageFromAsn1()` on the signer's X.509 chain but "
            "never invokes `verify_signed_data()` / `verify_signature()` "
            "on the actual signed payload. The signature is treated as "
            "a trust badge instead of a cryptographic binding to the "
            "document — ANY message signed by a key whose chain is "
            "valid is accepted, including one whose body was swapped "
            "AFTER the signature was made."
        ),
        pattern=_SMIME_CHAIN_VERIFY,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="mime-parser-no-strict-policy",
        name="email.parser instantiated without policy=email.policy.default",
        severity="MEDIUM",
        description=(
            "Python's default `email.parser` uses the *compat32* policy "
            "which silently accepts malformed headers, treats CRLF "
            "inconsistently, and does not enforce header refolding "
            "limits. Attackers exploit this with bare-LF in headers "
            "(Mutt-style 'from' smuggling), oversized header values "
            "that bypass length checks, and CRLF injection in returned "
            "values from `msg.get()`. The fix is one keyword argument "
            "— `policy=email.policy.default` — its absence is a high-"
            "signal vulnerability marker."
        ),
        pattern=_EMAIL_PARSER_NO_POLICY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="mime-attachment-filename-rtlo-bidi",
        name="Attachment filename contains bidi-control codepoints (RTLO / LRO / ...)",
        severity="HIGH",
        description=(
            "Filename literal contains Unicode bidirectional control "
            "characters (U+202A LRE, U+202B RLE, U+202C PDF, U+202D LRO, "
            "U+202E RLO, U+2066–U+2069 isolates, U+200E/U+200F marks). "
            "`invoice<RTLO>fdp.exe` displays as `invoiceexe.pdf` in "
            "most mail-client UIs but the actual file on disk is the "
            "EXE. Parsers that copy filenames verbatim from "
            "`Content-Disposition` headers without stripping or "
            "normalizing these codepoints propagate the attack."
        ),
        pattern=_MIME_FILENAME_BIDI_LITERAL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="mime-ics-method-request-no-sender-verify",
        name="ICS calendar invite parsed and acted on without sender trust check",
        severity="HIGH",
        description=(
            "An `.ics` body parsed via `icalendar.Calendar.from_ical()` "
            "/ `node-ical.parseICS()` / `ICAL.parse()` is dispatched to "
            "a calendar API based on `METHOD:REQUEST` (or `CANCEL` / "
            "`REPLY` / `COUNTER`) without verifying the sender. The "
            "attack: plant phishing events with malicious meeting-link "
            "`URL:` properties, overwrite legitimate events via "
            "colliding `UID:`, or DoS by sending thousands of "
            "`METHOD:CANCEL` events that delete real meetings."
        ),
        pattern=_ICS_PARSE_FROM_UNTRUSTED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="mime-custom-header-crlf-injection",
        name="Custom mail header (X-*) populated from untrusted input without CRLF sanitization",
        severity="HIGH",
        description=(
            "`nodemailer` / `email.mime` both accept arbitrary headers "
            "via a dict/object. Code that builds that object from user "
            "input — e.g. `headers: { 'X-Original-Subject': req.body.s }` "
            "or `msg['X-Original-IP'] = request.form['ip']` — gives the "
            "attacker a CRLF-injection vector if the input is not "
            "sanitized. The injected `\\r\\n` opens a new header (or "
            "terminates headers and begins the body), allowing BCC "
            "smuggling, custom `Reply-To` redirect, or full body "
            "replacement."
        ),
        pattern=_MAIL_CUSTOM_HEADER_FROM_UNTRUSTED_NODE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="mime-attachment-payload-insecure-deserialize",
        name="Attachment payload passed to pickle/msgpack/dill/yaml.load without safe loader",
        severity="CRITICAL",
        description=(
            "A mail-processing pipeline accepts inbound emails and "
            "reaches for `pickle.loads` / `msgpack.unpackb` / "
            "`dill.loads` / `cloudpickle.loads` / `marshal.loads` / "
            "`yaml.load` on a part of the message. Inbound email body "
            "is fully attacker-controlled content — pickle/dill/"
            "cloudpickle/marshal yield RCE, msgpack with custom "
            "ExtType handlers yields DoS / object confusion, and "
            "yaml.load without `SafeLoader` yields arbitrary Python "
            "object instantiation."
        ),
        pattern=_MAIL_DESERIALIZE_FROM_PART,
        owasp_asi="ASI-11",
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

      * M1 (boundary-attacker-controlled) — direct anchor match; no
        suppression (the attacker-controlled source IS the discriminator).
      * M2 (attachment-double-extension-rce) — direct literal match OR
        a `get_filename()` call paired with a write-to-disk call in a
        20-line forward window.
      * M3 (smime-chain-only) — anchor on the chain-verify call and
        require NO `verify_signed_data` / `verify_signature` marker in
        a 40-line window (signature verify usually appears very close
        to the chain verify).
      * M4 (parser-no-strict-policy) — anchor on the parser call and
        require NO `policy=` marker anywhere in the same file.
      * M5 (filename-rtlo-bidi) — literal-shape bidi match OR a
        `get_filename()` call with no sanitization marker in a 20-line
        forward window.
      * M6 (ics-no-sender-verify) — anchor on the ICS-parse call and
        require NO sender-trust marker in a 30-line forward window.
        ICS-content presence (METHOD:REQUEST) is a SOFT confirming
        signal (boosts confidence but not required).
      * M7 (custom-header-crlf-injection) — direct anchor (Node OR
        Python shape) with no CRLF-sanitizer marker on the same line.
      * M8 (attachment-payload-insecure-deserialize) — direct anchor.
        For yaml.load specifically, require NO SafeLoader marker in
        the same call expression.

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

    # ---- M1 : mime-boundary-attacker-controlled ----
    rule_m1 = rule_by_id["mime-boundary-attacker-controlled"]
    for m in _MIME_BOUNDARY_FROM_UNTRUSTED.finditer(text):
        _emit(rule_m1, m.start(), m.group(0))

    # ---- M2 : mime-attachment-double-extension-rce ----
    rule_m2 = rule_by_id["mime-attachment-double-extension-rce"]
    # Stage-A: direct double-extension literal in a filename= clause.
    for m in _MIME_DOUBLE_EXTENSION_LITERAL.finditer(text):
        _emit(rule_m2, m.start(), m.group(0))
    # Stage-B: get_filename() paired with a write-to-disk call in the
    # next 20 lines. High-precision (both halves required).
    for m in _MIME_GET_FILENAME_CALL.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 20)
        if _MIME_WRITE_TO_DISK.search(window) is not None:
            _emit(rule_m2, m.start(), m.group(0))

    # ---- M3 : mime-smime-chain-only-no-signature-verify ----
    rule_m3 = rule_by_id["mime-smime-chain-only-no-signature-verify"]
    for m in _SMIME_CHAIN_VERIFY.finditer(text):
        line, _ = _line_col(text, m.start())
        # Look in a 40-line window around the chain-verify call —
        # signature verification, if present, lives very close.
        window = _slice_window(text, line, 10, 30)
        if _SMIME_SIGNED_DATA_VERIFY.search(window) is not None:
            continue
        _emit(rule_m3, m.start(), m.group(0))

    # ---- M4 : mime-parser-no-strict-policy ----
    rule_m4 = rule_by_id["mime-parser-no-strict-policy"]
    # File-level: if policy= is in use anywhere in the file, treat as
    # safe (one canonical pattern per module is the dominant style).
    if not _file_contains(text, _EMAIL_POLICY_USED):
        for m in _EMAIL_PARSER_NO_POLICY.finditer(text):
            _emit(rule_m4, m.start(), m.group(0))

    # ---- M5 : mime-attachment-filename-rtlo-bidi ----
    rule_m5 = rule_by_id["mime-attachment-filename-rtlo-bidi"]
    # Stage-A: direct bidi-control codepoint in a filename literal —
    # always high precision.
    for m in _MIME_FILENAME_BIDI_LITERAL.finditer(text):
        _emit(rule_m5, m.start(), m.group(0))
    # Stage-B: get_filename() / parameters.filename used without
    # sanitization in a 20-line forward window.
    for m in _MIME_FILENAME_USE.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line, 20)
        if _MIME_FILENAME_SANITIZATION.search(window) is None:
            # Also require a write-to-disk in the same window — that is
            # the realistic attack path (open & save with attacker name).
            if _MIME_WRITE_TO_DISK.search(window) is not None:
                _emit(rule_m5, m.start(), m.group(0))

    # ---- M6 : mime-ics-method-request-no-sender-verify ----
    rule_m6 = rule_by_id["mime-ics-method-request-no-sender-verify"]
    for m in _ICS_PARSE_FROM_UNTRUSTED.finditer(text):
        line, _ = _line_col(text, m.start())
        # 30-line forward window — sender check, if present, lives in
        # the same handler body as the parse call.
        window = _slice_forward(text, line, 30)
        if _ICS_SENDER_TRUST_MARKER.search(window) is not None:
            continue
        _emit(rule_m6, m.start(), m.group(0))
    # Also flag bare-text METHOD:REQUEST anchors when they appear in
    # code (not inside .ics fixture text) — Stage-B requires the parse
    # call in the same file.
    if _file_contains(text, _ICS_PARSE_FROM_UNTRUSTED):
        for m in _ICS_METHOD_REQUEST.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 10, 20)
            if _ICS_SENDER_TRUST_MARKER.search(window) is None:
                _emit(rule_m6, m.start(), m.group(0))

    # ---- M7 : mime-custom-header-crlf-injection ----
    rule_m7 = rule_by_id["mime-custom-header-crlf-injection"]
    for m in _MAIL_CUSTOM_HEADER_FROM_UNTRUSTED_NODE.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 3, 3)
        if _MAIL_HEADER_SANITIZER.search(window) is not None:
            continue
        _emit(rule_m7, m.start(), m.group(0))
    for m in _MAIL_CUSTOM_HEADER_FROM_UNTRUSTED_PY.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 3, 3)
        if _MAIL_HEADER_SANITIZER.search(window) is not None:
            continue
        _emit(rule_m7, m.start(), m.group(0))

    # ---- M8 : mime-attachment-payload-insecure-deserialize ----
    rule_m8 = rule_by_id["mime-attachment-payload-insecure-deserialize"]
    for m in _MAIL_DESERIALIZE_FROM_PART.finditer(text):
        _emit(rule_m8, m.start(), m.group(0))
    # yaml.load(<part>...) — flag only if no SafeLoader marker in same
    # expression / nearby.
    for m in _MAIL_YAML_UNSAFE_FROM_PART.finditer(text):
        matched = m.group(0)
        if _MAIL_YAML_SAFE_MARKER.search(matched) is not None:
            continue
        _emit(rule_m8, m.start(), matched)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
