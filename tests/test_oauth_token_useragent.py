"""Regression guard: the OAuth token-endpoint requests MUST send a non-default
User-Agent (TRDD-32acd15f / verified 2026-06-09).

ROOT CAUSE this guards: urllib's default ``Python-urllib/<ver>`` User-Agent is banned
by Cloudflare at ``platform.claude.com/v1/oauth/token`` with **HTTP 403 / error code
1010** ("banned browser signature"). With no UA, BOTH the capture's code-exchange and
the keepalive refresh silently fail — the rotator can never mint or renew a slot. Adding
the ``claude-account-rotator`` UA (the same one the /roles + /usage calls already use)
gets straight past Cloudflare. Empirically: no-UA → 1010; rotator-UA → clean app response.

These tests capture the urllib Request the code builds (no network) and assert a
non-default User-Agent is set on the token POST.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scripts" / "oauth_rotator"))

import rotator  # noqa: E402
import slot_capture_browser as scb  # noqa: E402


class _FakeResp:
    """Minimal context-manager stand-in for urlopen's return (a token JSON body)."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


def _ua_of(req) -> str | None:
    """urllib lowercases header KEYS in Request.headers, so look up 'User-agent'."""
    # Request stores headers title-cased on the first word: 'User-agent'.
    for k, v in req.header_items():
        if k.lower() == "user-agent":
            return v
    return None


def test_capture_exchange_sends_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """slot_capture_browser._exchange MUST send a non-default User-Agent (else CF 1010)."""
    captured = {}

    def _fake_urlopen(req, *a, **k):
        captured["ua"] = _ua_of(req)
        return _FakeResp(b'{"access_token":"a","refresh_token":"r","expires_in":28800}')

    monkeypatch.setattr(scb.urllib.request, "urlopen", _fake_urlopen)
    scb._exchange("code", "verifier", "state")
    ua = captured.get("ua")
    assert ua, "no User-Agent set on the token exchange → Cloudflare 1010"
    assert "python-urllib" not in ua.lower(), f"default urllib UA {ua!r} is CF-banned"
    assert ua == "claude-account-rotator"


def test_refresh_sends_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """rotator.refresh_oauth_token MUST send a non-default User-Agent (else CF 1010 on
    every keepalive refresh — the rotator silently stops renewing)."""
    captured = {}

    def _fake_urlopen(req, *a, **k):
        captured["ua"] = _ua_of(req)
        return _FakeResp(b'{"access_token":"a2","refresh_token":"r2","expires_in":28800}')

    monkeypatch.setattr(rotator.urllib.request, "urlopen", _fake_urlopen)
    out = rotator.refresh_oauth_token({"claudeAiOauth": {"refreshToken": "r0"}})
    assert out is not None, "refresh returned None — the fake response should have been accepted"
    ua = captured.get("ua")
    assert ua, "no User-Agent set on the refresh → Cloudflare 1010"
    assert "python-urllib" not in ua.lower(), f"default urllib UA {ua!r} is CF-banned"
    assert ua == "claude-account-rotator"


def test_refresh_no_token_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blob with no refreshToken returns None WITHOUT hitting the network (no UA needed)."""
    called = {"n": 0}
    monkeypatch.setattr(rotator.urllib.request, "urlopen",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    assert rotator.refresh_oauth_token({"claudeAiOauth": {}}) is None
    assert called["n"] == 0
