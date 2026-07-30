#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""UserPromptSubmit hook — host-level user-presence breadcrumb (TRDD-fb4850b5).

Fires when the user types a prompt. On a GENUINE user prompt it writes the
cross-plugin breadcrumb the MANAGER's `amama-presence-tracker` reads as a
server-unreachable fallback:

    ~/.aimaestro/state/user-presence.json
    {"last_user_input_epoch": <int>, "source": "janitor", "written_at_epoch": <int>}

THE LOAD-BEARING TRAP: the janitor's own cron heartbeat arrives on the IDENTICAL
UserPromptSubmit channel as real typing — its prompt text starts with a
`[janitor-…]` marker (`[janitor-heartbeat]`, `[janitor-resume]`, `[janitor-renew]`,
`[janitor-reload]`, …). Those are NOT user presence; bumping on them would report
the user "present" every ~5 min forever. So any `[janitor-…]`-prefixed prompt is
skipped WITHOUT touching the breadcrumb.

The hook never blocks and never emits agent-context output — it is invisible to
the model. It exits 0 on every path; any error degrades to a no-op so a
breadcrumb problem can never abort the user's turn.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

# Loaded via importlib so CPV's PEP 723 static check doesn't misclassify the
# project-local `state` module as a third-party dependency (it has no PyPI
# counterpart). Runtime semantics are identical to `import state`.
state = importlib.import_module("state")


# How many leading lines may precede the marker before we stop looking. Small on purpose:
# enough to clear a prepended context block, far short of scanning a long human prompt.
_CRON_MARKER_SCAN_LINES = 5


def _is_cron_marker(prompt: str) -> bool:
    """True iff the prompt is a janitor cron/heartbeat injection, not user input.

    The discriminator is a `[janitor-…]` marker (`-heartbeat`, `-resume`, `-renew`,
    `-reload`, …) at the START OF A LINE within the first few lines — not, as before, at
    offset 0 of the whole prompt.

    WHY THE WIDENING (issue #113). The offset-0 form assumed the janitor's cron text is the
    FIRST thing in `payload["prompt"]`. On a host where something prepends to that string —
    another plugin's UserPromptSubmit hook, or the ai-maestro CLI wrapping a delivered
    prompt — the marker moves off offset 0, `startswith` misses, and the fire is recorded as
    GENUINE USER PRESENCE. Measured consequence there: `last_user_input_epoch` advancing on
    cron-only windows, so `recent_activity` read True forever on an unattended session and
    the TTL-aware cadence could never settle at SLOW — it oscillated SLOW↔MID, five
    `[janitor-renew]` re-arms in 2.5 h, each one a full turn. The cadence feature spent turns
    instead of saving them.

    I could not reproduce it on a standalone host, so the exact prepending agent is unproven.
    That is precisely why the fix is mechanism-independent: the chain is airtight without it
    — only `bump_user_presence` writes the observed shape (both epochs equal, `source:
    janitor`), and only this filter stands between a cron fire and that call, so the filter
    failed however the text was mutated. Fixing the CAUSE would require knowing whose text it
    is; fixing the DISCRIMINATOR does not.

    Trade-off accepted: a human prompt that begins one of its first few lines with
    `[janitor-` is read as a cron fire and does not stamp presence. That is one turn of lost
    recency, self-inflicted, and the offset-0 version had the same hazard at line 0.
    """
    for line in prompt.splitlines()[:_CRON_MARKER_SCAN_LINES]:
        if line.strip().startswith("[janitor-"):
            return True
    return False


def main() -> int:
    # Read + parse stdin defensively; any failure → no-op (never crash the turn).
    try:
        raw = sys.stdin.read()
    except Exception:  # pragma: no cover - stdin closed
        return 0
    if not raw or not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return 0

    # The load-bearing filter: a cron `[janitor-…]` prompt is NOT user presence.
    if _is_cron_marker(prompt):
        return 0

    # Genuine user input — stamp both epochs. bump_user_presence is itself
    # best-effort (swallows OSError), but guard the whole call so an unexpected
    # error path still degrades to a silent no-op.
    try:
        state.bump_user_presence()
    except Exception:  # noqa: BLE001 - a breadcrumb write must never abort the turn
        pass

    # Record which janitor verbs the user EXPLICITLY asked for (TRDD-RDFWQIFA, TRDD-USRPRES1).
    #
    # This hook is the ONLY surface that sees the user's raw keystrokes — everything downstream is
    # the model acting — so it is the only place a token meaning "a HUMAN authorized this" can
    # honestly be minted. Two consumers depend on it: `disarmed.flag` (which tells the fleet guardian
    # a human stopped the heartbeat, and which an agent could previously forge) and the self-trigger's
    # presence gate (which must never type into a pane whose human is mid-sentence unless they asked).
    #
    # Deliberately AFTER the cron-marker filter above: a `[janitor-…]` prompt is the machine talking
    # to itself, and it must never be able to authorize anything.
    try:
        user_intent = importlib.import_module("user_intent")
        user_intent.record_intent_from_prompt(prompt)
    except Exception:  # noqa: BLE001 - intent recording must never abort the turn
        pass
    return 0


if __name__ == "__main__":
    # Bare main() so the module is safely importable (no module-scope sys.exit);
    # the hook always exits 0 — it never blocks the prompt.
    main()
