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

It is also the janitor's ONE reminder channel for PROJECT findings awaiting approval. Those cannot be
fixed until a human (or the main Claude) approves them, so they must not be announced once and
forgotten — the one line that WAS printed may well have landed inside a compaction. Reminding from
each producing detector would be wrong twice over: a content-hashing detector goes silent exactly when
nothing changes (the case where the standing finding matters most), and a per-fire detector would nag
288 times a day. So the reminder lives here — driven by the board, capped, and rate-limited.

Emits nothing at all when there is no work, which is the common case (the zero-output contract).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import global_state as gs  # noqa: E402
import issue_catalog  # noqa: E402
import state  # noqa: E402
import ticket_proposal  # noqa: E402
import tickets  # noqa: E402

_REMIND_EVERY_S = 3600  # a standing finding is re-surfaced hourly, not every fire
_REMIND_CAP = 3  # …and never more than a handful of lines; the rest are counted, not listed


def _proposal_reminder(now: int) -> list[str]:
    """The standing "these are waiting on YOU" lines, or [] when it is not time (or nothing waits)."""
    # First, drop the proposals nobody can ever act on. A PROJECT finding is withdrawn only by the
    # detector that raises its code, so a code that stops being raised strands every proposal already
    # on the board: nothing re-raises them, nothing withdraws them, and this reminder nags about work
    # that has no producer left. Doing it HERE — the one channel that surfaces standing proposals,
    # driven by the board rather than by any detector — is what makes it independent of whichever
    # detector was retired. See issue_catalog.RETIRED_CODES.
    for code, uid in issue_catalog.reconcile_retired():
        state.log_line("ticket-dispatch", f"withdrew TRDD-{uid} — {code} is retired")

    waiting = ticket_proposal.pending()
    stamp = state.state_dir() / "ticket-remind-at.ts"
    if not waiting:
        # Nothing pending → drop the stamp, so the NEXT finding is announced immediately rather than
        # being swallowed by a cooldown left over from a batch that has since been approved.
        stamp.unlink(missing_ok=True)
        return []
    if now - state.read_int_state(stamp, 0) < _REMIND_EVERY_S:
        return []
    state.atomic_write(stamp, str(now))

    out = [
        f"[ticket] {len(waiting)} janitor proposal(s) await YOUR approval — nothing is fixed until one is approved:"
    ]
    for p in waiting[:_REMIND_CAP]:
        out.append(f"  ({p.severity}) {p.title[:100]} → {p.command}")
    if len(waiting) > _REMIND_CAP:
        out.append(f"  …and {len(waiting) - _REMIND_CAP} more → /janitor-support-tickets proposals")
    return out


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
    #
    # The lock guards DISPATCH, not the reminder: a PROJECT finding produces a PROPOSAL and no ticket
    # at all, so an empty queue is exactly the state in which the reminder matters. Returning early on
    # `not live` would make the janitor go quiet about every finding it is forbidden to fix itself.
    due: list[tickets.Ticket] = []
    with gs.ticket_dispatch_lock() as held:
        live = tickets.load_all() if held else []
        if live:
            # Reclaim tickets whose agent DIED (the weekly rate cap did exactly this to a background
            # agent on 2026-07-14). Without this they sit in `dispatched` forever and the queue quietly
            # stops working — and nothing says so.
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

    lines.extend(_proposal_reminder(now))

    if lines:
        print("\n".join(lines), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
