#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""OAuth one-time-login nudge (opt-in) — the reactive sibling of
oauth-cookie-reminder (TRDD-32acd15f, P4c).

When the local multi-account rotator is set up, this per-session detector
surfaces the accounts that need a ONE-TIME human login because they can
neither self-renew NOR auto-bootstrap:

  * no refreshToken  → the daemon's keepalive-refresh cannot keep it alive, AND
  * no live claude.ai Chrome session → the rotator's post-login auto-bootstrap
    (slot_capture_browser, Part B) has nothing to mint a refresh token from, AND
  * the token is expired / near-expired (within a small grace window).

Those three together mean only a fresh human sign-in can revive the account.
Accounts that DO carry a refreshToken (daemon-refreshed) or DO have a live
session (bootstrap-eligible) are deliberately NOT nudged here — single
responsibility, distinct from cookie-reminder which is about the cookie/OAuth
expiry RACE.

OPT-IN BY PRESENCE: silent no-op unless a rotator home containing a state.json
is found (CLAUDE_ROTATOR_HOME, ~/.claude/account-rotator, or
$CLAUDE_PLUGIN_DATA/oauth-rotator). NOT gated on the opt-in.flag — the login
nudge helps the user finish setup even before they flip full auto-management on.
Read-only: reads cookie + slot metadata, never secret values, never launches a
browser. Machine-scoped daily dedupe keeps it to ~one nudge/day while a login is
due, even though the per-session heartbeat fires it in every project.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))
sys.path.insert(0, str(_HERE.parent / "oauth_rotator"))

import cascade  # noqa: E402  # scripts/oauth_rotator/cascade.py (ROTATE→RENEW→REAUTH SSOT, TRDD-dfc0959a)
import dedupe  # noqa: E402
import notify  # noqa: E402  # scripts/lib/notify.py (human-notification channel, TRDD-4649ZLE0)
import rotator  # noqa: E402  # scripts/oauth_rotator/rotator.py (canonical session-key probe + profiles root)
import state  # noqa: E402
import supervisor  # noqa: E402  # scripts/oauth_rotator/supervisor.py (keychain-aware slot facts)

# Escalation dedupe key rank (TRDD-GZXTSJSR root cause 3) — "dead-refresh" and "expired"
# are equally maximal urgency (both mean only a human re-login fixes it right now).
_URGENCY_RANK = {"expired": 0, "dead-refresh": 0, "24h": 1, "48h": 2}


def _rotator_home() -> Path | None:
    """The rotator home the DAEMON uses, or None (opt-in no-op). Delegates to the SSOT
    `rotator.configured_rotator_home()` so this detector and the daemon ALWAYS read the same
    state.json. The old per-detector resolver checked the legacy `~/.claude/account-rotator`
    BEFORE the canonical `$CLAUDE_PLUGIN_DATA/oauth-rotator`, opposite to the daemon — so on a
    migrated install (both present) the detector read STALE legacy state (refresh_failures=0) and
    stayed silent while the daemon nudged every tick on the live canonical state (TRDD-5EUYV08H)."""
    return rotator.configured_rotator_home()


def slot_needs_login(
    has_refresh: bool,
    token_days: float | None,
    has_session_key: bool,
    grace_days: float,
    refresh_failures: int = 0,
) -> bool:
    """PURE: does this account need a ONE-TIME human login?

    Needs a human login iff it can't self-renew AND has no seeded session to
    auto-bootstrap from AND its token is expired / near-expired — OR its refresh token is
    present but DEAD (``refresh_failures`` ≥ the cascade's max consecutive keepalive-refresh
    failures), which is equally only fixable by a human re-login (TRDD-HJGR4I5W).

    Delegates to the cascade SSOT (TRDD-dfc0959a): a LOGIN is needed ⇔ the account
    lands in the cascade's REAUTH_NUDGE leg, so the daemon's cascade and this nudge
    can never disagree about which accounts are genuinely stuck. test_cascade proves
    this reproduces the historical truth table exactly.
    """
    return cascade.classify(
        cascade.AccountState(
            email="", is_live=False, has_refresh=has_refresh,
            token_expires_h=(token_days * 24.0 if token_days is not None else None),
            has_session_cookie=has_session_key,
            refresh_failures=refresh_failures,
        ),
        login_grace_days=grace_days,
    ) is cascade.CascadeLeg.REAUTH_NUDGE


def slot_capture_stalled(has_refresh: bool, has_session_key: bool, refresh_failures: int = 0) -> bool:
    """PURE (B3): is this account LOGGED IN but its OAuth capture has NOT completed?

    True iff it has a live claude.ai session (so it IS bootstrap-eligible — the human
    already did the one thing only they can do) yet has no USABLE refresh — either NO
    refreshToken, OR a DEAD one (``refresh_failures`` ≥ max; TRDD-J9TM3WQK). The automatic
    detached capture launches every tick, but if it keeps failing (CF challenge, missing
    playwright, a wedged consent page) the slot stays stuck in this state forever. That
    stuck-ness is itself the signal to nudge the user to run the capture MANUALLY once. A
    slot that still self-renews (a live refresh below the dead threshold) or has no session
    (that's slot_needs_login's LOGIN nudge, not this one) is NOT stalled.

    Delegates to the cascade SSOT (TRDD-dfc0959a): stalled ⇔ the cascade's RENEW_COOKIE leg
    (bootstrap-eligible) — the SAME set rotator._bootstrap_eligible drives the daemon's
    capture launches from, so the launch set and the stalled-nudge set can never diverge.
    ``refresh_failures`` MUST be threaded so the dead-refresh + cookie case (now RENEW_COOKIE)
    stays inside that invariant."""
    return cascade.classify(
        cascade.AccountState(
            email="", is_live=False, has_refresh=has_refresh,
            token_expires_h=None, has_session_cookie=has_session_key,
            refresh_failures=refresh_failures,
        )
    ) is cascade.CascadeLeg.RENEW_COOKIE


def _has_live_session(email: str, now: float) -> bool:
    """True iff a live (not-yet-expired) claude.ai sessionKey cookie exists for the
    account — i.e. the post-login auto-bootstrap could mint a refresh token from it.

    Delegates to the canonical engine probe ``rotator._profile_has_session_key`` so
    the LOGIN-eligibility decision is IDENTICAL to the rotator's own bootstrap gate
    (audit B-F4): sessionKey-only, ``host_key LIKE '%claude.ai'``, ``expires_utc >
    now`` (a session-cookie with ``expires_utc == 0`` is correctly excluded). The
    engine fn resolves the profiles root via ``rotator._profiles_root()`` — the
    shared resolver with the legacy fallback — so this also fixes the migrated-install
    root bypass (audit B-F1) for the session check in one stroke."""
    return rotator._profile_has_session_key(email, now=now)


def _grace_days() -> float:
    """Login-nudge grace window (days). Env-overridable; default 2.0 (48h).

    Widened from the original 1.0-day default (TRDD-GZXTSJSR root cause 1): a 1-day
    window only fires once a token is already near-dead — reactive, not proactive.
    2.0 days gives the human a full extra workday of runway before any account
    actually becomes unusable, matching the "prompt EARLY" requirement this TRDD
    exists for. A bad value (non-numeric / non-positive) falls back to the default
    so a typo in the env never crashes the heartbeat or disables the nudge silently."""
    raw = os.environ.get("CLAUDE_ROTATOR_LOGIN_NUDGE_GRACE_DAYS", "").strip()
    if not raw:
        return 2.0
    try:
        val = float(raw)
    except ValueError:
        return 2.0
    return val if val > 0 else 2.0


def _urgency(token_days: float | None, refresh_failures: int) -> str:
    """One-word urgency bucket for an account that needs a human login.

    Drives BOTH the notify severity (root cause 4 — the nudge must reach a REAL
    human channel, not just a heartbeat line nobody unattended reads) AND the
    escalation dedupe key (root cause 3 — a worsening account must produce a NEW
    signature so it re-notifies instead of going silent behind yesterday's daily
    key). Buckets are coarse and boundary-triggered by construction — they only
    change when the account's real state crosses a threshold, so this can never
    become a per-tick spam source."""
    if refresh_failures >= cascade.DEFAULT_MAX_REFRESH_FAILURES:
        return "dead-refresh"
    if token_days is None or token_days <= 0:
        return "expired"
    if token_days <= 1.0:
        return "24h"
    return "48h"


def _disp(path: Path) -> str:
    """`path` with the user's home collapsed to `~` — still copy-pasteable in a shell, but
    short enough that the remedy stays readable inside an already-long drift line."""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def _topup_stamp_path(home: Path) -> Path:
    return home / ".login-topup-last.txt"


def _topup_days() -> float:
    """Cadence (days) of the proactive "top up ALL logins" nudge (TRDD-GZXTSJSR P3c).

    Separate from `_grace_days()` — that one fires REACTIVELY once an account is close
    to needing a login; this one fires on a flat calendar cadence regardless of whether
    any single account is currently due, so tokens never approach expiry as a fleet."""
    return float(state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS"), 7))


def _topup_due(home: Path, now: float, every_days: float) -> bool:
    """True when the periodic top-up nudge is due: no stamp yet, or the stamp is older
    than `every_days`. A missing/corrupt stamp reads as "due" (fail-open toward nudging,
    never toward permanent silence)."""
    try:
        last = float(_topup_stamp_path(home).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    return (now - last) >= every_days * 86400


def main() -> int:
    state.init_state()

    home = _rotator_home()
    if home is None:
        return 0  # opt-in: no rotator configured on this machine -> silent no-op

    # Every path named in the messages below is RESOLVED, never hard-coded (janitor#258).
    # These lines used to spell `~/.claude/account-rotator/...` literally while the state read
    # went through `configured_rotator_home()` — so on a migrated install the detector read the
    # canonical dir and then told the reader to look in the legacy one. That is TRDD-5EUYV08H
    # exactly, one field over: the fix covered the DATA path and left the MESSAGE path behind.
    login_sh = _disp(rotator.open_login_script())

    grace = _grace_days()
    now = time.time()

    # supervisor._slot_facts is keychain-aware (reads each slot's token blob from
    # the OS keychain, plaintext-file fallback) and returns only NON-secret
    # metadata: (email, has_refresh, expires_days). Exactly what the classifier needs.
    facts = supervisor._slot_facts(home, now)
    if not facts:
        state.rotate_log_if_big("oauth-login-needed")
        return 0

    needing: list[tuple[str, str]] = []  # (email, urgency bucket) — needs a one-time human LOGIN
    stalled: list[str] = []   # B3: logged in (has session) but OAuth capture not yet completed
    for f in facts:
        has_session = _has_live_session(f.email, now)
        if slot_needs_login(f.has_refresh, f.expires_days, has_session, grace, f.refresh_failures):
            needing.append((f.email, _urgency(f.expires_days, f.refresh_failures)))
        elif slot_capture_stalled(f.has_refresh, has_session, f.refresh_failures):
            stalled.append(f.email)

    day = int(now // 86400)

    # PRIMARY nudge — accounts that need a fresh human sign-in. Machine-scoped daily
    # dedupe (the rotator is machine-wide, not per-project) so one nudge/day regardless
    # of how many sessions fire heartbeats.
    if needing:
        needing = sorted(needing)
        emails = ", ".join(e for e, _ in needing)
        seen = home / ".oauth-login-needed-seen.txt"
        # Escalation signature: bucket-aware, not just the email set (root cause 3). A
        # worsening account (48h -> 24h -> expired) changes the sig even within the
        # same day, so it re-notifies instead of staying silent behind yesterday's key.
        sig = hashlib.sha1(
            ",".join(f"{e}:{b}" for e, b in needing).encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:8]
        msg = (
            f"[oauth-login-needed] {len(needing)} account(s) need a one-time login: "
            f"{emails} — run `{login_sh} <email>` for each "
            f"(opens a DEDICATED Chrome window; your default browser is untouched). "
            f"The rotator auto-bootstraps the rest."
        )
        line = dedupe.emit_once(seen, f"due-{day}-{sig}", msg)
        if line is not None:
            print(line)

        # Root cause 4 (the decisive gap) — a heartbeat print is invisible to an
        # UNATTENDED session. Route through the real human channel too. notify.push
        # owns its own gates (severity floor, content-hash dedupe, 24h cap, digest),
        # so calling it every tick is safe; the worst-case account decides severity so
        # an expired/dead-refresh account escalates past a plain 48h-out HIGH.
        worst = min((b for _, b in needing), key=lambda b: _URGENCY_RANK[b])
        sev = "CRITICAL" if worst in ("expired", "dead-refresh") else "HIGH"
        try:
            notify.push(
                sev=sev,
                code="OAUTH-LOGIN-NEEDED",
                project="oauth-rotator",
                summary=f"{len(needing)} account(s) need a one-time login ({worst}): {emails}",
                hint=login_sh,
            )
        except Exception:  # noqa: BLE001 -- a notify fault must never break the heartbeat
            pass

    # SECONDARY nudge (B3) — accounts that ARE logged in but whose automatic OAuth capture
    # hasn't completed (the detached bootstrap keeps launching but never succeeds: CF
    # challenge, missing playwright, a wedged consent page). Tell the user to run the
    # capture MANUALLY once. Separate seen-file + signature so it dedupes independently of
    # the login nudge (the two sets are disjoint by construction).
    if stalled:
        stalled = sorted(stalled)
        seen2 = home / ".oauth-capture-stalled-seen.txt"
        sig2 = hashlib.sha1(",".join(stalled).encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        emails2 = ", ".join(stalled)
        # The per-account `bootstrap-<email>.log` exists ONLY if a capture was actually
        # LAUNCHED — `rotator._invoke_slot_capture` opens it at Popen time, and the launch is
        # skippable (auto-launch opted off, past the launch cap, or a denied domain). Naming it
        # unconditionally sent the reader to a missing file at the exact moment they had least
        # patience for one, and read as "the capture never started" when that was not the
        # finding (janitor#258). `rotator.log` is written unconditionally and carries the
        # decision either way, so it is the honest primary pointer; the bootstrap log is named
        # only when it is genuinely there.
        boot_logs = [
            p
            for p in (home / ("bootstrap-%s.log" % e.replace("/", "_")) for e in stalled)
            if p.is_file()
        ]
        evidence = f"`{_disp(home / 'rotator.log')}`"
        if boot_logs:
            evidence += " and " + ", ".join(f"`{_disp(p)}`" for p in boot_logs)
        msg2 = (
            f"[oauth-capture-stalled] {len(stalled)} account(s) are logged in but their OAuth "
            f"capture hasn't completed: {emails2} — the rotator retries the capture every tick; "
            f"if it keeps failing, check {evidence}, "
            f"and if the session has lapsed re-run `{login_sh} <email>`."
        )
        line2 = dedupe.emit_once(seen2, f"stalled-{day}-{sig2}", msg2)
        if line2 is not None:
            print(line2)

    # TERTIARY nudge — rotation is IMPOSSIBLE right now, and no human knows.
    #
    # The two nudges above cover per-account credential death. They do NOT cover the other
    # dead end: every account is alive but USAGE-EXHAUSTED, or there is no alternate to
    # rotate to at all. `rotator._decide()` records those to stdout and `rotator.log`, and
    # MEASURED 2026-08-20: nothing in `scripts/` reads that log for them. So the one moment
    # a human is the only way forward was the one moment the janitor said nothing, and the
    # session simply stalled — the shape the owner reports as "projects stall after a while".
    #
    # Reads the MARKER (`rotation-stuck.json`), never greps the log: the rotator knows it is
    # stuck and says so structurally, and a log grep would re-derive that by pattern-matching
    # prose that is free to be reworded.
    try:
        stuck = json.loads((home / "rotation-stuck.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- absent (the healthy case) or corrupt: stay silent
        stuck = None
    if isinstance(stuck, dict) and stuck.get("kind"):
        first = int(stuck.get("first_seen_epoch") or now)
        last = int(stuck.get("last_seen_epoch") or first)
        # STALENESS GATE. The marker is cleared on a successful rotation, but a host whose
        # rotator stopped running entirely would leave one behind forever. Only report while
        # the condition is still being OBSERVED, so this can never nag about a dead end that
        # ended when the rotator did.
        if now - last <= 3600:
            kind = str(stuck.get("kind"))
            hours = max(0.0, (now - first) / 3600.0)
            remedy = {
                "all-accounts-maxed":
                    "every paid account is over its usage window — nothing to do but wait for "
                    "a window to reset, or add another paid account",
                "no-alternates-configured":
                    f"there is no second account to rotate to — add one with `{login_sh} <email>`",
                "expired-and-offline":
                    "the live credential is expired and the API is unreachable — check the "
                    "network, then re-auth manually",
            }.get(kind, "see the rotator log for the decision")
            msg3 = (
                f"[oauth-rotation-stuck] rotation has been IMPOSSIBLE for {hours:.1f}h "
                f"({kind}): {remedy}. Until it clears, a rate-limited session cannot be "
                f"rescued by rotating — it will stall. Detail: {stuck.get('detail') or 'n/a'}"
            )
            seen3 = home / ".oauth-rotation-stuck-seen.txt"
            line3 = dedupe.emit_once(seen3, f"stuck-{day}-{kind}", msg3)
            if line3 is not None:
                print(line3)

    # QUATERNARY nudge (P3c) — proactive "top up ALL your logins" on a flat calendar
    # cadence, independent of whether any single account is currently flagged above.
    # Capture-before-crisis: refresh the whole fleet periodically instead of waiting
    # for individual accounts to become urgent one at a time.
    #
    # NOT gated on `supervisor._server_owns_chores()` (P5) — deliberately. That
    # predicate decides who runs the automatic 60s rotation TICK; a login is a HUMAN
    # action neither the janitor daemon nor the ai-maestro server can perform for the
    # user, so the nudge must surface regardless of which side currently owns
    # rotation. No shared suppression-flag protocol exists on the server side (none
    # found by grep) — inventing one here would be speculative, so both sides simply
    # notify; `notify.push`'s own content-hash dedupe + 24h cap already bound how often
    # the human is actually interrupted if both fire.
    topup_days = _topup_days()
    if topup_days > 0 and _topup_due(home, now, topup_days):
        try:
            notify.push(
                sev="HIGH",
                code="OAUTH-LOGIN-TOPUP",
                project="oauth-rotator",
                summary=f"proactive top-up: refresh all {len(facts)} rotator login(s) before any expire",
                hint="/janitor-capture-all-logins",
            )
        except Exception:  # noqa: BLE001 -- a notify fault must never break the heartbeat
            pass
        try:
            state.atomic_write(_topup_stamp_path(home), str(now))
        except Exception:  # noqa: BLE001 -- a stamp-write fault must never break the heartbeat
            pass

    state.rotate_log_if_big("oauth-login-needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
