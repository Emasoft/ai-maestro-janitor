#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing CLI for /janitor-findings (TRDD-FENWWB4E — ARCHITECTURE.md §4, ratified rev 3).

The on-demand BROWSER over the per-project findings ledger — the deep-read side of the
"concise at session start, pulled on demand" split: `on-session-start` injects a capped
index of unread lines; anything deeper is read HERE, only when asked.

Verbs:
  list [N]   render the newest N ledger entries (default 20), unread count first.
  show REF   resolve a finding's BODY: `T-…` → the ticket (open or closed);
             `TRDD-…`/bare id8 → the proposal/task TRDD file, printed verbatim.
  ack        advance the cursor — mark everything currently in the ledger as read.

Read-only except `ack` (which writes only the cursor file). Own-project only: the CLI
reads the CURRENT project's ledger (state.state_dir()) — machine-wide views stay behind
the explicit human commands the isolation invariant names (§3).
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

import findings_ledger as fl  # noqa: E402
import ticket_proposal  # noqa: E402
import tickets  # noqa: E402
import trdd_common  # noqa: E402


def _cmd_list(limit: int) -> int:
    entries, _size = fl._read_raw(None)  # noqa: SLF001 -- same package; the CLI IS the reader surface
    if not entries:
        print("findings ledger: empty — nothing recorded for this project.")
        return 0
    _lines, unread = fl.unread_entries(None, cap=len(entries), budget_bytes=1 << 20)
    print(f"findings ledger: {len(entries)} recorded, {unread} unread (`ack` marks all read)")
    for e in reversed(entries[-limit:]):  # newest first
        print(fl.render_line(e))
    if len(entries) > limit:
        print(f"…{len(entries) - limit} older — `/janitor-findings list {len(entries)}` for all")
    return 0


def _show_trdd(uid: str) -> int:
    project_dir = None  # current project — trdd_common resolves both scopes from it
    for folder in ("proposals", "tasks", "archived", "refused"):
        for _scope, path in trdd_common.trdd_files(folder, project_dir):
            if trdd_common.extract_uid(path.name) == uid:
                print(f"--- {path} ---")
                print(path.read_text(encoding="utf-8"))
                return 0
    print(f"no TRDD found for id {uid} in either design root.")
    return 1


def _cmd_show(ref: str) -> int:
    ref = ref.strip()
    if tickets.is_ticket_id(ref):
        t = tickets.load(ref)
        if t is None:
            print(f"no ticket found for {ref} (open or closed).")
            return 1
        print(f"--- ticket {t.id} [{t.status}] severity={t.severity} kind={t.kind} ---")
        print(t.title)
        print()
        print(t.detail)
        if t.evidence:
            print()
            print("evidence:")
            for ev in t.evidence:
                print(f"  - {ev}")
        return 0
    uid = ticket_proposal.parse_trdd_ref(ref)
    if uid is None:
        print(f"unrecognized ref `{ref}` — expected T-XXXXXXXX or TRDD-XXXXXXXX.")
        return 2
    return _show_trdd(uid)


def main() -> int:
    args = sys.argv[1:]
    verb = args[0] if args else "list"
    if verb == "list":
        limit = 20
        if len(args) > 1 and args[1].isdigit():
            limit = max(1, int(args[1]))
        return _cmd_list(limit)
    if verb == "show":
        if len(args) < 2:
            print("usage: findings_cli.py show <T-XXXXXXXX | TRDD-XXXXXXXX>")
            return 2
        return _cmd_show(args[1])
    if verb == "ack":
        fl.advance_cursor(None)
        print("findings ledger: cursor advanced — everything currently recorded is marked read.")
        return 0
    print("usage: findings_cli.py [list [N] | show <ref> | ack]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
