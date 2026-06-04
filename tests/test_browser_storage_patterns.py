"""Tests for browser_storage_patterns — 2 per rule, plus module-level checks.

Wave-30 browser storage pattern library tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the scripts/lib directory is importable regardless of where pytest
# is invoked from.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "lib"))

from browser_storage_patterns import RULES, Finding, Rule, scan_text  # noqa: E402

# ---------------------------------------------------------------------------
# Module-level sanity
# ---------------------------------------------------------------------------


def test_rules_is_nonempty_tuple():
    """RULES is a non-empty tuple of Rule instances."""
    assert isinstance(RULES, tuple)
    assert len(RULES) >= 5


def test_every_rule_has_required_fields():
    """Every Rule has non-empty id, name, severity, description, owasp_asi."""
    for rule in RULES:
        assert isinstance(rule, Rule)
        assert rule.id
        assert rule.name
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
        assert rule.description
        assert rule.owasp_asi


def test_scan_text_empty_returns_empty_list():
    """scan_text('') returns an empty list without error."""
    assert scan_text("") == []


def test_finding_is_named_tuple():
    """Finding can be constructed and accessed by field name."""
    f = Finding(
        rule_id="x",
        line=1,
        column=1,
        matched_text="match",
        severity="HIGH",
        description="desc",
        owasp_asi="ASI-07",
    )
    assert f.rule_id == "x"
    assert f.line == 1


# ---------------------------------------------------------------------------
# BS-01 : browser-storage-token-in-localstorage
# ---------------------------------------------------------------------------


def test_bs01_fires_on_localstorage_setitem_with_token_key():
    """BS-01 fires when localStorage.setItem() stores a token-named key."""
    code = "localStorage.setItem('github_token', data.token);"
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-token-in-localstorage" in ids


def test_bs01_fires_on_sessionstorage_setitem_with_jwt_key():
    """BS-01 fires on sessionStorage.setItem() with a JWT-semantic key."""
    code = 'sessionStorage.setItem("jwt_access", token);'
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-token-in-localstorage" in ids


def test_bs01_does_not_fire_on_nonsensitive_key():
    """BS-01 does NOT fire on localStorage.setItem() with a non-sensitive key."""
    code = "localStorage.setItem('theme', 'dark');"
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-token-in-localstorage" not in ids


# ---------------------------------------------------------------------------
# BS-02 : browser-storage-token-read-to-auth-header
# ---------------------------------------------------------------------------


def test_bs02_fires_when_getitem_followed_by_authorization_bearer():
    """BS-02 fires when getItem(token) is followed by Authorization: Bearer."""
    code = (
        "const token = localStorage.getItem('github_token');\n"
        "config.headers.Authorization = `Bearer ${token}`;\n"
    )
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-token-read-to-auth-header" in ids


def test_bs02_fires_on_axios_interceptor_pattern():
    """BS-02 fires on a realistic Axios request interceptor pattern."""
    code = (
        "api.interceptors.request.use((config) => {\n"
        "  const tok = localStorage.getItem('auth_token');\n"
        "  if (tok) { config.headers['Authorization'] = 'Bearer ' + tok; }\n"
        "  return config;\n"
        "});\n"
    )
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-token-read-to-auth-header" in ids


def test_bs02_does_not_fire_on_getitem_without_auth_header():
    """BS-02 does NOT fire when getItem is used without an Authorization header."""
    code = (
        "const theme = localStorage.getItem('auth_theme');\n"
        "document.body.classList.add(theme);\n"
    )
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-token-read-to-auth-header" not in ids


# ---------------------------------------------------------------------------
# BS-03 : browser-storage-route-guard-from-localstorage
# ---------------------------------------------------------------------------


def test_bs03_fires_on_ternary_route_guard():
    """BS-03 fires when getItem(token) is used as a ternary route guard."""
    code = (
        "const PrivateRoute = ({ children }) => {\n"
        "  const token = localStorage.getItem('github_token');\n"
        "  return localStorage.getItem('github_token') ? children : <Navigate to='/login' />;\n"
        "};\n"
    )
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-route-guard-from-localstorage" in ids


def test_bs03_fires_on_session_guard_pattern():
    """BS-03 fires on sessionStorage.getItem(session) ? ... : ... pattern."""
    code = "return sessionStorage.getItem('session') ? <Dashboard /> : <Login />;"
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-route-guard-from-localstorage" in ids


def test_bs03_does_not_fire_on_nonguard_getitem():
    """BS-03 does NOT fire on a plain getItem without a ternary."""
    code = "const val = localStorage.getItem('auth_theme');\nconsole.log(val);\n"
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-route-guard-from-localstorage" not in ids


# ---------------------------------------------------------------------------
# BS-04 : browser-storage-no-persist-guard
# ---------------------------------------------------------------------------


def test_bs04_fires_when_sensitive_setitem_without_persist():
    """BS-04 fires when setItem stores a token key and persist() is absent."""
    code = (
        "localStorage.setItem('api_key', response.key);\n"
        "localStorage.setItem('user', JSON.stringify(user));\n"
    )
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-no-persist-guard" in ids


def test_bs04_fires_on_access_token_without_persist():
    """BS-04 fires for 'access_token' key stored without navigator.storage.persist()."""
    code = 'localStorage.setItem("access_token", data.access_token);\n'
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-no-persist-guard" in ids


def test_bs04_does_not_fire_when_persist_is_present():
    """BS-04 does NOT fire when navigator.storage.persist() is called in the file."""
    code = (
        "localStorage.setItem('auth_token', token);\n"
        "navigator.storage.persist();\n"
    )
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-no-persist-guard" not in ids


# ---------------------------------------------------------------------------
# BS-05 : browser-storage-sw-cache-api-put
# ---------------------------------------------------------------------------


def test_bs05_fires_on_caches_open_then_put():
    """BS-05 fires on the caches.open().then(cache => cache.put(...)) pattern."""
    code = (
        "self.addEventListener('fetch', (event) => {\n"
        "  event.respondWith(\n"
        "    caches.open('api-cache-v1').then((cache) => {\n"
        "      return fetch(event.request).then((resp) => {\n"
        "        cache.put(event.request, resp.clone());\n"
        "        return resp;\n"
        "      });\n"
        "    })\n"
        "  );\n"
        "});\n"
    )
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-sw-cache-api-put" in ids


def test_bs05_fires_on_respond_with_fetch_pattern():
    """BS-05 fires on event.respondWith(fetch(...)) service worker pattern."""
    code = (
        "self.addEventListener('fetch', event => {\n"
        "  event.respondWith(fetch(event.request.clone()).then(r => r));\n"
        "});\n"
    )
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-sw-cache-api-put" in ids


def test_bs05_does_not_fire_on_plain_fetch_without_caches():
    """BS-05 does NOT fire on a plain fetch() call with no caches.open() or respondWith."""
    code = "fetch('/api/data').then(r => r.json()).then(d => console.log(d));\n"
    findings = scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "browser-storage-sw-cache-api-put" not in ids


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_scan_text_deduplicates_same_match():
    """scan_text does not emit duplicate findings for the same rule+line+col."""
    code = "localStorage.setItem('github_token', tok);\n"
    findings = scan_text(code)
    bs01 = [f for f in findings if f.rule_id == "browser-storage-token-in-localstorage"]
    assert len(bs01) == 1


# ---------------------------------------------------------------------------
# Finding field correctness
# ---------------------------------------------------------------------------


def test_finding_line_and_column_are_positive():
    """Every Finding has a positive line and column number."""
    code = "localStorage.setItem('access_token', tok);\n"
    findings = scan_text(code)
    for f in findings:
        assert f.line >= 1
        assert f.column >= 1


def test_finding_matched_text_is_truncated_when_long():
    """matched_text is capped at 200 chars + ellipsis for very long matches."""
    long_key = "a" * 300
    code = f"localStorage.setItem('token_{long_key}', tok);"
    findings = scan_text(code)
    for f in findings:
        assert len(f.matched_text) <= 204  # 200 + len("…")
