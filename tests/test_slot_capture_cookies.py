"""Tests for the OPT-IN Phase-2c keychain-cookie wiring in slot_capture_browser
(TRDD-dfc0959a): materialize-before / snapshot-after a capture, gated on
CLAUDE_ROTATOR_KEYCHAIN_COOKIES and best-effort so it NEVER breaks the proven capture.

These test the wiring HELPERS directly (no browser): the flag gate, that the right
cookie_vault calls are made when on, that nothing is called when off (byte-identical to
before), and that any cookie_vault failure is swallowed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scripts" / "oauth_rotator"))

import cookie_vault  # noqa: E402
import safe_storage  # noqa: E402
import slot_capture_browser as scb  # noqa: E402


# ---------------------------------------------------------------------------
# Flag parsing
# ---------------------------------------------------------------------------
def test_flag_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset (the default) → disabled. Capture stays byte-identical to pre-Phase-2c."""
    monkeypatch.delenv("CLAUDE_ROTATOR_KEYCHAIN_COOKIES", raising=False)
    assert scb._keychain_cookies_enabled() is False


def test_flag_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """1 / true / on / yes (any case) enable it; other values do not."""
    for v in ("1", "true", "TRUE", "on", "Yes"):
        monkeypatch.setenv("CLAUDE_ROTATOR_KEYCHAIN_COOKIES", v)
        assert scb._keychain_cookies_enabled() is True, v
    for v in ("0", "off", "", "no", "nope"):
        monkeypatch.setenv("CLAUDE_ROTATOR_KEYCHAIN_COOKIES", v)
        assert scb._keychain_cookies_enabled() is False, v


# ---------------------------------------------------------------------------
# Materialize / snapshot are NO-OPS when the flag is off (the safety property)
# ---------------------------------------------------------------------------
def test_materialize_noop_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag off → cookie_vault.materialize_from_keychain is NOT called at all."""
    monkeypatch.delenv("CLAUDE_ROTATOR_KEYCHAIN_COOKIES", raising=False)
    called: list = []
    monkeypatch.setattr(cookie_vault, "materialize_from_keychain",
                        lambda *a, **k: called.append(a))
    scb._materialize_cookies("a@x.com")
    assert called == []


def test_snapshot_noop_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag off → cookie_vault.snapshot_to_keychain is NOT called at all."""
    monkeypatch.delenv("CLAUDE_ROTATOR_KEYCHAIN_COOKIES", raising=False)
    called: list = []
    monkeypatch.setattr(cookie_vault, "snapshot_to_keychain",
                        lambda *a, **k: called.append(a))
    scb._snapshot_cookies("a@x.com")
    assert called == []


# ---------------------------------------------------------------------------
# Flag on → the right cookie_vault calls with the right profile DB path
# ---------------------------------------------------------------------------
def test_materialize_calls_cookie_vault_when_on(monkeypatch: pytest.MonkeyPatch,
                                                 tmp_path: Path) -> None:
    """Flag on → materialize_from_keychain(email, <profile>/Default/Cookies)."""
    monkeypatch.setenv("CLAUDE_ROTATOR_KEYCHAIN_COOKIES", "1")
    monkeypatch.setattr(scb.rotator, "_profiles_root", lambda: tmp_path)
    seen: list = []
    monkeypatch.setattr(cookie_vault, "materialize_from_keychain",
                        lambda email, db: seen.append((email, Path(db))) or 3)
    scb._materialize_cookies("a@x.com")
    assert seen == [("a@x.com", tmp_path / "chrome-profile-a@x.com" / "Default" / "Cookies")]


def test_snapshot_calls_cookie_vault_when_on(monkeypatch: pytest.MonkeyPatch,
                                             tmp_path: Path) -> None:
    """Flag on → snapshot_to_keychain(email, <profile>/Default/Cookies)."""
    monkeypatch.setenv("CLAUDE_ROTATOR_KEYCHAIN_COOKIES", "1")
    monkeypatch.setattr(scb.rotator, "_profiles_root", lambda: tmp_path)
    seen: list = []
    monkeypatch.setattr(cookie_vault, "snapshot_to_keychain",
                        lambda email, db: seen.append((email, Path(db))) or safe_storage.StoreResult.OK)
    scb._snapshot_cookies("a@x.com")
    assert seen == [("a@x.com", tmp_path / "chrome-profile-a@x.com" / "Default" / "Cookies")]


# ---------------------------------------------------------------------------
# Best-effort: a cookie_vault failure is swallowed (never breaks the capture)
# ---------------------------------------------------------------------------
def test_materialize_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A materialize exception must NOT propagate — the capture proceeds regardless."""
    monkeypatch.setenv("CLAUDE_ROTATOR_KEYCHAIN_COOKIES", "1")

    def _boom(*a, **k):
        raise RuntimeError("keychain exploded")
    monkeypatch.setattr(cookie_vault, "materialize_from_keychain", _boom)
    scb._materialize_cookies("a@x.com")  # must not raise


def test_snapshot_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A snapshot exception must NOT propagate — the slot is already filed."""
    monkeypatch.setenv("CLAUDE_ROTATOR_KEYCHAIN_COOKIES", "1")

    def _boom(*a, **k):
        raise RuntimeError("keychain exploded")
    monkeypatch.setattr(cookie_vault, "snapshot_to_keychain", _boom)
    scb._snapshot_cookies("a@x.com")  # must not raise


def test_snapshot_ignores_missing_cookie_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """A profile that never logged in (no Cookies DB → FileNotFoundError) is a quiet no-op."""
    monkeypatch.setenv("CLAUDE_ROTATOR_KEYCHAIN_COOKIES", "1")

    def _missing(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(cookie_vault, "snapshot_to_keychain", _missing)
    scb._snapshot_cookies("a@x.com")  # must not raise
