"""Model-scoped fallback PLANNER (TRDD-QE390SJA, janitor#222) — the pure decision layer.

A model-scoped window can be spent while the account is fine. Measured 2026-08-06: the live
account sat at 5h=42% / 7d=60% with the Fable window at ~98%, and the remedy was one
keystroke sequence — ESC, `/model opus` — which the owner typed BY HAND. This module decides
whether to type it; `terminal_trigger.send_verified` does the typing and
`terminal_trigger.confirm_model_switch` reports whether it took.

Everything here is PURE: the caller gathers (usage, pane text, stamps) and passes them in, so
the whole truth table is unit-testable without a live pane or a network call.

THE TWO RULES THAT ARE NOT OBVIOUS, both learned from the ai-maestro side's parallel build:

1. **Stamp the cooldown only on a CONFIRMED switch.** A switch whose confirming keystroke
   never landed leaves the session on the exhausted model AND holding the cooldown, so the
   retry is suppressed for a whole interval on a session that never moved. That is why
   `confirm_model_switch` is three-state and why `None` (cannot tell) must not be recorded as
   success — the two are one design decision, not two.
2. **Enforce the interval HERE, not by trusting the beat.** The janitor's heartbeat cadence is
   dynamic (it re-tiers between */5 and */15 on its own), so a faster beat would otherwise
   fire a burst of switches — the exact rate-limit ban the interval exists to avoid.

Ships DARK by default: the flag must be set explicitly. No test can prove the confirming
keystroke dismissed a real dialog — only that it was sent — so the first live switch is
watched by a human.
"""

from __future__ import annotations

import os

import state
import terminal_trigger

# The owner's number, shared with the ai-maestro side's `FALLBACK_INTERVAL_MS` (janitor#222).
FALLBACK_INTERVAL_S = 60
# Default target when the scoped window that is spent belongs to the model in use.
DEFAULT_FALLBACK_MODEL = "opus"
_ENABLED_ENV = "CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_ENABLED"
_TARGET_ENV = "CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_TARGET"

# Skip reasons — a CLOSED vocabulary so a caller can branch on them and a log line can be
# grepped. Every non-act outcome names itself; "nothing happened" is never silent.
SKIP_DISABLED = "disabled"
SKIP_NO_VERDICT = "no-verdict"
SKIP_ALREADY_OFF = "already-off-the-exhausted-model"
SKIP_TARGET_EXHAUSTED = "target-model-also-exhausted"
SKIP_UNKNOWN_MODEL = "current-model-unknown"
SKIP_COOLDOWN = "cooldown"


def enabled() -> bool:
    """Master opt-in. DEFAULT OFF — this types into the user's own pane, and the failure mode
    of getting it wrong is a session parked on an unanswered dialog, which is worse than the
    exhausted window it was trying to fix."""
    return state.is_truthy_env(_ENABLED_ENV, False)


def fallback_target() -> str:
    """The model to switch TO. Configurable so a future model tier does not need a code
    change; defaults to the next-best generally-available model."""
    return (os.environ.get(_TARGET_ENV, "") or "").strip() or DEFAULT_FALLBACK_MODEL


def plan_model_fallback(
    *,
    verdict: dict | None,
    current_model: str | None,
    target: str,
    last_switch_ts: int,
    now: int,
    is_enabled: bool,
    interval_s: int = FALLBACK_INTERVAL_S,
) -> dict:
    """Decide whether to type `/model <target>` right now. PURE.

    Returns `{"act": bool, "reason": str, "command": str | None}` — `reason` is always one of
    the SKIP_* constants (or `"switch"`), so the caller never has to infer why nothing
    happened. `verdict` is `token_burn.model_fallback_verdict`'s output (already
    freshness- and headroom-gated); `current_model` is the pane's badge via
    `terminal_trigger.parse_pane_model`.

    Ordering is deliberate: the cooldown is checked LAST, so a session that is already off the
    exhausted model reports that fact rather than a cooldown that is irrelevant to it.
    """
    if not is_enabled:
        return {"act": False, "reason": SKIP_DISABLED, "command": None}
    if not verdict:
        return {"act": False, "reason": SKIP_NO_VERDICT, "command": None}

    spent = terminal_trigger.model_family(str(verdict.get("model", "")))
    target_family = terminal_trigger.model_family(target)
    if target_family == spent:
        # Switching to the model that is already exhausted accomplishes nothing and burns a
        # cooldown; a caller with a smarter target list should pick another before asking.
        return {"act": False, "reason": SKIP_TARGET_EXHAUSTED, "command": None}
    if current_model is None:
        # The pane carries no model badge. UNKNOWN is not "probably still on the spent model":
        # typing a switch blind could land on a session that already moved, and the whole
        # module's discipline is that unproven state does not actuate.
        return {"act": False, "reason": SKIP_UNKNOWN_MODEL, "command": None}
    if terminal_trigger.model_family(current_model) != spent:
        # Already off it — by an earlier switch, or because the user did it by hand. This is
        # the single-session form of the candidate list draining itself.
        return {"act": False, "reason": SKIP_ALREADY_OFF, "command": None}
    if last_switch_ts and (now - last_switch_ts) < interval_s:
        return {"act": False, "reason": SKIP_COOLDOWN, "command": None}
    return {"act": True, "reason": "switch", "command": f"/model {target}"}
