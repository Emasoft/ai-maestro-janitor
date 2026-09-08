#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""model-fallback — a spent MODEL window switches the model, instead of stalling the session.

TRDD-QE390SJA / janitor#222. Measured 2026-08-06: the live account sat at 5h=42% / 7d=60%
with the Fable model-scoped window at ~98%. The account was FINE; only one model was spent.
The remedy was one keystroke sequence — ESC, then `/model opus` — and the owner typed it BY
HAND, after the (server-side) rotator had already evicted the fleet off its healthiest
account and disqualified it as a return target for ~123h. Detection had fired hours earlier:
`[window-burn-rate] 7d/Fable window 77% at 24% elapsed`. Nothing consumed it. This detector
is that missing consumer.

It owns NO decisions: the gate is `token_burn.model_fallback_verdict` (scoped-high AND
account-headroom AND both PROVEN), the plan is `model_fallback.plan_model_fallback` (target,
already-switched, cooldown), the typing is `terminal_trigger.send_verified` (the owner's
ratified empty-field / 8s-retry / verify-before-Enter rules), and the confirmation is
`terminal_trigger.confirm_model_switch` (three-state). This file is the glue that gathers
the inputs and records the outcome.

DEFAULT ON — `CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_ENABLED` defaults true; a spent model window
otherwise stalls the session until the window resets, and that idle session cannot self-heal.
No test can prove the confirming keystroke dismissed a real dialog, only that it was sent, so
the module still holds its confirmed-switch discipline (see `model_fallback` module docstring).
FAIL-OPEN throughout: a probe, pane read, or injection failure is a silent skip — a detector
crash must never break the heartbeat.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))
sys.path.insert(0, str(_HERE.parent / "oauth_rotator"))

import findings_ledger  # noqa: E402
import model_fallback as mfb  # noqa: E402
import rotator_usage  # noqa: E402
import session_liveness  # noqa: E402
import state  # noqa: E402
import terminal_trigger  # noqa: E402
import token_burn  # noqa: E402

_LOG = "model-fallback"
# The bars. Scoped-high is where a model window is "spent"; account-headroom is the ceiling
# under which the ACCOUNT counts as fine (the ai-maestro side's number, janitor#222).
_SCOPED_HIGH = 90.0
_ACCOUNT_HEADROOM = 90.0
_STAMP = "model-fallback-last-switch.ts"
_DECLINED_STAMP = "model-fallback-declined.ts"
# TRDD-M4HVFU2A (2026-09-06 incident): an unconfirmed switch (the owner cancelled the
# dialog) is retryable today and re-types every heartbeat — this is the back-off window
# after a SENT-but-not-confirmed switch, so a declined dialog is not re-typed every ~5 min.
_DECLINED_BACKOFF_S = 3600


def _last_switch_ts() -> int:
    return state.read_int_state(state.state_dir() / _STAMP, 0)


def _stamp_switch(now: int) -> None:
    """Record a CONFIRMED switch. Called ONLY on confirmation — a switch whose keystroke
    never landed must not hold the cooldown, or the retry is suppressed for a whole interval
    on a session that never moved (janitor#222, the ai-maestro side's measured defect)."""
    state.atomic_write(state.state_dir() / _STAMP, str(now))


def _this_terminal() -> dict[str, str]:
    """THIS session's own pane. Mirrors `terminal_trigger.self_terminal` — tmux first (cheap to
    capture), then iTerm (an osascript round-trip, still readable). Anything else resolves to
    a kind whose builders return None, and the injection declines rather than typing blind."""
    pane = os.environ.get("TMUX_PANE", "").strip()
    if pane:
        return {"kind": "tmux", "pane": pane}
    iterm = os.environ.get("ITERM_SESSION_ID", "").strip()
    if iterm:
        return {"kind": "iterm", "session_id": iterm.split(":")[-1].strip()}
    return {"kind": "unknown"}


def _declined_age_s(now: int) -> float | None:
    ts = state.read_int_state(state.state_dir() / _DECLINED_STAMP, 0)
    return None if ts <= 0 else float(now - ts)


def _stamp_declined(now: int) -> None:
    """A switch was SENT but not confirmed — back off, don't stamp the retry cooldown."""
    state.atomic_write(state.state_dir() / _DECLINED_STAMP, str(now))


def _sibling_has_headroom(verdict: dict, now: int) -> str | None:
    """A NON-live account whose window for the SAME model is still below 100% — the
    account to rotate to BEFORE switching models here.

    TRDD-M4HVFU2A (2026-09-06 incident, owner ruling): "rotation must come BEFORE any
    model change" — a model switch resets the whole cache, burning millions of tokens
    across every agent on the pane, so it must never be the first move when a cheaper
    remedy (rotate to a sibling with real headroom) is available. `is_active` is NOT part
    of this check — measured live the SAME day: the live account's own Fable window read
    97% with `is_active: true`, so the flag flips well before the window is actually
    spent (see `models_in_use`'s docstring in `token_burn.py`) and cannot answer "does
    this sibling have headroom". Only `util_pct < 100` answers that. Returns the
    sibling's label, or None when no sibling helps."""
    model = str(verdict.get("model") or "")
    try:
        accounts = rotator_usage.accounts_usage()
    except Exception:  # noqa: BLE001 — a rotator failure must not block the fallback
        return None
    for acct in accounts:
        if acct.get("is_live"):
            continue
        for w in token_burn.model_windows_from_usage(acct.get("usage") or {}, now):
            label = str(w.get("label", ""))
            if not label.endswith(f"/{model}"):
                continue
            if float(w.get("util_pct", 0.0)) < 100.0:
                return str(acct.get("label") or "sibling")
    return None


def _live_account() -> dict | None:
    """The LIVE account's usage sample, or None. Reuses the shared read-only gather, which
    already carries `sample_age_s` — the freshness the verdict refuses to act without."""
    try:
        for acct in rotator_usage.accounts_usage():
            if acct.get("is_live"):
                return acct
    except Exception:  # noqa: BLE001 — a rotator/network failure is a silent skip
        return None
    return None


def main() -> int:
    state.init_state()
    if not mfb.enabled():
        return 0  # explicitly disabled via CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_ENABLED=false

    now = int(time.time())
    acct = _live_account()
    if not acct:
        return 0
    verdict = token_burn.model_fallback_verdict(
        acct.get("usage") or {}, now,
        scoped_high=_SCOPED_HIGH, account_headroom=_ACCOUNT_HEADROOM,
        snapshot_age_s=acct.get("sample_age_s"),
        require_active=True,  # TRDD-M4HVFU2A: only a TRUE 100% qualifies — 97% is not spent
    )
    if not verdict:
        return 0  # window fine, account is the constraint, or the sample is unproven

    # TRDD-M4HVFU2A: rotation before any model change. If a sibling account still has
    # real headroom on this same model, the fix is rotating TO it, not switching models
    # on the live pane (a model switch resets the whole cache).
    sibling = _sibling_has_headroom(verdict, now)
    if sibling is not None:
        state.log_line(
            _LOG,
            f"{verdict['scoped_label']} spent on the live account, but {sibling} still "
            f"has {verdict['model']} headroom — rotate first: "
            f"/janitor-rotate-account-to {sibling}",
        )
        print(
            f"[model-fallback] {verdict['scoped_label']} spent on the live account, but "
            f"{sibling} still has {verdict['model']} headroom — rotate first: "
            f"/janitor-rotate-account-to {sibling}"
        )
        return 0

    declined_age = _declined_age_s(now)
    if declined_age is not None and declined_age < _DECLINED_BACKOFF_S:
        state.log_line(_LOG, f"skip: declined {declined_age:.0f}s ago, backing off")
        return 0

    terminal = _this_terminal()
    # READ the pane BEFORE planning: the plan needs to know whether this session is still on
    # the exhausted model (it may have been switched by an earlier pass, or by the user).
    try:
        pane = terminal_trigger.read_pane_text(terminal)
    except Exception:  # noqa: BLE001
        pane = None
    current = terminal_trigger.parse_pane_model(pane) if pane else None

    target = mfb.fallback_target()
    plan = mfb.plan_model_fallback(
        verdict=verdict, current_model=current, target=target,
        last_switch_ts=_last_switch_ts(), now=now, is_enabled=True,
    )
    if not plan["act"]:
        state.log_line(_LOG, f"skip: {plan['reason']} (scoped {verdict['scoped_label']} "
                             f"{verdict['scoped_util']:.0f}%, account {verdict['account_max_util']:.0f}%)")
        return 0

    command = str(plan["command"])
    # SEQUENCE IS STATE-DEPENDENT (owner spec 2026-08-15, from watching the real wall):
    # a pane in the TRUE error state (CC's retry signature on screen) gets
    # command+Enter → ESC → wait-for-Ask-user-menu → Enter; an idle pane keeps the
    # original ESC-first type-and-submit. ESC-first on an erroring pane ends the turn
    # before the command exists and the menu then swallows the slash command.
    true_error = bool(pane) and session_liveness.is_retry_wedge(pane or "")
    try:
        if true_error:
            sent, why = terminal_trigger.send_model_switch_true_error(terminal, command)
        else:
            sent, why = terminal_trigger.send_verified(terminal, command, esc_first=True)
    except Exception as exc:  # noqa: BLE001 — an injection fault must not break the heartbeat
        state.log_line(_LOG, f"inject raised: {exc!r}")
        return 0
    if not sent:
        state.log_line(_LOG, f"not sent: {why} — NOT stamping the cooldown, will retry")
        return 0

    # CONFIRM before stamping. Three-state: only True is success — None means the badge was
    # unreadable, which tells us keystrokes were sent and nothing more.
    try:
        after = terminal_trigger.read_pane_text(terminal)
    except Exception:  # noqa: BLE001
        after = None
    confirmed = terminal_trigger.confirm_model_switch(after, target) if after else None

    line = token_burn.format_model_fallback_line(verdict, target)
    if confirmed is True:
        _stamp_switch(now)
        print(f"{line} — CONFIRMED")
    else:
        shown = "NOT confirmed" if confirmed is False else "confirmation UNKNOWN"
        # No switch-cooldown stamp: an unconfirmed switch must stay retryable. But the
        # keystroke DID land (a human likely cancelled it), so the DECLINED back-off
        # applies — otherwise this re-types every ~5 min heartbeat (TRDD-M4HVFU2A).
        _stamp_declined(now)
        print(f"{line} — {shown}; cooldown NOT stamped (retryable, backing off {_DECLINED_BACKOFF_S}s)")

    try:
        findings_ledger.record(
            sev="HIGH" if confirmed is not True else "INFO",
            code="MODEL-FALLBACK", src=_LOG,
            msg=f"{line} — confirmed={confirmed}", ref="-", now=now,
        )
    except Exception:  # noqa: BLE001 — the mailbox must never break the alarm
        pass

    state.rotate_log_if_big(_LOG)
    return 0


if __name__ == "__main__":
    sys.exit(main())
