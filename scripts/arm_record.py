#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Everything /janitor-arm must do AFTER the cron exists (TRDD-DLI76AUC).

The counterpart to `arm_prepare.py`. It records what was actually armed:

  - `heartbeat-armed-at.ts`   — when (the renewal clock reads this)
  - `armed-cadence.cron`      — WHICH cadence is live, so the dispatcher's cadence phase can tell
                                whether the armed tier already matches the tier it wants and stop
                                re-emitting `[janitor-renew]` at a cron that is already correct
  - `heartbeat-cron-id.txt`   — the cron's id, so the NEXT arm can CronDelete it directly instead
                                of spending a CronList round-trip to find it (the call this whole
                                TRDD exists to remove)
  - clears `heartbeat-renew-seen.txt` — the renew-marker dedupe, stale the moment we re-arm

Storing the id is what makes the next arm cheap, and it is why `arm_prepare` CONSUMES the id
rather than merely reading it: if this script never runs (the turn died), no id is stored, and
the next arm sweeps with a CronList rather than trusting a stale one and leaking a second live
heartbeat. See the crash-safety note in `arm_prepare.py`.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

import state  # noqa: E402

# A cron id comes back from CronCreate and goes straight onto a CronDelete argument on the next
# arm. Validate its SHAPE before it is ever stored, so a malformed value fails here — loudly, at
# the moment it is produced — rather than silently becoming a delete that never matches, which
# would leak a heartbeat and double the fire cost.
CRON_ID_RE = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z")


def valid_cron_id(value: str) -> bool:
    return bool(CRON_ID_RE.match(value))


def record(state_dir: Path, *, cron: str, cron_id: str, now: int) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    state.atomic_write(state_dir / "heartbeat-armed-at.ts", str(now))
    state.atomic_write(state_dir / "armed-cadence.cron", cron)
    state.atomic_write(state_dir / "heartbeat-cron-id.txt", cron_id)
    try:
        (state_dir / "heartbeat-renew-seen.txt").unlink()
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(prog="arm_record")
    ap.add_argument("--cron", required=True, help="the cadence that was armed")
    ap.add_argument("--id", required=True, dest="cron_id", help="the id CronCreate returned")
    args = ap.parse_args()

    cron = args.cron.strip()
    cron_id = args.cron_id.strip()
    if not cron:
        print("refused: empty cron")
        return 2
    if not valid_cron_id(cron_id):
        print(f"refused: not a cron id: {cron_id[:32]!r}")
        return 2

    record(state.state_dir(), cron=cron, cron_id=cron_id, now=int(time.time()))
    print(f"armed cron={cron} id={cron_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
