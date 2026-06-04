"""Email / SMTP / MIME / IMAP deep-dive attack patterns.

Wave-21 distillation round 7, angle D.

Deep-dive past Wave 19's `dns_email_patterns.py`. Wave 19 covered the
BASICS (SPF/DKIM/DMARC records, the smtplib(host) + .login order at
file-level, nodemailer transport secure/requireTLS, CRLF-in-subject
single-line, DSN spoofing mention). This module goes DEEPER in five
orthogonal directions:

  * SMTP protocol-level smuggling (CVE-2023-51764 class) — `\\r\\n.\\r\\n`
    injection in DATA payloads.
  * MIME structural injection — attacker-controlled boundaries,
    `Subject =` assignment through `email.message`, parser-input
    desync.
  * IMAP / POP3 client-side — mailbox-name path traversal, SSL context
    with `check_hostname=False`.
  * MTA config drift — Postfix `mynetworks` too broad, missing
    `reject_unauth_destination`.
  * Mailing-list infrastructure — DSN reflection / amplification,
    listserv command-by-mail without From-verify, Maildir spool path
    traversal, SaaS-mail substitution-tag CRLF.

What is NOT here (already shipped under dns_email_patterns or
auth_flow_patterns — do not duplicate):

  * dns-smtp-tls-not-enforced            — Wave 19 catches the FILE-LEVEL
                                             nodemailer / smtplib-no-starttls
                                             shape. D4 goes DEEPER, catching
                                             `.login()` BEFORE `.starttls()`
                                             in same control-flow order.
  * dns-smtp-header-injection-unsanitized — Wave 19 catches the JS
                                             `subject: \\`${var}\\`` shape.
                                             D3 catches the Python
                                             `msg["Subject"] = value` shape
                                             (different SDK, different
                                             API surface).
  * Generic verify=False / rejectUnauthorized=false on requests/axios —
                                             auth_flow_patterns covers
                                             these. D5 narrows to smtplib /
                                             imaplib / poplib SDK-specific
                                             SSLContext shape.

What IS here (14 net-new SMTP / MIME / IMAP / MTA / mailing-list rules
from the distill round 7 angle D report):

  * email-smtp-smuggling-bare-crlf-in-body                     (CRITICAL) D1
  * email-mime-attacker-controlled-boundary                    (HIGH)     D2
  * email-mime-text-subject-contains-control                   (HIGH)     D3
  * email-smtplib-no-starttls-after-connect                    (HIGH)     D4
  * email-smtp-ssl-no-hostname-verify                          (CRITICAL) D5
  * email-imap-mailbox-name-from-user-input                    (HIGH)     D6
  * email-message-from-string-on-untrusted                     (HIGH)     D7
  * email-from-header-rfc5322-display-name-quote-injection     (HIGH)     D8
  * email-postfix-mynetworks-too-broad                         (CRITICAL) D9
  * email-postfix-recipient-restrictions-missing-unauth-reject (CRITICAL) D10
  * email-bounce-sender-not-verified-dsn-amplification         (HIGH)     D11
  * email-listserv-command-injection-via-subject-or-body       (HIGH)     D12
  * email-maildir-spool-path-traversal-from-recipient          (HIGH)     D13
  * email-sendgrid-mailgun-substitution-tag-crlf               (HIGH)     D14

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.
  * parse_postfix_main_cf(text) -> dict[str, str] — small Postfix parser
    helper used by rules D9 and D10.

OWASP ASI mapping used:
  ASI-02 — Data exfiltration / covert channels (SMTP smuggling, envelope
                                                  spoof, DSN reflection)
  ASI-04 — Insecure output / data leak       (smtplib cleartext creds,
                                                SSL-context no-verify)
  ASI-05 — Supply-chain / cross-tenant pivot (mynetworks open relay,
                                                missing reject_unauth_dest,
                                                SaaS-mail tag injection)
  ASI-07 — Authority / authorisation gaps    (MIME boundary, header
                                                CRLF, mailbox-name input,
                                                parser input, listserv
                                                command auth, Maildir
                                                path traversal)
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/agent_config_patterns.Finding
    so heartbeat detectors can render either kind uniformly."""

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
    """Compile a pattern with MULTILINE+UNICODE (no IGNORECASE by default —
    SMTP / MIME / IMAP code shapes are case-sensitive: `SMTP_SSL` is not
    `smtp_ssl`, `MIMEMultipart` is not `mimemultipart`). Per-rule overrides
    pass IGNORECASE explicitly where the underlying syntax is genuinely
    case-insensitive (mail header NAME values, Postfix config keys).

    Every pattern in this module is RE2-safe: no backreferences, no
    catastrophic-backtracking alternations, no unbounded nested
    quantifiers. Bridging windows use lazy `[\\s\\S]{0,N}?` with explicit
    upper bounds. The python `re` engine has no RE2 mode but the patterns
    are written so they would compile under RE2.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- D1: email-smtp-smuggling-bare-crlf-in-body -------------------------


# Stage-A trigger: raw socket SMTP write of a DATA payload with template
# interpolation between `DATA\r\n` and the trailing `\r\n.\r\n` terminator.
# The vulnerable shape is INTERPOLATED user content embedded in a literal
# SMTP DATA transcript without a dot-stuffing pass (RFC 5321 §4.5.2).
#
# Three concrete shapes:
#   Python: sock.send(f"DATA\r\n{body}\r\n.\r\n".encode())
#   JS:     sock.write("DATA\r\n" + body + "\r\n.\r\n")
#   JS:     sock.write(`DATA\r\n${body}\r\n.\r\n`)
#
# The 400-char bounded bridge is the per-arm content window: small enough
# to be RE2-linear, large enough to span typical handwritten SMTP wrappers.
_SMTP_SMUGGLING_TRIGGER = re.compile(
    # Arm A: Python f-string with DATA\r\n ... \r\n.\r\n shape and a
    # `{var}` interpolation inside.
    r"(?:sock|conn|s)\.send\s*\(\s*"
    r"f['\"][^'\"]{0,400}?DATA\\r\\n[^'\"]{0,400}?\{[^}]+\}[^'\"]{0,400}?\\r\\n\.\\r\\n"
    r"|"
    # Arm B: JS template-literal `DATA\r\n${...}\r\n.\r\n`
    r"(?:sock|conn|socket|client|stream)\.write\s*\(\s*"
    r"`[^`]{0,400}?DATA\\r\\n[^`]{0,400}?\$\{[^}]+\}[^`]{0,400}?\\r\\n\.\\r\\n"
    r"|"
    # Arm C: JS string concatenation: "DATA\r\n" + body + "\r\n.\r\n"
    r"(?:sock|conn|socket|client|stream)\.write\s*\(\s*"
    r"['\"]DATA\\r\\n['\"]\s*\+\s*[A-Za-z_$][\w$]*\s*\+\s*['\"]\\r\\n\.\\r\\n",
    re.MULTILINE | re.UNICODE,
)

# File-level negative guard: presence of a dot-stuffing pass (the RFC 5321
# countermeasure). Generic shapes: `.replace("\n.", "\n..")` or its regex
# / multi-line equivalents. If ANY appears, the wrapper is presumed safe.
_SMTP_DOTSTUFF_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\.replace\s*\(\s*['\"]\\n\.['\"]\s*,\s*['\"]\\n\.\.['\"]"),
    _re(r"\.replace\s*\(\s*/\^\\.\s*/m"),
    _re(r"\bdot[_-]?stuff(?:ing)?\b"),
    _re(r"#\s*smtp-smuggle-exempt\b"),
)


# ---- D2: email-mime-attacker-controlled-boundary ------------------------


# Stage-A trigger: explicit `boundary` argument to a multipart constructor
# (Python `MIMEMultipart(boundary=...)` / `set_boundary(...)`) where the
# boundary value is NOT a clear random-source literal.
#
# We also catch the JS hand-rolled multipart shape where a `Content-Type:`
# header carries `boundary=` whose value is an interpolated variable.
_MIME_BOUNDARY_TRIGGER = re.compile(
    # Python: MIMEMultipart(boundary=X) — X must be an identifier (not a
    # literal string). A literal string is suspicious only if short
    # (<16 chars), but that needs ANALYSIS — Stage-A flags the
    # name-source case.
    r"\bMIMEMultipart\s*\([^)]*\bboundary\s*=\s*[A-Za-z_][\w]*"
    r"|"
    # Python: msg.set_boundary(X) — same shape
    r"\.set_boundary\s*\(\s*[A-Za-z_][\w]*\s*\)"
    r"|"
    # Python: short literal boundary (<16 chars) - high collision risk.
    # The literal is captured for length analysis in scan_text().
    r"\bMIMEMultipart\s*\([^)]*\bboundary\s*=\s*['\"]([^'\"]{1,15})['\"]"
    r"|"
    # JS: `Content-Type: multipart/...; boundary=${var}` template
    r"Content-Type:\s*multipart/[a-zA-Z]+;\s*boundary=\$\{[^}]+\}",
    re.MULTILINE | re.UNICODE,
)

# Negative guard: if a secure-random source is referenced for the boundary,
# trust the developer. The guard is FILE-LEVEL because the random-gen call
# may sit several lines above the constructor.
_MIME_BOUNDARY_RAND_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bsecrets\.token_hex\s*\("),
    _re(r"\bsecrets\.token_urlsafe\s*\("),
    _re(r"\bcrypto\.randomBytes\s*\("),
    _re(r"\bos\.urandom\s*\("),
    _re(r"\buuid\.uuid4\s*\("),
    _re(r"\bcrypto\.randomUUID\s*\("),
    _re(r"#\s*mime-boundary-random\b"),
)


# ---- D3: email-mime-text-subject-contains-control -----------------------


# Stage-A trigger: `msg["Subject"] = expr` (or any RFC 5322 header)
# assignment in the Python email-package shape, where the right-hand-side
# is NOT a literal string and NOT wrapped in `Header(`. We also catch
# `msg.add_header("Subject", value)` and `msg.replace_header(...)`.
#
# IGNORECASE on header NAME because Python's email package case-folds
# header names — `msg["subject"]` and `msg["Subject"]` are equivalent.
_MIME_HEADER_ASSIGN = re.compile(
    # msg["Header"] = <expr>
    r"\b(?:msg|message|email|mail|mime|envelope)\s*\[\s*['\"]"
    r"(?:Subject|To|From|Cc|Bcc|Reply-To|Sender|Return-Path|"
    r"Message-ID|References|In-Reply-To|Date)"
    r"['\"]\s*\]\s*=\s*"
    r"(?!['\"][^'\"]{0,500}['\"]\s*(?:$|\n))"  # not a single-line literal
    r"[A-Za-z_][\w.()\[\]\"' +,-]*",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)

# Negative guard: same line uses `Header(`, `make_header(`, or sanitizes
# CRLF before assignment.
_MIME_HEADER_SAFE_SAMELINE = re.compile(
    r"\bHeader\s*\(|"
    r"\bmake_header\s*\(|"
    r"\.replace\s*\(\s*['\"][\\r\\n]+['\"]|"
    r"\.replace\s*\(\s*chr\s*\(\s*(?:10|13)",
    re.MULTILINE | re.UNICODE,
)


# ---- D4: email-smtplib-no-starttls-after-connect ------------------------


# Stage-A trigger: `smtplib.SMTP(host, port)` assigned to a variable,
# followed by `.login(...)` or `.sendmail(...)` on the SAME variable with
# no `.starttls()` call between.
#
# Wave 19's `dns-smtp-tls-not-enforced` is FILE-LEVEL — any `.starttls()`
# in the file suppresses the hit. This detector is STRICTER: it requires
# the .starttls() to appear in the SAME control flow (between SMTP() and
# .login()), catching the order violation where credentials hit the wire
# before TLS engages.
#
# The "between" check is done in scan_text() using a bounded text window;
# the regex captures the SMTP() assignment site.
_SMTPLIB_SMTP_CONSTRUCT = re.compile(
    # smtplib.SMTP("host", port) — NOT SMTP_SSL
    r"\bsmtplib\.SMTP\s*\(\s*"
    r"['\"]?(?P<host>[A-Za-z0-9._\-]+)?['\"]?",
    re.MULTILINE | re.UNICODE,
)

# Same shape but specifically tracking variable name through the
# subsequent .login/.sendmail call. We use a bounded forward window in
# scan_text() to find the next .login/.sendmail and check for .starttls
# in between.
_SMTPLIB_LOGIN_OR_SEND = re.compile(
    r"\.(?:login|sendmail|send_message)\s*\(",
    re.MULTILINE | re.UNICODE,
)

_SMTPLIB_STARTTLS = re.compile(
    r"\.starttls\s*\(", re.MULTILINE | re.UNICODE
)


# ---- D5: email-smtp-ssl-no-hostname-verify ------------------------------


# Stage-A trigger: SMTP_SSL / IMAP4_SSL / POP3_SSL constructor with a
# `context=` kwarg pointing to an unsafe SSLContext (check_hostname=False
# OR verify_mode=CERT_NONE). Two concrete shapes:
#
#   ctx.check_hostname = False
#   ctx.verify_mode = ssl.CERT_NONE
#   s = smtplib.SMTP_SSL(host, port, context=ctx)
#
#   ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
#   # SSLContext() defaults: check_hostname=False, verify_mode=CERT_NONE
#   s = smtplib.SMTP_SSL(host, port, context=ctx)
#
# Two-arm detector:
#   Arm 1: trigger directly on `check_hostname = False` / `CERT_NONE` in
#          file that ALSO references SMTP_SSL/IMAP4_SSL/POP3_SSL.
#   Arm 2: `ssl.SSLContext(` constructor with no follow-on safe assignment
#          (handled in scan_text()).
_MAIL_SSL_CONTEXT_UNSAFE = re.compile(
    r"\.check_hostname\s*=\s*False\b"
    r"|"
    r"\.verify_mode\s*=\s*ssl\.CERT_NONE\b"
    r"|"
    r"\bssl\._create_unverified_context\s*\(",
    re.MULTILINE | re.UNICODE,
)

# Mail-SDK context guard: only fire D5 if the file actually uses one of
# the mail SDK SSL constructors. Otherwise this is a generic SSL issue
# (handled by auth_flow_patterns).
_MAIL_SSL_SDK_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bsmtplib\.SMTP_SSL\s*\("),
    _re(r"\bimaplib\.IMAP4_SSL\s*\("),
    _re(r"\bpoplib\.POP3_SSL\s*\("),
)


# ---- D6: email-imap-mailbox-name-from-user-input ------------------------


# Stage-A trigger: imaplib operation on a mailbox name derived from
# request input. The bridging window is 200 chars between the SDK
# import / constructor and the dangerous call.
#
# Three concrete shapes:
#   imap.select(request.args["folder"])
#   imap.fetch(request.args["msgid"], "(RFC822)")
#   imap.list("INBOX", request.args["pattern"])
#
# RE2-safe: bridge is bounded `[\s\S]{0,200}?` and the argument
# capture is one bounded `[^)]*` group (no nested unbounded).
_IMAP_MAILBOX_USERINPUT = re.compile(
    r"\b(?:imap|client|conn|mailbox)\.(?:select|examine|fetch|status|"
    r"list|search|copy|rename|delete|subscribe|unsubscribe|"
    r"create|append|store)\s*\([^)]*"
    r"\b(?:request|req|input|args|form|json|body|params|user_input|"
    r"flask\.request)\b",
    re.MULTILINE | re.UNICODE,
)

# Negative guard: imap operations on hardcoded mailbox literals are safe.
# Negative guard (file-level): if the file imports `werkzeug.utils.secure_filename`
# OR has an `re.fullmatch` validator on the mailbox name, trust it.
_IMAP_MAILBOX_VALIDATE_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bsecure_filename\s*\("),
    _re(r"\bre\.fullmatch\s*\(\s*['\"][^'\"]{0,200}\bmailbox\b"),
    _re(r"\bMAILBOX_ALLOWLIST\b"),
    _re(r"#\s*imap-mailbox-validated\b"),
)


# ---- D7: email-message-from-string-on-untrusted -------------------------


# Stage-A trigger: parser entry-points from the Python email package
# called with a request-derived argument.
#
# Concrete shapes:
#   email.message_from_string(request.data)
#   email.message_from_bytes(req.body)
#   email.parser.Parser().parsestr(...)
#   email.parser.BytesParser().parsebytes(...)
_EMAIL_PARSER_UNTRUSTED = re.compile(
    r"\bemail\.message_from_(?:string|bytes)\s*\(\s*"
    r"(?:request|req|flask\.request|bottle\.request|fastapi\.Request|"
    r"input|args|form|json|body|params|user_input|stdin\.read)"
    r"|"
    r"\bemail\.parser\.(?:Bytes)?Parser\s*\(\s*\)\.parse(?:str|bytes)?\s*\(\s*"
    r"(?:request|req|flask\.request|bottle\.request|fastapi\.Request|"
    r"input|args|form|json|body|params|user_input|stdin\.read)",
    re.MULTILINE | re.UNICODE,
)


# ---- D8: email-from-header-rfc5322-display-name-quote-injection ---------


# Stage-A trigger: `"${var}" <addr>` / `f'"{var}" <addr>'` template
# construction. The displayName variable is interpolated INTO a quoted
# RFC 5322 phrase without escaping the inner `"`.
#
# Three concrete shapes:
#   JS:  `"${process.env.EMAIL_FROM_NAME}" <${FROM_ADDR}>`
#   Python: f'"{name}" <{addr}>'
#   TS:  `"${displayName}" <${addr}>`
_FROM_HEADER_INJECTION = re.compile(
    # JS / TS template-literal shape
    r"`\s*\\?\"\$\{[^}]+\}\\?\"\s*<\$\{[^}]+\}>"
    r"|"
    # Same with `from:` field context for tighter signal
    r"\bfrom\s*:\s*`\s*\\?\"\$\{[^}]+\}\\?\"\s*<"
    r"|"
    # Python f-string shape
    r"f['\"]\\?\"\{[^}]+\}\\?\"\s*<\{[^}]+\}>"
    r"|"
    # Python .format() shape
    r"['\"]\\?\"\{(?:0|[a-z_]+)\}\\?\"\s*<\{(?:0|[a-z_]+)\}>['\"]"
    r"\s*\.format\s*\(",
    re.MULTILINE | re.UNICODE,
)

# Negative guard: `.replace('"', '\\"')` (or `replace(/"/g, '\\"')`) within
# 3 lines of the construction site. We check this at the same-line level
# below (3-line window is hard to bound safely; same-line catches the
# common shape `${escape(name)}` where escape is a known sanitizer).
_FROM_HEADER_ESCAPE_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\.replace\s*\(\s*['\"]\\?\"['\"]\s*,"),
    _re(r"\.replace\s*\(\s*/\\?\"/g"),
    _re(r"\b(?:escape|sanitize|quote)(?:Display)?Name\s*\("),
    _re(r"\bemail\.utils\.formataddr\s*\("),
    _re(r"\baddressparser\.parse\b"),
    _re(r"#\s*display-name-sanitized\b"),
)


# ---- D9: email-postfix-mynetworks-too-broad -----------------------------


# Postfix configuration file detector.
# `mynetworks = ` line with broad CIDR (≥/16) or 0.0.0.0/0 / ::/0.
#
# IGNORECASE because Postfix is forgiving on key casing in main.cf
# despite docs using lowercase.
_POSTFIX_MYNETWORKS_LINE = re.compile(
    r"^\s*mynetworks\s*=\s*(.+)$",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)

# Specific bad CIDR shapes the value should NOT contain.
# Note: 127.0.0.0/8 (loopback) is excluded — that's the canonical safe
# value and must NOT trigger D9 even though it has a /8 prefix.
_POSTFIX_OPEN_CIDR = re.compile(
    r"\b0\.0\.0\.0\s*/\s*0\b"
    r"|"
    r"::\s*/\s*0\b"
    r"|"
    # /8 through /15 prefixes (but NOT 127.0.0.0/8 — see check below)
    r"\b(?:\d{1,3}\.){3}\d{1,3}\s*/\s*(?:[0-9]|1[0-5])\b",
    re.MULTILINE | re.UNICODE,
)

# Loopback CIDRs that look broad but are NOT trust violations.
_POSTFIX_LOOPBACK_CIDR = re.compile(
    r"\b127\.0\.0\.0\s*/\s*8\b",
    re.MULTILINE | re.UNICODE,
)


# ---- D10: email-postfix-recipient-restrictions-missing-unauth-reject ----


# Postfix `smtpd_(recipient|relay)_restrictions = ...` line that does NOT
# include the `reject_unauth_destination` token.
_POSTFIX_RECIP_RESTRICT_LINE = re.compile(
    r"^\s*smtpd_(?:recipient|relay)_restrictions\s*=\s*(.+)$",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- D11: email-bounce-sender-not-verified-dsn-amplification ------------


# Stage-A trigger: inbox-iteration construct (`imap.fetch`, `mailbox.Maildir`,
# `mailbox.mbox`) within 600 chars of a `smtp.sendmail` / `smtplib.send_message`
# call. The bridging window is bounded.
#
# This is the "bounce handler that resends" shape — without verifying that
# the X-Original-Recipient / In-Reply-To references a recently-sent
# message, the attacker can spoof DSNs and weaponise the relay.
_DSN_AMP_TRIGGER = re.compile(
    # Inbox-iter ... then send. `.fetch` / `.fetch_all` / `.fetch_one`
    # / `.fetch_recent` etc.
    r"\b(?:imap|client|mail)\.fetch[a-z_]*\s*\([\s\S]{0,600}?"
    r"(?:smtp|server|conn|relay)\.(?:sendmail|send_message)\s*\("
    r"|"
    r"\bmailbox\.(?:Maildir|mbox)\s*\([\s\S]{0,600}?"
    r"(?:smtp|server|conn|relay)\.(?:sendmail|send_message)\s*\(",
    re.MULTILINE | re.UNICODE,
)

# Negative guard: a recent-msgid verification step.
_DSN_AMP_VERIFY_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bSELECT[^;]{0,200}msgid\b"),
    _re(r"\bredis\.(?:exists|get)\s*\(\s*['\"]\w*msgid"),
    _re(r"\bsent_msgids\.(?:get|__contains__)"),
    _re(r"\bif\s+msgid\s+(?:in|not\s+in)\s+\w+"),
    _re(r"\bif\s+message_id\s+(?:in|not\s+in)\s+\w+"),
    _re(r"#\s*dsn-verified\b"),
)


# ---- D12: email-listserv-command-injection-via-subject-or-body ----------


# Stage-A trigger: parsing a listserv-style command from a Subject or body
# (SUBSCRIBE / UNSUBSCRIBE / SET / LIST keyword), followed by a subscribe
# call without a confirmation token.
#
# Two-arm pattern: trigger on the command keyword in a string that came
# from `msg["Subject"]` or `msg.get("Subject")`, plus a follow-on
# subscribe/unsubscribe call within 500 chars.
_LISTSERV_CMD = re.compile(
    # Same as Wave 18 but tighter — within 600 chars of an inbox-msg
    # iteration we expect SUBSCRIBE / UNSUBSCRIBE handling.
    r"\b(?:msg|message|email)\s*\[\s*['\"]Subject['\"]\s*\][\s\S]{0,300}?"
    r"\b(?:SUBSCRIBE|UNSUBSCRIBE|SET|JOIN|LEAVE)\b"
    r"|"
    r"\b(?:msg|message|email)\.get\s*\(\s*['\"]Subject['\"][\s\S]{0,300}?"
    r"\b(?:SUBSCRIBE|UNSUBSCRIBE|SET|JOIN|LEAVE)\b",
    re.MULTILINE | re.UNICODE,
)

# Negative guard: a confirmation-token mechanism in the same file.
_LISTSERV_CONFIRM_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bsecrets\.token_(?:hex|urlsafe|bytes)\s*\("),
    _re(r"\bconfirmation_token\b"),
    _re(r"\bconfirm[_-]?subscribe\b"),
    _re(r"\bdouble[_-]?opt[_-]?in\b"),
    _re(r"#\s*listserv-confirmed\b"),
)


# ---- D13: email-maildir-spool-path-traversal-from-recipient -------------


# Stage-A trigger: f-string / template-literal constructing a Maildir /
# mbox spool path with a variable substituted into `/var/mail/<X>/...`
# or `<X>/Maildir/...`.
#
# Concrete shapes:
#   spool = f"/var/mail/{recipient}/new/{uuid4()}"
#   mbox = mailbox.Maildir(f"/var/mail/{recipient}/Maildir")
_MAILDIR_PATH = re.compile(
    # Python f-string with /var/mail/{var}
    r"f['\"][^'\"]{0,200}?/var/mail/\{[A-Za-z_][\w]*\}"
    r"|"
    # Python f-string with /home/{var}/Maildir
    r"f['\"][^'\"]{0,200}?/home/\{[A-Za-z_][\w]*\}[^'\"]{0,200}?Maildir"
    r"|"
    # Python f-string ending in /Maildir or .mbox with variable
    r"f['\"][^'\"]{0,200}?\{[A-Za-z_][\w]*\}[^'\"]{0,100}?(?:/Maildir|\.mbox)"
    r"|"
    # JS template-literal /var/mail/${var}
    r"`[^`]{0,200}?/var/mail/\$\{[A-Za-z_$][\w$]*\}",
    re.MULTILINE | re.UNICODE,
)

# Negative guard: variable is normalized via secure_filename / replace.
_MAILDIR_NORMALIZE_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bsecure_filename\s*\("),
    _re(r"\.replace\s*\(\s*['\"]/['\"]"),
    _re(r"\.replace\s*\(\s*['\"]\.\.['\"]"),
    _re(r"\bos\.path\.normpath\s*\("),
    _re(r"\bpath\.normalize\s*\("),
    _re(r"\bRECIPIENT_ALLOWLIST\b"),
    _re(r"#\s*maildir-path-validated\b"),
)


# ---- D14: email-sendgrid-mailgun-substitution-tag-crlf ------------------


# Stage-A trigger: SaaS-mail provider SDK call with a `substitutions` /
# `personalizations` / `template_data` value coming from user input.
#
# Three concrete provider shapes:
#   sgMail.send({ personalizations: [{ substitutions: { '-name-': req.body.userName } }] })
#   mg.messages.create('domain', { 'h:X-Mailgun-Variables': JSON.stringify({ url: req.body.url }) })
#   SESClient.send(new SendEmailCommand({ TemplateData: JSON.stringify({ name: req.body.name }) }))
_SAAS_MAIL_SDK_TRIGGER = re.compile(
    r"\bsgMail\.send\s*\("
    r"|"
    r"\bsendgrid(?:Mail)?\.send\s*\("
    r"|"
    r"\b@sendgrid/mail\b"
    r"|"
    r"\bmg\.messages\.create\s*\("
    r"|"
    r"\bmailgun(?:-js)?\b"
    r"|"
    r"\bSendEmailCommand\s*\("
    r"|"
    r"\bSESClient\b"
    r"|"
    r"\bboto3\.client\s*\(\s*['\"]ses['\"]",
    re.MULTILINE | re.UNICODE,
)

# Substitution-with-req-input shape — the actual vulnerable line.
# The substitution-key form may be a plain identifier (`substitutions:`)
# or a quoted string (`'h:X-Mailgun-Variables':`) — handle both.
_SAAS_MAIL_SUB_USERINPUT = re.compile(
    # JS quoted key (Mailgun's `'h:X-Mailgun-Variables':`)
    r"['\"]h:X-Mailgun-Variables['\"]\s*:[\s\S]{0,500}?"
    r"\b(?:req|request)\.(?:body|params|query)\b"
    r"|"
    # JS / TS bareword key: substitutions: / personalizations: / etc.
    r"\b(?:substitutions|personalizations|template_data|TemplateData|"
    r"dynamic_template_data)\s*:[\s\S]{0,500}?"
    r"\b(?:req|request)\.(?:body|params|query)\b"
    r"|"
    # Python boto3 ses template data with request input
    r"\bTemplateData\s*=\s*[^,)]{0,200}?\b(?:request|req)\.(?:json|data|form)\b",
    re.MULTILINE | re.UNICODE,
)

# Negative guard: CRLF-stripping on the substitution value.
_SAAS_MAIL_CRLF_SAMELINE = re.compile(
    r"\.replace\s*\(\s*/\[\\?r\\?n\]/g"
    r"|"
    r"\.replace\s*\(\s*/\\?r\\?n/g"
    r"|"
    r"\.replace\s*\(\s*['\"]\\r['\"]"
    r"|"
    r"\.replace\s*\(\s*['\"]\\n['\"]"
    r"|"
    r"\bsanitize(?:Email)?(?:Value|Var)\s*\(",
    re.MULTILINE | re.UNICODE,
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="email-smtp-smuggling-bare-crlf-in-body",
        name="SMTP DATA payload with no dot-stuffing (CVE-2023-51764 class)",
        severity="CRITICAL",
        description=(
            "Raw socket SMTP write of `DATA\\r\\n{user_body}\\r\\n.\\r\\n` "
            "without a dot-stuffing pass (RFC 5321 §4.5.2 requires any "
            "body line starting with `.` to be prefixed with `..` on the "
            "wire). User content containing `\\r\\n.\\r\\n` terminates the "
            "current message; what follows is parsed as a NEW SMTP "
            "command sequence (`MAIL FROM`, `RCPT TO`, second message), "
            "delivered under the original authenticated session — see "
            "CVE-2023-51764 (Postfix), CVE-2023-51765 (Sendmail), "
            "CVE-2023-51766 (Exim). Public-knowledge anchor — corpus "
            "uses high-level SDKs that dot-stuff correctly."
        ),
        pattern=_SMTP_SMUGGLING_TRIGGER,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="email-mime-attacker-controlled-boundary",
        name="MIME multipart boundary from non-random source or too short",
        severity="HIGH",
        description=(
            "`MIMEMultipart(boundary=X)` / `set_boundary(X)` where X is a "
            "variable (potentially user-controlled) or a literal shorter "
            "than 16 chars (collision-prone — attacker chooses a body "
            "containing the boundary, splits the message into "
            "attacker-fabricated parts). RFC 2046 §5.1.1 suggests ~16 "
            "bytes of random; `secrets.token_hex(8)` / "
            "`crypto.randomBytes(8)` produce safe boundaries. "
            "Boundary-injection bypasses MIME-based AV / content "
            "filtering by hiding the second-stage payload."
        ),
        pattern=_MIME_BOUNDARY_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="email-mime-text-subject-contains-control",
        name="email.message header assigned from non-literal expression without Header() wrap",
        severity="HIGH",
        description=(
            "`msg[\"Subject\"] = value` (or `[\"To\"]`, `[\"From\"]`, "
            "`[\"Cc\"]`, `[\"Bcc\"]`, `[\"Reply-To\"]`, etc.) where "
            "`value` is not a literal and not wrapped in "
            "`email.header.Header(...)`. Under `email.policy.compat32` "
            "(historic default for `email.mime.*`), embedded `\\r\\n` "
            "in header values silently serialises into the wire "
            "message — letting attacker inject `Bcc:`, `Content-Type:`, "
            "or continuation lines that mail clients render as a new "
            "header set. Distinct from Wave 19's "
            "`dns-smtp-header-injection-unsanitized` which catches the "
            "JS / `sendmail()-from-arg` shape."
        ),
        pattern=_MIME_HEADER_ASSIGN,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="email-smtplib-no-starttls-after-connect",
        name="smtplib.SMTP().login() called before .starttls() in same flow",
        severity="HIGH",
        description=(
            "`smtplib.SMTP(host, port)` followed by `.login(user, pwd)` "
            "or `.sendmail(...)` WITHOUT a `.starttls()` call between "
            "them in the same control flow. Credentials transit in "
            "cleartext before TLS engages — any on-path network attacker "
            "captures them. Distinct from Wave 19's file-level "
            "`dns-smtp-tls-not-enforced`: this rule catches the "
            "construct-order violation, where `.starttls()` exists "
            "somewhere in the file but is called AFTER `.login()`."
        ),
        pattern=_SMTPLIB_SMTP_CONSTRUCT,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="email-smtp-ssl-no-hostname-verify",
        name="SMTP_SSL / IMAP4_SSL / POP3_SSL with check_hostname=False or CERT_NONE",
        severity="CRITICAL",
        description=(
            "Mail-SDK SSL constructor (`smtplib.SMTP_SSL`, "
            "`imaplib.IMAP4_SSL`, `poplib.POP3_SSL`) with a custom "
            "SSLContext that sets `check_hostname = False`, "
            "`verify_mode = ssl.CERT_NONE`, or uses "
            "`ssl._create_unverified_context()`. MITM-attacker reads "
            "MAIL FROM / RCPT TO / mailbox contents / credentials. "
            "Distinct from `auth-tls-verification-disabled` (which "
            "catches `verify=False` on requests/httpx) because the "
            "mail SDKs have a different SSL kwarg surface."
        ),
        pattern=_MAIL_SSL_CONTEXT_UNSAFE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="email-imap-mailbox-name-from-user-input",
        name="IMAP mailbox-name argument from request input without allowlist",
        severity="HIGH",
        description=(
            "imaplib operation (`select`, `examine`, `fetch`, `list`, "
            "`search`, `copy`, `rename`, `delete`, `subscribe`, "
            "`unsubscribe`, `create`, `append`, `store`) on a mailbox "
            "name derived from `request.args` / `req.body` / `params` "
            "without normalization. Attacker payloads: "
            "`../../another-user/INBOX` (path traversal on Dovecot "
            "mbox/Maildir mappings), `* OR 1=1` (SEARCH-criteria "
            "injection), `INBOX\"\\r\\nFETCH 1 BODY[HEADER]\\r\\n` "
            "(CRLF-in-mailbox-name command injection; imaplib does NOT "
            "sanitize CRLF in `_command()`)."
        ),
        pattern=_IMAP_MAILBOX_USERINPUT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="email-message-from-string-on-untrusted",
        name="email.message_from_string / parser on untrusted input",
        severity="HIGH",
        description=(
            "`email.message_from_string(request.data)`, "
            "`email.message_from_bytes(req.body)`, or "
            "`email.parser.Parser().parsestr(...)` with input coming "
            "from an HTTP request body / socket read. The Python email "
            "package has a fragile parser surface: CVE-2019-16056, "
            "CVE-2023-27043, CVE-2024-6232. Beyond CVEs, parsing "
            "untrusted RFC 5322 enables header-folding desync (auth "
            "gateway and renderer parse `From:` differently), "
            "encoded-word abuse (base64 → control chars / homoglyphs), "
            "and MIME re-injection via subsequent send paths."
        ),
        pattern=_EMAIL_PARSER_UNTRUSTED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="email-from-header-rfc5322-display-name-quote-injection",
        name="RFC 5322 From: template-string with unescaped display-name interpolation",
        severity="HIGH",
        description=(
            "`from = \\`\\\"${displayName}\\\" <${addr}>\\`` or Python "
            "`f'\\\"{name}\\\" <{addr}>'` where `displayName` is an "
            "interpolated variable without `\\\"` escaping. Attacker "
            "payload `Foo\\\" <evil@a.com>, \\\"Bar` parses as TWO "
            "envelope addresses (the first wins MAIL FROM), achieving "
            "cross-user envelope spoofing without needing CRLF. "
            "Distinct from Wave 19 which catches the CRLF-in-subject "
            "shape; this is the RFC 5322 quote-and-comma vector. "
            "Corpus anchor: sentinel-V2-claude `mailer.ts:88`."
        ),
        pattern=_FROM_HEADER_INJECTION,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="email-postfix-mynetworks-too-broad",
        name="Postfix mynetworks contains 0.0.0.0/0, ::/0, or /<16 prefix",
        severity="CRITICAL",
        description=(
            "Postfix `main.cf` / `master.cf` line `mynetworks = ...` "
            "containing `0.0.0.0/0`, `::/0`, or any CIDR with prefix "
            "length less than 16 (cross-tenant address space). Postfix "
            "treats `mynetworks` as the trust boundary; any source in "
            "`mynetworks` skips `smtpd_recipient_restrictions` → open "
            "relay. Result: unbounded spam attribution to that "
            "infrastructure, DKIM/SPF reputation destruction."
        ),
        pattern=_POSTFIX_MYNETWORKS_LINE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="email-postfix-recipient-restrictions-missing-unauth-reject",
        name="Postfix smtpd_recipient_restrictions without reject_unauth_destination",
        severity="CRITICAL",
        description=(
            "Postfix `smtpd_recipient_restrictions` (or "
            "`smtpd_relay_restrictions` on Postfix ≥ 2.10) line that "
            "does NOT include the `reject_unauth_destination` token. "
            "Without it, any source that ALSO doesn't match a permit "
            "rule earlier hits DEFAULT-PERMIT — open relay. Postfix "
            "documentation explicitly warns this is the #1 "
            "misconfiguration. The rule applies to every prod Postfix "
            "without exception."
        ),
        pattern=_POSTFIX_RECIP_RESTRICT_LINE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="email-bounce-sender-not-verified-dsn-amplification",
        name="Bounce handler resends without verifying original message-id",
        severity="HIGH",
        description=(
            "Inbox-iteration construct (`imap.fetch`, `mailbox.Maildir`, "
            "`mailbox.mbox`) followed (within ~600 chars) by "
            "`smtp.sendmail` / `smtplib.send_message` WITHOUT a "
            "message-id verification against a recently-sent table. "
            "Attacker sends a fake DSN-shaped message with "
            "`X-Original-Recipient: victim@target.com`; the handler "
            "believes its own message bounced and ships a fresh message "
            "to the victim — DSN reflection / amplification. Weaponizes "
            "the victim's own mail infrastructure."
        ),
        pattern=_DSN_AMP_TRIGGER,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="email-listserv-command-injection-via-subject-or-body",
        name="Listserv-style SUBSCRIBE / UNSUBSCRIBE without From-verify confirmation token",
        severity="HIGH",
        description=(
            "Code parses `msg[\"Subject\"]` / `msg.get(\"Subject\")` "
            "for `SUBSCRIBE` / `UNSUBSCRIBE` / `SET` / `JOIN` / `LEAVE` "
            "keywords and acts on them without a per-subscription "
            "confirmation token handshake. The classic LISTSERV / "
            "Majordomo / Mailman-1 vulnerability class — attacker "
            "subscribes anyone to any list (mail-bombing), or "
            "unsubscribes a target user (censorship). Mailman-3 "
            "enforces a confirmation token; rolling-your-own typically "
            "does not."
        ),
        pattern=_LISTSERV_CMD,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="email-maildir-spool-path-traversal-from-recipient",
        name="Maildir / mbox spool path constructed from recipient address without normalization",
        severity="HIGH",
        description=(
            "Template-literal / f-string constructs `/var/mail/{recipient}/...`, "
            "`/home/{recipient}/Maildir`, or `<recipient>.mbox` with "
            "`recipient` from external input. Attacker `recipient = "
            "\"../etc/cron.d\"` writes attacker-controlled content to a "
            "path used by another subsystem — arbitrary-file-write "
            "equivalent. Mitigation: `secure_filename(recipient)`, "
            "`os.path.normpath`, or strict RECIPIENT_ALLOWLIST."
        ),
        pattern=_MAILDIR_PATH,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="email-sendgrid-mailgun-substitution-tag-crlf",
        name="SaaS-mail (SendGrid/Mailgun/SES) substitution tag with un-sanitized user input",
        severity="HIGH",
        description=(
            "`sgMail.send({ personalizations: [{ substitutions: { '-name-': "
            "req.body.X } }] })`, Mailgun "
            "`h:X-Mailgun-Variables`, AWS SES `TemplateData` with values "
            "from `req.body` / `request.json` / `params` WITHOUT CRLF "
            "stripping. When the template renders the substituted value "
            "INTO a header (Subject contains `{{-name-}}`), CRLF in the "
            "value becomes a real header break on the provider's side — "
            "SendGrid's template engine does not strip CRLF. Provider "
            "docs explicitly say to pre-sanitize. Subject-injection / "
            "phishing-via-template-var; the SaaS provider's reputation "
            "is what lands the email in the inbox."
        ),
        pattern=_SAAS_MAIL_SDK_TRIGGER,
        owasp_asi="ASI-05",
    ),
)


# ---- The composed scanner -----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _line_text(text: str, line_no: int) -> str:
    """Return the full text of the 1-based line_no without trailing newline."""
    lines = text.split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


def parse_postfix_main_cf(text: str) -> dict[str, str]:
    """Parse Postfix `key = value` lines from a main.cf / master.cf file.

    Only the most-recent value per key is retained (Postfix override
    semantics). Comments (`# ...`) are stripped. Continuation lines
    (RFC 5321-ish: a line that begins with whitespace continues the
    previous logical line) are joined.

    Used by D9 and D10 to extract `mynetworks`, `smtpd_recipient_restrictions`,
    and `smtpd_relay_restrictions` values for downstream content analysis.
    """
    out: dict[str, str] = {}
    if not text:
        return out

    # First pass: join continuation lines.
    raw_lines = text.splitlines()
    logical: list[str] = []
    for line in raw_lines:
        # Strip Postfix comments (everything from `#` to EOL).
        stripped = line.split("#", 1)[0]
        if not stripped.strip():
            continue
        if line and line[0] in (" ", "\t") and logical:
            # Continuation — append to previous logical line.
            logical[-1] = logical[-1] + " " + stripped.strip()
        else:
            logical.append(stripped.rstrip())

    # Second pass: parse `key = value` lines.
    for ll in logical:
        if "=" not in ll:
            continue
        key, _, val = ll.partition("=")
        key = key.strip().lower()
        val = val.strip()
        if not key:
            continue
        out[key] = val
    return out


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Two-stage rules and their carve-outs:

      * Rule D1 (smtp-smuggling): suppress if a dot-stuffing pass is
        present anywhere in the file.
      * Rule D2 (mime-boundary): two arms — for the variable-source arm,
        suppress if a secure-random generator appears anywhere in file;
        for the literal-short-boundary arm, ALWAYS fire (length analysis
        is intrinsic).
      * Rule D3 (mime-header-assign): suppress if the same line uses
        `Header(` / `make_header(` / CRLF-strip-replace.
      * Rule D4 (smtplib-starttls-order): trigger on every smtplib.SMTP
        construction; bounded forward window to next .login/.sendmail;
        if .starttls is NOT between them, fire.
      * Rule D5 (mail-ssl-no-verify): require BOTH a mail-SDK SSL
        constructor in file AND an unsafe-context primitive.
      * Rule D6 (imap-mailbox-userinput): suppress if a mailbox validator
        guard is present in the file.
      * Rule D7 (email-parser-untrusted): no carve-outs — every match
        fires (Python email package is universally fragile on untrusted
        input).
      * Rule D8 (display-name-quote-injection): suppress if same-line OR
        a file-level escape guard is present.
      * Rule D9 (postfix-mynetworks): parse Postfix main.cf shape; flag
        broad CIDR values.
      * Rule D10 (postfix-recip-restrict): parse Postfix main.cf shape;
        flag absence of `reject_unauth_destination` token.
      * Rule D11 (dsn-amplification): suppress if a recent-msgid verify
        guard is present in the file.
      * Rule D12 (listserv-cmd-injection): suppress if a confirmation
        token guard is present in the file.
      * Rule D13 (maildir-path-traversal): suppress if a normalization
        guard is present in the file.
      * Rule D14 (saas-mail-substitution): require BOTH a SaaS-mail-SDK
        usage AND a sub-with-user-input shape; suppress if a CRLF-strip
        sanitizer is on the same line.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    # File-level guards evaluated once per scan (cheap, linear).
    smtp_dotstuff_safe = _file_contains_any(text, _SMTP_DOTSTUFF_GUARDS)
    mime_rand_safe = _file_contains_any(text, _MIME_BOUNDARY_RAND_GUARDS)
    mail_ssl_sdk_present = _file_contains_any(text, _MAIL_SSL_SDK_GUARDS)
    imap_validate_safe = _file_contains_any(text, _IMAP_MAILBOX_VALIDATE_GUARDS)
    from_header_escape_safe = _file_contains_any(
        text, _FROM_HEADER_ESCAPE_GUARDS
    )
    dsn_amp_verify_safe = _file_contains_any(text, _DSN_AMP_VERIFY_GUARDS)
    listserv_confirm_safe = _file_contains_any(text, _LISTSERV_CONFIRM_GUARDS)
    maildir_norm_safe = _file_contains_any(text, _MAILDIR_NORMALIZE_GUARDS)

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    # ---- D1 — SMTP smuggling --------------------------------------------
    if not smtp_dotstuff_safe:
        for m in _SMTP_SMUGGLING_TRIGGER.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(findings, seen, "email-smtp-smuggling-bare-crlf-in-body",
                  line, col, m.group(0))

    # ---- D2 — MIME boundary attacker-controlled -------------------------
    for m in _MIME_BOUNDARY_TRIGGER.finditer(text):
        matched = m.group(0)
        # Disambiguate the four arms by inspecting which capture matched:
        # arm 3 (literal short boundary) — always fires; the regex caps
        # length at 15 so any match means the literal is short.
        literal_short = m.group(1) if m.lastindex and m.lastindex >= 1 else None
        if literal_short is not None and len(literal_short) < 16:
            line, col = _line_col(text, m.start())
            _emit(findings, seen, "email-mime-attacker-controlled-boundary",
                  line, col, matched)
            continue
        # Other arms: suppress when a random-source guard is in the file.
        if mime_rand_safe:
            continue
        line, col = _line_col(text, m.start())
        _emit(findings, seen, "email-mime-attacker-controlled-boundary",
              line, col, matched)

    # ---- D3 — MIME / email.message header assigned -----------------------
    for m in _MIME_HEADER_ASSIGN.finditer(text):
        line, col = _line_col(text, m.start())
        ln = _line_text(text, line)
        if _MIME_HEADER_SAFE_SAMELINE.search(ln) is not None:
            continue
        _emit(findings, seen, "email-mime-text-subject-contains-control",
              line, col, m.group(0))

    # ---- D4 — smtplib login-before-starttls order ------------------------
    # For each SMTP() construction, scan forward (≤ 800 chars) for the
    # next .login / .sendmail / .send_message; if .starttls() is not in
    # between, fire.
    for m in _SMTPLIB_SMTP_CONSTRUCT.finditer(text):
        # Skip if host is literally localhost / 127.0.0.1 (dev SMTP).
        host = m.group("host") if "host" in m.groupdict() else None
        if host and host.lower() in {"localhost", "127.0.0.1", "::1"}:
            continue
        start = m.end()
        window_end = min(len(text), start + 800)
        window = text[start:window_end]
        login_match = _SMTPLIB_LOGIN_OR_SEND.search(window)
        if login_match is None:
            continue
        between = window[: login_match.start()]
        if _SMTPLIB_STARTTLS.search(between):
            continue
        line, col = _line_col(text, m.start())
        _emit(findings, seen, "email-smtplib-no-starttls-after-connect",
              line, col, m.group(0))

    # ---- D5 — mail-SDK SSL context without hostname verify --------------
    if mail_ssl_sdk_present:
        for m in _MAIL_SSL_CONTEXT_UNSAFE.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(findings, seen, "email-smtp-ssl-no-hostname-verify",
                  line, col, m.group(0))

    # ---- D6 — IMAP mailbox-name from user input -------------------------
    if not imap_validate_safe:
        for m in _IMAP_MAILBOX_USERINPUT.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(findings, seen, "email-imap-mailbox-name-from-user-input",
                  line, col, m.group(0))

    # ---- D7 — email parser on untrusted input ---------------------------
    for m in _EMAIL_PARSER_UNTRUSTED.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(findings, seen, "email-message-from-string-on-untrusted",
              line, col, m.group(0))

    # ---- D8 — display-name quote injection ------------------------------
    if not from_header_escape_safe:
        for m in _FROM_HEADER_INJECTION.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(findings, seen,
                  "email-from-header-rfc5322-display-name-quote-injection",
                  line, col, m.group(0))

    # ---- D9 — Postfix mynetworks too broad ------------------------------
    for m in _POSTFIX_MYNETWORKS_LINE.finditer(text):
        value = m.group(1) or ""
        # Strip loopback CIDR(s) from the value before checking — the
        # /8 prefix on 127.0.0.0 is intentional and safe; flagging it as
        # "broad" would produce a permanent false positive.
        value_no_loopback = _POSTFIX_LOOPBACK_CIDR.sub("", value)
        if _POSTFIX_OPEN_CIDR.search(value_no_loopback) is None:
            continue
        line, col = _line_col(text, m.start())
        _emit(findings, seen, "email-postfix-mynetworks-too-broad",
              line, col, m.group(0))

    # ---- D10 — Postfix smtpd_*_restrictions missing reject_unauth_dest --
    for m in _POSTFIX_RECIP_RESTRICT_LINE.finditer(text):
        value = m.group(1) or ""
        # Token-wise check: split on comma + whitespace; look for the
        # canonical token.
        tokens = {t.strip().lower() for t in re.split(r"[,\s]+", value) if t.strip()}
        if "reject_unauth_destination" in tokens:
            continue
        line, col = _line_col(text, m.start())
        _emit(findings, seen,
              "email-postfix-recipient-restrictions-missing-unauth-reject",
              line, col, m.group(0))

    # ---- D11 — DSN amplification ----------------------------------------
    if not dsn_amp_verify_safe:
        for m in _DSN_AMP_TRIGGER.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(findings, seen,
                  "email-bounce-sender-not-verified-dsn-amplification",
                  line, col, m.group(0))

    # ---- D12 — Listserv command injection -------------------------------
    if not listserv_confirm_safe:
        for m in _LISTSERV_CMD.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(findings, seen,
                  "email-listserv-command-injection-via-subject-or-body",
                  line, col, m.group(0))

    # ---- D13 — Maildir spool path traversal -----------------------------
    if not maildir_norm_safe:
        for m in _MAILDIR_PATH.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(findings, seen,
                  "email-maildir-spool-path-traversal-from-recipient",
                  line, col, m.group(0))

    # ---- D14 — SaaS-mail substitution-tag CRLF --------------------------
    # Require BOTH a SaaS-mail SDK trigger AND a user-input sub line.
    saas_sdk_present = _SAAS_MAIL_SDK_TRIGGER.search(text) is not None
    if saas_sdk_present:
        for m in _SAAS_MAIL_SUB_USERINPUT.finditer(text):
            line, col = _line_col(text, m.start())
            ln = _line_text(text, line)
            if _SAAS_MAIL_CRLF_SAMELINE.search(ln) is not None:
                continue
            _emit(findings, seen,
                  "email-sendgrid-mailgun-substitution-tag-crlf",
                  line, col, m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


# Rule-id → description / severity / asi lookup, populated lazily so the
# `_emit` helper is one cheap line.
_RULE_BY_ID: dict[str, Rule] = {r.id: r for r in RULES}


def _emit(
    findings: list[Finding],
    seen: set[tuple[str, int, int]],
    rule_id: str,
    line: int,
    col: int,
    matched: str,
) -> None:
    """Append a Finding to `findings`, deduping by (rule_id, line, col).
    Matched text is truncated at 200 chars to keep heartbeat output small.
    """
    key = (rule_id, line, col)
    if key in seen:
        return
    seen.add(key)
    rule = _RULE_BY_ID[rule_id]
    text = matched if len(matched) <= 200 else matched[:200] + "…"
    findings.append(Finding(
        rule_id=rule_id,
        line=line,
        column=col,
        matched_text=text,
        severity=rule.severity,
        description=rule.description,
        owasp_asi=rule.owasp_asi,
    ))
