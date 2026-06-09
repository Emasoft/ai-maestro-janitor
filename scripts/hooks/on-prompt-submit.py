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


def _is_cron_marker(prompt: str) -> bool:
    """True iff the prompt is a janitor cron/heartbeat injection, not user input.

    The discriminator is the leading `[janitor-…]` marker (the only thing that
    distinguishes a cron-injected prompt from genuine typing). Leading whitespace
    is tolerated. Matching the `[janitor-` prefix covers every current and future
    directive (`-heartbeat`, `-resume`, `-renew`, `-reload`, …) without an
    enumerated list that could drift out of date.
    """
    return prompt.lstrip().startswith("[janitor-")


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
    return 0


if __name__ == "__main__":
    # Bare main() so the module is safely importable (no module-scope sys.exit);
    # the hook always exits 0 — it never blocks the prompt.
    main()
