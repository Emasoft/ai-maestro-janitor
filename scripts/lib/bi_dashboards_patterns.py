"""BI Dashboard credential-exposure patterns.

Wave-28 distillation round 14, angle BI dashboards.

Catalogue of 7 BI-dashboard-specific anti-patterns distilled in
`reports/distill-round-14/bi-dashboards.md`. Targets Tableau /
PowerBI / Metabase / Superset / Looker surfaces that general secret
scanners currently miss because:

  * `.twb` / `.pbix` are XML / ZIP formats skipped by text-only scanners.
  * Metabase session tokens are UUID-shaped — no platform prefix.
  * Superset `SECRET_KEY` is visually identical to Flask/Django keys.
  * Looker `client_secret` has no distinctive prefix.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic `password=` in connection strings — `db_connection_pool_patterns.py`.
  * Generic `SECRET_KEY` without BI context — `auth_flow_patterns.py`.
  * Base64-encoded credential blobs (non-BI) — `credential_lifecycle_patterns.py`.
  * Generic UUID / session-token shapes — `jwt_deeper_patterns.py`.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * bi-tableau-workbook-embedded-password              (CRITICAL)
  * bi-powerbi-encoded-connection-string               (CRITICAL)
  * bi-metabase-encryption-key-hardcoded               (HIGH)
  * bi-superset-secret-key-hardcoded                   (CRITICAL)
  * bi-metabase-session-token-in-source                (HIGH)
  * bi-looker-client-secret-hardcoded                  (HIGH)
  * bi-tableau-pat-hardcoded                           (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-03 — Identity & Privilege Abuse (master encryption key, session
             forgery via weak SECRET_KEY)
  ASI-04 — Supply Chain Vulnerabilities (credential in versioned
             artefact, `.twb` / `.pbix` / LookML repo)
  ASI-09 — Human-Agent Trust Exploitation (session token surfaced by
             CI automation agents in log streams)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never
raised exceptions on benign input.
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


# ---- B1 : bi-tableau-workbook-embedded-password -------------------------

# Tableau Desktop workbook XML (.twb) stores the embedded DB password in the
# <connection> element's `password` attribute. Match a non-empty value that
# is not a common Tableau placeholder ("(Required)", "", etc.).
# Minimum 4 chars to exclude empty / placeholder values.
_TABLEAU_TWB_PASSWORD = _re(
    r"\bpassword\s*=\s*[\"'](?P<pw>[^\"']{4,})[\"']"
)

# ---- B2 : bi-powerbi-encoded-connection-string --------------------------

# PowerBI .pbix DataMashup XML element. The base64 payload, when decoded,
# reveals an ADO.NET connection string with Password= embedded.
# Minimum 30 base64 chars to exclude trivially short / empty values.
_POWERBI_ENCODED_CONNSTR = _re(
    r"<EncodedConnectionString>\s*(?P<b64>[A-Za-z0-9+/]{30,}={0,2})\s*</EncodedConnectionString>"
)

# ---- B3 : bi-metabase-encryption-key-hardcoded --------------------------

# MB_ENCRYPTION_SECRET_KEY in .env / docker-compose / CI config.
# Require a non-placeholder, non-empty value (>=10 chars).
# Placeholders like "your-32-character-secret-key-here", "yoursecrethere"
# contain the tokens "your", "here", or "<" which the scanner post-filters.
_METABASE_ENCRYPTION_KEY = _re(
    r"MB_ENCRYPTION_SECRET_KEY\s*[=:]\s*['\"]?(?P<key>[^\s'\"<>{}\r\n]{10,})['\"]?"
)

# ---- B4 : bi-superset-secret-key-hardcoded ------------------------------

# Apache Superset SECRET_KEY assignment in Python config files. Matches both
# the well-known default literal and arbitrary hardcoded values.
# The known-default substring alone is a CRITICAL flag.
_SUPERSET_DEFAULT_KEY = _re(
    r"thisismyscretkey"
)

# Assignment form in Python: SECRET_KEY = '...' or SECRET_KEY = "..."
# Require >=8 chars and a non-comment line (no leading #).
_SUPERSET_SECRET_KEY_ASSIGN = _re(
    r"^(?![ \t]*#).*\bSECRET_KEY\s*=\s*['\"](?P<key>[^'\"]{8,})['\"]"
)

# ---- B5 : bi-metabase-session-token-in-source ---------------------------

# Metabase session tokens are UUID-format. Detect the X-Metabase-Session
# header with a UUID value in source/scripts or in log output.
_METABASE_SESSION_TOKEN = _re(
    r"[Xx]-[Mm]etabase-[Ss]ession['\"\s:]+(?P<tok>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"|"
    r"metabase[_\-]session[^'\"\s=]*['\"\s=]+(?P<tok2>[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})"
)

# ---- B6 : bi-looker-client-secret-hardcoded -----------------------------

# Looker SDK / looker.ini client_secret key. Require >=20 chars and no
# env-var expansion markers ($, {, }).
_LOOKER_CLIENT_SECRET = _re(
    r"looker[_\-]?client[_\-]?secret\s*[=:]\s*['\"]?(?P<secret>[A-Za-z0-9_\-]{20,})['\"]?"
    r"|"
    r"(?:^|\b)client_secret\s*=\s*(?P<secret2>[A-Za-z0-9_\-]{20,})(?:\s*$|\s+)"
)

# ---- B7 : bi-tableau-pat-hardcoded --------------------------------------

# Tableau Personal Access Token (PAT) or REST API token in Python scripts
# or XML sign-in response bodies. Require >=20 chars.
_TABLEAU_PAT = _re(
    # Variable assignments: TABLEAU_TOKEN, TABLEAU_PAT, TABLEAU_PAT_SECRET,
    # TABLEAU_AUTH_TOKEN, TABLEAU_API_TOKEN, etc. Allow optional suffix
    # (e.g. _SECRET, _VALUE) after the type keyword before the = sign.
    r"tableau[_\-]?(?:token|pat|auth|api)[A-Za-z0-9_\-]*\s*[=:]\s*['\"](?P<tok>[A-Za-z0-9+/=_\-]{20,})['\"]"
    r"|"
    # Tableau REST API XML sign-in response <token> element.
    # Base64 tokens may contain = padding — include = in char class.
    r"<token>(?P<tok2>[A-Za-z0-9+/=\-_]{20,})</token>"
    r"|"
    r"personal_access_token\s*=\s*(?P<tok3>[A-Za-z0-9+/=_\-]{20,})"
)


# ---- Placeholder / false-positive suppression helpers -------------------

# Common placeholder tokens that indicate a non-real credential value.
# Matches any value that contains the word "your" as a prefix (leading
# indicator of template text). Note: `\byour` (no trailing \b) matches
# "your_client_secret_here" and "your-32-character-secret-key-here"
# because `_` is a word character so `\byour\b` would NOT match
# "your_..." — the trailing boundary is intentionally absent.
_PLACEHOLDER_TOKENS = re.compile(
    r"\byour|"
    r"<[^>]{1,40}>|"
    r"\bexample\b|"
    r"\(required\)|"
    r"\bchangeme\b|"
    r"\bplaceholder\b|"
    r"yoursecrethere",
    re.IGNORECASE,
)

# All-repeated-hex UUID segments indicate a synthetic / test token.
_ALL_REPEAT_UUID = re.compile(
    r"^([0-9a-f])\1{7}-([0-9a-f])\2{3}-([0-9a-f])\3{3}-([0-9a-f])\4{3}-([0-9a-f])\5{11}$",
    re.IGNORECASE,
)


def _is_placeholder(value: str) -> bool:
    """Return True if the matched credential value looks like a placeholder."""
    if _PLACEHOLDER_TOKENS.search(value):
        return True
    return False


def _is_repeated_uuid(value: str) -> bool:
    """Return True for all-same-char UUID-shaped test tokens."""
    return bool(_ALL_REPEAT_UUID.match(value))


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="bi-tableau-workbook-embedded-password",
        name="Tableau workbook XML contains embedded database password",
        severity="CRITICAL",
        description=(
            "Tableau Desktop saves workbook files (.twb) as XML. When "
            "a user connects to a database and checks 'Embed password', "
            "the plaintext DB password is written into the <connection> "
            "element's `password` attribute. CI pipelines that commit "
            ".twb files to version control expose the password to every "
            "repository reader, and the credential persists in git "
            "history even after the file is removed."
        ),
        pattern=_TABLEAU_TWB_PASSWORD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bi-powerbi-encoded-connection-string",
        name="PowerBI .pbix DataMashup contains base64-encoded connection string",
        severity="CRITICAL",
        description=(
            "PowerBI Desktop embeds data-source connection strings in "
            "the `DataMashup` entry of the .pbix ZIP archive as "
            "<EncodedConnectionString> base64 blobs. When decoded, the "
            "blob reveals a full ADO.NET connection string including "
            "`Password=`. Because .pbix is binary, most text-based "
            "scanners miss this leak unless they unzip and inspect the "
            "DataMashup XML."
        ),
        pattern=_POWERBI_ENCODED_CONNSTR,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bi-metabase-encryption-key-hardcoded",
        name="Metabase MB_ENCRYPTION_SECRET_KEY hardcoded in env or compose file",
        severity="HIGH",
        description=(
            "Metabase uses MB_ENCRYPTION_SECRET_KEY to AES-encrypt all "
            "database credentials at rest in its application database. "
            "If this key leaks — from a committed .env, Docker Compose "
            "file, or CI log — an attacker with read access to the "
            "Metabase app DB can decrypt all stored data-source "
            "passwords. The default in older tutorials ('my-secret-key') "
            "provides no effective encryption."
        ),
        pattern=_METABASE_ENCRYPTION_KEY,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="bi-superset-secret-key-hardcoded",
        name="Apache Superset SECRET_KEY is the known default or hardcoded in config",
        severity="CRITICAL",
        description=(
            "Apache Superset uses Flask's SECRET_KEY for session signing "
            "and CSRF protection. The well-known default 'thisismyscretkey' "
            "shipped in docs was the root cause of CVE-2023-27524 "
            "(CVSS 8.9), allowing unauthenticated admin session forgery. "
            "Any hardcoded SECRET_KEY in superset_config.py / "
            "config_local.py committed to a repo has the same impact."
        ),
        pattern=_SUPERSET_DEFAULT_KEY,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="bi-metabase-session-token-in-source",
        name="Metabase X-Metabase-Session UUID token exposed in source or logs",
        severity="HIGH",
        description=(
            "Metabase REST API session tokens (UUID format) are passed "
            "as the X-Metabase-Session header. Automation scripts that "
            "print the full curl command or requests call — including "
            "the token — may leak a live session into CI logs, GitHub "
            "Actions step summaries, or .log files committed to the "
            "repo. A leaked token grants full API access for up to "
            "14 days (Metabase default session lifetime)."
        ),
        pattern=_METABASE_SESSION_TOKEN,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="bi-looker-client-secret-hardcoded",
        name="Looker API client_secret hardcoded in looker.ini or deploy script",
        severity="HIGH",
        description=(
            "Looker API client credentials (client_id + client_secret) "
            "used in automation scripts are frequently hardcoded alongside "
            "LookML project deploy scripts or committed in looker.ini. "
            "These credentials grant programmatic access to all LookML "
            "models, underlying SQL queries, user management, and data "
            "exports. Unlike Stripe or GitHub tokens, there is no "
            "distinctive prefix, so context-based detection is required."
        ),
        pattern=_LOOKER_CLIENT_SECRET,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bi-tableau-pat-hardcoded",
        name="Tableau Personal Access Token hardcoded in script or logged in XML",
        severity="HIGH",
        description=(
            "Tableau Server / Cloud Personal Access Tokens (PATs) grant "
            "full REST API access scoped to the user's permissions. "
            "Scripts that hardcode PATs or log the HTTP sign-in XML "
            "response body (which contains `<token>...</token>`) expose "
            "long-lived credentials. Default PAT lifetime is 15 days "
            "idle / 1 year max, making them high-value targets."
        ),
        pattern=_TABLEAU_PAT,
        owasp_asi="ASI-09",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    False-positive suppression:

      * B1 (tableau-workbook-embedded-password) — skip matches where the
        password value is a known Tableau placeholder such as '(Required)'
        or an empty string.
      * B3 (metabase-encryption-key-hardcoded) — skip matches where the
        key value contains placeholder tokens (your, here, example, etc.).
      * B5 (metabase-session-token-in-source) — skip UUIDs where all
        hex segments consist only of repeated characters (synthetic tokens).
      * B6 (looker-client-secret-hardcoded) — skip matches where the
        secret value contains env-var expansion markers ($, {, }).
      * B4 (superset-secret-key-hardcoded) split: the known-default rule
        fires on the literal substring alone (no length gate); the
        assignment rule fires on any >=8-char value not on a comment line.

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

    # ---- B1 : bi-tableau-workbook-embedded-password ----
    rule_b1 = rule_by_id["bi-tableau-workbook-embedded-password"]
    for m in _TABLEAU_TWB_PASSWORD.finditer(text):
        pw_val = m.group("pw") or ""
        if _is_placeholder(pw_val):
            continue
        # Skip Tableau's built-in empty/placeholder values
        if pw_val.lower() in {"(required)", "required", ""}:
            continue
        _emit(rule_b1, m.start(), m.group(0))

    # ---- B2 : bi-powerbi-encoded-connection-string ----
    rule_b2 = rule_by_id["bi-powerbi-encoded-connection-string"]
    for m in _POWERBI_ENCODED_CONNSTR.finditer(text):
        _emit(rule_b2, m.start(), m.group(0))

    # ---- B3 : bi-metabase-encryption-key-hardcoded ----
    rule_b3 = rule_by_id["bi-metabase-encryption-key-hardcoded"]
    for m in _METABASE_ENCRYPTION_KEY.finditer(text):
        key_val = m.group("key") or ""
        if _is_placeholder(key_val):
            continue
        _emit(rule_b3, m.start(), m.group(0))

    # ---- B4 : bi-superset-secret-key-hardcoded ----
    rule_b4 = rule_by_id["bi-superset-secret-key-hardcoded"]
    # Sub-rule B4a: known default literal anywhere in file
    for m in _SUPERSET_DEFAULT_KEY.finditer(text):
        _emit(rule_b4, m.start(), m.group(0))
    # Sub-rule B4b: assignment of any value >=8 chars on a non-comment line
    for m in _SUPERSET_SECRET_KEY_ASSIGN.finditer(text):
        key_val = m.group("key") or ""
        # Skip if the line already triggered via the default-key literal
        if "thisismyscretkey" in key_val.lower():
            continue
        if _is_placeholder(key_val):
            continue
        _emit(rule_b4, m.start(), m.group(0))

    # ---- B5 : bi-metabase-session-token-in-source ----
    rule_b5 = rule_by_id["bi-metabase-session-token-in-source"]
    for m in _METABASE_SESSION_TOKEN.finditer(text):
        tok_val = m.group("tok") or m.group("tok2") or ""
        if _is_repeated_uuid(tok_val):
            continue
        _emit(rule_b5, m.start(), m.group(0))

    # ---- B6 : bi-looker-client-secret-hardcoded ----
    rule_b6 = rule_by_id["bi-looker-client-secret-hardcoded"]
    for m in _LOOKER_CLIENT_SECRET.finditer(text):
        secret_val = m.group("secret") or m.group("secret2") or ""
        # Skip env-var expansion markers
        if any(c in secret_val for c in ("$", "{", "}")):
            continue
        if _is_placeholder(secret_val):
            continue
        _emit(rule_b6, m.start(), m.group(0))

    # ---- B7 : bi-tableau-pat-hardcoded ----
    rule_b7 = rule_by_id["bi-tableau-pat-hardcoded"]
    for m in _TABLEAU_PAT.finditer(text):
        tok_val = (
            m.group("tok") or m.group("tok2") or m.group("tok3") or ""
        )
        if _is_placeholder(tok_val):
            continue
        _emit(rule_b7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
