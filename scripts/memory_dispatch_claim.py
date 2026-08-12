#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Claim one memory-maintenance dispatch — the CONSUMED flag the system never had (janitor#242).

`memory-maintenance` emits a bare `[janitor-memory-<chore>]` marker and records the
assignment on disk. The agent then has to find out WHICH assignment is its own, and until
now it was told to read `memory-maint-pending.json` — a single fixed slot the NEXT dispatch
overwrites unconditionally. Measured on a peer host: a `consolidate` dispatch overwrote an
in-flight `repair`'s authority 367 s later on the same root, while `pending-agents.json`
still listed the repair agent as running. The agent was reading a file that had changed
underneath it, and nothing anywhere said so.

`d5df92a7` fixed the WRITE side — every dispatch also gets its own immutable
`memory-maint-pending-<dispatch_id>.json`. But nothing ever NAMED that file to anybody: the
marker is bare (it must be — the cron clause matches it exactly) and the protocol rule still
pointed at the legacy slot. So the durable record existed and had no reader. This script is
the reader.

THE CLAIM IS THE POINT, not the lookup. `os.rename` is atomic on POSIX and on Windows for
this shape, so of two agents racing for the same dispatch exactly one wins and the loser
gets `FileNotFoundError` and moves to the next candidate. That gives three properties the
old fixed slot could not have:

  * an assignment is handed to exactly ONE agent, ever;
  * an agent's assignment cannot change after it is handed over (its file is renamed out of
    the candidate pool and never rewritten);
  * a dispatch that was never picked up stays visibly unclaimed, which is what makes
    `orphaned-memory-maint`'s question answerable at all.

FAIL CLOSED, DELIBERATELY. With no claimable dispatch this exits 2 and prints nothing on
stdout. It must never fall back to "whichever chore looks due" — that is janitor#150, where
a guessing agent ran a pass nobody scheduled, on a scope nobody chose.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import state  # noqa: E402

PENDING_PREFIX = "memory-maint-pending-"
CLAIMED_PREFIX = "memory-maint-claimed-"
LEGACY_NAME = "memory-maint-pending.json"


def _dispatch_epoch(path: Path) -> tuple[int, str]:
    """Sort key: the epoch baked into `<epoch>-<hex>`, name as tie-break.

    Parsed rather than stat'd because mtime is not stable across a copy, a restore, or a
    filesystem that rounds it — and picking the wrong "oldest" hands an agent a newer
    assignment while the older one starves.
    """
    stem = path.name[len(PENDING_PREFIX):-len(".json")]
    head = stem.split("-", 1)[0]
    return (int(head) if head.isdigit() else 0, path.name)


def candidates(state_dir: Path) -> list[Path]:
    """Unclaimed per-dispatch files, oldest first. A claimed one is renamed away, so its
    absence from this list is the claim — there is no flag to read and get wrong."""
    try:
        return sorted(state_dir.glob(f"{PENDING_PREFIX}*.json"), key=_dispatch_epoch)
    except OSError:
        return []


def claim_one(state_dir: Path) -> dict | None:
    """Atomically claim the oldest unclaimed dispatch and return its payload, else None.

    Reads BEFORE renaming: a rename we won is unrecoverable for anyone else, so if the read
    then failed the assignment would be lost with nothing left to point at it.
    """
    for path in candidates(state_dir):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # unreadable: leave it for the orphan detector to report, don't consume it
        if not isinstance(payload, dict):
            continue
        target = state_dir / f"{CLAIMED_PREFIX}{path.name[len(PENDING_PREFIX):]}"
        try:
            os.rename(path, target)
        except OSError:
            continue  # lost the race (or it vanished) — try the next candidate
        payload["claimed_path"] = str(target)
        return payload
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state-dir", default="", help="override the project's .janitor/state")
    ap.add_argument("--peek", action="store_true",
                    help="report the next claimable dispatch WITHOUT claiming it")
    args = ap.parse_args()

    state_dir = Path(args.state_dir) if args.state_dir else state.state_dir()
    if args.peek:
        nxt = candidates(state_dir)
        if not nxt:
            print("no claimable dispatch", file=sys.stderr)
            return 2
        print(nxt[0])
        return 0

    payload = claim_one(state_dir)
    if payload is None:
        # The legacy single slot is NOT a fallback. It is the very file whose clobbering
        # this exists to fix, so consuming it here would reintroduce the bug on exactly the
        # path where two dispatches overlap — the only path where it matters.
        legacy = state_dir / LEGACY_NAME
        hint = " (a legacy pending slot exists but is not claimable — it is not per-dispatch)" \
            if legacy.is_file() else ""
        print(f"no claimable memory-maintenance dispatch in {state_dir}{hint}", file=sys.stderr)
        return 2
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
