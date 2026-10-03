#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright>=1.40"]
# ///
"""Tier-3 OAuth re-auth — refresh the LIVE Claude credential, hands-free.

When the live token AND its refresh chain are dead (and every captured slot is
dead too), the rotator cannot swap its way out — the only fix is a full re-login.
This automates that last resort by driving the REAL `claude auth login`:

  1. start a DETACHED tmux session and run the login command in a TRUSTED folder
     (so the workspace-trust dialog is skipped); claude AUTO-opens the browser,
  2. read the consent URL it prints ("If the browser didn't open, visit: <URL>"),
  3. drive a browser that is ALREADY signed in to claude.ai (via Playwright over
     CDP — the cross-platform "puppeteer") to open that URL and click **Authorize**,
  4. `claude auth login` uses a MANUAL paste callback (redirect_uri =
     platform.claude.com/oauth/code/callback), NOT a localhost loopback — so the
     consent shows a `<code>#<state>`; we read it from the callback page's URL and
     `tmux send-keys` it into the "Paste code here >" prompt; claude exchanges it
     and prints "Login successful.",
  5. kill the tmux session.

WHY this works where the prior attempts failed: it uses `claude auth login` — the
OFFICIAL flow — so PKCE, token exchange, and the keychain write are CLAUDE's job.
We only (a) run the command via tmux, (b) click one button, and (c) paste back the
one-time code the consent shows. We do NOT re-implement OAuth and we do NOT seed a
throwaway browser profile (that is what broke before). The browser we click in is a
real, already-logged-in browser, reached over the Chrome DevTools Protocol — it can
be a DIFFERENT browser than the default one claude opens (e.g. claude opens Safari;
we drive a logged-in Chrome on the CDP port).

CROSS-PLATFORM: browser automation is Playwright/CDP (macOS, Linux, Windows) — no
AppleScript. The only *nix-specific piece is tmux (use WSL on Windows).

═══ PREREQUISITES (the script checks what it can; the rest is on you) ═══
  • tmux on PATH  (`brew install tmux` / `apt install tmux`).
  • `claude` on PATH.
  • A DEDICATED Chromium-family browser, SIGNED IN to claude.ai, launched with
    remote debugging AND a non-default --user-data-dir. Chrome 136+ REFUSES the
    debug port on the default profile ("DevTools remote debugging requires a
    non-default data directory"), so a dedicated profile is MANDATORY:
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
            --remote-debugging-port=9222 \\
            --user-data-dir="<ROTATOR_DATA_DIR>/reauth-chrome"
    where <ROTATOR_DATA_DIR> is the rotator's DATA-dir root
    (rotator._rotator_root() — the canonical janitor DATA dir, NOT the legacy
    ~/.claude/account-rotator standalone path). reauth.py PRINTS the exact
    launch command (with the resolved path) at startup and on --dry-run, so
    just copy that line.
    (Linux: `google-chrome` + the same two flags; Windows: `chrome.exe` + same.)
    The FIRST time, log into claude.ai in that window — the session persists in
    that user-data-dir, so later runs are hands-free. The script connects at
    --cdp-url (default http://127.0.0.1:9222) and clicks Authorize there. The
    default browser claude itself opens (e.g. Safari) is irrelevant — we drive
    THIS dedicated debug Chrome.
  • The login command runs from a TRUSTED --folder (default: this repo root) so
    the workspace-trust dialog never blocks it.

Run (real):   uv run scripts/oauth_rotator/reauth.py --email you@example.com
Manual click: uv run scripts/oauth_rotator/reauth.py --manual            (you click; no CDP)
Dry run:      uv run scripts/oauth_rotator/reauth.py --dry-run           (no launch)
Debug:        add --no-teardown to keep the tmux session (tmux attach -t claude-reauth)

This is the LIVE-credential path — the sibling of slot_capture_browser.py (which
captures an ALTERNATE account into a rotator SLOT). reauth.py writes the LIVE
keychain via `claude auth login`; it never writes a slot.
"""
from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import NoReturn

_HERE = Path(__file__).resolve().parent

# The OAuth consent URL claude opens. OBSERVED host: claude.com/cai/oauth/authorize
# (keep claude.ai too for forward-compat). capture_pane uses -J so the 80-col pane
# wrap of this long URL is rejoined into one line before this matches.
_AUTHORIZE_URL_RE = re.compile(r"https://[A-Za-z0-9.\-]*claude\.(?:ai|com)/[^\s\"'<>]*authorize[^\s\"'<>]*")
_EMAIL_RE = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")

# Playwright text/role locators for the consent approval control (first match wins).
APPROVE_SELECTORS = (
    'button:has-text("Authorize")',
    'button:has-text("Allow")',
    'button:has-text("Approve")',
    'button:has-text("Accept")',
)

# TUI markers (matched case-insensitively against the captured pane). The login
# completes once we paste the `<code>#<state>` from the consent into the
# "Paste code here >" prompt — claude exchanges it, prints "Login successful." and
# exits. "invalid code" is NOT a failure marker — an empty/early paste-prompt
# submission prints it harmlessly and claude re-prompts.
_DONE_MARKERS = ("login successful", "you are now logged in", "authentication successful",
                "signed in")
_FAIL_MARKERS = ("login failed", "authentication failed", "denied", "could not authenticate")


def log(msg: str) -> None:
    sys.stderr.write(f"[reauth] {msg}\n")
    sys.stderr.flush()


def die(msg: str, code: int = 1) -> NoReturn:
    log(f"FATAL: {msg}")
    raise SystemExit(code)


# The consent shows — and we `tmux send-keys` — a `<code>#<state>` pair. Once pasted, it is
# ON THE PANE, so any pane dump we log carries live credential material (audit finding 2).
# The code is single-use and expires in minutes, so it is inert once claude exchanges it —
# but if the exchange fails we still logged a code that stays valid for its full lifetime.
# Redact the pair (not every long token — over-redacting a diagnostic pane dump defeats the
# reason we print it at all).
_CODE_STATE_RE = re.compile(r"[A-Za-z0-9_\-]{16,}#[A-Za-z0-9_\-]{8,}")


def _redact(text: str) -> str:
    """`text` with any OAuth `<code>#<state>` pair masked. Applied to EVERY pane dump: the
    paste can land between our capture and our log, so redacting only the post-paste sites
    would be a race."""
    return _CODE_STATE_RE.sub("<code#state redacted>", text or "")


def _indent(text: str, prefix: str = "    | ") -> str:
    lines = (text or "(empty)").splitlines() or ["(empty)"]
    return "\n".join(prefix + ln for ln in lines)


def _run(cmd: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)  # noqa: S603


# ---- tmux ----------------------------------------------------------------
def tmux(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return _run(["tmux", *args], timeout=timeout)


def tmux_running(session: str) -> bool:
    return tmux("has-session", "-t", session).returncode == 0


def capture_pane(session: str) -> str:
    # -J joins wrapped lines: the long consent URL is split across the 80-col pane,
    # and without -J the regex only sees the first fragment.
    r = tmux("capture-pane", "-t", session, "-p", "-J", "-S", "-300")
    return r.stdout if r.returncode == 0 else ""


def kill_session(session: str) -> None:
    if tmux_running(session):
        log(f"killing tmux session {session!r}")
        tmux("kill-session", "-t", session)


def wait_for(session: str, predicate, *, timeout: float, interval: float = 1.0,
             label: str) -> str | None:
    """Poll capture-pane until predicate(text) is truthy, the session exits, or
    timeout. Returns the matching pane text, or None on timeout/exit."""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        if not tmux_running(session):
            log(f"session exited while waiting for {label}")
            return last if predicate(last) else None
        last = capture_pane(session)
        if predicate(last):
            return last
        time.sleep(interval)
    log(f"timeout ({timeout:.0f}s) waiting for {label}")
    return None


# ---- identity ------------------------------------------------------------
def resolve_intended_email(arg_email: str | None) -> str | None:
    if arg_email:
        return arg_email.strip()
    r = _run([sys.executable, str(_HERE / "rotator.py"), "live-email"], timeout=30)
    return (r.stdout or "").strip() or None


# ---- browser (Playwright over CDP — cross-platform) ----------------------
def authorize_and_capture_code(cdp_url: str, authorize_url: str | None,
                               intended_email: str | None, *, nav_timeout_ms: int = 20000,
                               click_timeout_ms: int = 8000,
                               redirect_timeout_ms: int = 20000) -> tuple[bool, str, str | None]:
    """Connect to the logged-in browser over CDP, open the consent URL, run the
    identity guard, click the consent button, and — because `claude auth login`
    uses a MANUAL paste callback (redirect_uri=platform.claude.com/oauth/code/
    callback), not a localhost loopback — wait for the redirect to that callback
    page and capture the `<code>#<state>` to paste back. Returns (ok, status, code).
    NEVER closes the user's browser — only disconnects."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]  # noqa: I001  # lazy; PEP-723 provides it
    except ImportError:
        return False, "playwright-missing (run via `uv run` so PEP-723 installs it)", None

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(cdp_url)
        except Exception as exc:  # noqa: BLE001
            return False, (f"cdp-connect-failed: {exc}. Launch a DEDICATED Chrome with BOTH "
                           f"--remote-debugging-port (matching {cdp_url}) AND a non-default "
                           f"--user-data-dir — Chrome 136+ refuses the debug port on the default "
                           f"profile — then sign into claude.ai in it once."), None
        try:
            if not authorize_url or not browser.contexts:
                return False, "no authorize URL / no browser context to open it in", None
            # ALWAYS open a FRESH consent tab on the CURRENT url. A leftover tab from
            # a prior run carries a stale OAuth state, and pasting its code fails.
            page = browser.contexts[0].new_page()
            page.goto(authorize_url, wait_until="domcontentloaded", timeout=nav_timeout_ms)

            # The consent renders async — poll for the button (don't click too early),
            # running the login-wall + identity guards each tick.
            clicked = None
            deadline = time.time() + 15
            while time.time() < deadline and clicked is None:
                body = ""
                try:
                    body = (page.inner_text("body", timeout=3000) or "").lower()
                except Exception:  # noqa: BLE001
                    pass
                if any(s in body for s in ("continue with google", "sign in to continue",
                                           "log in to claude")):
                    _safe_close(page)
                    return False, ("consent page shows a LOGIN WALL — sign into claude.ai in the "
                                   "debug Chrome (the --user-data-dir profile), then retry."), None
                if intended_email:
                    want = intended_email.lower()
                    seen = set(_EMAIL_RE.findall(body))
                    if seen and want not in seen:
                        _safe_close(page)
                        return False, f"guard-mismatch: page shows {sorted(seen)[0]!r}, not {want!r}", None
                for sel in APPROVE_SELECTORS:
                    loc = page.locator(sel)
                    try:
                        if loc.count() > 0:
                            loc.first.click(timeout=click_timeout_ms)
                            clicked = sel
                            break
                    except Exception:  # noqa: BLE001 - button vanished mid-click; poll again
                        pass
                if clicked is None:
                    page.wait_for_timeout(1000)
            if clicked is None:
                _safe_close(page)
                return False, "consent button not found (page still loading or unexpected layout)", None

            # claude auth login wants the code pasted — wait for the redirect to the
            # callback page, then read <code>#<state> from its URL.
            try:
                page.wait_for_url("**/oauth/code/callback*", timeout=redirect_timeout_ms)
            except Exception:  # noqa: BLE001
                _safe_close(page)
                return False, (f"clicked {clicked} but no callback redirect — likely the wrong "
                               f"button (e.g. a cookie banner); retrying."), None
            code = _code_from_callback_url(page.url or "")
            _safe_close(page)
            if not code:
                return False, "callback page reached but no code in its URL", None
            return True, f"clicked {clicked} -> captured code", code
        finally:
            try:
                browser.close()  # disconnects the CDP session; does NOT kill the browser
            except Exception:  # noqa: BLE001
                pass


def _safe_close(page) -> None:
    try:
        page.close()
    except Exception:  # noqa: BLE001
        pass


def _code_from_callback_url(url: str) -> str | None:
    """Extract `<code>#<state>` from a platform.claude.com/oauth/code/callback URL
    (the string `claude auth login` wants pasted). None if it is not that page."""
    if "/oauth/code/callback" not in url:
        return None
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    code = (params.get("code") or [""])[0]
    state = (params.get("state") or [""])[0]
    if not code:
        return None
    return f"{code}#{state}" if state else code


# ---- token-change verification + slot capture (reuses rotator.py) ---------
def _load_rotator(rotator_root: str | None):
    """Import the rotator engine and point its slot/state paths at `rotator_root`
    (so reauth.py reads/writes the SAME per-account slots the rotation uses).
    When `rotator_root` is None, resolve it via rotator's OWN smart resolver
    (`_rotator_root()`) so reauth and the daemon never diverge onto different roots
    (TRDD-7100178d F1 — the canonical DATA dir, with legacy fallback). Returns the
    module, or None if it cannot be imported."""
    try:
        sys.path.insert(0, str(_HERE))
        import rotator  # type: ignore[import-not-found]  # noqa: I001  # local module
    except Exception as exc:  # noqa: BLE001
        log(f"could not load rotator.py for verification: {exc}")
        return None
    root = Path(rotator_root).expanduser() if rotator_root else rotator._rotator_root()
    rotator.ROOT = root
    rotator.SLOTS = root / "slots"
    rotator.STATE_FILE = root / "state.json"
    return rotator


def _live_fingerprint(rot) -> str:
    """sha256(accessToken)[:16] of the CURRENT live keychain credential, or ''."""
    blob = rot.read_live_blob()
    return rot.fingerprint(blob) if blob else ""


def _verify_and_capture(rot, pre_fp: str, intended_email: str | None,
                        do_capture: bool) -> tuple[bool, str]:
    """The 'is the token really NEW?' check (your rule): compare the post-re-auth
    live token to what was there before AND to the stored slot. If the live token
    is UNCHANGED, claude reported success but minted nothing → renew FAILED. If it
    changed, it is genuinely new → overwrite the account's slot so rotation can
    swap it in. Returns (verified_new, human_message)."""
    new = rot.read_live_blob()
    if not new:
        return False, "could not read the live credential to verify the new token"
    new_fp = rot.fingerprint(new)
    if not new_fp:
        return False, "live credential has no accessToken to fingerprint"
    email = rot.account_email(new) or intended_email or "unknown"
    old_slot = rot.read_slot(email)
    old_slot_fp = rot.fingerprint(old_slot) if old_slot else ""

    if pre_fp and new_fp == pre_fp:
        return False, (f"renew FAILED — live token UNCHANGED ({new_fp}). claude printed "
                       f"'Login successful.' but the keychain blob did not change; NOT "
                       f"overwriting slot[{email}].")

    has_refresh = bool(rot._oauth(new).get("refreshToken"))
    exp = rot.expires_in_h(new)
    exp_s = f"{exp:.1f}h" if exp is not None else "?"
    detail = (f"{email}: live {pre_fp or '(none)'} → {new_fp} (refresh={has_refresh}, "
              f"expires in {exp_s}); slot was {old_slot_fp or '(none)'}")
    if not do_capture:
        return True, f"VERIFIED NEW token — {detail} (slot save skipped: --no-capture)"
    rot.SLOTS.mkdir(parents=True, exist_ok=True)
    rot.write_slot(email, new)
    return True, f"VERIFIED NEW token + saved to slot — {detail} → {rot.slot_path(email)}"


# ---- orchestration -------------------------------------------------------
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Tier-3 hands-free re-auth via claude auth login.")
    ap.add_argument("--email", help="account to re-auth: pre-fills the login page AND is the "
                                     "identity guard. Default: the rotator's live-email.")
    ap.add_argument("--login-cmd", default="claude auth login --claudeai",
                    help="the login command run inside tmux. Default: 'claude auth login "
                         "--claudeai' (full OAuth w/ refresh). Add --dangerously-skip-permissions "
                         "if your flow needs it.")
    ap.add_argument("--folder", default=str(_HERE.parent.parent),
                    help="TRUSTED folder to run in (skips the workspace-trust dialog). "
                         "Default: this repo root.")
    ap.add_argument("--session", default="claude-reauth", help="tmux session name.")
    ap.add_argument("--cdp-url", default="http://127.0.0.1:9222",
                    help="CDP endpoint of your logged-in, remote-debugging browser.")
    ap.add_argument("--manual", action="store_true",
                    help="do NOT auto-click; YOU click Authorize while the script waits.")
    ap.add_argument("--startup-wait", type=float, default=3.0,
                    help="seconds after sending the login command before reading the pane.")
    ap.add_argument("--url-timeout", type=float, default=30.0,
                    help="seconds to wait for the consent URL to be printed.")
    ap.add_argument("--authorize-timeout", type=float, default=120.0,
                    help="seconds to keep (re)clicking Authorize + waiting for 'Login successful.'.")
    ap.add_argument("--click-interval", type=float, default=3.0, help="seconds between click tries.")
    ap.add_argument("--dry-run", action="store_true", help="set up + print the plan; do not launch.")
    ap.add_argument("--no-teardown", action="store_true",
                    help="leave the tmux session alive afterward for inspection.")
    ap.add_argument("--rotator-root", default=None,
                    help="rotator state dir holding slots/ — where the VERIFIED new token is "
                         "saved so rotation can swap it in. Default (None): resolve via "
                         "rotator._rotator_root() — the canonical janitor DATA dir, with a "
                         "legacy-standalone fallback — so reauth and the daemon never diverge.")
    ap.add_argument("--no-capture", action="store_true",
                    help="verify the live token changed, but do NOT overwrite the account slot.")
    args = ap.parse_args(argv)

    for tool in ("tmux", "claude"):
        if shutil.which(tool) is None:
            die(f"{tool!r} not on PATH."
                + (" (`brew install tmux` / `apt install tmux`; on Windows use WSL)"
                   if tool == "tmux" else ""))

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        die(f"--folder is not a directory: {folder}")

    intended = resolve_intended_email(args.email)
    login_argv = shlex.split(args.login_cmd)
    if intended and "--email" not in login_argv:
        login_argv += ["--email", intended]
    login_cmd = shlex.join(login_argv)

    log(f"intended account : {intended or '(unknown — identity guard blocks only known-wrong accounts)'}")
    log(f"login command    : {login_cmd}")
    log(f"trusted folder   : {folder}")
    log(f"tmux session     : {args.session}")
    log(f"authorize click  : {'MANUAL (you click)' if args.manual else f'Playwright/CDP @ {args.cdp_url}'}")

    # Resolve the rotator engine ONCE (TRDD-dfc0959a A-F1) so the dedicated debug-Chrome
    # user-data-dir we tell the human to launch is anchored on the SAME canonical rotator
    # DATA root as everything else (rot.ROOT) — never the legacy ~/.claude/account-rotator
    # literal. Resolving here (before the dry-run return) means --dry-run shows it too.
    rot = _load_rotator(args.rotator_root)
    reauth_chrome = (rot.ROOT / "reauth-chrome") if rot is not None else None
    if reauth_chrome is not None:
        log(f"debug Chrome dir : {reauth_chrome}")
        log(f'  launch Chrome  : <chrome> --remote-debugging-port=<port in --cdp-url> '
            f'--user-data-dir="{reauth_chrome}"')

    if args.dry_run:
        log("DRY RUN — would: launch the login command in tmux, read the consent URL, "
            + ("wait for YOU to click Authorize, " if args.manual
               else "click Authorize via CDP, ")
            + "wait for 'Login successful.', then kill the session. No Enters, no code-paste.")
        return 0

    if tmux_running(args.session):
        log(f"a tmux session {args.session!r} already exists — killing it first")
        kill_session(args.session)

    # Snapshot the live token BEFORE re-auth so we can PROVE it changed afterward
    # (claude's "Login successful." is not proof on its own). `rot` was resolved
    # above (for the debug-Chrome-dir line) — reuse it, don't re-import.
    pre_fp = _live_fingerprint(rot) if rot else ""
    if rot is not None:
        log(f"pre-reauth live token fp: {pre_fp or '(none)'}  (slots dir: {rot.SLOTS})")

    ok = False
    try:
        # 1. Start the session running an interactive SHELL (not the login
        #    command directly). If the login command were the session's process,
        #    tmux would reap the whole session the instant it exits — leaving
        #    nothing to capture or attach to ("can't find pane"). With a shell as
        #    the pane process, the command runs *inside* it and the pane survives
        #    the command returning, so polling + post-hoc inspection both work.
        log("starting tmux session (interactive shell) …")
        r = tmux("new-session", "-d", "-s", args.session, "-c", str(folder))
        if r.returncode != 0:
            die(f"tmux new-session failed: {(r.stderr or '').strip()}")
        time.sleep(1.2)  # let the shell print its first prompt
        log(f"sending login command into the session: {login_cmd}")
        tmux("send-keys", "-t", args.session, login_cmd, "Enter")
        time.sleep(args.startup_wait)
        log("pane after startup:\n" + _indent(_redact(capture_pane(args.session))))

        # 2. Wait for the consent URL. claude opens the browser ITSELF ("Opening
        #    browser to sign in…") and prints "If the browser didn't open, visit:
        #    <URL>". We send NO keys: the prompt is "Paste code here if prompted >",
        #    but the Authorize click completes the flow via the callback — verified
        #    end-to-end with no paste and no Enter.
        pane = wait_for(
            args.session,
            lambda t: bool(_AUTHORIZE_URL_RE.search(t)),
            timeout=args.url_timeout, label="consent URL",
        )
        if pane is None:
            log("never saw a consent URL. Current pane:\n" + _indent(_redact(capture_pane(args.session))))
            log(f"attach to inspect: tmux attach -t {args.session}")
            die("login flow did not print a consent URL.", code=2)
        m = _AUTHORIZE_URL_RE.search(pane)
        authorize_url = m.group(0) if m else None
        log(f"consent URL: {authorize_url}")

        # 3. Authorize, then wait for "Login successful." — claude exits on its own
        #    afterward, so NO finalize keypress is needed. MANUAL: you click. AUTO:
        #    the CDP browser (which MUST be signed in to claude.ai) opens that URL
        #    and clicks Authorize; the callback then notifies the waiting claude.
        if args.manual:
            log("MANUAL mode — click Authorize in your browser, copy the code it shows, and paste "
                "it into the 'Paste code here >' prompt yourself. Waiting for success …")
        else:
            log(f"auto-authorizing via CDP @ {args.cdp_url} (click Authorize → capture code → paste) …")
        deadline = time.time() + args.authorize_timeout
        clicked = False
        last_status = ""
        while time.time() < deadline:
            if not tmux_running(args.session):
                break
            low = capture_pane(args.session).lower()
            if any(m in low for m in _DONE_MARKERS):
                ok = True
                break
            if any(m in low for m in _FAIL_MARKERS):
                log("login reported a failure marker:\n" + _indent(_redact(capture_pane(args.session)[-600:])))
                break
            if not args.manual:
                cok, status, code = authorize_and_capture_code(args.cdp_url, authorize_url, intended)
                if cok and code:
                    clicked = True
                    log(f"authorize: {status}; pasting the code into the session")
                    tmux("send-keys", "-t", args.session, "-l", code)
                    tmux("send-keys", "-t", args.session, "Enter")
                    done = wait_for(
                        args.session,
                        lambda t: any(m in t.lower() for m in _DONE_MARKERS),
                        timeout=30.0, label="login success after paste",
                    )
                    ok = done is not None
                    break
                if status.startswith("guard-mismatch:"):
                    die(f"IDENTITY GUARD blocked it — {status}. Sign into the correct account "
                        f"({intended}) in the debug Chrome, then retry.", code=3)
                if status != last_status:
                    log(f"authorize: {status}")
                    if status.startswith("cdp-connect-failed"):
                        log("  → hands-free needs a DEDICATED debug Chrome (--user-data-dir; see "
                            "prereqs) signed into claude.ai.")
                    last_status = status
            time.sleep(args.click_interval)

        log("final pane (code redacted):\n" + _indent(_redact(capture_pane(args.session))))

        # claude printed "Login successful." — now PROVE the keychain token changed
        # and save the new token into the account's slot for rotation.
        if ok and rot is not None:
            verified, vmsg = _verify_and_capture(rot, pre_fp, intended, not args.no_capture)
            log(("✅ " if verified else "❌ ") + vmsg)
            ok = verified  # a "successful" login that did not change the token is NOT a success
        elif ok and rot is None:
            log("⚠️ rotator.py unavailable — skipped token-change verification + slot capture; "
                "trusting claude's 'Login successful.' (run `claude auth status` to confirm).")

        if ok:
            log("✅ re-auth SUCCESS — NEW token verified (keychain refreshed; slot saved for rotation).")
            return 0
        log("❌ re-auth did NOT verifiably produce a new token.")
        if not args.manual and not clicked:
            log("   Authorize was never clicked — check the consent tab in your remote-debugging "
                "browser, confirm --cdp-url, or retry with --manual.")
        return 4
    finally:
        if args.no_teardown:
            log(f"--no-teardown: tmux session {args.session!r} left alive "
                f"(inspect: tmux attach -t {args.session}; kill: tmux kill-session -t {args.session})")
        else:
            kill_session(args.session)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
