"""Shared cron-period parser (TRDD-D7RLXAN1 follow-up; report
reports/hook-timeout/20260924_180842+0200-stagger-and-timeouts.md §2).

`arm_prepare._stagger` now rewrites the plain minute-step cron this janitor arms
(`*/N * * * *`) onto a per-project offset (`{offset}-59/N * * * *`) so every armed session's
heartbeat does not land in the same minute. Every OTHER reader of an armed cron that wants "how
often does this fire" only ever understood the plain shape — `orphaned_resume.cadence_seconds`
and `fleet_scan.stale_threshold_for` each had their own `field.startswith("*/")` check, so a
staggered cron silently failed to parse and both fell back to their (stricter) default staleness
window instead of the real period. Two independent copies of the same parser is how they were
about to drift: one function, both callers import it.

`external_clear.seconds_until_next_fire` has a THIRD, pre-existing copy but needs the offset too
(it computes the actual next fire minute, not just the period) — out of scope here, flagged in
the report; it is not made worse by this change and was never touched by the stagger.
"""

from __future__ import annotations

import re

_PLAIN_RE = re.compile(r"^\*/(\d+)$")
_STAGGERED_RE = re.compile(r"^(\d+)-59/(\d+)$")


def period_minutes(cron: str) -> int | None:
    """Minutes between fires for a `*/N * * * *` or arm_prepare's staggered `{offset}-59/N * *
    * *` minute field. None for anything else (a fixed-hour cron, garbage, or a step outside
    (0, 60] — the same bound `cadence_seconds` always enforced, so a nonsense step fails toward
    the caller's stricter default rather than inventing a schedule from a cron it cannot read).

    A staggered offset must satisfy `0 <= offset < step` — that is the only range
    `arm_prepare._stagger` ever produces (`hash % step`). An offset outside it (a hand-edited
    or corrupted `armed-cadence.cron`) is not a shape this janitor ever wrote, so it is treated
    the same as any other unrecognized cron: None, never a plausible-looking guess (review
    finding on this module — garbage-in must not produce a garbage-but-plausible period).
    """
    field = (cron or "").strip().split(" ")[0] if cron else ""
    plain = _PLAIN_RE.match(field)
    if plain:
        step = int(plain.group(1))
        return step if 0 < step <= 60 else None
    staggered = _STAGGERED_RE.match(field)
    if staggered:
        offset, step = int(staggered.group(1)), int(staggered.group(2))
        if 0 < step <= 60 and 0 <= offset < step:
            return step
    return None
