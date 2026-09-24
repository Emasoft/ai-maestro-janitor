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

`external_clear.seconds_until_next_fire` had a THIRD, pre-existing copy of this same
`*/N`-only check — it now delegates to `parse()` below too (TRDD-D7RLXAN1 follow-up review
item 1), the last of the three readers to learn the staggered shape.
"""

from __future__ import annotations

import re

_PLAIN_RE = re.compile(r"^\*/(\d+)$")
_STAGGERED_RE = re.compile(r"^(\d+)-59/(\d+)$")


def parse(cron: str) -> tuple[int, int] | None:
    """`(offset, step)` for a `*/N * * * *` (offset 0) or arm_prepare's staggered
    `{offset}-59/N * * * *` minute field. None for anything else (a fixed-hour cron, garbage,
    a step outside (0, 60], or a staggered offset outside `[0, step)` — the only range
    `arm_prepare._stagger` ever produces (`hash % step`); an offset outside it is not a shape
    this janitor ever wrote, so it is treated the same as any other unrecognized cron: None,
    never a plausible-looking guess (review finding on this module — garbage-in must not
    produce a garbage-but-plausible schedule).

    The single parse both `period_minutes` (how often) and
    `external_clear.seconds_until_next_fire` (when next) need — the latter needs the offset
    too, `period_minutes` just discards it.
    """
    field = (cron or "").strip().split(" ")[0] if cron else ""
    plain = _PLAIN_RE.match(field)
    if plain:
        step = int(plain.group(1))
        return (0, step) if 0 < step <= 60 else None
    staggered = _STAGGERED_RE.match(field)
    if staggered:
        offset, step = int(staggered.group(1)), int(staggered.group(2))
        if 0 < step <= 60 and 0 <= offset < step:
            return (offset, step)
    return None


def period_minutes(cron: str) -> int | None:
    """Minutes between fires for a `*/N * * * *` or arm_prepare's staggered `{offset}-59/N * *
    * *` minute field. None for anything else — see `parse()`."""
    parsed = parse(cron)
    return parsed[1] if parsed else None
