"""Tests for scripts/lib/headless_browser_patterns.py.

Pattern-coverage tests for the Wave-28 distill-round-14 headless-browser
catalogue (7 anti-patterns covering Playwright / Puppeteer / Selenium /
raw Chrome automation). Each rule has at least two tests: one positive
(canary) and one negative (carve-out or context filter).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import headless_browser_patterns as hbp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(hbp.RULES, tuple)
    rule_ids = {r.id for r in hbp.RULES}
    expected = {
        "headless-evaluate-fstring-injection",
        "headless-storage-state-committed",
        "headless-no-sandbox-disable-web-security",
        "headless-remote-debugging-port-exposed",
        "headless-user-data-dir-repo-path",
        "headless-ignore-certificate-errors",
        "headless-credential-file-direct-read",
    }
    assert expected == rule_ids
    assert len(hbp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in hbp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = hbp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-05",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-05"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert hbp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Findings must be returned sorted by (line, column, rule_id)."""
    src = (
        "ignoreHTTPSErrors: true\n"
        "await page.evaluate(f\"document.title = '{x}'\")\n"
        "storageState: 'playwright/.auth/user.json'\n"
    )
    findings = hbp.scan_text(src)
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


# ---------- HB-001 : evaluate f-string injection -------------------------


def test_hb001_positive_python_fstring() -> None:
    """page.evaluate(f'...') in Python triggers HB-001."""
    src = "await page.evaluate(f\"window.__showClick({cx}, {cy})\")\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-evaluate-fstring-injection" in ids


def test_hb001_positive_js_template_literal() -> None:
    """page.evaluate with JS template literal and interpolation triggers HB-001."""
    src = "await page.evaluate(`window.__cmd(\"${userInput}\")`)\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-evaluate-fstring-injection" in ids


def test_hb001_positive_frame_evaluate() -> None:
    """frame.evaluate(f'...') also triggers HB-001."""
    src = "result = await frame.evaluate(f'return {selector};')\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-evaluate-fstring-injection" in ids


def test_hb001_negative_safe_arg_passing() -> None:
    """page.evaluate with a static string and separate argument does not trigger."""
    src = (
        "await page.evaluate('(coords) => window.__showClick(coords.x, coords.y)',\n"
        "                    {'x': cx, 'y': cy})\n"
    )
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-evaluate-fstring-injection" not in ids


def test_hb001_negative_plain_string_constant() -> None:
    """page.evaluate with a plain (non-f) string literal does not trigger."""
    src = "await page.evaluate('window.scrollBy(0, 200)')\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-evaluate-fstring-injection" not in ids


# ---------- HB-002 : storage_state committed -----------------------------


def test_hb002_positive_storage_state_path_kwarg() -> None:
    """storage_state(path='auth.json') triggers HB-002."""
    src = "await context.storage_state(path='auth.json')\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-storage-state-committed" in ids


def test_hb002_positive_new_context_storage_state() -> None:
    """new_context(storage_state='tests/fixtures/auth.json') triggers HB-002."""
    src = "context = await browser.new_context(storage_state='tests/fixtures/auth.json')\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-storage-state-committed" in ids


def test_hb002_positive_ts_config_storage_state() -> None:
    """storageState: '...' in playwright.config.ts triggers HB-002."""
    src = "  use: { storageState: 'playwright/.auth/user.json' },\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-storage-state-committed" in ids


def test_hb002_negative_no_storage_state() -> None:
    """Code that does not call storage_state or storageState does not trigger."""
    src = "context = await browser.new_context(viewport={'width': 1280, 'height': 720})\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-storage-state-committed" not in ids


def test_hb002_negative_unrelated_json_path() -> None:
    """A JSON path in an unrelated context does not trigger HB-002."""
    src = "config = json.load(open('playwright/config.json'))\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-storage-state-committed" not in ids


# ---------- HB-003 : no-sandbox + disable-web-security -------------------


def test_hb003_positive_single_line_combo() -> None:
    """Both flags on a single line trigger HB-003."""
    src = "args=['--no-sandbox', '--disable-web-security']\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-no-sandbox-disable-web-security" in ids


def test_hb003_positive_multiline_args() -> None:
    """Both flags on separate lines within 10 lines trigger HB-003."""
    src = (
        "browser = await p.chromium.launch(args=[\n"
        "    '--no-sandbox',\n"
        "    '--disable-setuid-sandbox',\n"
        "    '--disable-web-security',\n"
        "])\n"
    )
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-no-sandbox-disable-web-security" in ids


def test_hb003_positive_reverse_order() -> None:
    """--disable-web-security before --no-sandbox triggers HB-003."""
    src = "args=['--disable-web-security', '--no-sandbox']\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-no-sandbox-disable-web-security" in ids


def test_hb003_negative_no_sandbox_only() -> None:
    """--no-sandbox alone (without --disable-web-security) does not trigger HB-003."""
    src = "browser = await p.chromium.launch(args=['--no-sandbox'])\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-no-sandbox-disable-web-security" not in ids


def test_hb003_negative_disable_web_security_only() -> None:
    """--disable-web-security alone does not trigger HB-003."""
    src = "args=['--disable-web-security']\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-no-sandbox-disable-web-security" not in ids


# ---------- HB-004 : remote debugging port exposed -----------------------


def test_hb004_positive_port_no_address() -> None:
    """--remote-debugging-port without loopback address triggers HB-004."""
    src = "subprocess.Popen(['google-chrome', '--remote-debugging-port=9222', '--headless'])\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-remote-debugging-port-exposed" in ids


def test_hb004_positive_in_playwright_args() -> None:
    """--remote-debugging-port in Playwright launch args triggers HB-004."""
    src = "browser = await p.chromium.launch(args=['--remote-debugging-port=9333'])\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-remote-debugging-port-exposed" in ids


def test_hb004_negative_loopback_address_same_line() -> None:
    """--remote-debugging-port with --remote-debugging-address=127.0.0.1 is safe."""
    src = (
        "args=['--remote-debugging-port=9222', '--remote-debugging-address=127.0.0.1']\n"
    )
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-remote-debugging-port-exposed" not in ids


def test_hb004_negative_localhost_address() -> None:
    """--remote-debugging-address=localhost suppresses HB-004."""
    src = (
        "args=['--remote-debugging-address=localhost', '--remote-debugging-port=9222']\n"
    )
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-remote-debugging-port-exposed" not in ids


# ---------- HB-005 : userDataDir / --user-data-dir in repo path ----------


def test_hb005_positive_userdatadir_relative() -> None:
    """userDataDir: './browser-profile' triggers HB-005."""
    src = "const browser = await puppeteer.launch({ userDataDir: './browser-profile', headless: true });\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-user-data-dir-repo-path" in ids


def test_hb005_positive_user_data_dir_flag() -> None:
    """--user-data-dir=./tests/chrome-profile triggers HB-005."""
    src = "opts.add_argument('--user-data-dir=./tests/chrome-profile')\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-user-data-dir-repo-path" in ids


def test_hb005_positive_launch_persistent_context() -> None:
    """launch_persistent_context with a repo path triggers HB-005."""
    src = (
        "browser = await p.chromium.launch_persistent_context(\n"
        "    './chrome-data',\n"
        "    headless=True,\n"
        ")\n"
    )
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-user-data-dir-repo-path" in ids


def test_hb005_negative_tempfile_mkdtemp() -> None:
    """userDataDir built from tempfile.mkdtemp() does not trigger HB-005."""
    src = "const dir = mkdtemp(); const browser = await puppeteer.launch({ userDataDir: dir });\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-user-data-dir-repo-path" not in ids


def test_hb005_negative_tmp_prefix() -> None:
    """--user-data-dir pointing into /tmp does not trigger HB-005."""
    src = "opts.add_argument('--user-data-dir=/tmp/chrome-run-12345')\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-user-data-dir-repo-path" not in ids


# ---------- HB-006 : ignore certificate errors ---------------------------


def test_hb006_positive_ignore_https_errors_js() -> None:
    """ignoreHTTPSErrors: true in Puppeteer config triggers HB-006."""
    src = "const browser = await puppeteer.launch({ ignoreHTTPSErrors: true });\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-ignore-certificate-errors" in ids


def test_hb006_positive_chrome_flag() -> None:
    """--ignore-certificate-errors flag triggers HB-006."""
    src = "browser = await p.chromium.launch(args=['--ignore-certificate-errors'])\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-ignore-certificate-errors" in ids


def test_hb006_positive_playwright_python() -> None:
    """ignore_https_errors=True in Playwright Python triggers HB-006."""
    src = "context = await browser.new_context(ignore_https_errors=True)\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-ignore-certificate-errors" in ids


def test_hb006_positive_accept_insecure_certs_selenium() -> None:
    """acceptInsecureCerts: True in Selenium capability triggers HB-006."""
    src = "opts.set_capability('acceptInsecureCerts', True)\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-ignore-certificate-errors" in ids


def test_hb006_negative_no_cert_bypass() -> None:
    """Code that does not suppress TLS validation does not trigger HB-006."""
    src = (
        "browser = await p.chromium.launch(headless=True)\n"
        "context = await browser.new_context()\n"
    )
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-ignore-certificate-errors" not in ids


def test_hb006_negative_ignore_https_errors_false() -> None:
    """ignoreHTTPSErrors: false does not trigger HB-006."""
    src = "const browser = await puppeteer.launch({ ignoreHTTPSErrors: false });\n"
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-ignore-certificate-errors" not in ids


# ---------- HB-007 : credential file direct read -------------------------


def test_hb007_positive_chrome_login_data_sqlite() -> None:
    """sqlite3.connect on a Chrome Login Data copy triggers HB-007."""
    src = (
        "import sqlite3, shutil\n"
        "shutil.copy(chrome_path / 'Login Data', '/tmp/ld.db')\n"
        "conn = sqlite3.connect('/tmp/ld.db')\n"
    )
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-credential-file-direct-read" in ids


def test_hb007_positive_cookies_sqlite_open() -> None:
    """open() call adjacent to cookies.sqlite triggers HB-007."""
    src = (
        "db_path = profile_dir / 'cookies.sqlite'\n"
        "conn = sqlite3.connect(str(db_path))\n"
    )
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-credential-file-direct-read" in ids


def test_hb007_positive_firefox_logins_json_read() -> None:
    """read_text() on logins.json triggers HB-007."""
    src = (
        "ff_profile = Path.home() / '.mozilla/firefox/abc.default/logins.json'\n"
        "data = json.loads(ff_profile.read_text())\n"
    )
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-credential-file-direct-read" in ids


def test_hb007_positive_node_login_data_read() -> None:
    """fs.readFileSync on Login Data path triggers HB-007."""
    src = (
        "const p = path.join(home, 'Library/Application Support/Google/Chrome/Default/Login Data');\n"
        "const buf = fs.readFileSync(p);\n"
    )
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-credential-file-direct-read" in ids


def test_hb007_negative_ioc_detection_exists_only() -> None:
    """path.exists() check on credential path without open/read does not trigger HB-007."""
    src = (
        "# IOC detection — just check presence, no read\n"
        "chrome_login_data = home / 'Library/Application Support/Google/Chrome/Default/Login Data'\n"
        "if chrome_login_data.exists():\n"
        "    print('CRED-006 indicator found')\n"
    )
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-credential-file-direct-read" not in ids


def test_hb007_negative_logins_json_string_constant_no_read() -> None:
    """logins.json as a string constant in a threat-db dict without read does not trigger."""
    src = (
        "THREAT_DB = {\n"
        "    'CRED-006': {\n"
        "        'paths': ['logins.json', 'Login Data', 'cookies.sqlite'],\n"
        "        'severity': 'CRITICAL',\n"
        "    }\n"
        "}\n"
    )
    ids = {f.rule_id for f in hbp.scan_text(src)}
    assert "headless-credential-file-direct-read" not in ids
