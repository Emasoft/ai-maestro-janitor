"""Tests for scripts/lib/electron_security_patterns.py.

Pattern-coverage tests for the Wave-32 distill-round-18 angle (Electron
desktop-app security). 9 rules, 2 positive/negative tests per rule
(18 rule-specific tests) plus data-model sanity checks.

Each rule has:
  - one positive test exercising the canary (should flag)
  - one negative test exercising the carve-out / context filter (should not flag)
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import electron_security_patterns as esp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 9 documented rule IDs."""
    assert isinstance(esp.RULES, tuple)
    rule_ids = {r.id for r in esp.RULES}
    expected = {
        "es-node-integration-renderer",
        "es-context-isolation-disabled",
        "es-remote-module-enabled",
        "es-renderer-sandbox-disabled",
        "es-shell-open-external-unvalidated",
        "es-file-protocol-path-traversal",
        "es-ipc-handler-no-validation",
        "es-load-url-user-input",
        "es-web-security-disabled",
    }
    assert expected == rule_ids
    assert len(esp.RULES) == 9


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in esp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = esp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-03",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-03"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert esp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        "const { shell } = require('electron');\n"
        "const { BrowserWindow } = require('electron');\n"
        "shell.openExternal(url);\n"
        "sandbox: false\n"
    )
    findings = esp.scan_text(src)
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


# ---------- Helper -------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[esp.Finding]:
    return [f for f in esp.scan_text(text) if f.rule_id == rule_id]


# ---------- EDS1 : es-node-integration-renderer --------------------------


def test_eds1_node_integration_true_flags_with_electron_import() -> None:
    """nodeIntegration: true with electron import → CRITICAL hit."""
    src = (
        "const { BrowserWindow } = require('electron');\n"
        "const win = new BrowserWindow({\n"
        "  webPreferences: {\n"
        "    nodeIntegration: true,\n"
        "    contextIsolation: false,\n"
        "  }\n"
        "});\n"
    )
    hits = _hits("es-node-integration-renderer", src)
    assert hits, "Expected CRITICAL finding for nodeIntegration: true"
    assert hits[0].severity == "CRITICAL"


def test_eds1_node_integration_true_no_electron_import_silent() -> None:
    """nodeIntegration: true without electron import → no hit (gate filters Jest configs)."""
    src = (
        "// jest.config.js — not an Electron main file\n"
        "module.exports = {\n"
        "  testEnvironmentOptions: {\n"
        "    nodeIntegration: true,\n"
        "  }\n"
        "};\n"
    )
    hits = _hits("es-node-integration-renderer", src)
    assert not hits, "Should be silent without Electron import gate"


# ---------- EDS2 : es-context-isolation-disabled -------------------------


def test_eds2_context_isolation_false_flags() -> None:
    """contextIsolation: false with electron import → CRITICAL hit."""
    src = (
        "const { BrowserWindow } = require('electron');\n"
        "const win = new BrowserWindow({\n"
        "  webPreferences: {\n"
        "    contextIsolation: false,\n"
        "    preload: path.join(__dirname, 'preload.js'),\n"
        "  }\n"
        "});\n"
    )
    hits = _hits("es-context-isolation-disabled", src)
    assert hits, "Expected CRITICAL finding for contextIsolation: false"
    assert hits[0].severity == "CRITICAL"


def test_eds2_context_isolation_false_no_electron_import_silent() -> None:
    """contextIsolation: false without electron import → no hit."""
    src = (
        "// Some non-Electron config\n"
        "const opts = { contextIsolation: false };\n"
    )
    hits = _hits("es-context-isolation-disabled", src)
    assert not hits, "Should be silent without Electron import gate"


# ---------- EDS3 : es-remote-module-enabled ------------------------------


def test_eds3_enable_remote_module_true_flags() -> None:
    """enableRemoteModule: true with electron import → HIGH hit."""
    src = (
        "import { BrowserWindow } from 'electron';\n"
        "const win = new BrowserWindow({\n"
        "  webPreferences: {\n"
        "    enableRemoteModule: true,\n"
        "    nodeIntegration: false,\n"
        "  }\n"
        "});\n"
    )
    hits = _hits("es-remote-module-enabled", src)
    assert hits, "Expected HIGH finding for enableRemoteModule: true"
    assert hits[0].severity == "HIGH"


def test_eds3_enable_remote_module_false_silent() -> None:
    """enableRemoteModule: false → no hit."""
    src = (
        "const { BrowserWindow } = require('electron');\n"
        "const win = new BrowserWindow({\n"
        "  webPreferences: {\n"
        "    enableRemoteModule: false,\n"
        "  }\n"
        "});\n"
    )
    hits = _hits("es-remote-module-enabled", src)
    assert not hits, "enableRemoteModule: false should not be flagged"


# ---------- EDS4 : es-renderer-sandbox-disabled --------------------------


def test_eds4_sandbox_false_with_browser_window_flags() -> None:
    """sandbox: false with BrowserWindow in file → HIGH hit."""
    src = (
        "const { BrowserWindow } = require('electron');\n"
        "const win = new BrowserWindow({\n"
        "  webPreferences: {\n"
        "    sandbox: false,\n"
        "    contextIsolation: true,\n"
        "  }\n"
        "});\n"
    )
    hits = _hits("es-renderer-sandbox-disabled", src)
    assert hits, "Expected HIGH finding for sandbox: false in Electron context"
    assert hits[0].severity == "HIGH"


def test_eds4_sandbox_false_jest_config_silent() -> None:
    """sandbox: false in a Jest config without BrowserWindow → no hit."""
    src = (
        "// jest.config.js\n"
        "module.exports = {\n"
        "  testEnvironment: 'jsdom',\n"
        "  testEnvironmentOptions: { sandbox: false },\n"
        "};\n"
    )
    hits = _hits("es-renderer-sandbox-disabled", src)
    assert not hits, "sandbox: false in Jest config should be suppressed"


# ---------- EDS5 : es-shell-open-external-unvalidated --------------------


def test_eds5_shell_open_external_variable_arg_flags() -> None:
    """shell.openExternal with variable argument → CRITICAL hit."""
    src = (
        "const { shell } = require('electron');\n"
        "ipcMain.on('open-link', (event, url) => {\n"
        "  shell.openExternal(url);\n"
        "});\n"
    )
    hits = _hits("es-shell-open-external-unvalidated", src)
    assert hits, "Expected CRITICAL finding for openExternal with variable"
    assert hits[0].severity == "CRITICAL"


def test_eds5_shell_open_external_hardcoded_https_silent() -> None:
    """shell.openExternal with hardcoded https:// URL → no hit (safe literal)."""
    src = (
        "const { shell } = require('electron');\n"
        "shell.openExternal('https://docs.example.com/help');\n"
    )
    hits = _hits("es-shell-open-external-unvalidated", src)
    assert not hits, "Hardcoded https:// URL should be suppressed as safe literal"


# ---------- EDS6 : es-file-protocol-path-traversal -----------------------


def test_eds6_register_file_protocol_flags() -> None:
    """protocol.registerFileProtocol → HIGH hit (all calls reviewed)."""
    src = (
        "const { protocol } = require('electron');\n"
        "protocol.registerFileProtocol('app', (request, callback) => {\n"
        "  const filePath = path.join(__dirname, 'dist', "
        "    request.url.replace('app://', ''));\n"
        "  callback(filePath);\n"
        "});\n"
    )
    hits = _hits("es-file-protocol-path-traversal", src)
    assert hits, "Expected HIGH finding for registerFileProtocol"
    assert hits[0].severity == "HIGH"


def test_eds6_register_buffer_protocol_flags() -> None:
    """protocol.registerBufferProtocol → HIGH hit (all register*Protocol reviewed)."""
    src = (
        "const { protocol } = require('electron');\n"
        "protocol.registerBufferProtocol('safe-app', handler);\n"
    )
    hits = _hits("es-file-protocol-path-traversal", src)
    assert hits, "Expected HIGH finding for registerBufferProtocol"


# ---------- EDS7 : es-ipc-handler-no-validation --------------------------


def test_eds7_ipc_main_handle_with_child_process_flags() -> None:
    """ipcMain.handle with child_process in file → HIGH hit."""
    src = (
        "const { ipcMain } = require('electron');\n"
        "const { exec } = require('child_process');\n"
        "\n"
        "ipcMain.handle('run-command', async (event, cmd) => {\n"
        "  return new Promise((resolve, reject) => {\n"
        "    exec(cmd, (err, stdout) => {\n"
        "      if (err) reject(err); else resolve(stdout);\n"
        "    });\n"
        "  });\n"
        "});\n"
    )
    hits = _hits("es-ipc-handler-no-validation", src)
    assert hits, "Expected HIGH finding for ipcMain.handle + child_process co-occurrence"
    assert hits[0].severity == "HIGH"


def test_eds7_ipc_main_handle_without_child_process_silent() -> None:
    """ipcMain.handle without child_process in file → no hit (gate suppresses safe handlers)."""
    src = (
        "const { ipcMain } = require('electron');\n"
        "\n"
        "ipcMain.handle('get-version', async () => {\n"
        "  return app.getVersion();\n"
        "});\n"
    )
    hits = _hits("es-ipc-handler-no-validation", src)
    assert not hits, "ipcMain.handle without child_process should be suppressed"


# ---------- EDS8 : es-load-url-user-input --------------------------------


def test_eds8_load_url_variable_arg_flags() -> None:
    """win.loadURL with variable argument → HIGH hit."""
    src = (
        "const { ipcMain, BrowserWindow } = require('electron');\n"
        "let mainWindow;\n"
        "\n"
        "ipcMain.on('navigate', (event, targetUrl) => {\n"
        "  mainWindow.loadURL(targetUrl);\n"
        "});\n"
    )
    hits = _hits("es-load-url-user-input", src)
    assert hits, "Expected HIGH finding for loadURL with variable arg"
    assert hits[0].severity == "HIGH"


def test_eds8_load_url_hardcoded_file_url_silent() -> None:
    """win.loadURL with hardcoded file:// quoted URL → no hit (safe literal)."""
    # Single-quoted file:// string is the canonical safe pattern — the
    # suppressor matches the quote+scheme prefix and silences the finding.
    src = (
        "const { BrowserWindow } = require('electron');\n"
        "const win = new BrowserWindow({});\n"
        "win.loadURL('file:///app/index.html');\n"
    )
    hits = _hits("es-load-url-user-input", src)
    assert not hits, "Hardcoded file:// URL literal should be suppressed"


# ---------- EDS9 : es-web-security-disabled ------------------------------


def test_eds9_web_security_false_with_browser_window_flags() -> None:
    """webSecurity: false with BrowserWindow in file → HIGH hit."""
    src = (
        "const { BrowserWindow } = require('electron');\n"
        "const win = new BrowserWindow({\n"
        "  webPreferences: {\n"
        "    webSecurity: false,\n"
        "    nodeIntegration: false,\n"
        "    contextIsolation: true,\n"
        "  }\n"
        "});\n"
    )
    hits = _hits("es-web-security-disabled", src)
    assert hits, "Expected HIGH finding for webSecurity: false in Electron context"
    assert hits[0].severity == "HIGH"


def test_eds9_web_security_false_without_browser_window_silent() -> None:
    """webSecurity: false in a non-Electron config → no hit (Vite/Webpack FP prevention)."""
    src = (
        "// vite.config.js\n"
        "export default {\n"
        "  server: {\n"
        "    proxy: { '/api': 'http://localhost:3000' },\n"
        "    // Some unrelated option:\n"
        "    webSecurity: false,\n"
        "  }\n"
        "};\n"
    )
    hits = _hits("es-web-security-disabled", src)
    assert not hits, "webSecurity: false in Vite config should be suppressed"
