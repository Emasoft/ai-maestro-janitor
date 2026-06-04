"""Tests for scripts/lib/browser_cookies_patterns.py.

Pattern-coverage tests for the Wave-24 distill-round-10 browser
cookie hygiene catalogue (6 rules: localStorage / sessionStorage auth
token persistence, cookie-without-HttpOnly, SameSite=None without
Secure, Django settings cookie-secure-false-prod, and __Host-/__Secure-
cookie prefix-contract violations). Each rule has one positive test
(canary triggers) and one negative test (carve-out / context filter
suppresses).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import browser_cookies_patterns as bcp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(bcp.RULES, tuple)
    rule_ids = {r.id for r in bcp.RULES}
    expected = {
        "bch-auth-token-in-local-storage",
        "bch-auth-token-in-session-storage",
        "bch-cookie-set-no-httponly",
        "bch-cookie-samesite-none-no-secure",
        "bch-django-cookie-secure-false-prod",
        "bch-host-prefix-cookie-violated",
    }
    assert expected == rule_ids
    assert len(bcp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in bcp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = bcp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert bcp.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[bcp.Finding]:
    return [f for f in bcp.scan_text(text) if f.rule_id == rule_id]


# ---------- P1 : bch-auth-token-in-local-storage --------------------------


def test_p1_localstorage_auth_token_flags() -> None:
    """`localStorage.setItem('token', ...)` → HIGH hit."""
    src = (
        "const login = async (email, pwd) => {\n"
        "  const res = await axios.post('/auth/login', { email, pwd });\n"
        "  localStorage.setItem('token', res.data.access_token);\n"
        "};\n"
    )
    hits = _hits("bch-auth-token-in-local-storage", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-04"


def test_p1_localstorage_non_auth_key_does_not_flag() -> None:
    """`localStorage.setItem('theme', ...)` is benign — must NOT flag."""
    src = (
        "localStorage.setItem('theme', 'dark');\n"
        "localStorage.setItem('lang', 'en-US');\n"
        "localStorage.setItem('lastVisit', String(Date.now()));\n"
    )
    assert _hits("bch-auth-token-in-local-storage", src) == []


# ---------- P2 : bch-auth-token-in-session-storage ------------------------


def test_p2_sessionstorage_auth_token_flags() -> None:
    """`sessionStorage.setItem('access_token', ...)` → HIGH hit."""
    src = (
        "function setSession(t) {\n"
        "  sessionStorage.setItem('access_token', t);\n"
        "}\n"
    )
    hits = _hits("bch-auth-token-in-session-storage", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p2_sessionstorage_non_auth_key_does_not_flag() -> None:
    """`sessionStorage.setItem('cart', ...)` is benign — must NOT flag."""
    src = (
        "sessionStorage.setItem('cart', JSON.stringify(items));\n"
        "sessionStorage.setItem('scrollPos', '450');\n"
    )
    assert _hits("bch-auth-token-in-session-storage", src) == []


# ---------- P3 : bch-cookie-set-no-httponly -------------------------------


def test_p3_express_session_cookie_without_httponly_flags() -> None:
    """Express `res.cookie('sessionid', ..., {secure: true})` without
    httpOnly → HIGH hit."""
    src = (
        "app.post('/login', async (req, res) => {\n"
        "  const sid = await createSession();\n"
        "  res.cookie('sessionid', sid, { secure: true, sameSite: 'lax' });\n"
        "  res.json({ ok: true });\n"
        "});\n"
    )
    hits = _hits("bch-cookie-set-no-httponly", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-06"


def test_p3_cookie_with_httponly_true_is_suppressed() -> None:
    """`res.cookie('sessionid', sid, { httpOnly: true, ... })` is
    correct and must NOT flag."""
    src = (
        "app.post('/login', async (req, res) => {\n"
        "  res.cookie('sessionid', sid, { httpOnly: true, secure: true });\n"
        "});\n"
    )
    assert _hits("bch-cookie-set-no-httponly", src) == []


# ---------- P4 : bch-cookie-samesite-none-no-secure -----------------------


def test_p4_samesite_none_without_secure_flags() -> None:
    """`sameSite: 'none'` without `secure: true` nearby → CRITICAL hit."""
    src = (
        "app.use(session({\n"
        "  name: 'sid',\n"
        "  cookie: {\n"
        "    httpOnly: true,\n"
        "    sameSite: 'none',\n"
        "    maxAge: 86400000,\n"
        "  },\n"
        "}));\n"
    )
    hits = _hits("bch-cookie-samesite-none-no-secure", src)
    assert hits
    assert hits[0].severity == "CRITICAL"
    assert hits[0].owasp_asi == "ASI-07"


def test_p4_samesite_none_with_secure_is_suppressed() -> None:
    """`sameSite: 'none'` accompanied by `secure: true` → no flag."""
    src = (
        "app.use(session({\n"
        "  cookie: {\n"
        "    httpOnly: true,\n"
        "    sameSite: 'none',\n"
        "    secure: true,\n"
        "  },\n"
        "}));\n"
    )
    assert _hits("bch-cookie-samesite-none-no-secure", src) == []


# ---------- P5 : bch-django-cookie-secure-false-prod ----------------------


def test_p5_django_session_cookie_secure_false_flags() -> None:
    """Django `SESSION_COOKIE_SECURE = False` at module level → HIGH hit."""
    src = (
        "# settings.py — production\n"
        "DEBUG = False\n"
        "ALLOWED_HOSTS = ['app.example.com']\n"
        "SESSION_COOKIE_SECURE = False\n"
        "CSRF_COOKIE_SECURE = False\n"
    )
    hits = _hits("bch-django-cookie-secure-false-prod", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-06"


def test_p5_django_session_cookie_secure_true_is_suppressed() -> None:
    """Django `SESSION_COOKIE_SECURE = True` → no flag (correct prod
    settings, no absence-form match either)."""
    src = (
        "# settings.py — production\n"
        "DEBUG = False\n"
        "ALLOWED_HOSTS = ['app.example.com']\n"
        "SESSION_COOKIE_SECURE = True\n"
        "CSRF_COOKIE_SECURE = True\n"
    )
    assert _hits("bch-django-cookie-secure-false-prod", src) == []


# ---------- P6 : bch-host-prefix-cookie-violated --------------------------


def test_p6_host_prefix_with_domain_flag_violates_contract() -> None:
    """`__Host-session` with Domain= present → MEDIUM hit (browser will
    silently reject)."""
    src = (
        "res.cookie('__Host-session', sid, {\n"
        "  httpOnly: true,\n"
        "  secure: true,\n"
        "  sameSite: 'lax',\n"
        "  path: '/api',\n"
        "  domain: 'app.example.com',\n"
        "});\n"
    )
    hits = _hits("bch-host-prefix-cookie-violated", src)
    assert hits
    assert hits[0].severity == "MEDIUM"
    assert hits[0].owasp_asi == "ASI-06"


def test_p6_host_prefix_correct_contract_is_suppressed() -> None:
    """`__Host-` cookie with Secure, Path=/ and no Domain= → no flag."""
    src = (
        "res.cookie('__Host-session', sid, {\n"
        "  httpOnly: true,\n"
        "  secure: true,\n"
        "  sameSite: 'lax',\n"
        "  path: '/',\n"
        "});\n"
    )
    assert _hits("bch-host-prefix-cookie-violated", src) == []
