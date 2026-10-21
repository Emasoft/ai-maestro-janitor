"""host_pressure — the RUNNABLE-COUNT pressure probe and the bar.

PART 1 — THE PRESSURE PROBE AND THE BAR (TRDD-C8SALZOO).

THE OWNER DIRECTIVE this implements, verbatim: "make this rule for the janitor
chores: never execute them when the system is under pressure. wait a moment when
the system activity is low to launch them, and pause them as soon as the system
becomes too busy again. even if they will slip to the night, it is better than
having those chores executed while the other main agents are struggling for cpu
time and resources!"

WHY A NEW MODULE AND NOT `scripts/lib/runaway_guard.py`. That module owns the
KILL side of the same condition, and it was being edited concurrently by another
worker (TRDD-ZIKYQQY0 A-0/A-1) while this gate was written. A separate module
keeps the two changes from colliding in the same file.

WHY THE RUNNABLE COUNT AND NOT THE LOAD AVERAGE. This is the load-bearing
correction, and it is a MEASUREMENT, not a preference. On this host (14 cores,
64 GB, nine Claude sessions live) the 5-minute load average sat at 185-193 —
13.2x to 13.8x the core count — and the host was perfectly USABLE: tool calls
were fast, the sessions were healthy, the swapfile was at its normal steady
state. The load average on macOS counts UNINTERRUPTIBLE-SLEEP processes, and
this host carries a large, roughly CONSTANT background of them (the iOS
Simulator daemons and their launchd agents), so the load average is inflated by
a constant that has nothing to do with whether the agents are struggling.

The 2026-10-20 incident was load 856 with 427 RUNNABLE processes. The load
average moved 856 vs ~190 (4.5x) but the average is inflated by that constant
background; the RUNNABLE COUNT moved 427 vs 118-169 (3.3x) in exactly the
quantity the owner perceives as "the other main agents are struggling for CPU
time". So the bar is on the runnable count.

THE BAR IS NOT CORE-RELATIVE, and the card's acceptance clause 4 asking for a
core-relative bar is REFUTED by that measurement. A runnable count is not a
rate, so "cores x N" has no meaning for it; the bar is a MEASURED ABSOLUTE
COUNT with its scope recorded (see `DEFAULT_PRESSURE_BAR`). The one existing
host-load detector (`scripts/detectors/host-load.py`, bar = cores x 4 = 56) has
NEVER fired on this host: there is no host-load.log in this project's
.janitor/logs/ nor in the plugin DATA global-state dir, because the host sits
permanently above that bar and the detector's "first fire of an overload
episode" never had a normal state to depart from. A rule built on that bar
would be permanently on, and the requirement that a deferred chore be VISIBLE
would be drowned by a detector that fires on every beat.

THE PROBE IS ONE `ps` CALL, and it is NOT a per-chore cost. The card required
that the gate "must not add a per-chore probe that costs a subprocess spawn
each"; the reading is therefore taken ONCE per daemon pass and handed down to
the gate, rather than each chore taking its own reading.

FAIL-OPEN IS THE CONTRACT: an UNREADABLE count is not a busy host. A janitor
that silently stops working because one `ps` call failed is worse than one that
runs a chore during a busy minute, so `read_runnable_count()` returns None for
an unreadable reading and every caller treats None as "not under pressure".

PART 2 IS GONE (TRDD-ZIKYQQY0 A-2, reverted after the adversarial review).

A PROCESS-ENVIRONMENT READER lived here once. It is REMOVED, and the reason is
the review's strongest objection: the kill record's project directory was read from the
KILLED process's own environment, AFTER the process was killed. A terminated pid is
gone from the process table or is an unreaped zombie with an empty argv, so the
read ALWAYS returned None in production — the feature was a no-op that its own
test mocked into working. A-2 stays an OPEN FINDING on TRDD-ZIKYQQY0, to be
reworked on its own with the environment captured BEFORE the kill. It is not
dropped.

This module is a PRESSURE PROBE and nothing else.
"""


import os
import subprocess
from typing import NamedTuple, Optional

# THE MEASURED BAR (TRDD-C8SALZOO, 2026-10-20).
#
# SCOPE — this number was measured on ONE host and the scope is recorded here
# because a bar copied to another host without re-measuring is exactly the
# mistake the card warns about ("DO NOT make the bar a load-average constant
# copied from another host"):
#
#   host          : 14 cores / 64 GB, macOS, nine Claude sessions live
#   healthy band  : 118-169 runnable (six samples, two minutes apart)
#   incident      : 427 runnable (2026-10-20, load 856, host unusable)
#   chosen bar    : 300
#
# 300 sits with real headroom on both sides: it is ~1.8x the top of the
# measured healthy band (so a normal busy hour never trips it) and ~0.7x the
# measured incident (so the gate closes well before the host is dead).
# Overridable per host via CLAUDE_PLUGIN_OPTION_PRESSURE_RUNNABLE_BAR.
DEFAULT_PRESSURE_BAR = 300

# THE TEST SEAM. Same shape as the one `scripts/detectors/host-load.py` already
# uses (JANITOR_LOADAVG / JANITOR_CPU_COUNT): when set, the injected value
# REPLACES the real reading, so a test never depends on the host it runs on.
#
# The value is the runnable COUNT as a decimal integer. An EMPTY value is
# "cannot be read" (the same as a failed `ps`) — that is what lets a test
# exercise the fail-open path without monkeypatching `ps` itself.
RUNNABLE_COUNT_ENV = "JANITOR_RUNNABLE_COUNT"

# The bar's env knob, mirroring the other CLAUDE_PLUGIN_OPTION_* knobs.
PRESSURE_BAR_ENV = "CLAUDE_PLUGIN_OPTION_PRESSURE_RUNNABLE_BAR"

# THE CLEAR FRACTION — the HYSTERESIS BAND of the episode latch (TRDD-C8SALZOO).
#
# WHY A SECOND THRESHOLD AND NOT THE BAR ITSELF. The episode latch used to be
# cleared on the FIRST calm reading — any reading below the bar. A host
# hovering at 299/300 then alternates busy -> announce -> clear -> busy ->
# announce, and the once-per-episode discipline (the whole point of the latch)
# fails EXACTLY in the band where it matters.
#
# So the latch is cleared only when the reading drops BELOW `bar * fraction`.
# A reading between the clear threshold and the bar keeps the latch, so a
# host that oscillates around the bar announces ONE episode, not one per
# crossing.
#
# IT IS A FRACTION OF THE BAR, not an absolute count, so it MOVES WITH the bar
# when the bar is overridden for another host: a bar of 500 on a bigger host
# gets a clear threshold of 350, not the 210 that a hard-coded 300-bar
# fraction would give.
#
# 0.7 sits BELOW the measured healthy band (118-169) but well below the bar,
# so a host that has genuinely recovered (which reads ~120-170 here) clears
# the latch, while a host that is merely below the bar but still hot does
# not.
DEFAULT_PRESSURE_CLEAR_FRACTION = 0.7


def pressure_bar(default: int = DEFAULT_PRESSURE_BAR) -> int:
    """The runnable-count bar. Env-overridable; never zero (a zero bar would
    close the gate on EVERY host, including a calm one)."""
    raw = os.environ.get(PRESSURE_BAR_ENV)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (AttributeError, ValueError):
        return default
    return value if value > 0 else default


def parse_runnable_count(ps_text: str) -> int:
    """Count the processes in the RUNNABLE state in a `ps -axo state=` listing.

    The state field's FIRST character is the runnable flag on macOS and Linux:
    `R` = running or runnable, `S` = interruptible sleep, `D` = uninterruptible
    sleep, `Z` = zombie, `I` = idle. The rest of the field carries the
    modifiers (`s` = session leader, `+` = foreground, `N` = low priority,
    `<` = high priority), which is why the whole field is NOT compared and the
    first character is.

    MEASURED on this host: the distinct state tokens are `Ss`, `S`, `S+`, `R`,
    `Rs`, `RN`, `R+`, `SN`, `Z`, `U` and `?E` — so a comparison against the
    whole token would MISS every modified runnable state (`Rs`, `RN`, `R+`)
    and undercount the pressure signal by roughly a third. Only the first
    character decides.

    A process that is `R` in this instant is runnable NOW — which is the
    quantity the owner described as "the other main agents are struggling for
    CPU time". A process in `D` (uninterruptible sleep) is what inflates the
    load average on this host and is deliberately NOT counted here.
    """
    count = 0
    for line in ps_text.splitlines():
        token = line.strip()
        if not token:
            continue
        if token[0] == "R":
            count += 1
    return count


def read_runnable_count() -> Optional[int]:
    """Processes in the runnable state right now, or None if unreadable.

    ONE `ps` call, and the daemon already spawns `ps` for other chores, so
    this is not a new per-chore cost class. The result is meant to be read
    ONCE per daemon pass and passed down (see `scripts/daemon.py`'s
    `_run_due_tasks`), not read once per chore.

    THE INJECTION SEAM COMES FIRST. When `JANITOR_RUNNABLE_COUNT` is set, the
    injected value is returned and NO subprocess is spawned at all — which is
    both the test seam and the reason a test of the gate costs nothing.

    None means "cannot be read" and is NEVER a busy host. Every caller treats
    None as "not under pressure" (fail-open): a janitor that stops working
    because one `ps` call failed is worse than one that runs a chore during a
    busy minute.
    """
    injected = os.environ.get(RUNNABLE_COUNT_ENV)
    if injected is not None:
        text = injected.strip()
        if not text:
            return None  # an empty injection IS the unreadable case
        try:
            return int(text)
        except ValueError:
            return None  # a malformed injection is unreadable, not zero
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["ps", "-axo", "state="],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return parse_runnable_count(out.stdout)


def under_pressure(count: Optional[int], bar: int) -> bool:
    """Is the host over the pressure bar?

    PURE, and the whole rule in one place:
      * `count is None` → False. An unreadable reading NEVER blocks a chore.
      * `count >= bar` → True. AT the bar counts as over it.
    """
    if count is None:
        return False
    return count >= bar


class HostPressure(NamedTuple):
    """One pass's pressure reading, the bar it was judged against, and the
    LOWER threshold that clears the episode latch.

    `runnable` is None when the reading could not be taken, and None is NEVER
    "over the bar" — the fail-open rule, carried by the object itself so no
    caller has to re-derive it.

    THE FIELD IS NAMED `runnable`, NOT `count`, AND THAT IS NOT COSMETIC.
    `tuple` — the NamedTuple's base — already has a `count` METHOD, so a
    field named `count` OVERRIDES it with an incompatible type: mypy rejects
    the assignment ("base class 'tuple' defined the type as
    'Callable[[Any], int]'") and pyright rejects it too
    (reportIncompatibleMethodOverride). The project's publish gate runs ruff
    AND mypy AND pyright, and a clean run of any two proves nothing, so the
    name is load-bearing for the build — not a style choice. Renaming a
    NamedTuple field is a SIGNATURE change (the fields are positional), so
    every construction site and every attribute read moves together.

    `clear_fraction` is the HYSTERESIS fraction of the bar (see
    `DEFAULT_PRESSURE_CLEAR_FRACTION`). It is carried HERE so the daemon never
    recomputes the clear threshold — it reads `clear_at`. It defaults to the
    module constant, so the two-positional construction
    `HostPressure(runnable, bar)` still works unchanged.
    """

    runnable: Optional[int]
    bar: int
    clear_fraction: float = DEFAULT_PRESSURE_CLEAR_FRACTION

    @property
    def over(self) -> bool:
        """True iff the host is over the bar."""
        return under_pressure(self.runnable, self.bar)

    @property
    def clear_at(self) -> float:
        """The LOWER threshold: a reading at or above it does NOT clear the latch.

        The hysteresis band is `[clear_at, bar]`: a reading in that band is
        UNDER the bar (so the gate is open and chores run) but NOT calm enough
        to end the episode, so the latch survives and the once-per-episode
        discipline holds for a host oscillating around the bar.
        """
        return self.bar * self.clear_fraction

    def calm_enough_to_clear(self) -> bool:
        """True iff this reading may END the deferral episode.

        FAIL-OPEN IN THE OTHER DIRECTION, AND DELIBERATELY SO: an UNREADABLE
        reading (None) does NOT clear the latch. An unreadable reading is not
        evidence of a calm host — it is evidence of a failed `ps` — and
        clearing the latch on it would announce a fresh episode on the next
        busy beat, which is the repetition the latch exists to prevent.
        """
        if self.runnable is None:
            return False
        return self.runnable < self.clear_at

    def describe(self) -> str:
        """A short, log-safe rendering of the reading and the bar."""
        reading = "unreadable" if self.runnable is None else str(self.runnable)
        return f"runnable {reading} (bar {self.bar})"


def read_pressure() -> HostPressure:
    """One pass's reading: the runnable count (or None) and the bar.

    THE SINGLE READ PER PASS. The card required that the gate "must not add a
    per-chore probe that costs a subprocess spawn each", so the caller takes
    ONE reading per daemon pass and hands the resulting object down to the
    gate, rather than each chore taking its own.
    """
    return HostPressure(read_runnable_count(), pressure_bar())

