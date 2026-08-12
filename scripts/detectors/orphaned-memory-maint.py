#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""orphaned-memory-maint — notice a memory-maintenance pass that was scheduled and
never ran (janitor#238, TRDD-2112XCKO).

The scheduler (`memory-maintenance.py`) stamps a pending dispatch and prints a bare
`[janitor-memory-<chore>]` marker for the cron turn to hand to a background agent. When
that hand-off fails — a partially-installed plugin registry (#232's shape: skills
present, zero `ai-maestro-janitor:*` agents enumerable), a session that dies between
marker and spawn — the pending record just sits there. Nothing else notices: a dropped
pass and a completed one look identical from the janitor's side.

Confirmed live on #238 (four consecutive drops in one session, three of them LOCAL):
the broken-registry session's PYTHON detectors ran fine throughout — the agent-spawn
step that failed is entirely downstream of this script — so THIS check is self-
contained by design: it reads only this project's own
`.janitor/state/memory-maint-pending.json`, no fleet scan required. See
`scripts/lib/orphaned_memory_maint.py` for the full mechanism (why age alone is not
enough, and why LOCAL gets a tighter bound than USER/PROJECT).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import findings_ledger  # noqa: E402
import memory_settings  # noqa: E402
import orphaned_memory_maint as omm  # noqa: E402
import state  # noqa: E402


def main() -> int:
    state.init_state()
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_ORPHANED_MEMORY_MAINT_ENABLED", True):
        return 0

    default_factor = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_ORPHANED_MEMORY_MAINT_FACTOR"),
        omm.DEFAULT_FACTOR,
        detector_name="orphaned-memory-maint",
        var_name="ORPHANED_MEMORY_MAINT_FACTOR",
    ) or omm.DEFAULT_FACTOR
    local_factor = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_ORPHANED_MEMORY_MAINT_LOCAL_FACTOR"),
        omm.LOCAL_FACTOR,
        detector_name="orphaned-memory-maint",
        var_name="ORPHANED_MEMORY_MAINT_LOCAL_FACTOR",
    ) or omm.LOCAL_FACTOR

    now = int(time.time())
    state_dir = state.state_dir()
    seen = state_dir / "orphaned-memory-maint-seen.txt"

    try:
        payload, malformed = omm.read_pending(state_dir)
    except Exception as exc:  # noqa: BLE001 - a read failure must never break the fire
        state.log_line("orphaned-memory-maint", f"read failed: {exc}")
        return 0

    if malformed:
        msg = (
            f"memory-maintenance pending state at {state_dir / omm.PENDING_NAME} "
            "exists but cannot be parsed — the scheduler's own record of what it last "
            "dispatched is unreadable, so a dropped pass here could never be told "
            "apart from a healthy one. Investigate/remove the file so the scheduler "
            "can re-stamp it cleanly."
        )
        line = dedupe.emit_once(seen, "malformed", f"[orphaned-memory-maint] {msg}")
        if line is not None:
            try:
                findings_ledger.record(
                    sev="HIGH", code="MEMPASS-MALFORMED", src="orphaned-memory-maint",
                    msg=msg, now=now,
                )
            except Exception as exc:  # noqa: BLE001
                state.log_line("orphaned-memory-maint", f"ledger write failed: {exc}")
            print(line, flush=True)
        return 0
    # The record parses again — forget the malformed dedupe so a future genuine
    # malformation re-alerts rather than staying suppressed forever.
    dedupe.emit_forget(seen, "malformed")

    if payload is None:
        return 0  # never dispatched — nothing to check, nothing wrong

    intervention = payload["intervention"]
    scope = payload["scope"]
    root = payload["root"]
    key = f"{intervention}|{scope}"

    try:
        cadence_s = memory_settings.interval_s_for(intervention)
    except ValueError:
        # An unknown intervention name — a scheduler/lib drift, not this project's fault.
        # Skip silently rather than guess a cadence for a chore that no longer exists.
        return 0

    last_run = memory_settings.read_last_run(intervention, scope, root)
    is_current = omm.pending_is_current(payload, last_run=last_run)
    age_s = omm.pending_age_s(payload, now=now)
    factor = omm.factor_for_scope(scope, default=default_factor, local=local_factor)
    orphaned = is_current and omm.is_orphaned(age_s, cadence_s, factor=factor)

    if not orphaned:
        # Healthy — either superseded by a newer dispatch (elsewhere) or simply not
        # stale yet. Clear any prior alert for this (intervention, scope) so a FUTURE
        # drop is reported fresh rather than suppressed by a stale dedupe entry.
        dedupe.emit_forget(seen, key)
        return 0

    msg = omm.format_finding(intervention, scope, age_s, cadence_s)
    line = dedupe.emit_once(seen, key, f"[orphaned-memory-maint] {msg}")
    if line is None:
        return 0  # already alerted for this exact (intervention, scope) drop

    try:
        findings_ledger.record(
            sev="HIGH", code="MEMPASS-ORPHANED", src="orphaned-memory-maint", msg=msg, now=now,
        )
    except Exception as exc:  # noqa: BLE001 - a ledger fault must never break the fire
        state.log_line("orphaned-memory-maint", f"ledger write failed: {exc}")

    state.log_line("orphaned-memory-maint", f"recorded MEMPASS-ORPHANED for {key} ({age_s}s)")
    print(line, flush=True)

    state.rotate_log_if_big("orphaned-memory-maint")
    return 0


if __name__ == "__main__":
    sys.exit(main())
