#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PreToolUse hook — warn the agent when ITS OWN token consumption is high.

Phase 2 of the heartbeat token meter (TRDD-a4e41e89), per the USER re-scope: the
Stop-hook meter MEASURES per-turn cost; this hook turns that measurement into a
REAL-TIME self-awareness warning so an over-consuming agent learns, mid-turn,
that it is burning too much — and can choose to be terse, wrap up the step, or
compact. The two purposes the USER named: control janitor/agent cost AND inform
the instance that IT is consuming too much.

Mirrors the context-watchdog (`pre-tool-context-usage`): it emits advisory
`hookSpecificOutput.additionalContext` with NO `permissionDecision`, so the
tool's normal permission flow is completely untouched — purely informational,
never auto-approves or blocks.

CONFIG (everything configurable):
  * CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_ENABLED — opt-in (default OFF). Firing on
    every tool call + reading the transcript tail is intrusive, so installs that
    don't want it pay nothing.
  * CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_OUTPUT — per-turn output-token budget
    (default 10000); at/above it the nudge fires. Set 0 to disable the turn check.

DATA: reuses `token_meter.tail_turn_usage(transcript_path)` — the SAME tested
turn-boundary parser the Stop-hook meter uses — to sum the CURRENT (in-progress)
turn's output tokens so far. No new accounting logic; one source of truth.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import token_meter  # noqa: E402

_DEFAULT_TURN_OUTPUT = 10_000


def _truthy(raw: str | None) -> bool:
    """Empty/unset → False; `false`/`0`/`no`/`off` → False; anything else → True."""
    if not raw:
        return False
    return raw.strip().lower() not in ("false", "0", "no", "off", "")


def _coerce_int(raw: str | None, default: int) -> int:
    """Best-effort non-negative int; junk → default (a typo must never crash a hook)."""
    if not raw:
        return default
    try:
        val = int(raw.strip())
    except (ValueError, AttributeError):
        return default
    return val if val >= 0 else default


def main() -> int:
    # OPT-IN — zero cost unless explicitly enabled (reading the transcript tail on
    # every tool call is intrusive; the user opts in when they want the guardrail).
    if not _truthy(os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_ENABLED")):
        return 0

    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return 0
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        return 0

    transcript = str(payload.get("transcript_path", "") or "")
    if not transcript:
        return 0

    usage = token_meter.tail_turn_usage(transcript)
    if usage is None:
        # Turn boundary not in the tail window (or transcript unreadable) — stay
        # silent rather than guess. A turn long enough to push the boundary past
        # the 512KB tail is rare; correctness-by-omission beats a wrong number.
        return 0

    budget = _coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_OUTPUT"),
        _DEFAULT_TURN_OUTPUT,
    )
    if budget <= 0 or usage.output_tokens < budget:
        return 0

    line = (
        f"⚠ Token budget: this turn has already produced ~{usage.output_tokens} "
        f"output tokens (at/above the {budget}-token budget) across "
        f"{usage.assistant_messages} assistant message(s) / {usage.tool_calls} "
        f"tool call(s). Consider being more concise, wrapping up the current step, "
        f"or compacting — sustained high output burns subscription usage fastest."
    )
    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": line,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    # Bare main() — side effects inside it so the module is import-safe (no
    # module-scope sys.exit), matching the other janitor hooks.
    main()
