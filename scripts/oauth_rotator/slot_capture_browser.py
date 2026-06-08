#!/usr/bin/env python3
"""Automated full-OAuth slot capture via the account's OWN Chrome profile.

Faithful port of the audited `claude-login-automation` project's
`completeOAuthInBrowser` (downloads_dev/CLAUDE-BROWSER-PROJECTS/_audit/
claude-login-automation-main/src/auth.ts) for the OAuth PROTOCOL, with the
TRANSPORT swapped to "drive the REAL Chrome over CDP" (the audit's
stealth-browser / pagerunner recipe).

It launches a REAL Chrome (`subprocess.Popen`) bound to the target account's
profile (``profiles/chrome-profile-<email>/``) with a remote-debugging port, then
ATTACHES Playwright over CDP (`connect_over_cdp`) — so the stored claude.ai session
cookie auto-authenticates the consent page — then auto-clicks the Authorize button,
captures the ``<code>#<state>`` from the manual callback page, exchanges it for a
token PAIR (access + **refresh**), and writes it into the rotator SLOT for
``<email>``.

WHY CDP-attach to real Chrome instead of Playwright's `launch_persistent_context`
(TRDD; verified 2026-06-08): Playwright forces the Chrome default args
``--use-mock-keychain`` + ``--password-store=basic``, so on macOS Chrome's OSCrypt
uses a MOCK key and CANNOT decrypt the claude.ai session cookies the human
``open-login.sh`` (a NORMAL Chrome) persisted with the real "Chrome Safe Storage"
keychain key. The profile then reads as logged-OUT → ``/oauth/authorize`` shows the
LOGIN page, never the Authorize button → renew fails. Simply dropping
``--use-mock-keychain`` is NOT enough — real Chrome then BLOCKS on a macOS
keychain-access PROMPT the unattended flow can't answer. Launching the real Chrome
binary ourselves (real keychain, already ACL-granted by the human's login, no mock
key, no prompt) and only ATTACHING Playwright over CDP is the working transport.

The live keychain (`Claude Code-credentials`) is NEVER touched, so a running
Claude session on another account is left undisturbed — this writes a slot, not
the live credential (unlike claude-login-automation's own `saveCredentials`,
which clobbers ~/.claude/.credentials.json; we deliberately do NOT do that).

WHY a per-account profile instead of `open <url>`: the authorize endpoint only
renders the consent page for an AUTHENTICATED session. Opening the URL in a cold
default browser (no claude.ai session) yields a login wall or an "invalid
request format" page — which is exactly the failure mode that blocked the manual
flow. Binding Chrome to the account's own profile (cookies) is how the audited
project succeeds with zero human interaction.

The OAuth constants are VERBATIM from claude-login-automation/src/auth.ts:
authorize on claude.ai, token + manual redirect on platform.claude.com, and the
reduced 4-scope set (which yields a refresh token).

Run:
    env -u CLAUDE_PLUGIN_DATA uv run --with playwright \\
        python slot_capture_browser.py <email> [--headless]

Token safety: no token is printed or logged; only the account email + status.
The slot file is 0600 (rotator.write_slot enforces it).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rotator  # type: ignore[import-not-found]  # noqa: E402

# Constants VERBATIM from claude-login-automation/src/auth.ts (the working ref).
# CLIENT_ID + TOKEN_URL are sourced from rotator (single source of truth; F2b reuses them).
CLIENT_ID = rotator.CLIENT_ID
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = rotator.TOKEN_URL
REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"
SCOPES = "user:profile user:inference user:sessions:claude_code user:mcp_servers"

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# Consent-page approval buttons. NB: "Continue" is deliberately EXCLUDED — the
# claude.ai LOGIN page uses "Continue with Google" / "Continue with email", and
# auto-clicking those on a not-yet-logged-in profile submits an empty form and
# dead-ends. The actual consent button is "Authorize" (verified on the live
# page); Allow/Approve are kept for forward-compat with consent variants. A bare
# "Accept" selector is deliberately ABSENT: it matched the Cloudflare/claude.ai
# COOKIE banner's "Accept All Cookies" and auto-dismissed it instead of authorizing
# (observed 2026-06-08), which dead-ends the flow. The _COOKIE_BUTTON_RE guard below
# is a second belt-and-braces filter on the matched button's text.
APPROVE_SELECTORS = [
    'button:has-text("Authorize")',
    'button:has-text("Allow")',
    'button:has-text("Approve")',
]
# Buttons whose visible text matches this are cookie-consent / decline controls
# (NOT the OAuth Authorize button) and must NEVER be auto-clicked by the approve
# loop. Case-insensitive substring/word match on the button's text_content().
_COOKIE_BUTTON_RE = re.compile(r"cookie|accept all|reject|decline", re.IGNORECASE)
# Page elements that may carry the displayed code on the callback page.
CODE_SELECTORS = ["code", "pre", "input[readonly]", ".code", "[data-code]", "textarea"]


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def profile_dir(email: str) -> Path:
    # Single source of truth for the profiles root (rotator._profiles_root): honours
    # CLAUDE_ROTATOR_PROFILES, then <ROOT>/profiles, then the legacy
    # ~/.claude/account-rotator/profiles durable fallback — so this capture, the daemon's
    # session-key probe, and open-login.sh always agree on where the seeded profile lives
    # (replaces the old runtime symlink; TRDD-7100178d).
    return rotator._profiles_root() / f"chrome-profile-{email}"


def _build_url(challenge: str, state: str) -> str:
    params = {
        "code": "true",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


def _free_port() -> int:
    """Pick a free localhost TCP port for Chrome's remote-debugging endpoint.

    Bind to port 0 (the OS assigns a free ephemeral port), read it back, then close
    immediately. There is an inherent TOCTOU race (the port could be re-taken before
    Chrome binds it), but it is vanishingly unlikely on a dev box and Chrome would just
    fail to open the port — caught by _wait_for_cdp's timeout. SECURITY: binds to
    127.0.0.1 only, never 0.0.0.0, so the debug port is never reachable off-host."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def _wait_for_cdp(port: int, timeout: float = 30.0) -> bool:
    """Poll ``http://127.0.0.1:<port>/json/version`` until Chrome's DevTools endpoint
    answers 200 (it is ready to accept a CDP connection) or ``timeout`` elapses.

    Returns True once ready, False on timeout. Best-effort GET with a short per-request
    timeout; connection-refused while Chrome is still starting is expected and retried."""
    deadline = time.time() + timeout
    probe = f"http://127.0.0.1:{port}/json/version"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(probe, timeout=2) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.3)
    return False


def _drive_browser(email: str, url: str, state: str, headless: bool) -> str | None:
    """Drive the account's REAL Chrome (CDP-attached), auto-click Authorize, return raw
    `code#state`.

    Transport rationale lives in the module docstring: we launch the real Chrome binary
    ourselves (real macOS keychain → decrypts the persisted claude.ai cookies, no mock
    key, no prompt) and ATTACH Playwright over CDP, rather than using Playwright's
    `launch_persistent_context` (which forces `--use-mock-keychain` and reads the profile
    as logged-out)."""
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found,import-untyped]

    prof = profile_dir(email)
    if not prof.is_dir():
        print(f"[capture] FAILED: no Chrome profile for {email} at {prof}.")
        print("[capture] (expected a logged-in profile created during initial slot capture.)")
        return None

    port = _free_port()
    chrome_args = [
        CHROME,
        f"--user-data-dir={prof}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "about:blank",
    ]
    # Pure headless is Cloudflare-blocked regardless of flags (audit §3-D) — default
    # headful; only go headless when the caller explicitly asks (e.g. on Xvfb).
    if headless:
        chrome_args.insert(1, "--headless=new")

    raw_code: str | None = None
    # Launch the REAL Chrome ourselves. Single try/finally guarantees BOTH the Popen'd
    # Chrome and the CDP-attached browser handle are torn down even on error, so no
    # orphan Chrome leaks across an unattended daemon's many capture attempts.
    proc = subprocess.Popen(
        chrome_args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_for_cdp(port):
            print(f"[capture] FAILED: Chrome DevTools port {port} never came up within 30s.")
            return None
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            try:
                ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)  # let any Cloudflare/JS settle

                # Diagnostic screenshot of whatever rendered (consent page or wall).
                consent_shot = rotator.ROOT / "capture-consent.png"
                try:
                    page.screenshot(path=str(consent_shot))
                    print(f"[capture] consent-page screenshot: {consent_shot}")
                except Exception:
                    pass

                # Poll up to 5 min: click any consent/approve button we see, until we
                # reach the manual callback. This tolerates a one-time interactive
                # login (Google SSO / password) happening in the window first — we
                # never click LOGIN buttons (see APPROVE_SELECTORS), so we simply wait
                # for the consent page to appear, then click Authorize on it.
                print("[capture] waiting for consent + callback — if a login prompt shows in "
                      "the window, log in as the target account; auto-proceeds (up to 5 min)…")
                reached = False
                deadline = time.time() + 300
                while time.time() < deadline:
                    try:
                        cur = str(page.evaluate("location.href"))
                    except Exception:
                        cur = ""
                    if "/oauth/code/callback" in cur:
                        reached = True
                        break
                    for sel in APPROVE_SELECTORS:
                        try:
                            btn = page.query_selector(sel)
                            if not btn:
                                continue
                            # Belt-and-braces: never click a cookie-consent / decline
                            # control even if a selector somehow matches it (the bare
                            # "Accept" selector that matched "Accept All Cookies" has been
                            # removed from APPROVE_SELECTORS; this is the second guard).
                            label = (btn.text_content() or "").strip()
                            if _COOKIE_BUTTON_RE.search(label):
                                continue
                            btn.click()
                            print(f"[capture] clicked approval button ({sel}).")
                            break
                        except Exception:
                            continue
                    page.wait_for_timeout(2000)
                if not reached:
                    print("[capture] FAILED: never reached the /oauth/code/callback page within 5 min.")
                    return None
                page.wait_for_timeout(1500)
                try:
                    page.screenshot(path=str(rotator.ROOT / "capture-callback.png"))
                except Exception:
                    pass

                # 1) Look for the code in known page elements.
                for sel in CODE_SELECTORS:
                    try:
                        el = page.query_selector(sel)
                        if not el:
                            continue
                        val = None
                        try:
                            val = el.input_value()
                        except Exception:
                            pass
                        txt = el.text_content()
                        cand = (val or txt or "").strip()
                        if len(cand) > 10:
                            raw_code = cand
                            break
                    except Exception:
                        continue

                # 2) Scan the body text for a code#state pattern.
                if not raw_code:
                    body = page.text_content("body") or ""
                    m = re.search(r"([A-Za-z0-9_-]{20,}#[A-Za-z0-9_-]{20,})", body)
                    if m:
                        raw_code = m.group(1)

                # 3) Fallback: reconstruct from the URL (query code + state/fragment).
                if not raw_code:
                    href = str(page.evaluate("location.href"))
                    hash_idx = href.find("#")
                    base = href[:hash_idx] if hash_idx >= 0 else href
                    frag = href[hash_idx + 1:] if hash_idx >= 0 else ""
                    qs = urllib.parse.urlparse(base).query
                    params = urllib.parse.parse_qs(qs)
                    code = (params.get("code") or [None])[0]
                    if code:
                        url_state = (params.get("state") or [None])[0]
                        raw_code = f"{code}#{url_state or frag or state}"
                return raw_code
            finally:
                # Close the CDP-attached handle ONLY (browser.close() over a
                # connect_over_cdp connection detaches Playwright; it does NOT wipe the
                # user's persistent profile data the way a launched-context close would).
                try:
                    browser.close()
                except Exception:
                    pass
    finally:
        # Terminate the Chrome we launched so no orphan process leaks across the
        # daemon's many unattended capture attempts. terminate → wait → kill escalation.
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _exchange(code: str, verifier: str, state: str) -> dict:
    """Exchange the authorization code for a token pair (faithful to the ref)."""
    body = json.dumps({
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
        "state": state,
    }).encode()
    # The reference sends only Content-Type (no anthropic-beta, no custom UA).
    req = urllib.request.Request(
        TOKEN_URL, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def capture(email: str, headless: bool) -> int:
    print(f"[capture] rotator state root: {rotator.ROOT}")
    print(f"[capture] target slot       : {rotator.slot_path(email)}")

    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = _b64url(secrets.token_bytes(32))
    url = _build_url(challenge, state)

    raw_code = _drive_browser(email, url, state, headless)
    if not raw_code:
        print("[capture] FAILED: no authorization code captured.")
        return 1

    code = raw_code.split("#", 1)[0].strip()
    returned_state = raw_code.split("#", 1)[1] if "#" in raw_code else state
    if returned_state != state:
        print("[capture] FAILED: state mismatch (CSRF guard).")
        return 1

    try:
        tok = _exchange(code, verifier, state)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        print(f"[capture] FAILED: token exchange HTTP {e.code}\n{detail}")
        return 1
    except urllib.error.URLError as e:
        print(f"[capture] FAILED: network error reaching token endpoint ({e.reason}).")
        return 1

    expires_at = tok.get("expiresAt")
    if expires_at is None and "expires_in" in tok:
        expires_at = int((time.time() + float(tok["expires_in"])) * 1000)
    scope_val = tok.get("scope", SCOPES)
    blob = {"claudeAiOauth": {
        "accessToken": tok.get("access_token") or tok.get("accessToken"),
        "refreshToken": tok.get("refresh_token") or tok.get("refreshToken"),
        "expiresAt": expires_at,
        "scopes": scope_val.split() if isinstance(scope_val, str) else SCOPES.split(),
        "subscriptionType": tok.get("subscriptionType", "max"),
    }}
    inner = blob["claudeAiOauth"]
    if not inner["accessToken"]:
        print(f"[capture] FAILED: token response had no access token; keys={list(tok.keys())}")
        return 1
    if not inner["refreshToken"]:
        print("[capture] WARNING: token response had NO refresh token — this behaves like a "
              f"setup-token (cannot be keepalive-refreshed). keys={list(tok.keys())}")

    actual = rotator.account_email(blob)
    if not actual:
        print("[capture] FAILED: authenticated, but /roles could not resolve the account; not filed.")
        return 1
    if actual.lower() != email.lower():
        print(f"[capture] NOTE: profile is logged in as {actual}, not {email} — filing under the "
              f"ACTUAL account {actual} (authoritative).")
    email = actual

    rotator.write_slot(email, blob)
    st = rotator.load_state()
    st.setdefault("slots", {})[email] = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "fp": rotator.fingerprint(blob),
        "expires_at": inner.get("expiresAt"),
        "via": "slot_capture_browser(full-oauth)",
    }
    rotator.save_state(st)

    eh = rotator.expires_in_h(blob)
    has_rt = "with refreshToken ✓" if inner["refreshToken"] else "NO refreshToken ✗"
    print(f"[capture] OK: filed FULL-OAUTH slot for {email} ({has_rt}; expires "
          f"~{eh if eh is not None else -1:.1f}h). Live session untouched.")
    return 0


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    headless = "--headless" in argv
    if not args:
        print("usage: slot_capture_browser.py <email> [--headless]")
        return 2
    return capture(args[0], headless)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
