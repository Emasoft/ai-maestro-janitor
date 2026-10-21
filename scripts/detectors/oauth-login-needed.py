#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""OAuth one-time-login nudge (opt-in) — the reactive sibling of
oauth-cookie-reminder (TRDD-32acd15f, P4c).

When the local multi-account rotator is set up, this per-session detector
records the accounts that need a ONE-TIME human login because they can
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
browser. PRINTS NOTHING and sends no account notification (USER ruling 2026-10-21, TRDD-1J9B7MWO): rotator
and account issues never reach an agent. It only records owner remediations in
owner-remediation.json; the janitor daemon notifies the user once per episode.
The one notification it raises itself is the daemon-stalled one (a hung or dead daemon cannot
report itself), under the daemon's episode key, so N sessions still yield ONE.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))
sys.path.insert(0, str(_HERE.parent / "oauth_rotator"))

import cascade  # noqa: E402  # scripts/oauth_rotator/cascade.py (ROTATE→RENEW→REAUTH SSOT, TRDD-dfc0959a)
import rotator  # noqa: E402  # scripts/oauth_rotator/rotator.py (canonical session-key probe + profiles root)
import rotator_alert  # noqa: E402  # scripts/lib/rotator_alert.py (stuck-rotation wording SSOT, TRDD-MI018FID)
import state  # noqa: E402
import supervisor  # noqa: E402  # scripts/oauth_rotator/supervisor.py (keychain-aware slot facts)


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


def _topup_days() -> float:
    """Cadence (days) of the proactive "top up ALL logins" nudge (TRDD-GZXTSJSR P3c).

    Separate from `_grace_days()` — that one fires REACTIVELY once an account is close
    to needing a login; this one fires on a flat calendar cadence regardless of whether
    any single account is currently due, so tokens never approach expiry as a fleet."""
    return float(
        state.coerce_int(
            os.environ.get("CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS"),
            7,
            detector_name="oauth-login-needed",
            var_name="CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS",
        )
    )


def _topup_cycle(now: float, every_days: float) -> int:
    """The calendar cycle number of the top-up nudge: floor(now / period). It is the record's kind,
    so a new cycle is a NEW notification episode and the same cycle is one. WHY no "last nudged"
    stamp: a stamp written before the daemon notified lost the weekly nudge whenever the daemon
    was down; the record is refreshed on every heartbeat of the cycle and the episode store alone
    remembers that it was sent."""
    return int(now // (every_days * 86400))


def main() -> int:
    state.init_state()

    home = _rotator_home()
    if home is None:
        return 0  # opt-in: no rotator configured on this machine -> silent no-op

    now = time.time()

    # USER ruling 2026-10-21 (TRDD-1J9B7MWO): rotator and account issues NEVER reach an agent, so
    # this detector prints nothing and notifies nobody. It only RECORDS owner remediations
    # (owner-remediation.json); the janitor DAEMON is the one notifier and tells the user once per
    # episode. The single exception is the daemon's own stall: a hung or dead daemon cannot report
    # itself, so the heartbeat side raises that one under the daemon's episode key, which the
    # machine-wide notify-sent store collapses to one notification across every session.
    try:
        rotator_alert.notify_session_tick_stalled(
            home, now, server_owns_tick=supervisor._server_owns_chores()
        )
    except Exception:  # noqa: BLE001 -- a notify fault must never break the heartbeat
        pass

    # Every path named in the messages below is RESOLVED, never hard-coded (janitor#258).
    # These lines used to spell `~/.claude/account-rotator/...` literally while the state read
    # went through `configured_rotator_home()` — so on a migrated install the detector read the
    # canonical dir and then told the reader to look in the legacy one. That is TRDD-5EUYV08H
    # exactly, one field over: the fix covered the DATA path and left the MESSAGE path behind.
    login_sh = _disp(rotator.open_login_script())

    grace = _grace_days()

    # supervisor._slot_facts is keychain-aware (reads each slot's token blob from
    # the OS keychain, plaintext-file fallback) and returns only NON-secret
    # metadata: (email, has_refresh, expires_days). Exactly what the classifier needs.
    # It stays HERE (a per-heartbeat, per-session process), never in the daemon's 60 s loop:
    # a keychain read there risks a prompt storm.
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

    # OBSERVED CLEARS: an account seen fine on this pass (logged in, self-renewing, or captured) has
    # its record deleted and its episode ended, so a later relapse notifies again. Only this pass
    # observes it; a gap between heartbeats never ends an episode (facts empty: unobserved, no clear).
    rotator_alert.clear_owner_remediations(
        home, "oauth-login-needed", now, keep_slots=frozenset(e for e, _ in needing)
    )
    rotator_alert.clear_owner_remediations(
        home, "oauth-capture-stalled", now, keep_slots=frozenset(stalled)
    )

    # PRIMARY — accounts that need a fresh human sign-in. One record per account (not one aggregated
    # record: an account that logs in must clear alone, and a second account must still notify).
    # The urgency
    # bucket is the record's kind, so a worsening account (48h -> 24h -> expired) is a NEW
    # episode and the daemon notifies again, while an unchanged one stays silent.
    for email, bucket in sorted(needing):
        rotator_alert.record_owner_remediation(
            home,
            "oauth-login-needed",
            f"account {email} needs a one-time login ({bucket}) - run `{login_sh} {email}` "
            f"(opens a DEDICATED Chrome window; your default browser is untouched)",
            now,
            kind=bucket,
            slot=email,
        )

    # SECONDARY (B3) — accounts that ARE logged in but whose automatic OAuth capture hasn't
    # completed (the detached bootstrap keeps launching but never succeeds: CF challenge,
    # missing playwright, a wedged consent page). One record per account.
    if stalled:
        stalled = sorted(stalled)
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
        for email in stalled:
            rotator_alert.record_owner_remediation(
                home,
                "oauth-capture-stalled",
                f"account {email} is logged in but its OAuth capture hasn't completed - the "
                f"rotator retries every tick; if it keeps failing, check {evidence}, and if the "
                f"session has lapsed re-run `{login_sh} {email}`",
                now,
                slot=email,
            )

    # The "rotation is IMPOSSIBLE" dead end (rotation-stuck.json) is NOT handled here any more:
    # `rotator_alert.active_conditions` already reads the same marker with the same one-hour
    # staleness gate, and the daemon notifies it once per (condition, kind) episode. Wording it
    # from `stuck_text` here printed the false all-accounts-maxed verdict to agents (TRDD-1J9B7MWO).

    # QUATERNARY nudge (P3c) — proactive "top up ALL your logins" on a flat calendar
    # cadence, independent of whether any single account is currently flagged above.
    # Capture-before-crisis: refresh the whole fleet periodically instead of waiting
    # for individual accounts to become urgent one at a time.
    #
    # NOT gated on `supervisor._server_owns_chores()` (P5) — deliberately. That
    # predicate decides who runs the automatic 60s rotation TICK; a login is a HUMAN
    # action neither the janitor daemon nor the ai-maestro server can perform for the
    # user, so the nudge must surface regardless of which side currently owns rotation.
    topup_days = _topup_days()
    if topup_days > 0:
        # The cycle number is the record's kind: a new calendar cycle is a NEW episode, the same
        # cycle is one (re-recorded every heartbeat, notified once by the daemon).
        rotator_alert.record_owner_remediation(
            home,
            "oauth-login-topup",
            f"proactive top-up: refresh all {len(facts)} rotator login(s) before any "
            f"expire - run /janitor-capture-all-logins",
            now,
            kind=str(_topup_cycle(now, topup_days)),
        )

    state.rotate_log_if_big("oauth-login-needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
