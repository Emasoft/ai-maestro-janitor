"""Unit tests for the RENEW browser-transport fix in slot_capture_browser.py
(CDP-attach to a real Chrome) and the shared profiles-root resolver in rotator.py.

Scope — only the parts that are unit-testable WITHOUT a real browser / network /
keychain (the audit explicitly notes the live CDP+OAuth flow is NOT unit-testable):
  * `_free_port` returns a usable free localhost port.
  * `_wait_for_cdp` returns False quickly on a port nobody is serving, and True
    once a trivial local HTTP server answers /json/version with 200 — exercising
    the real polling loop against a real socket, no mock of the code under test.
  * the approve-button selectors no longer include a bare "Accept" (which matched
    the cookie banner's "Accept All Cookies"), and the `_COOKIE_BUTTON_RE` guard
    matches cookie/decline controls but never the real Authorize/Allow/Approve.
  * `slot_capture_browser.profile_dir` and `rotator._profile_has_session_key` both
    resolve through the SAME shared resolver (`rotator._profiles_root`), and that
    resolver honours the env override, the canonical root, and the legacy fallback.

NO mocks of the code under test: a real socket, a real local HTTP server, and the
real resolver are used. The `_drive_browser` full flow (real Chrome over CDP) is
deliberately NOT exercised here — it needs a real Chrome + a logged-in profile.
"""

from __future__ import annotations

import importlib.util
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROTATOR_DIR = _HERE.parent / "scripts" / "oauth_rotator"
_ROTATOR_PY = _ROTATOR_DIR / "rotator.py"
_SLOT_PY = _ROTATOR_DIR / "slot_capture_browser.py"


def _load(mod_name: str, path: Path):
    """Import a path-only module (these live outside any package). slot_capture_browser
    does its own ``sys.path.insert(parent)`` + ``import rotator`` at top, so loading it
    transitively imports the real rotator — fine for the pure helpers tested here."""
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rotator = _load("rotator_transport_under_test", _ROTATOR_PY)
scb = _load("slot_capture_under_test", _SLOT_PY)


# --------------------------------------------------------------------------- #
# _free_port                                                                    #
# --------------------------------------------------------------------------- #
def test_free_port_returns_bindable_localhost_port() -> None:
    """_free_port returns an int in the ephemeral range that we can actually bind."""
    port = scb._free_port()
    assert isinstance(port, int)
    assert 1024 < port < 65536
    # The port was released before return, so we can bind it ourselves now.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))  # must not raise
    finally:
        s.close()


def test_free_port_varies() -> None:
    """Successive _free_port calls don't always return the same port (OS ephemeral)."""
    ports = {scb._free_port() for _ in range(5)}
    assert len(ports) >= 2  # extremely unlikely to collide on all 5


# --------------------------------------------------------------------------- #
# _wait_for_cdp                                                                  #
# --------------------------------------------------------------------------- #
def test_wait_for_cdp_times_out_on_dead_port() -> None:
    """_wait_for_cdp returns False (does not hang) when nothing serves the port."""
    dead = scb._free_port()  # free => nobody is listening
    assert scb._wait_for_cdp(dead, timeout=0.5) is False


def test_wait_for_cdp_true_when_endpoint_answers_200() -> None:
    """_wait_for_cdp returns True once a real local server answers /json/version 200.

    Exercises the actual urllib polling loop against a real HTTP server (no mock of
    the code under test); the server stands in for Chrome's DevTools endpoint."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"Browser":"test"}')

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - matches BaseHTTPRequestHandler signature; silence test-server logging
            _ = (format, args)  # intentionally unused — no-op override to keep the test server quiet

    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        assert scb._wait_for_cdp(port, timeout=5.0) is True
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


# --------------------------------------------------------------------------- #
# Approval-selector + cookie-guard fix                                          #
# --------------------------------------------------------------------------- #
def test_approve_selectors_exclude_bare_accept() -> None:
    """The bare "Accept" selector (which matched "Accept All Cookies") is gone; only
    real consent buttons remain."""
    joined = " ".join(scb.APPROVE_SELECTORS)
    assert 'has-text("Accept")' not in joined
    assert 'has-text("Authorize")' in joined
    assert 'has-text("Allow")' in joined
    assert 'has-text("Approve")' in joined


@pytest.mark.parametrize(
    "label",
    ["Accept All Cookies", "Reject", "Reject all", "Decline", "Manage cookies", "COOKIE settings"],
)
def test_cookie_guard_matches_cookie_and_decline_controls(label: str) -> None:
    """_COOKIE_BUTTON_RE matches the consent-banner / decline buttons that must NOT be
    auto-clicked by the approve loop."""
    assert scb._COOKIE_BUTTON_RE.search(label) is not None


@pytest.mark.parametrize("label", ["Authorize", "Allow", "Approve", "Continue"])
def test_cookie_guard_never_matches_real_consent_buttons(label: str) -> None:
    """_COOKIE_BUTTON_RE never matches the real OAuth consent buttons."""
    assert scb._COOKIE_BUTTON_RE.search(label) is None


# --------------------------------------------------------------------------- #
# Human-verification-challenge detection (janitor#228)                          #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text",
    [
        "Performing security verification...",
        "Checking your browser before accessing claude.ai",
        "Please verify you are human",
        "Verifying you are human. This may take a few seconds.",
        "cloudflare Ray ID: 1234abcd",
        "Complete the Turnstile challenge to continue",
        "Attention Required! | Cloudflare",
        "Solve this CAPTCHA to proceed",
    ],
)
def test_looks_like_challenge_matches_interstitial_copy(text: str) -> None:
    """_looks_like_challenge fires on the specific Cloudflare/captcha interstitial copy —
    the generic-timeout failure mode this detection exists to distinguish (janitor#228)."""
    assert scb._looks_like_challenge(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Sign in to claude.ai to continue",
        "Authorize this app to access your account",
        "Continue with Google",
        "Accept All Cookies",
    ],
)
def test_looks_like_challenge_never_matches_ordinary_consent_copy(text: str) -> None:
    """_looks_like_challenge stays narrow: it must NOT fire on ordinary login/consent/cookie
    copy — a false "captcha" claim is worse than a generic timeout."""
    assert scb._looks_like_challenge(text) is False



# --------------------------------------------------------------------------- #
# Consent-page account guard (TRDD-0SU2C2IM)                                    #
# --------------------------------------------------------------------------- #
_CONSENT_PAGE = (
    "Claude\nAuthorize access\nClaude Code would like to connect to your account\n"
    "Authorize\nDecline\n"
)


def test_consent_email_from_footer_in_realistic_page() -> None:
    """The "Logged in as <email>" footer inside a full consent page yields the address."""
    text = _CONSENT_PAGE + "Logged in as first@users.noreply.github.com\nSwitch account\n"
    assert scb._consent_logged_in_email(text) == "first@users.noreply.github.com"


def test_consent_email_mixed_case_and_newline_after_as() -> None:
    """Case is ignored, the address is lower-cased, a newline between "as" and it is fine."""
    text = _CONSENT_PAGE + "LOGGED IN AS\nFirst@Users.NoReply.GitHub.com\nSwitch account"
    assert scb._consent_logged_in_email(text) == "first@users.noreply.github.com"


def test_consent_email_none_without_any_address() -> None:
    """A page with no address (login prompt, bare consent page) yields None."""
    assert scb._consent_logged_in_email(_CONSENT_PAGE) is None
    assert scb._consent_logged_in_email("") is None


def test_consent_email_stops_before_switch_account() -> None:
    """Text on the next line ("Switch account") is never part of the address."""
    text = "Logged in as first@users.noreply.github.com\nSwitch account"
    assert scb._consent_logged_in_email(text) == "first@users.noreply.github.com"


def test_consent_email_non_english_prefix_single_address() -> None:
    """A localized footer works: the only address on the page is the account."""
    text = "Connecté en tant que First@Users.NoReply.GitHub.com\nChanger de compte"
    assert scb._consent_logged_in_email(text) == "first@users.noreply.github.com"


def test_consent_email_picks_the_logged_in_line_among_two() -> None:
    """With two addresses, the one on the "Logged in" line wins."""
    text = "Questions? second@users.noreply.github.com\nLogged in as first@users.noreply.github.com\nSwitch account"
    assert scb._consent_logged_in_email(text) == "first@users.noreply.github.com"


def test_consent_email_none_for_two_addresses_without_logged_in_line() -> None:
    """Two addresses and no "Logged in" line is ambiguous, so None (fail closed upstream)."""
    assert scb._consent_logged_in_email("first@users.noreply.github.com\nsecond@users.noreply.github.com") is None


def test_consent_refusal_decision() -> None:
    """Mismatch and unknown account refuse (no click); a case-insensitive match proceeds."""
    assert scb._consent_refusal("second@users.noreply.github.com", "first@users.noreply.github.com") == (
        "[capture] REFUSED: the Chrome profile for first@users.noreply.github.com is signed in as "
        "second@users.noreply.github.com; not authorizing (no grant minted). Sign that profile in as "
        "first@users.noreply.github.com with open-login.sh."
    )
    assert scb._consent_refusal(None, "first@users.noreply.github.com") == (
        "[capture] REFUSED: could not confirm which account the consent page is signed in as; "
        "not authorizing."
    )
    assert scb._consent_refusal("first@users.noreply.github.com", "First@Users.NoReply.GitHub.com") is None


# --------------------------------------------------------------------------- #
# Shared profiles-root resolver wiring                                          #
# --------------------------------------------------------------------------- #
def test_profile_dir_uses_shared_resolver(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """slot_capture_browser.profile_dir resolves through rotator._profiles_root (the
    single source of truth), so the capture and the daemon's session-key probe agree."""
    target = tmp_path / "shared-profiles"
    monkeypatch.setattr(rotator, "_profiles_root", lambda: target)
    # slot_capture_browser imported its OWN `rotator` object; ensure it's the same module
    # we patched (both load the path-only rotator, but as distinct module objects).
    monkeypatch.setattr(scb.rotator, "_profiles_root", lambda: target)
    assert scb.profile_dir("a@x.com") == target / "chrome-profile-a@x.com"


def test_profiles_root_resolution_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """_profiles_root: env override > canonical-if-exists > legacy-if-exists > canonical
    default. The legacy fallback is the durable replacement for the old runtime symlink."""
    canonical = tmp_path / "data" / "oauth-rotator"
    legacy = tmp_path / "legacy" / "account-rotator"
    monkeypatch.setattr(rotator, "ROOT", canonical)
    monkeypatch.setattr(rotator, "_legacy_rotator_root", lambda: legacy)
    monkeypatch.delenv("CLAUDE_ROTATOR_PROFILES", raising=False)

    # 1. neither profiles dir exists -> canonical default.
    assert rotator._profiles_root() == canonical / "profiles"

    # 2. only legacy/profiles exists -> legacy fallback.
    (legacy / "profiles").mkdir(parents=True)
    assert rotator._profiles_root() == legacy / "profiles"

    # 3. canonical/profiles now exists too -> canonical wins.
    (canonical / "profiles").mkdir(parents=True)
    assert rotator._profiles_root() == canonical / "profiles"

    # 4. env override beats everything.
    override = tmp_path / "override"
    monkeypatch.setenv("CLAUDE_ROTATOR_PROFILES", str(override))
    assert rotator._profiles_root() == override
