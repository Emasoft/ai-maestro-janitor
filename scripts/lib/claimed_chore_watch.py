# Claimed-but-stale chore detection — the PURE decision layer (TRDD-6CRC9SQQ item 1).
#
# THE GAP THIS CLOSES. When a live ai-maestro server CLAIMS a janitor daemon chore, the
# daemon yields it and `daemon_watchdog.emit_if_daemon_stale` deliberately returns early
# for exactly that chore ("yields by design" — and it IS by design, so alarming there
# would be wrong). The result is that the claim handshake answers "who owns this?" and
# nothing anywhere answers "is the owner doing it?". A claimed-but-wedged chore is
# strictly WORSE than an unclaimed one, because the fallback that would have covered it
# is suppressed precisely then.
#
# Measured cost of the gap: janitor#221 — the server-absorbed OAuth rotator tick stopped
# COMPLETING for 3.7 days while wedged between two slot captures. Rotation was off, the
# owner rotated by hand, and the janitor side raised nothing at all.
#
# This module is the mirror image of `harness_backend.unabsorbed_chores()` /
# `global-chore-blackout`, which alarms on the chores the server did NOT claim. Between
# them every machine-global chore is watched by someone: unclaimed ones by the blackout
# detector, claimed ones by this.
#
# PURE by construction — every input is injected, nothing here reads a file, a clock, or
# the environment. That is what lets the detector's whole judgement be tested by passing
# numbers instead of by freezing a real stamp on a real host.

from __future__ import annotations

from typing import Callable, NamedTuple

# The card's headline bound: a claimed chore whose completion stamp has aged past 3x its
# own cadence is not merely late, it has missed two whole turns.
DEFAULT_FACTOR = 3

# ...but 3x alone is unusable at the short end. `oauth-rotator-tick` runs every 60 s, and
# 3x60 = 180 s is inside the normal jitter of a busy host — the alarm would fire on a
# healthy server that was briefly behind, and an alarm that cries wolf gets filtered out
# by the human long before the real 3.7-day wedge arrives (the issue-#9 lesson, learned
# once already on `daemon_watchdog`). The floor makes the shortest-cadence chore judged
# on an 11-minute window instead: still ~500x tighter than the incident it exists to
# catch, and far outside anything a healthy tick produces.
DEFAULT_MIN_GRACE_S = 600

VERDICT_OK = "ok"
VERDICT_STALE = "stale"
VERDICT_NO_EVIDENCE = "no-evidence"


def stale_threshold(
    cadence_s: int,
    *,
    factor: int = DEFAULT_FACTOR,
    min_grace_s: int = DEFAULT_MIN_GRACE_S,
) -> int:
    """Seconds a claimed chore's completion stamp may age before it counts as stale."""
    return max(factor * cadence_s, cadence_s + min_grace_s)


class Verdict(NamedTuple):
    """One chore's judgement. `age_s` is -1 when there is no stamp to age."""

    chore: str
    verdict: str
    age_s: int
    cadence_s: int
    threshold_s: int

    @property
    def is_finding(self) -> bool:
        return self.verdict != VERDICT_OK


def classify(
    *,
    chore: str,
    last_run: int,
    cadence_s: int,
    now: int,
    factor: int = DEFAULT_FACTOR,
    min_grace_s: int = DEFAULT_MIN_GRACE_S,
) -> Verdict:
    """Judge ONE claimed chore from its completion stamp. Total — never raises.

    `last_run <= 0` is NOT silently OK here, unlike in `daemon_watchdog`. There, a
    missing stamp means "our own daemon has not finished a first run yet" and will
    resolve itself within one cadence. Here it means the CLAIM-HOLDER has left no
    completion evidence at all, so this watchdog is blind to that chore for as long as
    the claim stands — which is the guard-that-cannot-fire failure this project has now
    shipped twice. Being blind is itself the finding; see `VERDICT_NO_EVIDENCE`.
    """
    threshold = stale_threshold(cadence_s, factor=factor, min_grace_s=min_grace_s)
    if last_run <= 0:
        return Verdict(chore, VERDICT_NO_EVIDENCE, -1, cadence_s, threshold)
    # A stamp in the future is clock skew (or a stamp written by a host whose clock ran
    # ahead), never staleness. Clamp rather than report a negative age.
    age = max(0, now - last_run)
    verdict = VERDICT_STALE if age > threshold else VERDICT_OK
    return Verdict(chore, verdict, age, cadence_s, threshold)


def evaluate(
    chores: list[str],
    *,
    last_run_of: Callable[[str], int],
    cadence_of: Callable[[str], int | None],
    now: int,
    factor: int = DEFAULT_FACTOR,
    min_grace_s: int = DEFAULT_MIN_GRACE_S,
) -> list[Verdict]:
    """Judge every claimed chore; return only the findings, worst-first.

    A chore whose cadence is unknown (`cadence_of` returns None) is SKIPPED, not guessed.
    That is the per-chore claim path: `harness_backend` honours a capability token equal
    to any chore name so ai-maestro can migrate chore-by-chore without a janitor release,
    which means a claim can legitimately name something this version has never heard of.
    Inventing a cadence for it would manufacture a verdict about a chore we cannot
    describe; staying quiet is the honest answer, and the roster is the place to fix it.
    """
    out: list[Verdict] = []
    for chore in chores:
        cadence = cadence_of(chore)
        if not cadence or cadence <= 0:
            continue
        v = classify(
            chore=chore,
            last_run=last_run_of(chore),
            cadence_s=cadence,
            now=now,
            factor=factor,
            min_grace_s=min_grace_s,
        )
        if v.is_finding:
            out.append(v)
    # Worst first: real staleness ahead of no-evidence (a wedged chore is actionable now;
    # a missing stamp is a contract gap), then by how far past its own threshold it is —
    # ratio, not absolute age, so a 6-hourly chore does not always outrank a 60 s one.
    out.sort(key=lambda v: (v.verdict != VERDICT_STALE, -(v.age_s / v.threshold_s)))
    return out


def describe(v: Verdict) -> str:
    """One chore's finding, as it appears inside the drift line."""
    if v.verdict == VERDICT_NO_EVIDENCE:
        return f"{v.chore} (no completion stamp ever)"
    return f"{v.chore} ({v.age_s // 60}m stale, bound {v.threshold_s // 60}m)"
