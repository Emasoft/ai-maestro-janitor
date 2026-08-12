"""Orphaned memory-maintenance pass detection (issue #238, TRDD-2112XCKO) — the PURE
decision layer.

The memory-maintenance SCHEDULER (`scripts/detectors/memory-maintenance.py`) stamps
`memory_settings.mark_ran(intervention, scope, root, now)` and, in the SAME instant,
writes `.janitor/state/memory-maint-pending.json` with that identical `now` as
`stamped_at`, then prints a bare `[janitor-memory-<chore>]` marker for the cron turn to
act on. Nothing DELETES that file when the dispatched agent finishes — there is no
"consumed" flag the way `resume-after-compact.flag` has one. So an old pending file is
not by itself proof of anything: MOST of the time it is simply the record of the last
dispatch, quietly aging until the next one is due.

What DOES prove a drop is the combination of two facts, both readable from disk:

  1. This pending record is still the MACHINE-WIDE last word on its (intervention,
     scope, root) key — `memory_settings.read_last_run` for that key has not moved past
     `stamped_at`, i.e. nobody (this session or any other) has re-dispatched it since.
  2. Its age has exceeded several multiples of that intervention's own cadence — so
     whatever *should* have re-armed it (either the cron-turn's agent spawn completing
     and the next cadence window opening, or a healthy peer session picking up a shared
     scope) plainly has not.

Confirmed live on janitor#238 (an orchestrator peer session, four consecutive drops):
a plugin whose registry lost every `ai-maestro-janitor:*` agent (#232's partial-install
shape) still runs its heartbeat's PYTHON detectors fine — the agent-spawn step that
fails is downstream of this script — so the same broken-registry session that drops a
pass can also be the one that reports it, self-contained, no fleet scan required.

LOCAL vs USER/PROJECT (the load-bearing distinction from #238): a LOCAL scope's root
belongs to exactly one project, so ONLY that project's own sessions can ever re-dispatch
it — a drop there is not deferred, it is STRANDED until a healthy session returns. A
USER (or PROJECT) scope's root can be re-dispatched by any OTHER session sharing it, so
one missed window is not yet a pattern. `factor_for_scope` encodes that: LOCAL tolerates
one missed cadence, everything else tolerates three (mirroring
`orphaned_resume.stale_window`'s "one fire is a hiccup, three is a pattern").
"""

from __future__ import annotations

import json
import math
from pathlib import Path

PENDING_NAME = "memory-maint-pending.json"

# Staleness factors (multiples of the intervention's own cadence). LOCAL has no other
# session to recover it (#238's core finding), so it gets the tight bound; everything
# else can be legitimately re-dispatched elsewhere before it counts as a pattern.
DEFAULT_FACTOR = 3
LOCAL_FACTOR = 1


def factor_for_scope(scope: str, *, default: int = DEFAULT_FACTOR, local: int = LOCAL_FACTOR) -> int:
    """The staleness factor (in cadences) for `scope`. See module docstring."""
    return local if (scope or "").strip().upper() == "LOCAL" else default


def read_pending(state_dir: Path) -> tuple[dict | None, bool]:
    """The legacy pending payload for `state_dir`.

    Returns `(payload, malformed)`:
      * `(dict, False)` — a well-formed payload with every field this module needs.
      * `(None, False)` — no pending file at all (nothing was ever dispatched — healthy;
        absence of a dispatch history is not evidence of a drop).
      * `(None, True)`  — the file EXISTS but cannot be parsed into the expected shape.
        That is itself a finding (absence-of-signal-is-not-health): a scheduler that
        writes garbage is at least as broken as one that writes nothing.
    """
    path = Path(state_dir) / PENDING_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None, False
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("pending payload is not an object")
        # Every field `is_orphaned`/`pending_is_current` needs — fail loud (as
        # "malformed") rather than silently treating a partial record as complete.
        int(data["stamped_at"])
        str(data["intervention"])
        str(data["scope"])
        str(data["root"])
    except (ValueError, KeyError, TypeError):
        return None, True
    return data, False


def pending_age_s(payload: dict, *, now: int) -> int:
    """Seconds since this pending record was stamped. Never negative — a clock skew (or
    a fixture built against a frozen test clock) must not manufacture a negative age."""
    return max(0, now - int(payload["stamped_at"]))


def pending_is_current(payload: dict, *, last_run: int) -> bool:
    """True iff no NEWER dispatch of the same (intervention, scope, root) has landed
    since this record was stamped — i.e. this record is still the authoritative last
    word on that key.

    `last_run` is `memory_settings.read_last_run(intervention, scope, root)` — a
    MACHINE-WIDE stamp (TRDD-c1397102): the scheduler calls `mark_ran` with the exact
    same `now` used for `stamped_at`, right before writing the pending file. A USER (or
    PROJECT) scope root can be re-dispatched by a DIFFERENT, healthy session on a
    different project; that healing shows up here as `last_run > stamped_at`, and this
    record must NOT be reported as orphaned even though it is, personally, old — the
    corpus WAS attended to, just not by the session that stamped this exact file.
    """
    try:
        return int(payload["stamped_at"]) >= last_run
    except (KeyError, TypeError, ValueError):
        return False


def is_orphaned(age_s: int, cadence_s: float, *, factor: int = DEFAULT_FACTOR) -> bool:
    """PURE: is a pending dispatch of this age, for an intervention with this cadence,
    orphaned? A disabled intervention (cadence == inf, 0/day) never orphans — nothing
    was ever expected to happen again, so an old record is simply history."""
    if not math.isfinite(cadence_s) or cadence_s <= 0:
        return False
    return age_s >= cadence_s * factor


def format_finding(intervention: str, scope: str, age_s: int, cadence_s: float) -> str:
    """One ledger-ready line. LOCAL gets its own wording (#238) so the reader restarts
    the session instead of waiting for a rescue that cannot come."""
    hours = age_s / 3600.0
    age = f"{hours:.1f}h" if hours < 48 else f"{hours / 24:.1f}d"
    cadence_h = "disabled" if not math.isfinite(cadence_s) else f"{cadence_s / 3600:.1f}h"
    if (scope or "").strip().upper() == "LOCAL":
        stranding = (
            "no other session can recover this LOCAL scope — restart this project's "
            "session (or run /janitor-arm in it) so the heartbeat re-dispatches it"
        )
    else:
        stranding = (
            "another healthy session sharing this scope should have picked it up by "
            "now — if none exists, run /janitor-arm in a session of this or any "
            "project sharing this scope"
        )
    return (
        f"memory-maintenance pass '{intervention}' ({scope}) was dispatched {age} ago "
        f"(cadence {cadence_h}) and never re-fired: {stranding}."
    )
