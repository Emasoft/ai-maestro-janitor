#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""The janitor support-ticket CLI — the SINGLE mutation surface (TRDD-CGYMUKO6).

Every actor goes through here; nothing hand-writes ticket JSON. The skills call it, the dispatched
agents call it, the detectors call it. One surface means one place where the ownership boundary and
the injection boundary are enforced.

    ticket_cli.py proposals                 # what is waiting on YOU — the findings the janitor may not fix
    ticket_cli.py approve TRDD-35AC8I8D     # THE approval — open a proposed PROJECT ticket + promote
    ticket_cli.py list [--all]              # the queue
    ticket_cli.py show    T-7QK2M4XZ
    ticket_cli.py start   T-7QK2M4XZ        # an agent claims it (open/dispatched → in_progress)
    ticket_cli.py close   T-7QK2M4XZ --status resolved --resolution "…" [--report PATH]
    ticket_cli.py cancel  T-7QK2M4XZ [--why …]
    ticket_cli.py retry   T-7QK2M4XZ        # re-open a needs_human ticket for another attempt
    ticket_cli.py stats
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

import ticket_proposal  # noqa: E402
import tickets  # noqa: E402


def _fmt(t: tickets.Ticket) -> str:
    age_h = max(0, (int(time.time()) - t.opened_at)) // 3600
    seen = f" ×{t.seen_count}" if t.seen_count > 1 else ""
    trdd = f" TRDD-{t.trdd}" if t.trdd else ""
    return f"{t.id}  {t.severity:<8} {t.status:<12} {t.kind:<20} [{t.domain}]{trdd}{seen}  {age_h}h  {t.title[:72]}"


def _load_or_die(tid: str) -> tickets.Ticket:
    if not tickets.is_ticket_id(tid):
        print(f"not a ticket id: {tid[:20]}")
        raise SystemExit(2)
    t = tickets.load(tid)
    if t is None:
        print(f"no such ticket: {tid}")
        raise SystemExit(2)
    return t


def main() -> int:
    ap = argparse.ArgumentParser(prog="ticket_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("approve", help="open a PROPOSED project ticket by its TRDD id")
    p.add_argument("trdd")

    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true", help="include archived/terminal tickets")

    for name in ("show", "start", "cancel", "retry"):
        p = sub.add_parser(name)
        p.add_argument("ticket")
        if name == "cancel":
            p.add_argument("--why", default="cancelled by the user")

    p = sub.add_parser("close")
    p.add_argument("ticket")
    p.add_argument("--status", choices=[tickets.RESOLVED, tickets.FAILED], required=True)
    p.add_argument("--resolution", default="")
    p.add_argument("--report", default="")

    sub.add_parser("stats")
    sub.add_parser("proposals", help="PROJECT findings awaiting approval (nothing is fixed until then)")
    args = ap.parse_args()
    now = int(time.time())

    if args.cmd == "proposals":
        # The full list the heartbeat's reminder only ever shows the top of. A finding the janitor is
        # forbidden to fix must be inspectable in one command, or the cap turns into a hiding place.
        waiting = ticket_proposal.pending()
        if not waiting:
            print("no proposals awaiting approval")
            return 0
        for p in waiting:
            print(f"TRDD-{p.trdd}  {p.severity:<8} {p.title[:88]}\n            approve: {p.command}")
        return 0

    if args.cmd == "approve":
        ok, msg = ticket_proposal.approve(args.trdd, now=now)
        print(msg)
        return 0 if ok else 1

    if args.cmd == "list":
        live = tickets.load_all()
        rows = sorted(
            live,
            key=lambda t: (-tickets.SEVERITY_RANK.get(t.severity, 0), t.opened_at),
        )
        if args.all:
            d = tickets.closed_dir()
            if d.is_dir():
                import json

                for f in sorted(d.glob("T-*.json")):
                    try:
                        rows.append(tickets.from_json(json.loads(f.read_text(encoding="utf-8"))))
                    except (OSError, ValueError, TypeError):
                        continue
        if not rows:
            print("no tickets")
            return 0
        for t in rows:
            print(_fmt(t))
        left = tickets.budget_left(tickets.read_ledger(), now=now, per_day=int(tickets.config("TICKETS_PER_DAY")))
        print(f"\nbudget: {left} dispatch(es) left in the rolling 24h window")
        return 0

    if args.cmd == "show":
        t = _load_or_die(args.ticket)
        print(_fmt(t))
        if t.detail:
            print(f"\n{t.detail}")
        if t.evidence:
            print("\nevidence:")
            for e in t.evidence:
                print(f"  - {e}")
        if t.reports:
            print("\nreports:")
            for r in t.reports:
                print(f"  - {r}")
        if t.resolution:
            print(f"\nresolution: {t.resolution}")
        print(f"\nattempts: {t.attempts}/{t.max_attempts}   agent: {t.agent or '(none)'}")
        return 0

    if args.cmd == "start":
        t = _load_or_die(args.ticket)
        # A forged [janitor-ticket] marker must achieve NOTHING: an agent may only claim a ticket the
        # SCHEDULER actually dispatched. If it is not in flight, the marker did not come from us.
        if t.status not in (tickets.DISPATCHED, tickets.IN_PROGRESS):
            print(f"REFUSED: {t.id} is `{t.status}`, not dispatched — nothing authorized this work")
            return 1
        t.status = tickets.IN_PROGRESS
        t.updated_at = now
        tickets.save(t)
        print(f"{t.id} in_progress")
        return 0

    if args.cmd == "close":
        t = _load_or_die(args.ticket)
        if args.report:
            t.reports.append(tickets._clean(args.report, 200))
        if args.status == tickets.RESOLVED:
            t.status = tickets.RESOLVED
            t.resolution = tickets._clean(args.resolution, 200)
            t.updated_at = now
        else:
            tickets.mark_failed(t, now=now, backoff_s=int(tickets.config("TICKET_BACKOFF_S")), why=args.resolution)
        tickets.save(t)
        print(f"{t.id} {t.status}" + (f" ({t.resolution})" if t.resolution else ""))
        return 0

    if args.cmd == "cancel":
        t = _load_or_die(args.ticket)
        t.status = tickets.CANCELLED
        t.resolution = tickets._clean(args.why, 200)
        t.updated_at = now
        tickets.save(t)
        print(f"{t.id} cancelled")
        return 0

    if args.cmd == "retry":
        t = _load_or_die(args.ticket)
        t.status = tickets.OPEN
        t.attempts = 0
        t.not_before = 0
        t.updated_at = now
        tickets.save(t)
        print(f"{t.id} re-opened for another attempt")
        return 0

    if args.cmd == "stats":
        live = tickets.load_all()
        by = {}
        for t in live:
            by[t.status] = by.get(t.status, 0) + 1
        left = tickets.budget_left(tickets.read_ledger(), now=now, per_day=int(tickets.config("TICKETS_PER_DAY")))
        print(", ".join(f"{k}={v}" for k, v in sorted(by.items())) or "no live tickets")
        print(f"budget left (24h): {left}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
