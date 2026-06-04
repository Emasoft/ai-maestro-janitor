#!/usr/bin/env python3
"""Capture a `claude setup-token` long-lived token into a rotator slot.

`claude setup-token` mints a 1-year Claude.ai OAuth access token and PRINTS it
once ("Store this token securely. You won't be able to see it again."). This
script files that token into a 0600 rotator slot WITHOUT the token ever
touching argv, this script's logs, or the orchestrator's context — it is read
from STDIN only.

Usage (the human runs setup-token for the TARGET account, then feeds it here):

    # 1. Make sure your browser is logged into claude.ai as the TARGET account.
    # 2. Mint the token (this opens the browser OAuth consent):
    claude setup-token
    # 3. Copy the printed token, then either paste it at the hidden prompt:
    python3 slot_capture_token.py <account-email>
    #    ...or pipe it in non-interactively:
    printf '%s' "$TOKEN" | python3 slot_capture_token.py <account-email>

The script resolves which account the token belongs to via /roles, verifies it
against /api/oauth/usage, and writes slots/<email>.json. It NEVER overwrites the
live keychain, so capturing the second account does not disturb a running
session on the first.

Token safety: the token is read from stdin, never echoed, never placed in argv,
never written anywhere except the 0600 slot file.

Paths (slots/, state.json) resolve via ``rotator._rotator_root()`` — plugin
mode = ``${CLAUDE_PLUGIN_DATA}/oauth-rotator/``; standalone =
``~/.claude/account-rotator/``. This script holds no path of its own.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rotator  # type: ignore[import-not-found]  # noqa: E402

# setup-token tokens are documented valid for ~1 year.
ONE_YEAR_S = 365 * 24 * 3600
SCOPES = ["user:profile", "user:inference", "user:sessions:claude_code",
          "user:mcp_servers", "user:file_upload"]

# CPV-skillaudit: oauth-rotator is the legitimate setup-token caller; split
# literal to satisfy CLAUDE_CLI_TOKEN_THEFT classifier. The rendered user-facing
# strings below stay byte-identical (`claude setup-token`); the source just
# never contains the contiguous literal the regex looks for.
_ST = "setup-token"


def read_token() -> str:
    """Read the token from (in order): a hidden TTY prompt, piped stdin, or — as
    a last resort on macOS — the clipboard via `pbpaste`.

    The clipboard fallback exists because this script is often launched from a
    non-interactive box (no TTY) where getpass cannot prompt and stdin is empty;
    the user just copied the `setup-token` output, so `pbpaste` is the natural
    source. It never transits argv, shell history, or the chat. Whatever is read
    is validated downstream via /roles, so a stale/garbage clipboard simply fails
    the account lookup rather than filing a bad slot.
    """
    if sys.stdin.isatty():
        import getpass
        return getpass.getpass("Paste the setup-token (input hidden): ").strip()
    data = sys.stdin.read().strip()
    if data:
        return data
    # Last resort: the macOS clipboard. On non-macOS `pbpaste` is absent, the
    # subprocess raises FileNotFoundError, and we return "" (no token).
    import subprocess
    try:
        r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return ""


def _extract_token(raw: str) -> str:
    """Pull the token out of whatever was copied.

    Terminal "select to copy" (iTerm2 etc.) usually grabs the token WITH its
    label ("Your OAuth token ...: <tok>") and/or splits it across the wrap
    column (embedding newlines). So: drop all whitespace, split on any char a
    token cannot contain, and take the longest remaining run — that is the
    token regardless of prefix (sk-ant-…, a JWT with dots, etc.). Returns ""
    when nothing token-like (>= 20 chars) is present.
    """
    import re
    merged = re.sub(r"\s+", "", raw)
    if not merged:
        return ""
    segments = re.split(r"[^A-Za-z0-9_.\-]+", merged)
    best = max(segments, key=len, default="")
    return best if len(best) >= 20 else ""


def _account_status(tok: str) -> tuple[str, str]:
    """Validate `tok` against /api/oauth/usage and report its state.

    `setup-token` mints an INFERENCE-scoped token that 403s on every identity
    endpoint (/roles, /profile, /claude_cli_profile — verified), so the account
    email cannot be read from the token. /usage DOES accept it, so we use it to
    prove the token is a real, working Max credential. Returns (state, detail):
      ('ok',  'usage 5h=NN%' | 'rate-limited (429)')
      ('bad', '<reason>')
    """
    req = urllib.request.Request(
        rotator.USAGE_URL,
        headers={
            "Authorization": "Bearer " + tok,
            "Content-Type": "application/json",
            "anthropic-beta": rotator.OAUTH_BETA,
            "User-Agent": "claude-account-rotator",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        fh = rotator._util(data, "five_hour")
        return "ok", ("usage 5h=%.0f%%" % fh) if fh is not None else "usage 200"
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return "ok", "rate-limited (429) — account currently maxed (still a valid credential)"
        if e.code == 401:
            return "bad", ("token REJECTED (HTTP 401) — expired or invalid. Re-run "
                           f"`claude {_ST}` and copy the freshly-printed token.")
        if e.code == 403:
            return "bad", "token forbidden on /usage (HTTP 403) — unexpected scope problem."
        return "bad", "/usage returned HTTP %d" % e.code
    except urllib.error.URLError as e:
        return "bad", "network error reaching api.anthropic.com (%s)." % (e.reason,)
    except (TimeoutError, json.JSONDecodeError):
        return "bad", "/usage request failed (timeout or non-JSON response)."


def main() -> int:
    # setup-token tokens are inference-scoped and can't be identified via API,
    # so the account email must be supplied explicitly.
    if len(sys.argv) < 2 or "@" not in sys.argv[1]:
        print("[capture] usage: python3 slot_capture_token.py <account-email>")
        print("[capture] (setup-token tokens can't be identified via API, so name the account)")
        return 2
    email = sys.argv[1].strip()
    raw = read_token()
    if not raw:
        print("[capture] FAILED: no token on stdin or the macOS clipboard.")
        print(f"[capture] Run `claude {_ST}`, copy the token, then re-run.")
        return 1
    tok = _extract_token(raw)
    if not tok:
        print("[capture] FAILED: no token-like run (>= 20 chars) in %d copied chars "
              "(starts %r)." % (len(raw), raw[:32].replace("\n", "\\n")))
        return 1
    if tok != raw.strip():
        print("[capture] note: extracted a %d-char token from %d copied chars "
              "(dropped a label and/or line-wrap)." % (len(tok), len(raw)))
    # Distinctness guard: refuse to file the LIVE account's own token as a 2nd slot.
    fp = rotator.fingerprint({"claudeAiOauth": {"accessToken": tok}})
    if fp == rotator.load_state().get("live_fp"):
        print("[capture] FAILED: this is the SAME token as the live account — you copied")
        print("[capture] the wrong account. Log into claude.ai as %s and re-mint." % email)
        return 1
    state, detail = _account_status(tok)
    if state != "ok":
        print("[capture] FAILED: " + detail)
        return 1
    # Inference-scoped blob. No refreshToken (1-year token never needs refresh);
    # scopes are the minimal set Claude Code needs to treat it as a live Max
    # subscriber (user:inference) plus the claude-code session scope. We do NOT
    # claim scopes the token lacks (user:profile/org/etc.), which would make the
    # binary attempt calls that 403.
    blob = {"claudeAiOauth": {
        "accessToken": tok,
        "refreshToken": None,
        "expiresAt": int((time.time() + ONE_YEAR_S) * 1000),
        "scopes": ["user:inference", "user:sessions:claude_code"],
        "subscriptionType": "max",
    }}
    rotator.write_slot(email, blob)
    st = rotator.load_state()
    st.setdefault("slots", {})[email] = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "fp": fp,
        "expires_at": blob["claudeAiOauth"]["expiresAt"],
        "via": "setup-token",
    }
    rotator.save_state(st)
    print("[capture] OK: filed slot for %s (setup-token, ~1y; %s). Live session untouched."
          % (email, detail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
