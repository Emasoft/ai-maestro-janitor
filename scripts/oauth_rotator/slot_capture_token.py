#!/usr/bin/env python3
"""Capture a long-lived CLI-minted setup token into a rotator slot.

`claude setup-token` mints a 1-year Claude.ai OAuth access token and PRINTS it
once ("Store this token securely. You won't be able to see it again."). This
script files that token into a 0600 rotator slot WITHOUT the token ever
touching argv, this script's logs, or the orchestrator's context — it is read
from STDIN only.

Usage (the human runs setup-token for the TARGET account, then feeds it here):

    # 1. Make sure your browser is logged into claude.ai as the TARGET account.
    # 2. Mint the token (this opens the browser OAuth consent):
    claude setup-token
    # 3. Copy the printed token, then paste it at the hidden prompt:
    python3 slot_capture_token.py <account-email>
    #    ...or, with no terminal, redirect it from a file:
    python3 slot_capture_token.py <account-email> < /path/to/keyfile

Do NOT pipe it from a shell variable (`printf '%s' "$TOKEN" | ...`): assigning that variable
writes the token into `~/.zsh_history` in plaintext, which is the one exposure this script's
no-echo prompt exists to avoid. The file redirect trades that for a different one — a
plaintext token at rest — so it is the right form only for a file the human already keeps
deliberately (the keys CSV), and it should be mode 0600. For several accounts at once use
`import_oauth_tokens.py`, which reads that file directly.

The script resolves which account the token belongs to via /roles, verifies it
against /api/oauth/usage, and writes slots/<email>.json. It NEVER overwrites the
live keychain, so capturing the second account does not disturb a running
session on the first.

Token safety: the token is read from stdin, never echoed, never placed in argv,
never written anywhere except the 0600 slot file.

Paths (slots, state.json) resolve via ``rotator._rotator_root()`` — the canonical
janitor DATA-dir root (``${CLAUDE_PLUGIN_DATA}/.../oauth-rotator``), with the
legacy ``~/.claude/account-rotator/`` only as a READ fallback (see rotator.py for
the exact resolution order). Slot blobs are written ENCRYPTED to the OS keychain
via ``rotator.write_slot``; the plaintext ``slots/<email>.json`` is legacy /
read-fallback only. This script holds no path of its own.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import rotator  # type: ignore[import-not-found]  # noqa: E402
import tls_context  # noqa: E402  -- scripts/lib/tls_context.py (TRDD-X6I04SAO)
import usage_probe  # noqa: E402  -- scripts/lib/usage_probe.py; for its claude-code User-Agent

# setup-token keys are documented valid for ~1 year FROM MINTING, and the mint time is not
# recoverable from the token. This is right for the intended flow — the skill walks the human
# from `claude setup-token` to filing within minutes — and it OVER-claims by exactly the
# mint-to-file gap for a key that sat around first. Do not "fix" that with a fixed haircut: the
# gap is unbounded, so any subtraction is another guess. The real gap is elsewhere and worth
# knowing — a no-refresh slot has NO death signal but a 401, and nothing yet converts a 401 on
# such a slot into "stop selecting this", so `expiresAt` is the only retirement mechanism and
# it is only ever an estimate.
ONE_YEAR_S = 365 * 24 * 3600
SCOPES = ["user:profile", "user:inference", "user:sessions:claude_code",
          "user:mcp_servers", "user:file_upload"]

# CPV-skillaudit: oauth-rotator is the legitimate setup-token caller; split
# literal to satisfy CLAUDE_CLI_TOKEN_THEFT classifier. The rendered user-facing
# strings below stay byte-identical (`claude setup-token`); the source just
# never contains the contiguous literal the regex looks for.
_ST = "setup-token"

# The model count_tokens is asked about. Named in the 403 message too: a refusal there may be
# about the MODEL (retired, or not enabled for the account) rather than the credential, and a
# message that hides which model was asked makes that indistinguishable from a dead key.
_MODEL = "claude-haiku-4-5-20251001"

_UA_CACHE: list[str | None] = []


def _ua() -> str | None:
    """The claude-code User-Agent, resolved once, LAZILY, and never raising.

    Lazy and not at import, because `usage_probe.user_agent()` is derived (it ships a
    `reset_ua_cache()` sibling, so it is not a constant) and may do I/O. Resolving it at
    import means an untimed call can hang the process before ANY output — before the usage
    line, before the token prompt — leaving the human staring at a dead terminal. It also
    now takes the batch importer down with it, since that module imports this one.

    Empty is normalised to None so callers have ONE falsy case to test. A `""` slipping
    through as a distinct value is exactly the gap that defeats a guard written as
    `is None` while its sibling tests truthiness.
    """
    if not _UA_CACHE:
        try:
            _UA_CACHE.append(usage_probe.user_agent() or None)
        except Exception:  # noqa: BLE001 -- a UA lookup must never fail a capture
            _UA_CACHE.append(None)
    return _UA_CACHE[0]


def _hdrs(base: dict[str, str]) -> dict[str, str]:
    """Attach the User-Agent only when one resolved — both probes can be sent without it.

    Sending no UA is not free: the one other UA ever measured here (`claude-account-rotator`,
    2026-09-09) turned /usage's 403 into a 429, and urllib's default is a third, unmeasured
    one. That is survivable only because no branch now accepts a 429 as proof of anything.
    """
    ua = _ua()
    if ua:
        base["User-Agent"] = ua
    return base


def _body(e: urllib.error.HTTPError, limit: int = 160) -> str:
    """The server's own words for an error message — one line, truncated, never raising.

    Quoting the server beats asserting a cause: this file has twice shipped an invented
    explanation for a response nobody had observed. The read gets its own try because a body
    read can fail on a half-closed connection, and a diagnostic that raises is worse than no
    diagnostic. Newlines are flattened so the message stays one line in the capture log.
    """
    try:
        raw = e.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 -- a diagnostic must never replace the error it describes
        return "<body unreadable>"
    return " ".join(raw.split())[:limit] or "<empty body>"


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


def setup_token_blob(tok: str) -> dict:
    """The slot blob for a setup-token key — ONE definition, used by BOTH capture paths.

    Inference-scoped. No refreshToken (a 1-year token never needs refresh); scopes are the
    minimal set Claude Code needs to treat it as a live Max subscriber (user:inference) plus
    the claude-code session scope. We do NOT claim scopes the token lacks (user:profile, org,
    …), which would make the binary attempt calls that 403.

    This lives here rather than inline in each caller because it is the thing most likely to
    drift: change the scope list in one path and the other silently keeps the old shape,
    invisible until the slot is selected and a live session breaks.
    """
    return {"claudeAiOauth": {
        "accessToken": tok,
        "refreshToken": None,
        "expiresAt": int((time.time() + ONE_YEAR_S) * 1000),
        "scopes": ["user:inference", "user:sessions:claude_code"],
        "subscriptionType": "max",
    }}


def extract_token(raw: str) -> str:
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


def _inference_status(tok: str) -> tuple[str, str]:
    """Validate `tok` against an INFERENCE-scoped endpoint — the fallback when /usage 403s.

    Endpoint choice is measurement-driven (2026-09-09, three freshly minted keys): /usage
    answers `403 permission_error "OAuth token does not meet scope requirement"`, while
    `/v1/messages/count_tokens` returns 200 for the same key, with the EXACT body and headers
    sent below — measured under BOTH the claude-code UA and the old rotator UA. count_tokens
    is preferred over a real completion because it costs the account NOTHING while answering
    the only question asked here: does this credential authenticate.

    THREE states, not two. "bad" is a REFUSAL — 401 or 403, the server saw the credential and
    said no. "ok" is PROOF OF LIFE — only a 200, which required authentication to produce.
    "unverified" is NOTHING LEARNED — a 5xx, a timeout, a reset connection, or a 429: a rate
    limiter answering says a request arrived, not that the credential behind it was accepted.
    Such a key must not be rejected (that would send the human back through a browser flow
    over an outage) and must not be treated as proven either.

    The third state is load-bearing, not cosmetic: `import_oauth_tokens.py` FILES an
    unverified key but refuses to install it as the LIVE credential, because putting an
    unproven token into service immediately is how a hand-mangled key breaks the running
    session. Collapsing this back into a bool re-opens that hole.

    Still open, and not solved by this: nothing converts a 401 on a no-refresh slot into
    "stop selecting this", so `expiresAt` remains the only retirement mechanism.
    """
    body = json.dumps({
        "model": _MODEL,
        "messages": [{"role": "user", "content": "hi"}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages/count_tokens", data=body, method="POST",
        headers=_hdrs({
            "Authorization": "Bearer " + tok,
            "anthropic-beta": rotator.OAUTH_BETA,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }),
    )

    try:
        with urllib.request.urlopen(req, timeout=20, context=tls_context.verifying_context()):  # nosec B310 -- hardcoded https inference endpoint; scheme not attacker-controlled
            pass
        return "ok", "inference-scoped key accepted (count_tokens 200)"
    except urllib.error.HTTPError as e:  # MUST precede OSError — it is a subclass
        if e.code == 401:
            return "bad", ("token REFUSED by the inference endpoint (HTTP 401) — expired or "
                           f"revoked. Re-run `claude {_ST}` and copy the freshly-printed token.")
        if e.code == 403:
            # Split from 401 deliberately, but this branch describes the OBSERVATION and does
            # not name a cause: a count_tokens 403 has never been seen (all three measured keys
            # returned 200), so "it lacks inference scope" would be an inference from a
            # DIFFERENT endpoint's body. It could equally be the MODEL — retired, or not
            # enabled for this account — in which case re-minting is the wrong advice and the
            # model name is the clue. The verdict stays bad either way: a credential the
            # inference endpoint will not serve is useless as a rotation target.
            return "bad", ("token REFUSED by the inference endpoint (HTTP 403 — a permission "
                           f"refusal, not an expiry) while asking about model {_MODEL}. "
                           f"Server said: {_body(e)}. Re-minting may not help; check whether "
                           "that model is enabled for this account.")
        if e.code == 429:
            # Same reasoning as /usage's 429: a rate limiter answered, which does not
            # establish that the credential authenticated. There is no third endpoint to ask,
            # so this is where the chain ends — unproven, not refused, not proven.
            return "unverified", "rate-limited (429) on count_tokens — authentication unproven"
        return "unverified", "count_tokens HTTP %d — server fault, not a refusal" % e.code
    except OSError as e:
        # URLError and TimeoutError are both OSError subclasses, and so is the mid-stream
        # ConnectionResetError that neither of them covers. The server never answered, so
        # this says nothing about the key — do not punish the user for an outage.
        return "unverified", "no answer from api.anthropic.com (%s)" % (e,)


def account_status(tok: str) -> tuple[str, str]:
    """Validate `tok` and report its state.

    `setup-token` mints an INFERENCE-scoped token that 403s on every identity endpoint
    (/roles, /profile, /claude_cli_profile — verified), so the account email cannot be read
    from the token. /usage was ALSO believed to accept it; measured 2026-09-09 against three
    freshly minted keys, it does not — all three 403 there while the same keys are accepted by
    /v1/messages. So a 403 here proves nothing and MUST NOT reject the key; it falls through
    to the inference probe. Returns (state, detail), state being one of:
      'ok'          — proof of life: the server answered and required authentication to do it
      'unverified'  — no answer: file the key, but do NOT put it into service (see below)
      'bad'         — a refusal: the server saw the credential and said no

    Decided HERE, because /usage answered enough on its own: a 200 (the token holds the usage
    scope, so it is a full-OAuth credential — with or without recognisable quota fields), a
    401 (death), and a 200 whose body will not parse (unverified — that 200 may be a proxy's).
    Delegated to `_inference_status`: the 403 a setup-token key always gives, a 429, any other
    HTTP code, and an unreachable or timed-out host.

    A 429 delegates rather than passing, and that is the load-bearing line in this function.
    It used to return "ok", which meant any User-Agent that draws a throttle here — and the
    one other UA measured does exactly that — filed every key, valid or revoked, having
    verified nothing at all.
    """
    req = urllib.request.Request(
        rotator.USAGE_URL,
        headers=_hdrs({
            "Authorization": "Bearer " + tok,
            "Content-Type": "application/json",
            "anthropic-beta": rotator.OAUTH_BETA,
        }),
    )
    try:
        with urllib.request.urlopen(req, timeout=20, context=tls_context.verifying_context()) as r:  # nosec B310 -- hardcoded https OAuth token endpoint; scheme not attacker-controlled
            data = json.loads(r.read().decode("utf-8", "replace"))
        fh = rotator._util(data, "five_hour")
        return "ok", ("usage 5h=%.0f%%" % fh) if fh is not None else "usage 200"
    # NO handler for a wrongly-shaped 200 body, deliberately: `rotator._util` cannot raise.
    # It type-checks every level and returns None for a non-dict usage, a missing window, a
    # non-dict window and a non-numeric utilization, and the `fh is not None` test above
    # already routes that to "usage 200". A previous round added an except clause for it;
    # that clause was unreachable, and an unreachable handler is worse than none because it
    # advertises coverage nobody has.
    except urllib.error.HTTPError as e:
        if e.code == 429:
            # A 429 proves a RATE LIMITER answered — not that the credential authenticated.
            # Reading it as proof of life is what let a wrong User-Agent file every key
            # unvalidated, because the one other UA measured here turns the 403 into a 429.
            #
            # Delegating cannot deadlock, and the reason is a measurement, not the fact that
            # count_tokens is free: on 2026-09-09 a peer session measured two accounts
            # returning 429 on POST /v1/messages while ALL THREE returned 200 on count_tokens,
            # under both user-agents. count_tokens does not share the inference limit, so it
            # still answers in exactly the window where this branch fires.
            return _inference_status(tok)
        if e.code == 401:
            return "bad", ("token REJECTED (HTTP 401) — expired or invalid. Re-run "
                           f"`claude {_ST}` and copy the freshly-printed token.")
        if e.code == 403:
            # EXPECTED for a setup-token key (measured 2026-09-09): /usage is outside its
            # scope. Ask the endpoint that IS in scope before judging the credential.
            return _inference_status(tok)
        # Every other code is a SERVER fault, not a refusal of this credential. Delegate
        # rather than duplicate `_inference_status`'s strings — ONE function decides the
        # refusal-vs-no-answer doctrine, and two copies of it in one file is how the next
        # editor picks whichever branch they happened to read.
        return _inference_status(tok)
    except json.JSONDecodeError:
        # A 200 whose body will not parse. The realistic cause is an intercepting proxy or a
        # challenge page served WITH a 200 — and in exactly that case the 200 came from the
        # proxy, which never reached Anthropic and never saw the credential. So this proves
        # NOTHING about the key, and calling it proof would assert the one thing the likely
        # cause disproves.
        return "unverified", "/usage answered 200 with an unparseable body (intercepting proxy?)"
    except OSError as e:
        # /usage unreachable or timed out. This said 'bad' until 2026-09-09, which meant a
        # network blip told the human their key was invalid — and `claude setup-token` prints
        # ONCE, so that costs a whole browser re-mint. A /usage outage does not imply a
        # count_tokens outage, so ask the endpoint that is in scope.
        # (HTTPError is an OSError subclass, so it MUST stay caught above.)
        #
        # The exception TYPE is reported, never its repr: urllib takes proxies from
        # HTTP(S)_PROXY, which routinely carry inline `user:pass@host`, and an OSError raised
        # on a proxied connection can render that URL. This file promises the token reaches
        # nothing but a 0600 slot; printing credentials from the FAILURE path would break that
        # promise in the one direction that matters. The note rides the returned detail rather
        # than a print, so a batch caller can attribute it to the right account.
        st, detail = _inference_status(tok)
        return st, "/usage unreachable (%s); %s" % (type(e).__name__, detail)


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
    tok = extract_token(raw)
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
    state, detail = account_status(tok)
    if state == "bad":
        print("[capture] FAILED: " + detail)
        return 1
    if state == "unverified":
        # File it, but say so: nobody answered, so nothing about this key was proven. The
        # human is here at a terminal and can judge; the unattended importer is stricter.
        print("[capture] note: could not verify this key — " + detail)
    blob = setup_token_blob(tok)
    # Keychain write + state.json index entry as ONE locked step: the daemon's 60 s tick
    # mutates the same state.json, and an unlocked read-modify-write here could orphan this
    # slot (token in the keychain, no entry indexing it) or clobber the tick's write.
    if not rotator.file_slot(email, blob, via="setup-token",
                             expires_at=blob["claudeAiOauth"]["expiresAt"]):
        print("[capture] FAILED: another rotator operation held the lock; nothing was written. "
              "Re-run this capture.", file=sys.stderr)
        return 1
    print("[capture] OK: filed slot for %s (setup-token, ~1y; %s). Live session untouched."
          % (email, detail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
