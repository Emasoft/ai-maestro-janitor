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
already-switched, cooldown), the typing is `pane_actuate.act` with `Event.NO_HEADROOM`
(TRDD-8P4BNY5J: the one screen-state reader + policy table decide and run the keystrokes —
this file no longer types directly), and the confirmation is
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
import pane_actuate  # noqa: E402
import rotator_usage  # noqa: E402
import state  # noqa: E402
import terminal_trigger  # noqa: E402
import token_burn  # noqa: E402

_LOG = "model-fallback"
# The bars. Scoped-high is where a model window is "spent"; account-headroom is the ceiling
# under which the ACCOUNT counts as fine (the ai-maestro side's number, janitor#222).
# The rotation verb's has-Fable-headroom bar — MUST equal rotator.SCOPED_SWITCH_AT (pinned by
# test_the_detectors_bars_equal_the_rotation_verbs_bars). Since TRDD-M4HVFU2A the verdict itself
# ignores it (require_active=True admits only a true 100 %); it now gates ONLY the rotate-first
# sibling scan, so do not "fix" it to 100 to match the verdict.
_SCOPED_HIGH = 90.0
_ACCOUNT_HEADROOM = 90.0  # == rotator.SCOPED_ACCOUNT_HEADROOM, same pin
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


def _actuate_terminal(terminal: dict[str, str]) -> dict[str, str]:
    """Convert `_this_terminal()`'s `{kind, pane|session_id}` shape (terminal_trigger's own
    reader convention) to the `{tmux_pane|iterm_session_id}` shape `pane_state`/`pane_actuate`/
    `fleet_inject` expect (`fleet_scan.capture_pane_text`'s convention). TWO conventions
    genuinely coexist in this codebase; this file still needs the first for
    `terminal_trigger.read_pane_text`/`parse_pane_model`/`confirm_model_switch` (pure text
    parsing, untouched by TRDD-8P4BNY5J), and now needs the second so the actual keystrokes go
    through `pane_actuate.act` instead of typing directly. An unrecognized/unknown kind maps to
    `{}`, which `pane_actuate.act` reads as "no channel" and no-ops on — the same fail-open
    the old code got from `terminal_trigger.read_pane_text` returning None for an unknown kind.
    """
    if terminal.get("kind") == "tmux" and terminal.get("pane"):
        return {"tmux_pane": terminal["pane"]}
    if terminal.get("kind") == "iterm" and terminal.get("session_id"):
        return {"iterm_session_id": terminal["session_id"]}
    return {}


def _declined_age_s(now: int) -> float | None:
    ts = state.read_int_state(state.state_dir() / _DECLINED_STAMP, 0)
    return None if ts <= 0 else float(now - ts)


def _stamp_declined(now: int) -> None:
    """A switch was SENT but not confirmed — back off, don't stamp the retry cooldown."""
    state.atomic_write(state.state_dir() / _DECLINED_STAMP, str(now))


def _sibling_has_headroom(verdict: dict, now: int) -> tuple[str, float] | None:
    """A NON-live account that `/janitor-rotate-account-to` (no argument) would pick as a
    `<model>`-headroom target — account windows at/under `_ACCOUNT_HEADROOM` AND the
    same-model window under `_SCOPED_HIGH` — as (label, model util_pct), or None.

    TRDD-M4HVFU2A (owner ruling, 2026-09-06): "rotation must come BEFORE any model change" —
    a model switch resets the whole cache for every agent on the pane. The predicate is
    `token_burn.model_headroom_candidate`, SHARED with rotate_to.py's auto-select, so this
    stand-down never names a slot the rotation verb would refuse (review 2026-09-08: the
    first cut used `< 100`, no account check, and printed the account's LABEL — a local part
    the explicit `rotate_to.py <email>` path rejects as UNKNOWN_ACCOUNT). `is_active` plays
    no part: measured live, it is true at 97 %. A sibling whose token is about to expire
    still qualifies here while rotate_to's auto-select skips it — then the verb answers
    NO_TARGET and this detector keeps standing down; accepted, and said on the card."""
    model = str(verdict.get("model") or "")
    try:
        accounts = rotator_usage.accounts_usage()
    except Exception:  # noqa: BLE001 — a rotator failure must not block the fallback
        return None
    for acct in accounts:
        if acct.get("is_live"):
            continue
        util = token_burn.model_headroom_candidate(
            acct.get("usage") or {}, now, model,
            scoped_high=_SCOPED_HIGH, account_headroom=_ACCOUNT_HEADROOM,
        )
        if util is not None:
            return str(acct.get("label") or "sibling"), util
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
        label, util = sibling
        line = (
            f"{verdict['scoped_label']} spent on the live account, but {label} still has "
            f"{verdict['model']} headroom ({util:.0f}% used) — rotate first: "
            f"/janitor-rotate-account-to"
        )
        state.log_line(_LOG, line)
        print(f"[model-fallback] {line}")
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

    # TRDD-8P4BNY5J: route the keystrokes through pane_actuate/pane_policy's Event.NO_HEADROOM
    # row instead of calling terminal_trigger.send_verified/send_model_switch_true_error
    # directly. This file used to classify the wedge itself (`true_error`, above) and hand-pick
    # which hand-rolled sequence to type — exactly the bypass TRDD-N954KWUC's "ONE screen-state
    # reader drives EVERY keystroke" invariant forbids. `pane_actuate.act` re-reads the pane
    # fresh and `pane_policy.plan()` picks the sequence from THAT read: at a retry_wedge OR an
    # idle pane still on the exhausted model it is the ESC-flush(-if-wedged) -> `/model <target>`
    # -> confirm chain TRDD-3T9HQEQ6 ratified (`pane_policy._at_wedge`/`_at_idle`'s NO_HEADROOM
    # rows, extended by the 8P4BNY5J follow-up so a spent window on an otherwise-idle pane is no
    # longer a silent no-op); a live turn (`_at_working`) still refuses, by design (law 2).
    # `command=` carries the CONFIGURED target (CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_TARGET)
    # through `pane_actuate.act`'s existing pass-through to `pane_policy.plan()`, so a non-
    # default target is honored instead of the policy table's hardcoded "/model opus" fallback.
    # No `bypass_interrupt_cooldown` equivalent exists in `pane_actuate`/`fleet_inject` at
    # all -- daemon-driven actuation never enforced that guard for any event, which for THIS
    # call site is what `bypass_interrupt_cooldown=True` already asked for (owner finding
    # 2026-09-15, #306: this switch IS the recovery from the session's own exhausted-model
    # state, so a just-issued Esc/Ctrl-C must not defer it).
    try:
        outcome = pane_actuate.act(
            _actuate_terminal(terminal),
            pane_actuate.Event.NO_HEADROOM,
            command=f"/model {target}",
            project_dir=str(state.project_root()),
            log=lambda m: state.log_line(_LOG, m),
        )
    except Exception as exc:  # noqa: BLE001 — an injection fault must not break the heartbeat
        state.log_line(_LOG, f"inject raised: {exc!r}")
        return 0
    if not outcome.touched:
        state.log_line(
            _LOG, f"not sent: {outcome.status.value} — NOT stamping the cooldown, will retry",
        )
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
