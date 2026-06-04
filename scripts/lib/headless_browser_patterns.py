"""Headless browser automation security patterns.

Wave-28 distillation round 14, angle headless-browser.

Catalogue of 7 headless-browser-specific anti-patterns distilled in
`reports/distill-round-14/headless-browser.md`. Targets Playwright /
Puppeteer / Selenium / raw Chrome/Chromium automation surfaces used in
CI pipelines, AI agent demos, and security-scanner scripts.

What is NOT here (already shipped — DO NOT duplicate):

  * Set-Cookie attribute hygiene (HttpOnly / Secure / SameSite) —
    `browser_cookies_patterns.py`.
  * localStorage / sessionStorage auth storage —
    `browser_cookies_patterns.py`.
  * Browser extension manifest permissions / content-script injection —
    `browser_extension_patterns.py`.
  * Generic outbound URL env-var POST without host allowlist —
    `dns_email_patterns.py` rule 5.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * headless-evaluate-fstring-injection                        (HIGH)
  * headless-storage-state-committed                           (CRITICAL)
  * headless-no-sandbox-disable-web-security                   (CRITICAL)
  * headless-remote-debugging-port-exposed                     (HIGH)
  * headless-user-data-dir-repo-path                           (HIGH)
  * headless-ignore-certificate-errors                         (HIGH)
  * headless-credential-file-direct-read                       (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Goal Hijacking (JS injection breaks automation intent)
  ASI-02 — Tool Misuse (dangerous launch flags, sandbox removal)
  ASI-03 — Identity & Privilege Abuse (session state, credentials)
  ASI-04 — Supply Chain Vulnerabilities (committed auth artefacts)
  ASI-05 — Unexpected Code Execution (evaluate injection, sandbox combo)
  ASI-07 — Insecure Inter-Agent Communication (CDP exposed, bad TLS)
  ASI-10 — Rogue Agents (direct credential-file reads)

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


# ---- HB-001 : headless-evaluate-fstring-injection -----------------------

# Python: page.evaluate(f"...") or frame.evaluate(f"...")
# JS/TS:  page.evaluate(`...${ ... }`)
_EVALUATE_FSTRING = _re(
    r"\b(?:page|frame|iframe)\.evaluate\s*\(\s*f[\"']"
    r"|"
    r"\b(?:page|frame|iframe)\.evaluate\s*\(`[^`]{0,200}\$\{"
)


# ---- HB-002 : headless-storage-state-committed --------------------------

# Python: storage_state(path="...json") or new_context(storage_state="...")
# TS/JS:  storageState: '...'   in config objects
_STORAGE_STATE_PATH = _re(
    r"\bstorage_state\s*\(\s*path\s*=\s*[\"'][^\"']{1,200}\.json[\"']"
    r"|"
    r"\bnew_context\s*\(\s*storage_state\s*=\s*[\"'][^\"']{1,200}[\"']"
    r"|"
    r"\bstorageState\s*:\s*[\"'][^\"']{1,200}[\"']"
)


# ---- HB-003 : headless-no-sandbox-disable-web-security ------------------

# Both flags on the same line (single-line arg list).
# Multi-line lists are handled via a 10-line window scan in scan_text.
_NO_SANDBOX_PATTERN = _re(r"--no-sandbox")
_DISABLE_WEB_SECURITY_PATTERN = _re(r"--disable-web-security")

# Also catch the single-line combo directly.
_SANDBOX_WEB_SECURITY_COMBO = _re(
    r"--no-sandbox[^\"'\n]{0,200}--disable-web-security"
    r"|"
    r"--disable-web-security[^\"'\n]{0,200}--no-sandbox"
)


# ---- HB-004 : headless-remote-debugging-port-exposed --------------------

# Flag with any port number. Loopback-bind carve-out is handled in
# scan_text by checking for --remote-debugging-address=127.0.0.1 or
# =localhost in the same line.
_REMOTE_DEBUGGING_PORT = _re(
    r"--remote-debugging-port\s*=?\s*\d{2,5}"
)

# Pattern that indicates a safe loopback bind on the SAME line.
_LOOPBACK_ADDRESS = _re(
    r"--remote-debugging-address\s*=\s*(?:127\.0\.0\.1|localhost|::1)"
)


# ---- HB-005 : headless-user-data-dir-repo-path --------------------------

# userDataDir: '...relative...' OR --user-data-dir=./something
# Carve-out: paths that clearly route through tempfile / mkdtemp / os.tmpdir.
_USER_DATA_DIR = _re(
    r"\buserDataDir\s*[=:]\s*[\"'](?!.*(?:tmpdir|tempfile|mkdtemp|os\.temp))[^\"']{1,200}[\"']"
    r"|"
    r"--user-data-dir=(?!(?:/tmp|%TEMP|tmpdir|tempfile|mkdtemp))[^\"'\s]{1,200}"
    r"|"
    r"\blaunch_persistent_context\s*\(\s*[\"'](?!(?:/tmp|%TEMP))[^\"']{1,200}[\"']"
)


# ---- HB-006 : headless-ignore-certificate-errors ------------------------

_IGNORE_CERT = _re(
    r"\bignoreHTTPSErrors\s*:\s*true"
    r"|"
    r"--ignore-certificate-errors\b"
    r"|"
    r"\bignore_https_errors\s*=\s*True"
    r"|"
    r"\bacceptInsecureCerts[\"'\s]*:\s*[Tt]rue"
    r"|"
    r"\bset_capability\s*\(\s*[\"']acceptInsecureCerts[\"']\s*,\s*True\s*\)"
)


# ---- HB-007 : headless-credential-file-direct-read ----------------------

# Chrome "Login Data", Firefox "logins.json", browser "Cookies" / "cookies.sqlite".
# Must involve an open / read / copy operation on the same or adjacent line.
# The broad path-literal match is the trigger; scanner refines via window.
_CREDENTIAL_FILE_PATH = _re(
    r"\bLogin\s+Data\b"
    r"|"
    r"\bcookies\.sqlite\b"
    r"|"
    r"\blogins\.json\b"
    r"|"
    r"\bCookies_db\b"
    r"|"
    r"Chrome[/\\]Default[/\\](?:Login\s+Data|Cookies)\b"
    r"|"
    r"\.mozilla[/\\]firefox[/\\][^\"'\s]{0,80}logins\.json"
)

# Indicators that the match is an active read (not a mere string constant
# for IOC detection). Checked in a narrow window around the match.
_CRED_FILE_READ_OP = _re(
    r"\b(?:open|sqlite3\.connect|shutil\.copy|fs\.readFileSync"
    r"|fs\.copyFileSync|conn\.execute|read_bytes|read_text|get\b)\s*\("
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="headless-evaluate-fstring-injection",
        name="headless-evaluate-fstring-injection",
        severity="HIGH",
        description=(
            "page.evaluate() or frame.evaluate() is called with a Python "
            "f-string or a JS template literal that embeds dynamic data. "
            "When the interpolated value originates from page content, "
            "user-supplied input, or a file read, an attacker who controls "
            "the DOM or input can break out of the injected string and execute "
            "arbitrary JavaScript in the authenticated browser session. "
            "Use structured argument passing instead: "
            "page.evaluate('(arg) => fn(arg)', value)."
        ),
        pattern=_EVALUATE_FSTRING,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="headless-storage-state-committed",
        name="headless-storage-state-committed",
        severity="CRITICAL",
        description=(
            "Playwright storage_state() serialises all cookies, localStorage, "
            "and sessionStorage to disk as plain JSON. Writing this file to a "
            "project-relative path (which is likely committed to git or emitted "
            "as a CI artefact) exposes every session token, CSRF cookie, and "
            "OAuth bearer in the captured state. Write storage state only to "
            "a gitignored or ephemeral temp path."
        ),
        pattern=_STORAGE_STATE_PATH,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="headless-no-sandbox-disable-web-security",
        name="headless-no-sandbox-disable-web-security",
        severity="CRITICAL",
        description=(
            "Both --no-sandbox and --disable-web-security are present in the "
            "browser launch arguments. --no-sandbox removes the OS-level "
            "process sandbox that isolates the renderer from the host; "
            "--disable-web-security removes the Same-Origin Policy. Together "
            "they allow a malicious page the automation visits to make "
            "arbitrary cross-origin requests AND to exploit any renderer "
            "vulnerability to reach the host process. Remove --disable-web-security; "
            "use --no-sandbox only in verified rootless-container contexts."
        ),
        pattern=_SANDBOX_WEB_SECURITY_COMBO,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="headless-remote-debugging-port-exposed",
        name="headless-remote-debugging-port-exposed",
        severity="HIGH",
        description=(
            "Chrome DevTools Protocol (CDP) is exposed via "
            "--remote-debugging-port without an explicit loopback bind "
            "(--remote-debugging-address=127.0.0.1). Chrome may listen on "
            "0.0.0.0 by default, allowing any process on the container or "
            "CI pod network to connect and issue CDP commands: read cookies, "
            "extract localStorage, navigate pages, execute JavaScript, or "
            "inject keystrokes. Always pair the port flag with "
            "--remote-debugging-address=127.0.0.1."
        ),
        pattern=_REMOTE_DEBUGGING_PORT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="headless-user-data-dir-repo-path",
        name="headless-user-data-dir-repo-path",
        severity="HIGH",
        description=(
            "The browser profile directory (userDataDir / --user-data-dir / "
            "launch_persistent_context path) points to a literal project-relative "
            "or well-known shared path rather than an ephemeral temp directory. "
            "This directory persists cookies, saved passwords, localStorage, "
            "and browsing history. Any process that can read the directory "
            "obtains full session state, equivalent to a committed "
            "Playwright storage_state JSON file. Use tempfile.mkdtemp() or "
            "the OS temp directory for the profile path."
        ),
        pattern=_USER_DATA_DIR,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="headless-ignore-certificate-errors",
        name="headless-ignore-certificate-errors",
        severity="HIGH",
        description=(
            "TLS certificate validation is suppressed via ignoreHTTPSErrors, "
            "--ignore-certificate-errors, ignore_https_errors, or "
            "acceptInsecureCerts. Automation that authenticates to real services "
            "with this flag cannot distinguish a legitimate server from a MITM "
            "proxy. An attacker who can intercept the runner's traffic receives "
            "cleartext credentials or session tokens submitted by the automation. "
            "Remove the flag and fix the certificate issue at its source."
        ),
        pattern=_IGNORE_CERT,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="headless-credential-file-direct-read",
        name="headless-credential-file-direct-read",
        severity="CRITICAL",
        description=(
            "Code directly opens or copies browser credential files: Chrome "
            "'Login Data' (saved passwords, DPAPI-encrypted), 'Cookies' / "
            "'cookies.sqlite' (live session tokens), or Firefox 'logins.json'. "
            "Legitimate browser automation communicates via CDP or WebDriver — "
            "it never opens the profile's credential files directly. Code that "
            "does is either infostealer malware, a credential-exfiltration "
            "payload, or a research POC that must not reach production."
        ),
        pattern=_CREDENTIAL_FILE_PATH,
        owasp_asi="ASI-03",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


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

      * HB-003 (no-sandbox + disable-web-security) — also fires when the two
        flags are found within 10 lines of each other (multi-line arg list).
      * HB-004 (remote-debugging-port) — suppressed when
        --remote-debugging-address=127.0.0.1 or =localhost appears on the
        SAME line as the port flag.
      * HB-007 (credential-file-direct-read) — fires only when a file-read
        operation (open, sqlite3.connect, shutil.copy, etc.) appears within
        a 5-line window around the credential path literal. Pure IOC-detection
        string constants (path.exists checks) are excluded.

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

    # ---- HB-001 : evaluate f-string injection ----
    rule_hb1 = rule_by_id["headless-evaluate-fstring-injection"]
    for m in _EVALUATE_FSTRING.finditer(text):
        _emit(rule_hb1, m.start(), m.group(0))

    # ---- HB-002 : storage_state committed ----
    rule_hb2 = rule_by_id["headless-storage-state-committed"]
    for m in _STORAGE_STATE_PATH.finditer(text):
        _emit(rule_hb2, m.start(), m.group(0))

    # ---- HB-003 : --no-sandbox + --disable-web-security combo ----
    rule_hb3 = rule_by_id["headless-no-sandbox-disable-web-security"]
    # Single-line combo.
    for m in _SANDBOX_WEB_SECURITY_COMBO.finditer(text):
        _emit(rule_hb3, m.start(), m.group(0))
    # Multi-line: --no-sandbox and --disable-web-security within 10 lines.
    for m_ns in _NO_SANDBOX_PATTERN.finditer(text):
        line_no, _ = _line_col(text, m_ns.start())
        window = _slice_window(text, line_no, 0, 10)
        if _file_contains(window, _DISABLE_WEB_SECURITY_PATTERN):
            _emit(rule_hb3, m_ns.start(), m_ns.group(0))

    # ---- HB-004 : remote debugging port exposed ----
    rule_hb4 = rule_by_id["headless-remote-debugging-port-exposed"]
    for m in _REMOTE_DEBUGGING_PORT.finditer(text):
        line_no, _ = _line_col(text, m.start())
        # Get the text of this specific line only.
        line_text = _slice_window(text, line_no, 0, 0)
        if not _file_contains(line_text, _LOOPBACK_ADDRESS):
            _emit(rule_hb4, m.start(), m.group(0))

    # ---- HB-005 : userDataDir / --user-data-dir in repo path ----
    rule_hb5 = rule_by_id["headless-user-data-dir-repo-path"]
    for m in _USER_DATA_DIR.finditer(text):
        _emit(rule_hb5, m.start(), m.group(0))

    # ---- HB-006 : ignore certificate errors ----
    rule_hb6 = rule_by_id["headless-ignore-certificate-errors"]
    for m in _IGNORE_CERT.finditer(text):
        _emit(rule_hb6, m.start(), m.group(0))

    # ---- HB-007 : credential file direct read ----
    rule_hb7 = rule_by_id["headless-credential-file-direct-read"]
    for m in _CREDENTIAL_FILE_PATH.finditer(text):
        line_no, _ = _line_col(text, m.start())
        window = _slice_window(text, line_no, 2, 3)
        if _file_contains(window, _CRED_FILE_READ_OP):
            _emit(rule_hb7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
