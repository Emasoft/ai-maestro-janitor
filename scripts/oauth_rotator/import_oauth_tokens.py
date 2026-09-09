#!/usr/bin/env python3
"""Import the owner's long-lived setup-token keys from one CSV into their rotator slots,
and adopt the new key for the account that is live right now.

The human mints one 1-year key per account (`/login`, then `claude setup-token`) and writes
them into ONE file, `email,token` per line. This reads that file, validates each key, files
it into its slot, and — when the LIVE account's own credential changed — swaps it so a
running `claude` picks the new one up on its next turn without restarting.

Why a file and not a per-account prompt: the prompt path needs a TTY, so an agent cannot run
it. In a tool call there is no terminal, the hidden prompt never opens, stdin is empty, and
the fallback reads the macOS clipboard — one value for three accounts, silently filing the
wrong key. A file the human already maintains has neither problem.

WHAT THIS CANNOT CHECK: an inference-scoped token 403s on every identity endpoint, so nothing
can verify that a token actually belongs to the email on its line. The `/login`-then-mint
ordering is the ONLY thing binding them. Mint for the wrong account and the rotator will
believe it has N accounts while spending one account's quota under two names.

Token safety: tokens are read from the file, never echoed, never placed in argv, never
logged. Only emails and 8-char fingerprint prefixes are ever printed.
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import global_state as gs  # noqa: E402  -- scripts/lib/global_state.py; for the shared state dir
import rotator  # type: ignore[import-not-found]  # noqa: E402
import slot_capture_token as sct  # noqa: E402  -- the single-account path; shared validator + blob

DEFAULT_CSV = Path.home() / ".claude" / "oauth_keys" / "claude_code_oauth_long_lived_keys.csv"

# The ai-maestro server's OWN rotation-tick lock, in the same machine-wide state dir this
# plugin owns. Name and window read from its source (lib/server-lockfile.ts,
# lib/oauth-rotator/tick-lock.ts), not from a description of it.
SERVER_TICK_LOCK = "oauth-rotator-server-tick.lock"
SERVER_STALE_S = 5 * 60


def read_rows(path: Path) -> list[tuple[str, str]]:
    """Parse `email,token` rows, REPORTING every line it drops.

    A row survives when field 0 contains "@" and field 1 yields a token through the same
    extractor the single-account path uses (which absorbs a stray quote, a line-wrap, or a
    copied label). That rejects a header line without special-casing one.

    Dropping silently would be data loss on hand-edited input: a mangled token simply
    vanishes and the summary says "filed 2" for a 3-line file with nothing to explain the
    third. `reader.line_num` is used rather than a counter because it stays correct across
    embedded newlines in a quoted field.
    """
    out: list[tuple[str, str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row or not any(f.strip() for f in row):
                continue
            if len(row) < 2:
                print("[import] IGNORED line %d — needs `email,token`, found %d field(s)."
                      % (reader.line_num, len(row)))
                continue
            email = row[0].strip()
            tok = sct.extract_token(row[1])
            if "@" not in email:
                print("[import] IGNORED line %d — field 1 is not an email address."
                      % reader.line_num)
                continue
            if not tok:
                print("[import] IGNORED line %d (%s) — no token-like value (>= 20 chars) in "
                      "field 2." % (reader.line_num, email))
                continue
            out.append((email, tok))
    return out


def _secure(path: Path) -> None:
    """Make the DEFAULT key file owner-only; only warn about any other path.

    Fixing beats warning on the default file — a warning is a chore the human has to
    remember, and that file holds year-long bearer tokens. But `--csv` accepts an arbitrary
    path, and a file that is group-readable ON PURPOSE (a shared fixture, something another
    tool reads) would be silently broken for its other readers by a run the user thought only
    read it. Narrow the mutation to the one file this tool owns by convention.
    """
    mode = path.stat().st_mode & 0o777
    if not mode & 0o077:
        return
    if path == DEFAULT_CSV:
        path.chmod(0o600)
        print("[import] tightened %s from mode %o to 600 (it held world- or group-readable "
              "long-lived tokens)." % (path, mode))
    else:
        print("[import] WARNING: %s is mode %o — other users on this Mac can read these "
              "tokens. Not changing it, since you named this path explicitly. Run "
              "`chmod 600 %s` if that is not deliberate." % (path, mode, path))


def server_tick_holder() -> int | None:
    """The pid of a LIVE ai-maestro rotation tick, or None if nothing holds its lock.

    OBSERVE ONLY — never create, never reclaim, never unlink. That restraint is the whole
    design. The server's lock is an O_EXCL lockfile; mine is a POSIX flock, and the two
    cannot exclude each other (Node has no `flock`, which is why the server took a separate
    file with a deliberately different name). So a tick can land mid-import and orphan a
    slot: the token in the keychain with nothing indexing it.

    Participating in its protocol properly would mean reclaiming a lock I judge stale — and
    if my staleness window or pid parse disagrees with the server's by even a little, I
    delete a lockfile a LIVE tick is holding and break a mechanism that works correctly
    today. That failure is silent and it would be mine. Refusing to run is loud, costs a
    re-run, and cannot corrupt anything: this is a command a human invoked, so "not now"
    is an acceptable answer in a way it would never be for a daemon.

    Fields are read from the server's own source: the file holds `<pid>\\t<iso>` and is
    presumed abandoned past a five-minute window.
    """
    p = gs.global_state_dir() / SERVER_TICK_LOCK
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
        age = time.time() - p.stat().st_mtime
    except OSError:
        return None  # absent, or vanished between the two calls — nothing holds it
    if age > SERVER_STALE_S:
        return None  # a crashed holder that never released; the server reclaims it, not me
    try:
        pid = int(raw.split("\t")[0].strip())
    except (ValueError, IndexError):
        return None  # empty or corrupt: the server treats this as reclaimable, so not a holder
    if pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None  # holder is gone
    except PermissionError:
        return pid  # alive, owned by another user
    except OSError:
        return None
    return pid


def _live_credential_is_dead() -> bool:
    """True when the credential in use RIGHT NOW is already past its own expiry.

    This is what makes it safe to install an unverified key. Normally an unverified key must
    not go live: nobody answered for it, so a hand-mangled token would take down the running
    session. But when the live credential is itself already expired, the session has nothing
    working to lose, and refusing to install a probably-good key because the network happened
    to be down is the worse outcome. Unknown beats known-dead.
    """
    blob = rotator.read_live_blob()
    if not blob:
        return False
    eh = rotator.expires_in_h(blob)
    return eh is not None and eh < 0


def main() -> int:
    argv = sys.argv[1:]
    csv_path = DEFAULT_CSV
    if "--csv" in argv:
        i = argv.index("--csv")
        if i + 1 >= len(argv):
            print("[import] usage: import_oauth_tokens.py [--csv <path>]")
            return 2
        csv_path = Path(argv[i + 1]).expanduser()
    if not csv_path.exists():
        print("[import] no key file at %s" % csv_path)
        print("[import] Create it with one `email,token` line per account, then re-run.")
        return 2

    holder = server_tick_holder()
    if holder is not None:
        print("[import] NOT RUNNING: an ai-maestro rotation tick holds its lock right now "
              "(pid %d). It writes the same slot index this import does, and the two locks "
              "cannot exclude each other, so filing now could leave a key in the keychain "
              "with nothing indexing it." % holder)
        print("[import] A tick takes seconds. Re-run in a minute, or stop the ai-maestro "
              "server first. Nothing was written.")
        return 1

    _secure(csv_path)
    rows = read_rows(csv_path)
    if not rows:
        print("[import] FAILED: no usable `email,token` rows in %s" % csv_path)
        return 1

    # Duplicate guard, replacing the single-account path's live-fingerprint check. Filing the
    # live account's OWN new key is the whole point here, so comparing against live_fp would
    # refuse the common case. What must still not happen is the same token on two lines: that
    # means `/login` was on one account while `setup-token` ran for another, so one account
    # got minted twice and another has no key at all.
    by_fp: dict[str, str] = {}
    for email, tok in rows:
        fp = rotator.fingerprint({"claudeAiOauth": {"accessToken": tok}})
        if fp in by_fp:
            print("[import] FAILED: %s and %s carry the SAME token, so one account was minted "
                  "twice and another has none. `/login` decides which account `claude "
                  "setup-token` mints for — re-mint in login-then-mint order and re-run."
                  % (by_fp[fp], email))
            return 1
        by_fp[fp] = email

    # No pre-loop state read: the wrong-account check that needed it is gone (see the loop),
    # and the switch decision below deliberately re-reads AFTER the loop instead. Validation is
    # a network round trip per row, so several rows can span a whole daemon tick — deciding
    # from a state snapshot taken a minute earlier is how this would rotate back to an account
    # the daemon had just rotated away from.
    filed: dict[str, str] = {}          # email -> fingerprint of what we filed
    proven: set[str] = set()            # emails whose key the server actually answered for
    failed: list[str] = []
    for email, tok in rows:
        state, detail = sct.account_status(tok)
        if state == "bad":
            print("[import] SKIP %s — %s" % (email, detail))
            failed.append(email)
            continue
        blob = sct.setup_token_blob(tok)
        fp = rotator.fingerprint(blob)
        if not rotator.file_slot(email, blob, via="setup-token",
                                 expires_at=blob["claudeAiOauth"]["expiresAt"]):
            print("[import] SKIP %s — another rotator operation held the lock; re-run." % email)
            failed.append(email)
            continue
        filed[email] = fp
        if state == "ok":
            proven.add(email)
        print("[import] %s %s (fp %s, ~1y) — %s"
              % ("OK  " if state == "ok" else "OK? ", email, fp[:8], detail))
        # NO wrong-account check here, deliberately. The mistake worth catching is minting
        # while a different account is signed in, and a fingerprint comparison against
        # `live_fp` catches only the sliver of it where the mis-minted key happens to be the
        # LIVE one. The common shape — mint for A while A is not live, paste on C's line —
        # matches nothing and passes in silence. Meanwhile `live_fp` is itself unreliable (the
        # live credential is not always mirrored into its slot), so the check fires falsely,
        # and its only implied remedy is a re-mint: a browser round trip through a Cloudflare
        # challenge for a one-shot key. Near-zero true positives against expensive false ones
        # is a check whose reliable effect is teaching the human to skim this output.
        #
        # Nothing can bind a token to an email here: these keys 403 on every identity
        # endpoint, so login-then-mint ordering is the only safeguard and it lives in the
        # skill's prose, where it is honest about being the only one.

    # Adopt the new key for whichever account is live RIGHT NOW. Without this the running
    # session keeps presenting the OLD credential for that same account, so an import that
    # printed three OKs would change nothing where it actually matters.
    #
    # State is re-read HERE, not before the loop: validation is a network round trip per row
    # with a 20 s timeout, so three rows can span a whole daemon tick. Deciding from a
    # minute-old `live_email` would let this rotate back to an account the daemon had just
    # rotated AWAY from because it was near its limit — and the next tick would rotate away
    # again. That flap looks to the user like the rotator malfunctioning.
    #
    # Gated on `proven`, not merely `filed`: an unverified key is one nobody answered for, and
    # installing an unproven credential as the one in use right now is how a hand-mangled
    # token takes down the live session. Filing it is safe (a slot is only selected later);
    # switching to it is not.
    st = rotator.load_state()
    live_now = st.get("live_email")
    if live_now and live_now in filed:
        if live_now not in proven and not _live_credential_is_dead():
            print("[import] NOTE: %s's slot was filed but NOT verified, so the live credential "
                  "was left alone. Re-run when the network is back to adopt it." % live_now)
        elif st.get("live_fp") == filed[live_now]:
            print("[import] live credential for %s is already this key — nothing to swap."
                  % live_now)
        else:
            if live_now not in proven:
                print("[import] %s's new key could NOT be verified, but the credential in use "
                      "is already past its own expiry — installing the unverified key, because "
                      "unknown beats known-dead. Watch the next turn for auth errors."
                      % live_now)
            rc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parent / "rotator.py"),
                 "switch", live_now], check=False).returncode
            if rc == 0:
                print("[import] live credential refreshed in place for %s — a running `claude` "
                      "adopts it on its next turn, no restart." % live_now)
            else:
                print("[import] NOTE: slot filed for %s but the live swap failed (rc %d). Run "
                      "`/janitor-rotate-account-to %s` to apply it." % (live_now, rc, live_now))

    if failed:
        print("[import] not filed: %s — re-mint those and re-run." % ", ".join(failed))
    print("[import] filed %d of %d (%d verified)." % (len(filed), len(rows), len(proven)))
    # Exit code answers ONE question: must a human do something about the run as a whole.
    # A partial import is a success — the accounts that landed are usable now, and the ones
    # that did not are named above. Returning 1 there would make an agent report failure on a
    # mostly-good run and retry the whole import, redoing keychain writes that were correct.
    # 2 is reserved for a usage error, matching rotator.py and slot_capture_token.py.
    return 0 if filed else 1


if __name__ == "__main__":
    raise SystemExit(main())
