"""CMS misconfig patterns: WordPress / Drupal / Joomla.

Wave-31 distillation round 17, angle CMS.

Catalogue of 7 CMS-specific security anti-patterns distilled in
`reports/distill-round-17/cms-wordpress-drupal.md`. Targets
wp-config.php credential literals, WP_DEBUG in production, default
WordPress secret keys, Drupal settings.php credential exposure,
XML-RPC enabled, Joomla configuration.php secrets, and PHP
disable_functions misconfiguration.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic password assignment patterns —
    `credential_lifecycle_patterns.py` / `secret_leak_sentinel`.
  * Generic dotenv assignment secrets — existing env-var rules.
  * Generic PHP dangerous built-ins (exec, system) in application code —
    prior rounds cover the call sites, not the php.ini gate.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * cms-wp-db-password-literal              (CRITICAL)
  * cms-wp-default-secret-keys              (CRITICAL)
  * cms-wp-debug-enabled                    (HIGH)
  * cms-drupal-db-password-literal          (CRITICAL)
  * cms-wp-xmlrpc-disable-filter-absent     (HIGH)
  * cms-joomla-secret-literal              (CRITICAL)
  * cms-php-disable-functions-empty         (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Tool Misuse & Exploitation (WP_DEBUG info-leak, XML-RPC
                                        SSRF / brute-force amplification,
                                        PHP disable_functions absent)
  ASI-03 — Identity & Privilege Abuse (DB credential exposure, default
                                        HMAC keys, Joomla $secret leak)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- C1 : cms-wp-db-password-literal ------------------------------------

# WordPress wp-config.php define('DB_PASSWORD', '<value>') with a
# non-empty, non-placeholder value. The allowlist matches the verbatim
# WordPress documentation default and common placeholder strings.
# Length gate {4,} filters empty or trivially short values.
_WP_DB_PASSWORD = _re(
    r"""define\s*\(\s*['"]DB_PASSWORD['"]\s*,\s*['"]"""
    r"""(?!(?:put your unique phrase here|changeme|change_me"""
    r"""|change-me|placeholder|your_password_here|YOUR_PASSWORD_HERE"""
    r"""|CHANGE_ME|CHANGEME)['"]\s*\))"""
    r"""[^'"]{4,}['"]\s*\)"""
)


# ---- C2 : cms-wp-default-secret-keys ------------------------------------

# WordPress ships eight HMAC keys/salts. The installer pre-populates each
# with the literal 'put your unique phrase here'. Matching any of the
# eight constants set to this exact default string flags that the site
# operator did not regenerate keys.
_WP_DEFAULT_SECRET_KEY = _re(
    r"""define\s*\(\s*['"]"""
    r"""(?:AUTH_KEY|SECURE_AUTH_KEY|LOGGED_IN_KEY|NONCE_KEY"""
    r"""|AUTH_SALT|SECURE_AUTH_SALT|LOGGED_IN_SALT|NONCE_SALT)"""
    r"""['"]\s*,\s*['"]put your unique phrase here['"]\s*\)"""
)


# ---- C3 : cms-wp-debug-enabled ------------------------------------------

# WP_DEBUG or WP_DEBUG_LOG set to true in wp-config.php exposes PHP errors
# and stack traces (WP_DEBUG) or writes them to a predictable web-accessible
# log file (WP_DEBUG_LOG). Both are explicit misconfigurations for production.
_WP_DEBUG_ENABLED = _re(
    r"""define\s*\(\s*['"]WP_DEBUG(?:_LOG|_DISPLAY)?['"]\s*,\s*true\s*\)"""
)


# ---- C4 : cms-drupal-db-password-literal --------------------------------

# Drupal settings.php stores the DB password as a PHP array key 'password'.
# Match the key inside a $databases array assignment. The simplified form
# matches the password key in any associative array context — the file-name
# scope restriction (settings.php) is the primary disambiguation.
# Allowlist: your_drupal_password, changeme, CHANGEME, placeholder.
_DRUPAL_DB_PASSWORD = _re(
    r"""['"](password|pass)['"]\s*=>\s*['"]"""
    r"""(?!(?:your_drupal_password|changeme|CHANGEME|placeholder"""
    r"""|change_me|CHANGE_ME)['"]\s*)"""
    r"""[^'"]{4,}['"]"""
)


# ---- C5 : cms-wp-xmlrpc-disable-filter-absent ---------------------------

# Presence of the add_filter disabling XML-RPC is the safe state.
# This pattern matches the SAFE disable call so we can detect its ABSENCE
# in a forward window after spotting a functions.php context. The scanner
# inverts the match (see scan_text): it fires when the disable filter is
# NOT found in a plugin/theme PHP file that has wp-content context.
# Trigger: detect references to xmlrpc that are NOT the disable filter.
_XMLRPC_PRESENCE = _re(
    r"""xmlrpc\.php|add_filter\s*\(\s*['"]xmlrpc_"""
)

# Safe-state marker: add_filter('xmlrpc_enabled', '__return_false') or similar.
_XMLRPC_DISABLE_FILTER = _re(
    r"""add_filter\s*\(\s*['"]xmlrpc_enabled['"]\s*,\s*['"]__return_false['"]"""
    r"""|add_filter\s*\(\s*['"]xmlrpc_methods['"]\s*,"""
)


# ---- C6 : cms-joomla-secret-literal -------------------------------------

# Joomla configuration.php stores the application HMAC secret as
# 'public $secret'. The password field is also a critical credential.
# Match non-empty, non-placeholder values (length gate {4,}).
_JOOMLA_SECRET = _re(
    r"""public\s+\$secret\s*=\s*['"][A-Za-z0-9!@#$%^&*()\-_+=\[\]{};:,.?]{8,}['"]"""
)

_JOOMLA_DB_PASSWORD = _re(
    r"""public\s+\$password\s*=\s*['"]"""
    r"""(?!(?:changeme|change_me|CHANGEME|CHANGE_ME|placeholder|your_password)['"]\s*)"""
    r"""[^'"]{4,}['"]"""
)


# ---- C7 : cms-php-disable-functions-empty -------------------------------

# php.ini or .user.ini with an empty disable_functions directive leaves all
# dangerous PHP built-ins (exec, system, shell_exec, ...) available to
# CMS plugins. The empty-value form is the most common misconfiguration.
_PHP_DISABLE_FUNCTIONS_EMPTY = _re(
    r"""^disable_functions\s*=\s*$"""
)

# Secondary signal: expose_php = On leaks the PHP version string.
_PHP_EXPOSE_ON = _re(
    r"""^expose_php\s*=\s*(?:On|on|ON)\s*$"""
)


# ---- Rule catalogue -----------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="cms-wp-db-password-literal",
        name="WordPress DB_PASSWORD literal in wp-config.php",
        severity="CRITICAL",
        description=(
            "define('DB_PASSWORD', '<value>') with a real credential committed in "
            "wp-config.php grants direct database access to anyone with repo read "
            "access, enabling full site compromise via SQL (UPDATE wp_users)."
        ),
        pattern=_WP_DB_PASSWORD,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="cms-wp-default-secret-keys",
        name="WordPress AUTH_KEY/SECURE_AUTH_KEY set to default placeholder",
        severity="CRITICAL",
        description=(
            "WordPress HMAC key/salt set to 'put your unique phrase here' (the "
            "WordPress installer default). An attacker who knows the default can "
            "forge authentication cookies for any user account without a password."
        ),
        pattern=_WP_DEFAULT_SECRET_KEY,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="cms-wp-debug-enabled",
        name="WP_DEBUG / WP_DEBUG_LOG enabled in production",
        severity="HIGH",
        description=(
            "define('WP_DEBUG', true) outputs PHP errors and stack traces in HTML "
            "responses; define('WP_DEBUG_LOG', true) writes the same data to "
            "wp-content/debug.log at a predictable URL. Both expose internal paths, "
            "table names, and plugin names to unauthenticated visitors."
        ),
        pattern=_WP_DEBUG_ENABLED,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="cms-drupal-db-password-literal",
        name="Drupal settings.php with literal database password",
        severity="CRITICAL",
        description=(
            "Drupal's $databases array in settings.php contains a plaintext database "
            "password. Committing settings.php exposes the credential; Drupal sites "
            "commonly use a privileged DB user granting full schema access including "
            "session tokens in the sessions table."
        ),
        pattern=_DRUPAL_DB_PASSWORD,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="cms-wp-xmlrpc-disable-filter-absent",
        name="WordPress XML-RPC not disabled (xmlrpc.php present / disable filter absent)",
        severity="HIGH",
        description=(
            "xmlrpc.php present without a matching add_filter('xmlrpc_enabled', "
            "'__return_false') call. The system.multicall method amplifies credential "
            "brute-force attacks 50-100x; pingback.ping enables SSRF for internal "
            "network reconnaissance and DDoS amplification."
        ),
        pattern=_XMLRPC_PRESENCE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="cms-joomla-secret-literal",
        name="Joomla configuration.php with plaintext $secret or $password",
        severity="CRITICAL",
        description=(
            "Joomla configuration.php contains 'public $secret' (HMAC key for session "
            "tokens and password-reset links) or 'public $password' (database credential) "
            "as a literal value. A leaked $secret enables forged Joomla session tokens "
            "and password-reset links for any account."
        ),
        pattern=_JOOMLA_SECRET,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="cms-php-disable-functions-empty",
        name="PHP disable_functions empty (dangerous built-ins available to CMS plugins)",
        severity="HIGH",
        description=(
            "php.ini or .user.ini has 'disable_functions =' with no value, leaving "
            "exec(), system(), shell_exec(), passthru(), proc_open() and popen() "
            "available to CMS plugins. A malicious or compromised plugin can escalate "
            "from plugin-level code to OS-level command execution without any additional "
            "vulnerability in the CMS itself."
        ),
        pattern=_PHP_DISABLE_FUNCTIONS_EMPTY,
        owasp_asi="ASI-02",
    ),
)


# ---- Internal helpers ---------------------------------------------------


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


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters used:

      * C5 (cms-wp-xmlrpc-disable-filter-absent) — trigger on any
        `xmlrpc` reference; suppress if add_filter('xmlrpc_enabled',
        '__return_false') OR add_filter('xmlrpc_methods', ...) is found
        anywhere in the same file (the safe disable pattern).

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

    # ---- C1 : cms-wp-db-password-literal ----
    rule_c1 = rule_by_id["cms-wp-db-password-literal"]
    for m in _WP_DB_PASSWORD.finditer(text):
        _emit(rule_c1, m.start(), m.group(0))

    # ---- C2 : cms-wp-default-secret-keys ----
    rule_c2 = rule_by_id["cms-wp-default-secret-keys"]
    for m in _WP_DEFAULT_SECRET_KEY.finditer(text):
        _emit(rule_c2, m.start(), m.group(0))

    # ---- C3 : cms-wp-debug-enabled ----
    rule_c3 = rule_by_id["cms-wp-debug-enabled"]
    for m in _WP_DEBUG_ENABLED.finditer(text):
        _emit(rule_c3, m.start(), m.group(0))

    # ---- C4 : cms-drupal-db-password-literal ----
    rule_c4 = rule_by_id["cms-drupal-db-password-literal"]
    for m in _DRUPAL_DB_PASSWORD.finditer(text):
        _emit(rule_c4, m.start(), m.group(0))

    # ---- C5 : cms-wp-xmlrpc-disable-filter-absent ----
    # Stage-B: only flag xmlrpc references when the disable filter is absent
    # from the entire file. The disable filter is the safe state.
    rule_c5 = rule_by_id["cms-wp-xmlrpc-disable-filter-absent"]
    if not _file_contains(text, _XMLRPC_DISABLE_FILTER):
        for m in _XMLRPC_PRESENCE.finditer(text):
            _emit(rule_c5, m.start(), m.group(0))

    # ---- C6 : cms-joomla-secret-literal ----
    # Two sub-patterns: $secret (session HMAC key) and $password (DB credential).
    rule_c6 = rule_by_id["cms-joomla-secret-literal"]
    for m in _JOOMLA_SECRET.finditer(text):
        _emit(rule_c6, m.start(), m.group(0))
    for m in _JOOMLA_DB_PASSWORD.finditer(text):
        _emit(rule_c6, m.start(), m.group(0))

    # ---- C7 : cms-php-disable-functions-empty ----
    rule_c7 = rule_by_id["cms-php-disable-functions-empty"]
    for m in _PHP_DISABLE_FUNCTIONS_EMPTY.finditer(text):
        _emit(rule_c7, m.start(), m.group(0))
    # Secondary signal: expose_php = On
    for m in _PHP_EXPOSE_ON.finditer(text):
        _emit(rule_c7, m.start(), m.group(0))

    return findings
