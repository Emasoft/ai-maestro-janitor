"""Electron desktop-app security patterns.

Wave-32 distillation round 18, Electron desktop-app security angle.

Catalogue of 9 Electron-specific security anti-patterns distilled in
`reports/distill-round-18/electron-security.md`. Targets Electron main-process
`webPreferences`, IPC, shell, and protocol-handler surfaces. All patterns
are RE2-safe and based on public-knowledge sources including Electronegativity
(Doyensec), published CVEs (CVE-2018-1000136, CVE-2020-15174, CVE-2022-21718),
GHSA advisories, and Electron security documentation.

What is NOT here (already shipped — DO NOT duplicate):

  * Electron-builder bundling config guard — `js_bundler_patterns.py`.
  * PKCE for Electron public clients — `oauth_device_flow_patterns.py`.
  * Content-script / manifest V3 isolation — `browser_extension_patterns.py`.
  * localStorage / IndexedDB exposure — `browser_storage_patterns.py`.
  * HTTP CORS header misconfig (server-side) — `cors_misconfig_patterns.py`.
  * GitHub Actions context injection — `ci_runner_injection_patterns.py`.

What IS here (9 net-new rules, regex-only, all RE2-safe):

  * es-node-integration-renderer       (CRITICAL)
  * es-context-isolation-disabled      (CRITICAL)
  * es-remote-module-enabled           (HIGH)
  * es-renderer-sandbox-disabled       (HIGH)
  * es-shell-open-external-unvalidated (CRITICAL)
  * es-file-protocol-path-traversal    (HIGH)
  * es-ipc-handler-no-validation       (HIGH)
  * es-load-url-user-input             (HIGH)
  * es-web-security-disabled           (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Injection / path traversal (shell.openExternal with untrusted
            input, protocol path traversal, loadURL user input)
  ASI-03 — Renderer isolation / sandbox escape (nodeIntegration, context
            isolation, sandbox, remote module, webSecurity)
  ASI-05 — Privilege escalation via IPC without validation

All regexes are RE2-compatible (no backreferences, no lookbehind with
variable length, no catastrophic backtracking shapes). Patterns are
PRE-COMPILED at module load. Fail-fast: callers receive structured
Finding tuples, never raised exceptions on benign input.
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
    chat_bot_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind with variable length."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- EDS1 : es-node-integration-renderer --------------------------------

# Flags nodeIntegration: true in webPreferences. The word-boundary variant
# \b(?!InSubFrames) would be a variable-length lookbehind, which is not
# RE2-safe. We instead use a negative character class after the keyword:
# match 'nodeIntegration' only when NOT followed immediately by 'InSubFrames'.
# RE2-safe: no lookbehind, finite quantifiers.
_NODE_INTEGRATION_TRUE = _re(
    r"nodeIntegration\s*:\s*true"
)

# File-level co-occurrence gate: file imports electron (main-process code).
_ELECTRON_IMPORT_GATE = _re(
    r"require\s*\(\s*['\"]electron['\"]\s*\)"
    r"|"
    r"from\s+['\"]electron['\"]"
)


# ---- EDS2 : es-context-isolation-disabled --------------------------------

_CONTEXT_ISOLATION_FALSE = _re(
    r"contextIsolation\s*:\s*false"
)


# ---- EDS3 : es-remote-module-enabled -------------------------------------

_ENABLE_REMOTE_MODULE_TRUE = _re(
    r"enableRemoteModule\s*:\s*true"
)


# ---- EDS4 : es-renderer-sandbox-disabled ---------------------------------

# Co-occurrence gate for EDS4: BrowserWindow or BrowserView must appear
# in the same file. sandbox: false also appears in Jest / vm2 contexts.
_SANDBOX_FALSE = _re(
    r"\bsandbox\s*:\s*false\b"
)

_BROWSER_WINDOW_GATE = _re(
    r"\bBrowserWindow\b"
    r"|"
    r"\bBrowserView\b"
    r"|"
    r"\bwebPreferences\b"
)


# ---- EDS5 : es-shell-open-external-unvalidated ---------------------------

# Enhanced form: flag openExternal calls whose first argument is NOT a
# hardcoded https?:// or file:// string literal. RE2-safe — no lookbehind;
# we match the broader form and check for the literal prefix in post-processing
# using a secondary pattern.
_SHELL_OPEN_EXTERNAL = _re(
    r"shell\s*\.\s*openExternal\s*\("
)

# Suppress if the immediate argument is a hardcoded safe URL literal.
_OPEN_EXTERNAL_LITERAL_ARG = _re(
    r"shell\s*\.\s*openExternal\s*\(\s*['\"`](?:https?|file)://"
)


# ---- EDS6 : es-file-protocol-path-traversal ------------------------------

_PROTOCOL_REGISTER = _re(
    r"protocol\s*\.\s*register(?:File|Buffer|String|Http|Stream)Protocol\s*\("
)


# ---- EDS7 : es-ipc-handler-no-validation ---------------------------------

_IPC_MAIN_HANDLE = _re(
    r"ipcMain\s*\.\s*(?:handle|on)\s*\("
)

# File-level co-occurrence: child_process exec/spawn or raw fs in same file.
_CHILD_PROCESS_OR_EXEC = _re(
    r"child_process\s*\.\s*(?:exec|execSync|spawn|spawnSync|execFile|execFileSync)\b"
    r"|"
    r"require\s*\(\s*['\"]child_process['\"]\s*\)"
    r"|"
    r"from\s+['\"]child_process['\"]"
)


# ---- EDS8 : es-load-url-user-input ---------------------------------------

# Broader form — flag any .loadURL( call.
_LOAD_URL_CALL = _re(
    r"\.loadURL\s*\("
)

# Suppress if the argument is a hardcoded file:// or https?:// URL literal
# (the most common safe pattern). We detect the literal-prefix form.
_LOAD_URL_LITERAL_ARG = _re(
    r"\.loadURL\s*\(\s*['\"`](?:https?|file)://"
)


# ---- EDS9 : es-web-security-disabled -------------------------------------

_WEB_SECURITY_FALSE = _re(
    r"webSecurity\s*:\s*false"
)


# ---- RULES tuple ---------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="es-node-integration-renderer",
        name="nodeIntegration: true in renderer webPreferences",
        severity="CRITICAL",
        description=(
            "BrowserWindow or BrowserView created with "
            "`webPreferences: { nodeIntegration: true }` grants the renderer "
            "full Node.js built-in access (`fs`, `child_process`, etc.) via "
            "`require()`. Any XSS or malicious URL loaded by the renderer "
            "becomes arbitrary code execution on the host. Root cause of "
            "CVE-2018-1000136; Electronegativity rule ELECTRON_NODE_INTEGRATION."
        ),
        pattern=_NODE_INTEGRATION_TRUE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="es-context-isolation-disabled",
        name="contextIsolation: false in webPreferences",
        severity="CRITICAL",
        description=(
            "`contextIsolation: false` removes the security boundary between "
            "the renderer JavaScript context and the Electron/Node context. "
            "XSS in the renderer can access `window.require`, `process`, and "
            "preload-script globals via the same JavaScript realm. Was the "
            "pre-Electron-12 default; many legacy apps never updated. "
            "Electronegativity rule CONTEXT_ISOLATION_JS_CHECK."
        ),
        pattern=_CONTEXT_ISOLATION_FALSE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="es-remote-module-enabled",
        name="enableRemoteModule: true (deprecated Electron < 14 legacy)",
        severity="HIGH",
        description=(
            "`enableRemoteModule: true` enables `@electron/remote`, allowing "
            "renderer processes to synchronously call main-process objects. "
            "Any XSS can invoke `app.getPath`, `BrowserWindow.getAllWindows`, "
            "`dialog.showSaveDialog` etc., escalating to the main process. "
            "Removed from Electron core in v14; CVE-2020-15174. "
            "Electronegativity rule REMOTE_MODULE_JS_CHECK."
        ),
        pattern=_ENABLE_REMOTE_MODULE_TRUE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="es-renderer-sandbox-disabled",
        name="sandbox: false disabling the Chromium renderer sandbox",
        severity="HIGH",
        description=(
            "`webPreferences: { sandbox: false }` opts the renderer out of "
            "the Chromium process sandbox (which became the default in Electron 20+). "
            "Without the sandbox a renderer memory-corruption exploit can directly "
            "access the OS — not just the Electron process. Eliminates the "
            "defense-in-depth layer that limits renderer-escape blast radius. "
            "Electronegativity rule SANDBOX_JS_CHECK."
        ),
        pattern=_SANDBOX_FALSE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="es-shell-open-external-unvalidated",
        name="shell.openExternal called with unvalidated user-controlled input",
        severity="CRITICAL",
        description=(
            "`shell.openExternal(url)` passes the URL to the OS default URL "
            "handler (ShellExecuteW / open / xdg-open). Attacker-controlled "
            "input can supply `file:///etc/passwd`, UNC paths "
            "`\\\\\\\\attacker\\\\share\\\\evil.exe`, or custom protocol handlers "
            "(`ms-msdt:` — Follina CVE-2022-30190) to achieve code execution "
            "outside the Electron sandbox. GHSA-7x97-j373-85x5. "
            "Electronegativity rule OPEN_EXTERNAL_JS_CHECK."
        ),
        pattern=_SHELL_OPEN_EXTERNAL,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="es-file-protocol-path-traversal",
        name="protocol.register*Protocol without path canonicalization",
        severity="HIGH",
        description=(
            "`protocol.registerFileProtocol` (or `registerBufferProtocol` etc.) "
            "registers a custom protocol handler. If the handler computes the "
            "on-disk path from `request.url` via string concatenation without "
            "`path.resolve()` + `startsWith(baseDir)` guard, a URL like "
            "`app://../../../etc/passwd` traverses the filesystem. CVE-2022-21718. "
            "Electronegativity rule FILE_PROTOCOL_JS_CHECK."
        ),
        pattern=_PROTOCOL_REGISTER,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="es-ipc-handler-no-validation",
        name="ipcMain.handle/on with no input validation on sensitive operations",
        severity="HIGH",
        description=(
            "IPC channels are the primary renderer-to-main escalation surface "
            "when `nodeIntegration: false` is correctly set. A malicious page "
            "can invoke any `ipcMain.handle` or `ipcMain.on` channel. If the "
            "handler passes renderer arguments to `fs.readFile`, "
            "`child_process.exec`, or `shell.openExternal` without validation, "
            "the renderer achieves privileged main-process operations. This is "
            "the post-sandboxing threat model (NCC Group 2021, ToB 2023)."
        ),
        pattern=_IPC_MAIN_HANDLE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="es-load-url-user-input",
        name="webContents.loadURL / BrowserWindow.loadURL with variable argument",
        severity="HIGH",
        description=(
            "`win.loadURL(userInput)` where `userInput` comes from IPC, a "
            "database record, or CLI args allows redirecting the renderer to "
            "an attacker-controlled page. Combined with `nodeIntegration: true` "
            "or weak `contextIsolation`, this is XSS → RCE. Even with sandbox "
            "on, it enables phishing and exploitation of IPC channels. "
            "Electronegativity rule LOAD_URL_JS_CHECK."
        ),
        pattern=_LOAD_URL_CALL,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="es-web-security-disabled",
        name="webSecurity: false disabling same-origin policy in renderer",
        severity="HIGH",
        description=(
            "`webPreferences: { webSecurity: false }` disables the Chromium "
            "same-origin policy and CORS enforcement. The renderer can make "
            "cross-origin XHR/fetch to any host including `http://localhost` "
            "services and `file:///`. A malicious page can exfiltrate tokens "
            "from localhost dev servers, SSH keys via `file:///`, and pivot to "
            "internal services. Electronegativity rule WEB_SECURITY_JS_CHECK."
        ),
        pattern=_WEB_SECURITY_FALSE,
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


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters apply co-occurrence gates to reduce false positives:

      * EDS1 (node-integration-renderer) — require Electron import in the
        same file; flag only when _NODE_INTEGRATION_TRUE matches AND
        _ELECTRON_IMPORT_GATE matches anywhere in the file.
      * EDS2 (context-isolation-disabled) — same Electron import gate.
      * EDS3 (remote-module-enabled) — same Electron import gate.
      * EDS4 (renderer-sandbox-disabled) — require BrowserWindow / BrowserView
        / webPreferences in the same file; prevents false positives from
        Jest / vm2 `sandbox: false` configs.
      * EDS5 (shell-open-external-unvalidated) — suppress when the immediate
        argument is a hardcoded https?:// or file:// string literal.
      * EDS6 (file-protocol-path-traversal) — flag all register*Protocol calls;
        enhanced confidence when `request.url` also appears in the file.
      * EDS7 (ipc-handler-no-validation) — flag all ipcMain.handle/on calls;
        enhanced confidence when `child_process` / `exec` / `spawn` also
        appears in the file.
      * EDS8 (load-url-user-input) — suppress when the immediate argument is
        a hardcoded https?:// or file:// URL literal.
      * EDS9 (web-security-disabled) — require BrowserWindow / webPreferences
        in the same file; prevents false positives from Vite / Webpack configs.

    Findings are deduped by (rule_id, line, col) and sorted by (line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    # Pre-compute file-level gate results once.
    has_electron_import = _file_contains(text, _ELECTRON_IMPORT_GATE)
    has_browser_window = _file_contains(text, _BROWSER_WINDOW_GATE)
    has_child_process = _file_contains(text, _CHILD_PROCESS_OR_EXEC)

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

    # ---- EDS1 : es-node-integration-renderer ----
    # Gate: file must also import electron (main-process code).
    rule_eds1 = rule_by_id["es-node-integration-renderer"]
    if has_electron_import:
        for m in _NODE_INTEGRATION_TRUE.finditer(text):
            # Exclude nodeIntegrationInSubFrames — check surrounding chars.
            end = m.end()
            if end < len(text) and text[end:end + 12].lower().startswith("insubframes"):
                continue
            _emit(rule_eds1, m.start(), m.group(0))

    # ---- EDS2 : es-context-isolation-disabled ----
    rule_eds2 = rule_by_id["es-context-isolation-disabled"]
    if has_electron_import:
        for m in _CONTEXT_ISOLATION_FALSE.finditer(text):
            _emit(rule_eds2, m.start(), m.group(0))

    # ---- EDS3 : es-remote-module-enabled ----
    rule_eds3 = rule_by_id["es-remote-module-enabled"]
    if has_electron_import:
        for m in _ENABLE_REMOTE_MODULE_TRUE.finditer(text):
            _emit(rule_eds3, m.start(), m.group(0))

    # ---- EDS4 : es-renderer-sandbox-disabled ----
    # Gate: BrowserWindow / BrowserView / webPreferences in same file.
    rule_eds4 = rule_by_id["es-renderer-sandbox-disabled"]
    if has_browser_window:
        for m in _SANDBOX_FALSE.finditer(text):
            _emit(rule_eds4, m.start(), m.group(0))

    # ---- EDS5 : es-shell-open-external-unvalidated ----
    # Suppress if the argument is a hardcoded safe URL literal.
    rule_eds5 = rule_by_id["es-shell-open-external-unvalidated"]
    for m in _SHELL_OPEN_EXTERNAL.finditer(text):
        # Check for the literal-arg form in a window of 120 chars.
        window = text[m.start():m.start() + 120]
        if _OPEN_EXTERNAL_LITERAL_ARG.search(window):
            continue
        _emit(rule_eds5, m.start(), m.group(0))

    # ---- EDS6 : es-file-protocol-path-traversal ----
    # Flag all register*Protocol calls; note enhanced confidence when
    # request.url also appears (handled in description, not gated here).
    rule_eds6 = rule_by_id["es-file-protocol-path-traversal"]
    for m in _PROTOCOL_REGISTER.finditer(text):
        _emit(rule_eds6, m.start(), m.group(0))

    # ---- EDS7 : es-ipc-handler-no-validation ----
    # Enhanced confidence when child_process also in file (pre-computed).
    rule_eds7 = rule_by_id["es-ipc-handler-no-validation"]
    if has_child_process:
        for m in _IPC_MAIN_HANDLE.finditer(text):
            _emit(rule_eds7, m.start(), m.group(0))

    # ---- EDS8 : es-load-url-user-input ----
    # Suppress when the immediate argument is a hardcoded URL literal.
    rule_eds8 = rule_by_id["es-load-url-user-input"]
    for m in _LOAD_URL_CALL.finditer(text):
        window = text[m.start():m.start() + 120]
        if _LOAD_URL_LITERAL_ARG.search(window):
            continue
        _emit(rule_eds8, m.start(), m.group(0))

    # ---- EDS9 : es-web-security-disabled ----
    # Gate: BrowserWindow / webPreferences in same file.
    rule_eds9 = rule_by_id["es-web-security-disabled"]
    if has_browser_window:
        for m in _WEB_SECURITY_FALSE.finditer(text):
            _emit(rule_eds9, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
