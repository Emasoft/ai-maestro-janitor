#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""claimed-chore-stale — alarm when the ai-maestro server CLAIMS a chore but stops running it.

THE CONDITION THIS EXISTS FOR (TRDD-6CRC9SQQ item 1). The claim handshake answers "who owns
this chore?" and nothing answers "is the owner doing it?". When a live server claims one of
`SERVER_ABSORBED_TASKS`, the janitor daemon yields it AND `daemon_watchdog` returns early for
exactly that chore — correctly, because a yielded chore's stamp goes stale by design on our
side. So a claimed-but-WEDGED chore is watched by no one, and it is strictly worse than an
unclaimed one: the fallback that would have covered it is suppressed precisely then.

Measured cost: janitor#221 — the server-absorbed OAuth rotator tick stopped COMPLETING for
3.7 days, wedged between two slot captures. Rotation was off, the owner rotated by hand, and
nothing on the janitor side said a word.

THE MIRROR of `global-chore-blackout`, which alarms on the chores the server did NOT claim.
Between the two, every machine-global chore has a watcher; neither alone is enough.

WHAT COUNTS AS EVIDENCE. The claim-holder's own completion stamps,
`~/.claude/janitor-control/<chore>.last-run.ts` — the files ai-maestro#111 asked the server to
write, read through `global_state.read_last_run` so all three control-plane eras are covered.
Verified present and fresh for all five claimed chores on the owner's host 2026-08-06, which
is what makes this a guard that can actually fire rather than one watching an empty set.

READ-ONLY and CHEAP: one liveness probe plus a file stat per claimed chore. No network, no
`gh`, no subprocess.

SURFACE-ONLY, deliberately. It does NOT un-yield a chore whose claim has gone dead. That
decision is still open on the card (it needs hysteresis, or a server restart blip flaps
ownership back and forth), and shipping the alarm without the actuation is the half that is
safe to ship alone.

SILENT unless ALL of these hold:
  * a live server is claiming chores (no claim ⇒ nothing delegated ⇒ nothing to watch), AND
  * at least one claimed chore is stale past 3x its own cadence (floored — see
    `claimed_chore_watch.DEFAULT_MIN_GRACE_S`) or has never been stamped at all.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import claimed_chore_watch as ccw  # noqa: E402
import dedupe  # noqa: E402
import global_state as gs  # noqa: E402
import harness_backend  # noqa: E402
import state  # noqa: E402

_NAME = "claimed-chore-stale"

# How many chores the drift line spells out before folding the rest into a count.
_NAMED_IN_LINE = 3


def _cadence_of(chore: str) -> int | None:
    """The chore's cadence in seconds, from the SSOT roster + its env override.

    `GLOBAL_CHORES` is the single roster `daemon.py` is test-asserted against name-for-name
    and default-for-default, so this can never describe a cadence the daemon does not use.
    An unknown chore returns None and `evaluate` skips it rather than guessing.
    """
    entry = harness_backend.GLOBAL_CHORES.get(chore)
    if entry is None:
        return None
    env_var, default_s = entry
    import os  # noqa: PLC0415 -- lazy; the hot path is a no-op on most hosts

    return state.coerce_int(os.environ.get(env_var), default_s)


def _completion_log(state_dir: Path) -> Path:
    return state_dir / "claimed-chore-completions.json"


def _record_completions(state_dir: Path, chores: list[str]) -> dict[str, int]:
    """Append each chore's CURRENT completion stamp to its history; return the measured
    period per chore.

    This is what makes the bound describe the EXECUTOR rather than our roster
    (janitor#225). We only ever store DISTINCT completion values, so a wedged chore adds
    nothing and its measured period stops growing — which is exactly the property that
    keeps self-calibration from masking the wedge it exists to catch.

    Bounded to the last `_KEEP` completions per chore, and fail-open: any read/write fault
    yields an empty map, which makes `stale_threshold` fall back to the roster cadence
    (the pre-#225 behaviour) rather than suppressing the alarm.
    """
    _KEEP = 8
    path = _completion_log(state_dir)
    try:
        hist: dict[str, list[int]] = json.loads(path.read_text()) if path.exists() else {}
    except Exception:  # noqa: BLE001 -- fail-open to the roster bound
        hist = {}
    changed = False
    for chore in chores:
        ts = gs.read_last_run(chore)
        if ts <= 0:
            continue
        seen = hist.setdefault(chore, [])
        if ts not in seen:
            seen.append(ts)
            del seen[:-_KEEP]
            changed = True
    if changed:
        try:
            state.atomic_write(path, json.dumps(hist))
        except Exception:  # noqa: BLE001 -- a bookkeeping fault must not break the beat
            pass
    return {c: ccw.observed_period(hist.get(c, [])) for c in chores}


def main() -> int:
    try:
        if not harness_backend.server_runs_chores():
            return 0
        claimed = sorted(harness_backend.claimed_chores())
        if not claimed:
            return 0

        now = int(time.time())
        observed = _record_completions(state.state_dir(), claimed)
        findings = ccw.evaluate(
            claimed,
            last_run_of=gs.read_last_run,
            cadence_of=_cadence_of,
            now=now,
            observed_of=lambda c: observed.get(c, 0),
        )
        if not findings:
            return 0

        named = ", ".join(ccw.describe(v) for v in findings[:_NAMED_IN_LINE])
        extra = len(findings) - _NAMED_IN_LINE
        if extra > 0:
            named += f", +{extra} more"

        blind = [v for v in findings if v.verdict == ccw.VERDICT_NO_EVIDENCE]
        wedged = [v for v in findings if v.verdict == ccw.VERDICT_STALE]

        msg = (
            f"[{_NAME}] {len(findings)} chore(s) CLAIMED by the live ai-maestro server are not "
            f"completing: {named}. The janitor yielded these and its own watchdog is silent on "
            f"them by design, so nothing else will notice or self-heal."
        )
        if wedged:
            # Name the remedy on the side that owns it. Our daemon cannot take these back
            # without an un-yield decision that is still open, so pointing the operator at
            # janitor health here would send them to the wrong repo.
            msg += (
                " Fix belongs to the SERVER side: check the ai-maestro server is executing its"
                " absorbed chores (janitor#221 was a 3.7-day wedge of exactly this shape)."
            )
        if blind:
            # Distinct remedy, distinct owner: this is a contract gap, not a wedge. Without
            # the stamp we cannot tell a healthy chore from a dead one for as long as the
            # claim stands, and silence about that is how a guard becomes decorative.
            msg += (
                f" {len(blind)} of them have left NO completion stamp at all — this watchdog is"
                " blind to those until the claim-holder writes one (asked for on"
                " Emasoft/ai-maestro#111)."
            )

        # Once per day. The condition changes on the scale of hours-to-days and the remedy is
        # not ours to apply, so an hourly repeat would only train the reader to skip it.
        seen = state.state_dir() / f"{_NAME}-seen.txt"
        key = f"claimed-stale@{now // 86400}:{','.join(sorted(v.chore for v in findings))}"
        out = dedupe.emit_once(seen, key, msg)
        if out is not None:
            print(out)
    except Exception as exc:  # noqa: BLE001 -- fail-soft is the contract
        state.log_line(_NAME, f"skipped: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
