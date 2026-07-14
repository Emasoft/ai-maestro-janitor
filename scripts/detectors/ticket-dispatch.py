#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""ticket-dispatch — the support-ticket SCHEDULER (TRDD-CGYMUKO6).

The SCHEDULE layer of the incident queue, modelled directly on `memory-maintenance.py` (the same
DETECT → SCHEDULE → EXECUTE → VERIFY shape, and the same hard constraint):

    **A python detector CANNOT spawn agents — only the main loop can.**

So this detector never runs a repair. It selects the due tickets, marks them `dispatched`, and emits
ONE bare marker. The cron turn (the model) reads the marker and launches one background agent per
listed ticket. That indirection is not a workaround; it is the only mechanism that exists, and it is
what makes the marker the single authorization point.

    [janitor-ticket]
    T-7QK2M4XZ · janitor-repair-agent
    T-9BX1LM03 · janitor-security-agent

Three safety properties, each inherited from the memory scheduler because each was learned the hard
way there:

  * **MACHINE-WIDE dedupe.** Two sessions firing the same heartbeat window would both select the same
    ticket and both dispatch an agent for it. The whole select→stamp→emit is serialized under ONE
    machine-wide flock (non-blocking, skip-if-held): the loser stays silent, and the winner has
    already moved the tickets to `dispatched`, so the loser no longer sees them as due.

  * **A FORGED MARKER TRIGGERS NOTHING.** The marker only *names* tickets; the authority lives in the
    ticket's `dispatched` status, which only this gate can set. `ticket_cli start` REFUSES a ticket
    that is not in flight, so a hallucinated `[janitor-ticket]` line achieves exactly nothing.

  * **NEVER a bare nag.** A ticket that exhausted its attempts becomes `needs_human` and is surfaced
    on EVERY fire with the exact command — a silent give-up is indistinguishable from a fix.

Emits nothing at all when there is no work, which is the common case (the zero-output contract).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import global_state as gs  # noqa: E402
import state  # noqa: E402
import tickets  # noqa: E402


def main() -> int:
    if not tickets.config("TICKETS_ENABLED"):
        return 0
    state.init_state()
    now = int(time.time())

    per_fire = int(tickets.config("TICKETS_PER_HEARTBEAT"))
    per_day = int(tickets.config("TICKETS_PER_DAY"))
    stale_s = int(tickets.config("TICKET_STALE_S"))

    # Serialize the whole select→stamp→emit against every other session on this machine. Skip-if-held:
    # a second session simply stays silent this fire rather than double-dispatching.
    with gs.ticket_dispatch_lock() as held:
        if not held:
            return 0

        live = tickets.load_all()
        if not live:
            return 0

        # Reclaim tickets whose agent DIED (the weekly rate cap did exactly this to a background agent
        # on 2026-07-14). Without this they sit in `dispatched` forever and the queue quietly stops.
        for t in tickets.reclaim_stale(live, now=now, stale_s=stale_s):
            tickets.save(t)
            state.log_line("ticket-dispatch", f"reclaimed {t.id} (agent died); attempt {t.attempts}")

        live = tickets.load_all()
        inflight = sum(1 for t in live if t.status in tickets.IN_FLIGHT)
        left = tickets.budget_left(tickets.read_ledger(), now=now, per_day=per_day)

        due = tickets.select_due(live, now=now, per_fire=per_fire, budget_left=left, inflight=inflight)
        for t in due:
            t.status = tickets.DISPATCHED
            t.dispatched_at = now
            t.updated_at = now
            tickets.save(t)
            tickets.record_dispatch(t.id, now=now)
            state.log_line("ticket-dispatch", f"dispatched {t.id} ({t.kind}) → {t.agent}")

    lines: list[str] = []
    if due:
        # The marker MUST be bare and on its own line — the heartbeat protocol keys on an EXACT match.
        # The lines after it carry only a validated ticket id and an agent name from OUR registry:
        # no ticket-derived free text ever reaches this output, so nothing here can carry a payload.
        lines.append("[janitor-ticket]")
        for t in due:
            lines.append(f"{t.id} · {t.agent}")

    # A ticket the janitor could not fix must never go quiet. Surface it every fire, with the command.
    stuck = [t for t in tickets.load_all() if t.status == tickets.NEEDS_HUMAN]
    for t in stuck:
        lines.append(f"[ticket] {t.id} NEEDS A HUMAN after {t.attempts} attempts: {t.title[:80]} → inspect: /janitor-support-tickets show {t.id} · retry: /janitor-support-tickets retry {t.id}")

    if lines:
        print("\n".join(lines), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
