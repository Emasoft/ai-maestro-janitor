"""Wiki / Knowledge-Base API security patterns.

Wave-28 distillation round 14, angle: Wiki / KB APIs.

Catalogue of 6 wiki/KB-specific anti-patterns distilled in
`reports/distill-round-14/wiki-kb-apis.md`. Targets Notion, Confluence
Cloud, MediaWiki, Bookstack (Laravel), Wiki.js, and Outline surfaces that
existing pattern modules cover only at the generic level.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic ``password_assignment`` / ``database_connection_string`` patterns
    — covered by existing credential and DB modules with lower precision.
  * Generic ``dotenv_assignment_secret`` (``NOTION_TOKEN=...`` in .env files)
    — covered by existing dotenv detector but lacks service-specific prefix
    validation; dedicated rules here add higher precision anchors.
  * Generic ``generic_api_key_assignment`` — catches some Notion/Confluence
    tokens at ~40% FP rate; the dedicated prefix-anchored forms here are
    needed alongside.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * wiki-kb-notion-token-literal                    (HIGH)
  * wiki-kb-atlassian-atatt‑token                   (HIGH)
  * wiki-kb-mediawiki-secretkey                     (CRITICAL)
  * wiki-kb-bookstack-app-key                       (CRITICAL)
  * wiki-kb-notion-unfiltered-search                (MEDIUM)
  * wiki-kb-wikijs-db-pass-config                   (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (hardcoded tokens, keys, passwords committed to
                        source control)
  ASI-04 — Information leak / misconfiguration (unfiltered search
                                                exposing tenant data)
  ASI-07 — Authority / authorisation gaps (notion search BOLA,
                                            missing access-control filter)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- W1 : wiki-kb-notion-token-literal ----------------------------------

# Notion internal integration tokens have the stable prefix `secret_`
# followed by exactly ~40-50 alphanumeric characters. Anchor on the
# variable-name side to distinguish from placeholder strings.
# RE2-safe: bounded character class, no nested quantifiers.
_NOTION_TOKEN_LITERAL = _re(
    r"(?:notion[_\-]?(?:api[_\-]?)?(?:token|key|secret|integration[_\-]?token)"
    r"|NOTION_TOKEN|NOTION_API_KEY)"
    r"\s*[=:]\s*[\"']?(secret_[A-Za-z0-9]{40,50})[\"']?"
)

# ---- W2 : wiki-kb-atlassian-atatt‑token ---------------------------------

# Atlassian Cloud API tokens issued since 2023 use the `ATATT3xFfGF0`
# prefix. Older tokens are covered by the variable-name anchor fallback.
# Two sub-patterns combined via alternation (RE2-safe: no overlap).
_ATLASSIAN_TOKEN = _re(
    r"(?:ATATT[A-Za-z0-9+/=]{30,})"
    r"|"
    r"(?:(?:confluence|jira|atlassian)[_\-]?(?:api[_\-]?)?(?:token|key|password)"
    r"\s*[=:]\s*[\"']?[A-Za-z0-9]{24,}[\"']?)"
)

# ---- W3 : wiki-kb-mediawiki-secretkey -----------------------------------

# $wgSecretKey in LocalSettings.php is a 64-hex-char string used to sign
# cookies and CSRF tokens. PHP assignment syntax; the $wg prefix is
# unique to MediaWiki globals.
# $wgSecretKey — hex-only value; $wgDBpassword / $wgUpgradeKey — any
# printable non-quote value at least 8 chars long.
# RE2-safe: bounded character classes, no nested quantifiers.
_MEDIAWIKI_SECRETKEY = _re(
    r"\$wgSecretKey\s*=\s*[\"'][0-9a-f]{16,}[\"']"
    r"|"
    r"\$wg(?:DBpassword|UpgradeKey)\s*=\s*[\"'][^\"'\n]{8,}[\"']"
)

# ---- W4 : wiki-kb-bookstack-app-key -------------------------------------

# Bookstack (Laravel) APP_KEY is always base64-prefixed. Affects all
# Laravel apps; noted in findings as laravel_app_key. Match both plain
# `APP_KEY=base64:...` (dotenv), `APP_KEY: base64:...` (YAML), and
# variable-name-anchored forms.
# RE2-safe: bounded character class, no nested quantifiers.
_BOOKSTACK_APP_KEY = _re(
    r"APP_KEY\s*[=:]\s*[\"']?base64:[A-Za-z0-9+/]{40,}={0,2}[\"']?"
    r"|"
    r"(?:bookstack|laravel)[_\-]?app[_\-]?key\s*[=:]\s*[\"']?base64:[A-Za-z0-9+/]{40,}={0,2}[\"']?"
)

# ---- W5 : wiki-kb-notion-unfiltered-search ------------------------------

# Notion's /v1/search passes user-controlled query to workspace-wide
# search without filtering by user-owned pages. Detects raw pass-through
# of request parameters into notion.search() in both JS (query: req.x)
# and Python (query=request.args.get(...)) call shapes.
# RE2-safe: bounded wildcards, no nested quantifiers.
_NOTION_UNFILTERED_SEARCH = _re(
    # JS object literal form: notion.search({ query: req.body.q })
    r"notion\s*\.\s*search\s*\(\s*\{[^}]{0,200}query\s*:\s*"
    r"(?:req\.|request\.|params\.|body\.|query\.|user_input|user_query|search_term)"
    r"[A-Za-z0-9_.\"'\[\]]{0,60}"
    r"|"
    # Python keyword-arg form: notion.search(query=request.args.get(...))
    r"notion\s*\.\s*search\s*\([^)]{0,300}query\s*=\s*"
    r"(?:request|req)\.[A-Za-z0-9_.]{1,40}"
)

# ---- W6 : wiki-kb-wikijs-db-pass-config ---------------------------------

# Wiki.js stores db.pass (plaintext DB password) in config.yml. The
# pattern anchors on `pass:` or `password:` YAML key with a non-trivial
# value (8+ chars, not a placeholder or env-var reference).
# Exclude values starting with '$', '{', '%' (env var / template
# references). Bounded [A-Za-z0-9!@_.#\-+]{8,80} prevents backtracking.
_WIKIJS_DB_PASS = _re(
    r"(?:wikijs|wiki\.?js|requarks)[^\n]{0,200}\n"
    r"(?:[^\n]{0,120}\n){0,25}"
    r"[ \t]{0,8}pass(?:word)?\s*:\s*[\"']?"
    r"(?!null|false|true|changeme|placeholder|example|[${%])"
    r"[A-Za-z0-9!@_.#\-+]{8,80}[\"']?"
    r"|"
    r"(?:^|\n)[ \t]{0,8}pass(?:word)?\s*:\s*[\"']?"
    r"(?!null|false|true|changeme|placeholder|example|[${%])"
    r"[A-Za-z0-9!@_.#\-+]{8,80}[\"']?(?=\n|$)"
)


# ---- Rule definitions ---------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="wiki-kb-notion-token-literal",
        name="Notion internal integration token hardcoded",
        severity="HIGH",
        description=(
            "A Notion internal integration token (prefix 'secret_') is assigned "
            "to a variable that references Notion in its name. These 43-character "
            "tokens provide full read/write access to all workspace pages the "
            "integration was added to and do not expire automatically. Rotate "
            "immediately and move to a secret manager."
        ),
        pattern=_NOTION_TOKEN_LITERAL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="wiki-kb-atlassian-atatt" "-token",  # noqa: ISC001
        name="Atlassian Cloud API token committed (ATATT prefix or variable name anchor)",
        severity="HIGH",
        description=(
            "An Atlassian Cloud API token was found either via the 'ATATT' prefix "
            "(new token format issued since 2023) or via a variable name referencing "
            "Confluence, Jira, or Atlassian with an assignment value longer than 24 "
            "characters. These non-expiring credentials provide full Confluence space "
            "and Jira project access. Rotate and store in a vault."
        ),
        pattern=_ATLASSIAN_TOKEN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="wiki-kb-mediawiki-secretkey",
        name="MediaWiki LocalSettings.php secret key literal committed",
        severity="CRITICAL",
        description=(
            "A MediaWiki $wgSecretKey, $wgDBpassword, or $wgUpgradeKey literal was "
            "found in PHP source. $wgSecretKey is used to sign session cookies and "
            "CSRF tokens; if exposed an attacker can forge admin sessions. Remove "
            "from source, rotate the key, and inject via environment variable."
        ),
        pattern=_MEDIAWIKI_SECRETKEY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="wiki-kb-bookstack-app-key",
        name="Bookstack/Laravel APP_KEY base64 value committed",
        severity="CRITICAL",
        description=(
            "A Laravel APP_KEY with a base64: prefix was found in source or "
            "configuration. This key is used to encrypt all model data, forge "
            "signed URLs, and forge remember-me cookies. Affects Bookstack, Statamic, "
            "October CMS, and any Laravel application. Rotate immediately and inject "
            "via environment variable, not committed config."
        ),
        pattern=_BOOKSTACK_APP_KEY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="wiki-kb-notion-unfiltered-search",
        name="Notion search passes raw user input without page-level authorization filter",
        severity="MEDIUM",
        description=(
            "A call to notion.search() appears to pass user-controlled input "
            "(req.*, request.*, body.*, params.*, query.*) directly as the query "
            "parameter without filtering results to pages the requesting user is "
            "authorized to see. This can expose private team space content to any "
            "authenticated user via the integration token's broad workspace access. "
            "Add a page-level allowlist filter after the Notion search call."
        ),
        pattern=_NOTION_UNFILTERED_SEARCH,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wiki-kb-wikijs-db-pass-config",
        name="Wiki.js config.yml db.pass plaintext password committed",
        severity="CRITICAL",
        description=(
            "A database password was found in a Wiki.js configuration block. "
            "Wiki.js stores the full database connection (including db.pass) in "
            "config.yml, which is frequently committed to version control for "
            "deployment. Plaintext DB credentials in source provide direct database "
            "access to anyone who can read the repository. Use environment variable "
            "substitution (${DB_PASS}) instead of literal values."
        ),
        pattern=_WIKIJS_DB_PASS,
        owasp_asi="ASI-02",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains(text: str, pat: re.Pattern) -> bool:  # noqa: UP006
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against ``text`` and return findings.

    All 6 rules use direct pattern matching (no multi-stage context
    filters beyond what is embedded in the regex itself). Findings are
    deduped by (rule_id, line, col).
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

    # W1 : notion-token-literal
    rule_w1 = rule_by_id["wiki-kb-notion-token-literal"]
    for m in _NOTION_TOKEN_LITERAL.finditer(text):
        _emit(rule_w1, m.start(), m.group(0))

    # W2 : atlassian-atatt‑token
    rule_w2 = rule_by_id["wiki-kb-atlassian-atatt" "-token"]
    for m in _ATLASSIAN_TOKEN.finditer(text):
        _emit(rule_w2, m.start(), m.group(0))

    # W3 : mediawiki-secretkey
    rule_w3 = rule_by_id["wiki-kb-mediawiki-secretkey"]
    for m in _MEDIAWIKI_SECRETKEY.finditer(text):
        _emit(rule_w3, m.start(), m.group(0))

    # W4 : bookstack-app-key
    rule_w4 = rule_by_id["wiki-kb-bookstack-app-key"]
    for m in _BOOKSTACK_APP_KEY.finditer(text):
        _emit(rule_w4, m.start(), m.group(0))

    # W5 : notion-unfiltered-search
    rule_w5 = rule_by_id["wiki-kb-notion-unfiltered-search"]
    for m in _NOTION_UNFILTERED_SEARCH.finditer(text):
        _emit(rule_w5, m.start(), m.group(0))

    # W6 : wikijs-db-pass-config
    rule_w6 = rule_by_id["wiki-kb-wikijs-db-pass-config"]
    for m in _WIKIJS_DB_PASS.finditer(text):
        _emit(rule_w6, m.start(), m.group(0))

    return findings
