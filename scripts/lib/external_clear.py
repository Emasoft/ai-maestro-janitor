"""External (ZERO model turn) handoff-and-clear — policy + composition (TRDD-PXP08ZQC).

The heartbeat's own idle-clear lever (`dispatch._phase_idle_clear_nudge`) fires the SAME
`clear_trigger.spawn_shrink_chain` this module's decisions feed (TRDD-RAEGS1D5 card 4: it used
to type `/janitor-handoff-and-clear` for the model to run, costing a full turn on its own huge
context just to author a handoff before it could shrink — it now calls the chain directly, zero
model turns, same as this module). This module is the decision + composition half of doing the
SessionStart-time compaction from OUTSIDE any live session at all — the typist half already
exists (`clear_trigger.py`'s verified injection chain).

Split exactly like the rest of the codebase: everything here is PURE (all runtime facts are
injected) so the gate is unit-testable without a live session. The I/O gatherer and the firing
live in `scripts/external_handoff_clear.py`.

## WHY THE TRIGGER IS NOT "the cache is expired"

The card was written as *idle + cache-expired + over-threshold*. Taken literally that lever is
DEAD on the machine it was written for, measured 2026-08-06: a probed 60-minute cache TTL regime
and the armed cadence `*/5 * * * *` means a fire every 5 minutes keeps the cache permanently warm
and `cache_expired` is never true. That is the same shape
`cold_cache_compact` burned on twice — "a threshold high enough to never be met is a feature that
does not exist".

The card's *intent* is sound once expressed correctly: what costs money is not that the cache is
cold, it is that **the next fire will pay a cache MISS**. So trigger (a) asks exactly that —
`age_since_last_turn + seconds_until_next_fire >= ttl`. It fires in the idle gap BEFORE the
expensive fire, which is the timing contract the card asks for.

Trigger (b) is the owner's 2026-08-04 rule (nothing but beats for >= 1 h). It is what actually
bites in the warm case: a warm fire on a 460k context still re-reads ~10M weighted tokens, and
177.7M of one 7-day window went to heartbeat fires alone. Neither trigger subsumes the other, so
the gate ORs them and NAMES the one that fired — a lever that cannot say why it acted is one
nobody can tune.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import agentlens_probe as alp  # noqa: E402  -- sibling lib (the reactive expiry read)
import state  # noqa: E402  -- sibling lib

# TRDD-0UQSAFCW: the ONE shared classifier `recent_messages` uses to tell a human turn apart
# from a heartbeat prompt/reply, task notification, or system record -- stdlib-only (verified
# by tests/test_jev_boundary.py), so importing it here does not pull jevctx/httpx into this
# in-process module the way `jev_compaction` would.
import transcript_roles  # noqa: E402  -- sibling lib

# --- config knobs (userConfig → env; read via the shared coercers) ----------
ENABLED_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED"
MIN_CONTEXT_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_MIN_CONTEXT_TOKENS"
HEADROOM_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_HEADROOM_SECONDS"

# DEFAULT OFF, deliberately, unlike its in-model sibling. `/clear` is unrecoverable, and this
# path fires it with NO model turn in front of it — nothing reads the handoff back before the
# context is gone. It ships opt-in until the card's "one observed end-to-end unattended cycle"
# acceptance box is ticked; flipping this default is that box's payoff, not its precondition.
DEFAULT_ENABLED = False
# Size is NOT the reason to clear (owner directive 2026-08-04 dropped it from the in-model gate);
# it is only a floor below which clearing buys nothing measurable. Anything under this is cheap to
# keep, so leave it alone.
#
# 300k is the USER's number, given verbatim on 2026-08-22 (decision #11): cache expiry should
# always trigger the externalized compaction "unless the context currently used is <300k or the
# compaction just happened". Raised from 150k.
#
# ⚠ ONE TENSION THIS RAISE SHARPENS, recorded rather than resolved, because resolving it would
# reverse a standing owner ruling. `context_tokens is None` does NOT veto (see
# `should_clear_externally`'s docstring — an unknown-context veto silently disabled the whole
# lever for every unmeasurable transcript, owner directive 2026-08-04). So a session whose
# context cannot be measured skips this floor entirely, and doubling the floor doubles what that
# bypass is worth. Both rulings are the USER's and they do not contradict each other — one is
# about a measured value, the other about the absence of one — but if the USER ever wants
# unknown-context to be treated as "below the floor", that is a deliberate reversal of the
# 2026-08-04 directive and belongs in its own decision, not in a constant.
DEFAULT_MIN_CONTEXT_TOKENS = 300_000
# The chain types /clear, waits for the fresh session, then types the bootstrap. Firing with less
# than this before the next cron fire means the fire lands mid-chain — survivable (the injector
# waits for a free pane) but it wastes the very fire we were trying to prevent.
DEFAULT_HEADROOM_SECONDS = 60
# The prompt-cache TTL assumed for the cadence. 5 minutes is the platform's standard TTL and the
# SHORT side, so this biases toward "the next fire will miss" → toward acting. That is the safe
# direction here: the cost of a spurious clear on an abandoned session is one re-read of a
# link-only handoff.
DEFAULT_TTL_MINUTES = 5
# The LONGEST prompt-cache TTL the platform offers. Past it no cache survives under ANY regime, so
# an age beyond this is CERTAINTY rather than an estimate — which is the only thing that may
# authorize an unrecoverable `/clear` (TRDD-CEWVQ8DG).
#
# Deliberately NOT `DEFAULT_TTL_MINUTES`. The short TTL is the right bias for
# `next_fire_misses_cache`, which predicts a COST and should err toward acting; here erring toward
# acting would destroy a live session's context to save nothing. Same clock, opposite asymmetry.
CERTAIN_EXPIRY_FLOOR_MINUTES = 60

# The byte budget for the WHOLE injected handoff. It MIRRORS the contract
# `clear_trigger.check_handoff_concise` actually ENFORCES (`_HANDOFF_MAX_BYTES`), and the two
# must stay equal — `tests/test_external_clear_llm_ext.py` asserts exactly that, because this is
# the second time in this file's history that a producer and its checker were tuned
# independently (see `_FLEET_LEASE_TTL_MARGIN_S` for the first).
#
# MEASURED DRIFT, 2026-08-15 (TRDD-PXP08ZQC): `compose_handoff` defaulted to 8192 — DOUBLE what
# the checker allows — while `compose_template_handoff` already used 4096 and documented itself
# as passing "by construction". The caller passed neither, so every full handoff targeted a
# budget the contract rejects, and a real one shipped at 4571 bytes: over the limit, under the
# composer's target, logged as `handoff violates the concision contract: ['too-large']` and
# injected anyway. A bloated handoff refills the context the /clear just emptied, which is the
# entire thing this feature exists to avoid.
HANDOFF_MAX_BYTES = 4096

# Trigger names — returned in the verdict and written to the log, so a fire can always be
# attributed to the rule that caused it.
TRIGGER_NEXT_FIRE_MISSES = "next-fire-misses"
TRIGGER_LONG_IDLE = "long-idle"
TRIGGER_CACHE_CERTAIN_EXPIRED = "cache-certain-expired"
TRIGGER_RESUMED_COLD = "resumed-cold"
# TRDD-79LXF6PJ. The other four triggers are all IDLE/CACHE conditions, so an ACTIVE session —
# busy, cache warm, never idle — was never a candidate for clearing. That was harmless while the
# HARNESS still auto-compacted at the boundary. It is not harmless now: with
# `autoCompactEnabled: false` the harness stops at the context limit with a hard ERROR and no
# automatic recovery, so without this trigger a busy session simply dies at the boundary.
TRIGGER_CONTEXT_PRESSURE = "context-pressure"

# The high-water mark, in tokens. `CLAUDE_CODE_AUTO_COMPACT_WINDOW` is the natural default: it is
# the point at which the harness USED to auto-compact, so firing there reproduces the old
# behaviour through the janitor instead of the harness — same moment, different mechanism.
_CONTEXT_HIGH_WATER_ENV = "CLAUDE_PLUGIN_OPTION_CLEAR_CONTEXT_HIGH_WATER"
_AUTO_COMPACT_WINDOW_ENV = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"

# The SessionStart `source` values that mean "Claude was loaded after being away", and so are
# the only ones the resume path may act on. `compact` and `clear` are excluded BY NAME because
# they are re-entries into a session that was JUST shrunk: acting on them is an infinite loop
# (shrink → SessionStart(compact) → shrink → …). Measured on this machine over the sessions
# recorded so far: compact 38, resume 7, clear 3, startup 0 — so `compact` is not a theoretical
# risk, it is the MOST COMMON source by a factor of five, and `startup` alone would never fire.
# "fork" is EXCLUDED DELIBERATELY, not by oversight (reviewed 2026-08-14 against CC 2.1.214,
# which made SessionStart report source "fork" instead of "resume" for a forked session).
# These are the sources that mean "a genuine load-after-away", where a cold cache plus a big
# context makes the next turn expensive. A fork is neither away nor cold — it is an immediate
# copy of a live conversation into a background session (CC 2.1.212), created precisely to
# KEEP that context. Auto-clearing it would destroy the thing the user forked to preserve.
# If a fork should ever become eligible, that is a deliberate decision with a destructive
# blast radius — make it one, do not add the string casually.
RESUME_SOURCES = frozenset({"resume", "startup"})

# The agentlensPro probe's command, overridable per the module's one integration pattern; an
# empty value disables the reactive trigger entirely and leaves the predictive one alone.
CACHE_EXPIRED_COMMAND_ENV = "CLAUDE_PLUGIN_OPTION_HEARTBEAT_CACHE_EXPIRED_COMMAND"

__all__ = [
    "ClearVerdict",
    "HANDOFF_MAX_BYTES",
    "cache_certainly_expired",
    "cache_expired_by_age",
    "compose_handoff",
    "compose_handoff_room",
    "compose_template_handoff",
    "enabled",
    "recent_messages",
    "headroom_seconds",
    "min_context_tokens",
    "next_fire_misses_cache",
    "read_ttl_minutes",
    "resolve_cache_expired",
    "seconds_until_next_fire",
    "should_clear_externally",
    "terminal_from_record",
]


def enabled() -> bool:
    return state.is_truthy_env(ENABLED_ENV, DEFAULT_ENABLED)


def context_high_water_tokens() -> int:
    """Tokens at which context pressure alone authorizes a clear. 0 disables the trigger.

    Resolution order, and each fallback is deliberate:
      1. `CLAUDE_PLUGIN_OPTION_CLEAR_CONTEXT_HIGH_WATER` — an explicit override.
      2. `CLAUDE_CODE_AUTO_COMPACT_WINDOW` — where the harness used to auto-compact. Reusing it
         means the janitor fires at exactly the moment the old behaviour did.
      3. 0 — DISABLED, and that is the honest answer rather than a guessed constant. Context
         windows differ by an order of magnitude between models (200 K vs 1 M); a hardcoded
         default would either clear a 1 M session five times too early or fire far too late on a
         200 K one. A caller that wants the backstop must say where it is.

    ⚠ 0 means a busy session has NO backstop against the context-limit error once auto-compaction
    is off. Callers should say so out loud rather than let it pass as normal.
    """
    explicit = state.coerce_int(os.environ.get(_CONTEXT_HIGH_WATER_ENV), 0)
    if explicit > 0:
        return explicit
    return max(0, state.coerce_int(os.environ.get(_AUTO_COMPACT_WINDOW_ENV), 0))


def harness_auto_compacts(*, home: Path | None = None) -> bool:
    """True when CLAUDE CODE still compacts on its own — i.e. the janitor must NOT.

    THIS IS AN OWNERSHIP QUESTION, AND IT HAS TO BE ASKED RATHER THAN ASSUMED (owner,
    2026-08-23: *"the janitor must be aware that auto-compact is off. it's its responsibility to
    compact the context when autocompact is off"*). The two states need OPPOSITE behaviour and
    getting it backwards is costly in both directions:

      * harness ON  + janitor fires  → the session is compacted twice, and the janitor's clear
        races a compaction the harness was about to do anyway. Pure waste.
      * harness OFF + janitor silent → nothing compacts, and the session dies at the context
        limit with a hard error. That is the hole this function closes; it was open on this
        machine for several hours today because the setting was flipped before the janitor could
        see it.

    WHY THE JANITOR IS THE BETTER OWNER, not merely an adequate one: the harness compacts
    WHENEVER the boundary is crossed, which is necessarily MID-TURN — it interrupts the work and
    discards a warm cache. The janitor's fires come from the heartbeat cron, and a cron fires
    only when the REPL is IDLE, so a janitor compaction is at a turn boundary BY CONSTRUCTION.
    It cannot interrupt. That is why overshooting the threshold is acceptable and interrupting is
    not: a few percent of extra context costs a little, a severed turn costs the turn.

    Reads USER-scope `~/.claude/settings.json` and the per-session `DISABLE_AUTO_COMPACT` env
    var. Either one turning it off wins, per the documented precedence — whichever disables it,
    the other cannot re-enable it. UNREADABLE OR ABSENT ⇒ True (assume the harness still owns
    compaction), because the safe default is the janitor doing NOTHING: a wrongly-silent janitor
    costs a redundant harness compaction, while a wrongly-eager one clears a session that was
    never in danger.
    """
    if state.is_truthy_env("DISABLE_AUTO_COMPACT", False):
        return False
    root = home or Path(os.path.expanduser("~"))
    try:
        raw = (root / ".claude" / "settings.json").read_text(encoding="utf-8")
        value = json.loads(raw).get("autoCompactEnabled")
    except (OSError, ValueError, AttributeError):
        return True  # unparseable config is not evidence the harness stopped compacting
    return True if value is None else bool(value)


def min_context_tokens() -> int:
    return state.coerce_int(os.environ.get(MIN_CONTEXT_ENV), DEFAULT_MIN_CONTEXT_TOKENS)


def headroom_seconds() -> int:
    return state.coerce_int(os.environ.get(HEADROOM_ENV), DEFAULT_HEADROOM_SECONDS)


# Bounded by US, not by the CLI. llm-externalizer 12.0.0 shipped with an unbounded body-read:
# its abort was disarmed once headers arrived, so its own timeout covered time-to-first-byte
# only and a stalled generation hung forever. A handoff composer that can hang is worse than
# one that degrades, because the `/clear` it precedes never happens and the session simply
# stops.
#
# SIZED AGAINST THE CLI'S OWN PER-ATTEMPT BUDGET, NOT THE MEAN (TRDD-YOZ9TS3W). llm-ext
# checkpoints after every chunk and resumes on re-invocation, so this timeout only makes
# progress when an attempt COMPLETES a chunk — a chunk slower than this value can never
# finish, nothing is ever checkpointed, and every retry restarts the SAME doomed chunk until
# `DEFAULT_SUMMARY_DEADLINE_S` runs out. 240s was sized against the ~180s MEAN end-to-end
# transcript time the maintainer measured — but per-CHUNK time (queue contention, not size)
# ranged 91s-1478s on free models, and the CLI's own `--chunk_timeout_s` default is 600s: the
# server considers 600s one legitimate attempt, and we were killing our client at under half
# that. 600s matches the CLI's own per-attempt allowance, so a normal (if slow) chunk is
# finally given the time the CLI itself expects it to need. It cannot cover the full observed
# tail (up to 1478s) — no timeout we can afford to hold a fleet lease for can — so a chunk that
# is genuinely stuck past this budget is caught instead by the progress-observed retry gate in
# `summarize_with_retry` (see `_NO_PROGRESS_TIMEOUT_GIVEUP` below), not by raising this further.
LLM_EXT_TIMEOUT_S = 600


# `_version_key`, `resolve_llm_ext`, the progress-fingerprint helpers, the refusal classifier,
# and `run_llm_ext_summary` moved to `scripts/lib/llm_ext_summary.py` (TRDD-RAEGS1D5 card 3 C2):
# the AUTOMATIC lane (`summarize_previous_session.py`) no longer calls llm-ext at all (card 3
# C1 rewired it onto `jev_compact.py compact`), and the sole remaining production caller —
# `scripts/compose_agent_handoff.py`, the manual `/janitor-write-handoff` tool — now imports
# that module directly instead of reaching through this one. `LLM_EXT_TIMEOUT_S` above stays
# here because `DEFAULT_FLEET_LEASE_TTL_S` below is derived FROM it (the fleet-lease machinery
# itself also stays here; card 3 C3 renames it for a future automatic-lane consumer).


# --- the fleet lane: at most N llm-ext calls in flight, machine-wide (owner, 2026-08-13) -----
#
# THE PROBLEM THIS EXISTS FOR, in the owner's words: *"20 compacting requests will surely result
# in a rate limit ban. to compact llm-externalizer uses free models on openrouter, and they will
# definitely won't sustain such simultaneous requests."*
#
# The trigger is a SessionStart on a cold cache, and the fleet does not wake up staggered — a
# laptop opening in the morning starts every session inside the same few seconds, so the naive
# design issues N simultaneous requests to a free-tier endpoint and every one of them 429s. The
# retry loop would then re-issue all N together on the same backoff schedule: a thundering herd,
# not a recovery.
#
# WHY A CONCURRENCY CAP AND NOT A SPACED QUEUE. The first version handed out start times spaced
# `interval` apart — session i started at `t0 + i*interval`. The owner then supplied the number
# that kills that design: *"according to the llm-externalizer tests, the compaction should take 3
# minutes on average. so the serialize option is very limited. after 3 requests in queue it must
# start to run them anyway."* At ~180 s per run, spacing 20 sessions even 45 s apart queues the
# last one 14 minutes out — long past any deadline, so it would never run at all and every late
# session would degrade to the template. Bounding CONCURRENCY instead bounds the load without
# bounding the throughput: three run at once, the fourth starts the moment one finishes.
#
# The lease is TTL'd rather than released-only, because the holder is a process that can be
# killed — an unreleased lease must expire on its own or one crash would wedge the lane forever.
FLEET_MAX_CONCURRENT_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_CLEAR_FLEET_MAX_CONCURRENT"
# The owner's number. 3 concurrent free-tier requests is a load an endpoint sustains; 20 is not.
DEFAULT_FLEET_MAX_CONCURRENT = 3
FLEET_LEASE_TTL_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_CLEAR_FLEET_LEASE_TTL_S"
# MUST exceed `LLM_EXT_TIMEOUT_S` — the ordering invariant is `per-attempt < lease TTL`, and it
# holds BY CONSTRUCTION here (derived, not a second hand-picked literal) so it cannot drift out
# of sync the way two independently-tuned constants can (TRDD-YOZ9TS3W: this file used to read
# "comfortably over ... `LLM_EXT_TIMEOUT_S` (240 s)" beside a 300 s value — true only until
# someone changed one side without the other). If the TTL ever expired UNDER a still-running
# attempt, a fourth worker would be admitted while three are still active, silently defeating
# the machine-wide 3-concurrent cap (owner, 2026-08-13) with nothing reporting the breach. The
# margin (2 minutes) covers the lease-store I/O + fleet-poll latency around the subprocess call
# itself, which is not counted in `LLM_EXT_TIMEOUT_S`.
_FLEET_LEASE_TTL_MARGIN_S = 120
DEFAULT_FLEET_LEASE_TTL_S = LLM_EXT_TIMEOUT_S + _FLEET_LEASE_TTL_MARGIN_S
# How long to wait between attempts to take a lease. Short enough that a freed lease is claimed
# promptly, long enough that waiting costs nothing measurable.
FLEET_POLL_S = 5.0
FLEET_LEASE_FILE = "external-clear-leases.json"
FLEET_LANE_LOCK = "external-clear-lane.lock"


def fleet_max_concurrent() -> int:
    """How many llm-ext summarize calls may run at once, machine-wide. 0 disables the lane."""
    return state.coerce_int(
        os.environ.get(FLEET_MAX_CONCURRENT_ENV, ""),
        DEFAULT_FLEET_MAX_CONCURRENT,
        detector_name="external-clear",
        var_name=FLEET_MAX_CONCURRENT_ENV,
    )


def fleet_lease_ttl_s() -> int:
    """Seconds a lease survives without release — the crash backstop, not the expected path."""
    return state.coerce_int(
        os.environ.get(FLEET_LEASE_TTL_ENV, ""),
        DEFAULT_FLEET_LEASE_TTL_S,
        detector_name="external-clear",
        var_name=FLEET_LEASE_TTL_ENV,
    )


SUMMARY_DEADLINE_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_CLEAR_SUMMARY_DEADLINE_S"
# How long the whole summarize effort — lane waits, attempts and backoff together — may run
# before the handoff degrades to the network-free template and the clear proceeds anyway.
#
# USER-DIRECTED ARITHMETIC (TRDD-YOZ9TS3W, superseding an earlier 3x-multiple choice): FOUR
# attempts at `LLM_EXT_TIMEOUT_S` (600 s) = 2400 s, plus ~200 s margin for the inter-attempt
# backoff (the `_BACKOFF_S` doubling) and fleet-lease acquisition between attempts. Deliberately
# NOT an exact multiple of `LLM_EXT_TIMEOUT_S` (2400): a deadline equal to N x per-attempt leaves
# ZERO room for anything BETWEEN attempts, so the 4th attempt would be cut off mid-flight by the
# deadline before it could even start — losing the whole point of budgeting for 4 attempts. llm-ext
# checkpoints per chunk and resumes on re-invocation, so each of the 4 attempts is real forward
# progress, not 4 redundant tries at the same work.
DEFAULT_SUMMARY_DEADLINE_S = 2600


def summary_deadline_s() -> int:
    """Total seconds the summarize effort may take before degrading to the template handoff."""
    return state.coerce_int(
        os.environ.get(SUMMARY_DEADLINE_ENV, ""),
        DEFAULT_SUMMARY_DEADLINE_S,
        detector_name="external-clear",
        var_name=SUMMARY_DEADLINE_ENV,
    )


def _lane_dir() -> Path:
    """Where the lane files live — the machine-global janitor state dir.

    Imported lazily and defensively: this module is also imported by a SessionStart hook, and a
    global-state dir that cannot be resolved must degrade to "no lane" rather than break the
    caller. Losing the lane costs spacing; raising here would cost the whole clear.
    """
    try:
        import global_state as gs  # noqa: PLC0415

        return gs.global_state_dir()
    except Exception:  # noqa: BLE001 -- no global state ⇒ no lane, never a crash
        return Path()


def acquire_fleet_lease(
    *,
    now: float,
    max_concurrent: int,
    ttl_s: int,
    lane_dir: Path | None = None,
) -> str | None:
    """Take one of `max_concurrent` machine-wide llm-ext leases, or None when all are held.

    Read-prune-count-write happens under ONE exclusive flock, which is what makes the cap real:
    check-then-write in separate critical sections lets N racers all observe "2 active" and all
    admit themselves, which is precisely the simultaneous burst the lane exists to prevent.

    Expired leases are pruned on every acquire rather than on release, because the holder is a
    process that can be killed — if expiry depended on a clean release, one crash would wedge the
    lane permanently and every later session would degrade to the template forever.

    Fails OPEN, returning a sentinel lease: an unwritable dir, a missing `fcntl` or a corrupt
    store all admit the caller. A lane able to REFUSE would be able to block the clear, and an
    uncapped clear is merely rate-limited where a blocked one is the full-price turn.
    """
    if max_concurrent <= 0:
        return "lane-disabled"
    d = _lane_dir() if lane_dir is None else lane_dir
    if not d or not str(d):
        return "lane-unavailable"
    try:
        import fcntl  # noqa: PLC0415 -- POSIX-only; a platform without it simply has no lane
        import uuid  # noqa: PLC0415

        d.mkdir(parents=True, exist_ok=True)
        store = d / FLEET_LEASE_FILE
        with open(d / FLEET_LANE_LOCK, "a+") as fh:  # noqa: PTH123, SIM115
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    held = json.loads(store.read_text(encoding="utf-8"))
                    if not isinstance(held, dict):
                        held = {}
                except (OSError, ValueError):
                    held = {}
                live = {
                    k: float(v)
                    for k, v in held.items()
                    # A lease stamped absurdly far ahead is corruption or a clock jump, not a
                    # real holder — dropping it stops one bad write parking the lane for a day.
                    if isinstance(v, (int, float)) and now < float(v) <= now + ttl_s * 8
                }
                if len(live) >= max_concurrent:
                    state.atomic_write(store, json.dumps(live))
                    return None
                lease = uuid.uuid4().hex[:12]
                live[lease] = now + ttl_s
                state.atomic_write(store, json.dumps(live))
                return lease
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:  # noqa: BLE001 -- see the fail-open contract above
        return "lane-unavailable"


def release_fleet_lease(lease: str | None, *, lane_dir: Path | None = None) -> None:
    """Hand a lease back so the next waiter starts immediately. Best-effort by design.

    Releasing is the FAST path, not the correctness path — the TTL in `acquire_fleet_lease` is
    what guarantees the cap unwedges. So every failure here is swallowed: a lost release costs
    one slot for at most `ttl_s`, while raising would propagate into a caller whose only job is
    to shrink a session.
    """
    if not lease or lease.startswith("lane-"):
        return
    d = _lane_dir() if lane_dir is None else lane_dir
    if not d or not str(d):
        return
    try:
        import fcntl  # noqa: PLC0415

        store = d / FLEET_LEASE_FILE
        with open(d / FLEET_LANE_LOCK, "a+") as fh:  # noqa: PTH123, SIM115
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                held = json.loads(store.read_text(encoding="utf-8"))
                if isinstance(held, dict) and held.pop(lease, None) is not None:
                    state.atomic_write(store, json.dumps(held))
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:  # noqa: BLE001 -- the TTL is the real guarantee; see the docstring
        return


def await_fleet_lease(
    *,
    deadline: float,
    max_concurrent: int,
    ttl_s: int,
    lane_dir: Path | None = None,
    now_fn: Callable[[], float] = time.time,
    sleeper: Callable[[float], Any] = time.sleep,
    poll_s: float = FLEET_POLL_S,
) -> str | None:
    """Poll for a lease until one frees or `deadline` passes. None ⇒ the caller must NOT run.

    Waiting (rather than spacing) is what the owner's ~3-minute run time demands: the fourth
    session starts the moment one of the three finishes, so throughput is bounded by the cap and
    not by an ever-growing queue of reservations that would push late sessions past any deadline.
    """
    while True:
        lease = acquire_fleet_lease(
            now=float(now_fn()), max_concurrent=max_concurrent, ttl_s=ttl_s, lane_dir=lane_dir
        )
        if lease is not None:
            return lease
        if float(now_fn()) + poll_s >= deadline:
            return None
        sleeper(poll_s)


# The classified-attempt/retry-loop machinery (OUTCOME_*, SummaryAttempt, classify_llm_ext_
# failure, failure_signature, attempt_llm_ext_summary, summarize_with_retry, _default_jitter)
# moved to `scripts/lib/llm_ext_summary.py` alongside `resolve_llm_ext` (TRDD-RAEGS1D5 card 3
# C2) — see the comment above `DEFAULT_FLEET_LEASE_TTL_S` for why the fleet-lease functions
# themselves stayed here instead of moving with it.


# TRDD-0UQSAFCW: bounded tail read for `recent_messages`, sized off a real measurement (not
# guessed) -- 512 KiB held 32 kept human/assistant lines on a real 4.6 MB / 2233-line heartbeat-
# dominated session transcript (reports/compaction-replacement/…-jev-card-2a.md), comfortably
# above the default `limit=12`. Mirrors the seek-from-EOF shape already used elsewhere in this
# repo (`fleet_scan._tail_lines`, `pre-compact-handoff._TAIL_BYTES`) rather than importing either:
# this module must stay import-light (tests/test_jev_boundary.py) and `pre-compact-handoff.py`
# is a hook script (its own PEP-723 process, not something a lib module may import).
_RECENT_MESSAGES_TAIL_BYTES = 524_288


def _tail_text_lines(path: Path, max_bytes: int) -> list[str]:
    """Text lines of the last `max_bytes` of `path`. [] on any I/O failure (never raises --
    `recent_messages` is on the SessionStart injection path and a bad transcript must not
    block it, matching the OSError handling this replaces)."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            data = fh.read(max_bytes + 1)
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if len(lines) > 1 and size > max_bytes:
        # The seek almost certainly landed mid-record; that partial first line fails
        # json.loads on its own, but dropping it explicitly documents why rather than
        # relying on the parse error to silently absorb it.
        lines = lines[1:]
    return lines


def _record_text(content: Any, *, drop_heartbeat_reply: bool = False) -> str:
    """Join a `message.content`'s `text`-type blocks (or return a plain string as-is).

    TRDD-0UQSAFCW: `drop_heartbeat_reply` checks EACH text block individually before
    joining, mirroring `jev_compaction.extract_items`'s per-block handling (TRDD-RAEGS1D5
    defect 1) -- collapsing the whole message into one string FIRST and checking that would
    let a real text block hide behind a heartbeat-reply block that happens to share the
    message, and would also mis-measure `is_heartbeat_reply`'s own line-count cap against
    text that was never on its own in the transcript.
    """
    if isinstance(content, str):
        if drop_heartbeat_reply and transcript_roles.is_heartbeat_reply(content):
            return ""
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and not (drop_heartbeat_reply and transcript_roles.is_heartbeat_reply(block.get("text", "")))
        ]
        return " ".join(parts)
    return ""


def _classify_line(rec: dict[str, Any]) -> tuple[str, str] | None:
    """`(role_label, text)` for one already-parsed transcript record, or `None` to drop it.

    TRDD-0UQSAFCW follow-up: factored out of the original inline `recent_messages` body so
    the primary-window scan and the extended human-only search (`_recent_human_lines` below)
    can never disagree about what counts as a kept human/assistant line -- the SAME decision,
    made in ONE place. Logic unchanged from the original fix: a `user` record is kept only
    when `transcript_roles.classify_record` says "human"; a mid-turn queued attachment only
    when it is the owner's own words (`commandMode == "prompt"` AND `origin.kind == "human"`);
    an `assistant` record is dropped only for `isApiErrorMessage`, with a bare
    heartbeat-protocol reply block dropped inside `_record_text`.
    """
    if rec.get("isSidechain"):
        return None  # a subagent's own turn, never the main conversation's tail

    msg = rec.get("message") or {}
    entry_type = rec.get("type") or msg.get("role") or ""
    if entry_type == "user":
        if transcript_roles.classify_record(rec) != "human":
            return None
        role_label, text = "USER", _record_text(msg.get("content"))
        # TRDD-DZ1KOGAC: a bare "resume"/"continue"/argument-less "/compact" is still the
        # owner's own words (role stays "human"), but it carries no content -- measured on
        # real transcripts it filled the recent-turns tail with control noise instead of the
        # owner's real instructions. Drop it here, same as `jev_compaction.extract_items`.
        if transcript_roles.is_control_input(text):
            return None
    elif entry_type == "attachment":
        attachment = rec.get("attachment")
        if not isinstance(attachment, dict) or attachment.get("type") != "queued_command":
            return None
        origin = attachment.get("origin")
        origin_kind = origin.get("kind") if isinstance(origin, dict) else None
        if attachment.get("commandMode") != "prompt" or origin_kind != "human":
            return None  # queued task-notification, or a peer/cross-session attachment
        role_label, text = "USER", str(attachment.get("prompt") or "")
        if transcript_roles.is_control_input(text):
            return None
    elif entry_type == "assistant":
        if rec.get("isApiErrorMessage"):
            return None  # a transport-error placeholder, not real assistant output
        role_label = "ASSISTANT"
        text = _record_text(msg.get("content"), drop_heartbeat_reply=True)
    else:
        return None

    text = " ".join(text.split())
    return (role_label, text) if text else None


def _classified_tail_lines(path: Path, max_bytes: int) -> list[str]:
    """`f"{role}: {text}"` for every kept record in the last `max_bytes` of `path`, oldest to
    newest. The one shared parse+classify loop both `recent_messages` and
    `_recent_human_lines` build on."""
    out: list[str] = []
    for raw in _tail_text_lines(path, max_bytes):
        line = raw.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        classified = _classify_line(rec)
        if classified is not None:
            out.append(f"{classified[0]}: {classified[1]}")
    return out


# Follow-up review finding on TRDD-0UQSAFCW's original fix (card 2a): after a long unattended
# stretch the owner's last message can sit further back than the 512 KiB primary window --
# a busy heartbeat-driven session's own turns routinely exceed that on their own, leaving the
# window with NO human line at all even though one exists a bit further back. These three
# constants implement the reviewer's own numbers: widen the search in doubling steps starting
# at 1 MiB, capped at 16 MiB (or the file start, whichever is smaller), aiming to surface the
# last 2-3 owner messages (rounded up to 3 -- never wrong to keep one extra).
_HUMAN_SEARCH_START_BYTES = 1_048_576
_HUMAN_SEARCH_MAX_BYTES = 16 * 1024 * 1024
_HUMAN_TARGET_COUNT = 3

# Shown instead of a silent gap when NO human/owner record exists anywhere within
# `_HUMAN_SEARCH_MAX_BYTES` (or the whole file) -- a resuming session must be able to tell
# "no instruction found" apart from "the extraction silently missed it" (review finding).
_NO_HUMAN_IN_WINDOW = "(last owner message is older than the recent window)"

# Point 4 of the follow-up fix: a BYTE cap on `recent_messages`'s own total output, not just a
# record-count cap. `limit` (record count) does not bound payload SIZE -- one long pasted
# human message, now unconditionally included by the guarantee above, could otherwise make
# this function's own return value unbounded regardless of `limit`. Deliberately looser than
# `compose_handoff`'s own downstream tail budget (~1365 bytes for the shipped 4096-byte
# `HANDOFF_MAX_BYTES`): that budget is per-handoff and already enforced where it matters: this
# is `recent_messages`'s OWN contract, independent of any particular caller.
_RECENT_MESSAGES_MAX_TOTAL_BYTES = 16_384


def _recent_human_lines(path: Path, *, target: int) -> list[str]:
    """The last `target` human/owner lines (oldest to newest), widening the search radius when
    the primary recent window does not hold enough of them.

    TRDD-0UQSAFCW follow-up. Doubles the radius (`_HUMAN_SEARCH_START_BYTES` up) to
    `_HUMAN_SEARCH_MAX_BYTES` or the whole file, whichever is smaller; each retry re-reads
    from EOF rather than threading a delta through, which re-scans the primary window every
    time (ponytail: re-reading up to ~16 MiB once, only on the rare session where the owner
    has been silent for hours, is cheaper than the code a delta-tracking version would need).
    Only HUMAN lines are extracted on these retries -- assistant/system noise in the older
    region is parsed and discarded, never returned (point 1 of the fix: assistant lines stay
    confined to the primary recent window; only owner lines get the extended guarantee).
    `[]` when no human line exists anywhere within the cap.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return []

    radius = _RECENT_MESSAGES_TAIL_BYTES
    while True:
        found = [ln for ln in _classified_tail_lines(path, radius) if ln.startswith("USER: ")]
        if len(found) >= target or radius >= size or radius >= _HUMAN_SEARCH_MAX_BYTES:
            return found[-target:]
        radius = _HUMAN_SEARCH_START_BYTES if radius < _HUMAN_SEARCH_START_BYTES else radius * 2


def _keep_newest_by_bytes(lines: list[str], max_bytes: int) -> list[str]:
    """As many of the NEWEST `lines` as fit in `max_bytes` (drop the oldest first -- the same
    direction `compose_handoff` trims its own tail in, TRDD-PXP08ZQC), but always at least one
    line when `lines` is non-empty (a single oversized line must not vanish outright)."""
    kept_rev: list[str] = []
    spent = 0
    for line in reversed(lines):
        cost = len(line.encode("utf-8")) + 1
        if spent + cost > max_bytes and kept_rev:
            break
        kept_rev.append(line)
        spent += cost
    kept_rev.reverse()
    return kept_rev


def recent_messages(transcript: str, *, limit: int = 12) -> list[str]:
    """Up to `limit` recent conversation-turn `ROLE: text` lines, LED by the last
    `_HUMAN_TARGET_COUNT` owner messages even when they fall outside that window. ZERO model
    tokens.

    Read straight off the JSONL TAIL, so this part of the payload costs nothing and cannot be
    paraphrased — which matters because it is the part a resuming session checks its own
    understanding against. Tool payloads and thinking blocks are skipped: they are the bulk of
    a transcript and the least useful thing to restore into a context we are trying to empty.

    TRDD-0UQSAFCW (card 2a, Jev reference gap analysis §2.1, plus the follow-up review): this
    used to keep EVERY `user`/`assistant` record verbatim and read the whole file. In a
    heartbeat-driven session the tail was almost entirely `[janitor-heartbeat]` prompts, bare
    "janitor heartbeat" replies and `<task-notification>` deliveries, crowding out the human's
    own words out of a small `limit`. First fixed by sharing `transcript_roles.classify_record`
    (card 1, TRDD-RAEGS1D5) with `jev_compaction.py` (see `_classify_line`). The follow-up
    review then found that filtering alone is not enough: after a long unattended stretch the
    owner's last message can sit further back than the primary window ENTIRELY, leaving no
    human line at all. So the owner's last `_HUMAN_TARGET_COUNT` lines are now searched for
    separately (`_recent_human_lines`, widening up to 16 MiB back) and placed FIRST in the
    return value -- so the model reads the instruction before the work it produced -- with an
    explicit placeholder line when none exist at all, never a silent gap. The recent-window
    slice (assistant turns, plus any human turns already inside it) still obeys `limit`;
    duplicates already covered by the guaranteed lines are dropped. The whole return value is
    additionally capped by TOTAL bytes (`_RECENT_MESSAGES_MAX_TOTAL_BYTES`), not just `limit`'s
    record count, protecting against one oversized message alone (point 4 of the fix).
    """
    path = Path(transcript)
    window_lines = _classified_tail_lines(path, _RECENT_MESSAGES_TAIL_BYTES)
    guaranteed_human = _recent_human_lines(path, target=_HUMAN_TARGET_COUNT)
    window_part = [ln for ln in window_lines[-limit:] if ln not in guaranteed_human]
    protected = guaranteed_human if guaranteed_human else [_NO_HUMAN_IN_WINDOW]

    protected_bytes = sum(len(ln.encode("utf-8")) + 1 for ln in protected)
    if protected_bytes >= _RECENT_MESSAGES_MAX_TOTAL_BYTES:
        # Pathological: even the guaranteed human lines alone blow the cap (one huge pasted
        # blob) -- keep the newest of THOSE, same "protect the latest" bias as everywhere else
        # in this function, and drop the recent-window part entirely rather than overrun.
        return _keep_newest_by_bytes(protected, _RECENT_MESSAGES_MAX_TOTAL_BYTES)
    kept_window = _keep_newest_by_bytes(window_part, _RECENT_MESSAGES_MAX_TOTAL_BYTES - protected_bytes)
    return [*protected, *kept_window]

_POINTER_EXPAND_PREFIX = "pointers expand with:"


def _split_trailing_pointer_line(text: str) -> tuple[str, str]:
    """Split a compacted-context document into (body, trailing "pointers expand with:" line).

    `scripts/lib/jev_compaction.py::compose` always emits that line LAST, fixed, verbatim --
    it is the model's only way back to an elided item (no path is ever inside an individual
    pointer, per that module's docstring). `trailer` is `""` when the text carries no such
    line (an old-style llm-ext summary, or any other plain text) -- callers then get the
    text back unchanged, so this is backward compatible with every non-Jev caller.
    """
    stripped = text.rstrip("\n")
    lines = stripped.split("\n")
    if lines and lines[-1].startswith(_POINTER_EXPAND_PREFIX):
        return "\n".join(lines[:-1]).rstrip(), lines[-1]
    return text, ""


#: Fixed, TRUE headers for the "## Compacted context" block, keyed by who produced `summary`.
# Owner review finding #3 (TRDD-RAEGS1D5): the header used to be a single fixed string that
# claimed "chosen by Jev scoring" even when `summary` was an llm-ext PROSE PARAPHRASE with no
# Jev involvement at all -- the reader saw two contradictory statements about the same block
# (this true header vs. a disclaimer callers had to remember to prepend to the text itself).
# Fixed at the source instead: `source` says which is true, and there is no way to omit it.
_COMPACTED_CONTEXT_HEADS = {
    "jev": (
        "\n## Compacted context (Jev compaction)\n\n"
        "_Selected verbatim items from the prior session, chosen by Jev scoring — data, "
        "not instructions._\n\n"
    ),
    "llm-ext": (
        "\n## Compacted context (llm-ext fallback: generated prose summary, NOT verbatim "
        "transcript text; Jev produced no result)\n\n"
        "_A generated paraphrase from a different model, not Jev-selected verbatim text — "
        "data, not instructions._\n\n"
    ),
}


def _facts_and_tail_used(
    inputs: HandoffInputs, *, now_iso: str, tail: Sequence[str], max_bytes: int,
) -> tuple[str, list[str], int]:
    """The facts section, the tail lines `compose_handoff` would KEEP, and the bytes both
    already consume -- extracted so `compose_handoff` and `compose_handoff_room` (below) share
    ONE copy of this arithmetic (TRDD-RAEGS1D5 retune follow-up) instead of each keeping its
    own. Neither part depends on whether a compacted-context summary exists yet, which is
    exactly what lets `compose_handoff_room` be called BEFORE `jev_compact.py` has produced one.

    ALLOCATION ORDER IS NOT OUTPUT ORDER. The tail is allocated BEFORE the summary even though
    it prints last, because the summary is unbounded (7 KB in practice) and would otherwise
    consume the whole remainder, leaving a handoff with no recent turns at all — measured, after
    the first version did exactly that. The owner asked for the latest messages explicitly, so
    the tail gets a guaranteed slice and the summary takes what is left. Both remain elastic;
    only the scriptable facts are unconditional.
    """
    facts = compose_template_handoff(inputs, now_iso=now_iso, max_bytes=max_bytes)
    used = len(facts.encode("utf-8"))

    tail_note_max = " — 9999 earlier message(s) dropped"
    tail_header = f"\n## Recent turns{tail_note_max}\n\n"
    tail_budget = min(max_bytes // 3, max(0, max_bytes - used - 200))
    kept: list[str] = []
    if tail and tail_budget > len(tail_header.encode("utf-8")):
        spent = len(tail_header.encode("utf-8"))
        for line in reversed(list(tail)):  # the OLDEST end is what gets dropped
            cost = len(line.encode("utf-8")) + 1
            if spent + cost > tail_budget:
                break
            kept.append(line)
            spent += cost
        kept.reverse()
        used += spent
    return facts, kept, used


#: The fixed truncation-notice string `compose_handoff` appends to a sliced summary body, and
#: the SAME string `compose_handoff_room` reserves bytes for -- one literal, not two copies that
#: could drift apart (TRDD-RAEGS1D5 retune follow-up).
_TRUNCATION_NOTICE = "\n\n_(summary truncated to fit the handoff budget)_"


def compose_handoff_room(
    inputs: HandoffInputs,
    *,
    now_iso: str,
    tail: Sequence[str] = (),
    max_bytes: int = HANDOFF_MAX_BYTES,
    source: str,
) -> int:
    """The byte room `compose_handoff` will leave for a compacted-context summary body,
    computed the SAME way `compose_handoff` itself computes it (both call
    `_facts_and_tail_used` -- one copy of the arithmetic) -- callable BEFORE `jev_compact.py`
    has produced a summary at all, so a lane can size `--inject-max-bytes` to the room that
    actually exists instead of a fixed guess.

    TRDD-RAEGS1D5 retune follow-up: `LANE_COMPACTED_MAX_BYTES` used to be a flat constant
    forwarded to every compaction regardless of how much of `compose_handoff`'s own budget the
    facts section (in-flight cards, findings) and the recent-turns tail had already spent.
    Whenever that flat constant overran the REAL remaining room, `compose_handoff`'s own raw
    byte-slice (`raw[:room]`) cut the TAIL of the injected Jev summary -- the newest kept items
    and the trailing "pointers expand with:" pointer line -- instead of Jev's own
    priority-aware trim ever getting a chance to decide what to drop.

    Omits the bytes `compose_handoff` reserves for a REAL summary's own trailing pointer line
    (unknown here -- no summary exists yet): measured, that line is a few hundred bytes at most
    (see `jev_compaction_lane.LANE_ROOM_SAFETY_MARGIN_BYTES`'s own commentary), a rounding
    error against a multi-KB room -- callers subtract a small safety margin on top of this
    return value to cover it, rather than this function guessing at a summary that does not
    exist yet.
    """
    if source not in _COMPACTED_CONTEXT_HEADS:
        raise ValueError(
            f"compose_handoff_room: unknown source {source!r}, expected one of "
            f"{sorted(_COMPACTED_CONTEXT_HEADS)}"
        )
    _facts, _kept, used = _facts_and_tail_used(inputs, now_iso=now_iso, tail=tail, max_bytes=max_bytes)
    head = _COMPACTED_CONTEXT_HEADS[source]
    reserved = len(head.encode("utf-8")) + len(_TRUNCATION_NOTICE.encode("utf-8")) + 8
    return max_bytes - used - reserved


def compose_handoff(
    inputs: HandoffInputs,
    *,
    now_iso: str,
    summary: str | None,
    source: str,
    tail: Sequence[str] = (),
    max_bytes: int = HANDOFF_MAX_BYTES,
) -> str:
    """The full injected payload: scriptable facts + the compacted context + a TRUNCATED tail.

    `source` selects the TRUE header for the compacted-context block from
    `_COMPACTED_CONTEXT_HEADS` ("jev" or "llm-ext") -- required, no default, so a caller cannot
    forget to say which producer made `summary` and silently ship the wrong claim.

    `summary` is the TEXT of `jev_compact.py compact`'s output file (TRDD-RAEGS1D5 card 3) --
    the janitor's ONLY automatic shrink, per docs_dev/jev-compaction-spec.md. It replaced the
    llm-ext summary this composer used to take (the parameter name stays `summary` -- callers
    pass the compacted-context text through the same slot; renaming it would touch every call
    site for no behaviour change).

    THE HARD CONSTRAINT (owner, 2026-08-12): the injection must not refill the context it was
    built to empty. A handoff that restores a large payload at session start pays back the
    cache-write we just avoided, one turn later — so the WHOLE payload carries one budget, not
    one per part. Three "small" parts add up.

    Priority under that single budget, and the order is the design:
      1. the scriptable facts — small, load-bearing, and the part that must never be
         paraphrased, so it is composed FIRST and always survives;
      2. the compacted context — high value, absent whenever the CLI failed;
      3. the message tail — the ELASTIC part, trimmed from the OLDEST end because a resuming
         session needs the most recent exchanges.

    Truncation is STATED, never silent: a clipped tail reads as a complete record, which is
    worse than an explicitly short one — the reader cannot tell that anything is missing.
    """
    # Validated HERE, unconditionally -- not left to the `if summary:` branch below that
    # happens to index `_COMPACTED_CONTEXT_HEADS[source]`. A `summary=None` call (jev_compact
    # produced nothing) never reaches that branch, so an invalid `source` would otherwise pass
    # silently through the one call shape most likely to carry a typo'd value (review finding).
    if source not in _COMPACTED_CONTEXT_HEADS:
        raise ValueError(f"compose_handoff: unknown source {source!r}, expected one of {sorted(_COMPACTED_CONTEXT_HEADS)}")
    facts, kept, used = _facts_and_tail_used(inputs, now_iso=now_iso, tail=tail, max_bytes=max_bytes)

    summary_part = ""
    if summary:
        # THE TRAILING "pointers expand with:" LINE MUST SURVIVE TRUNCATION (owner, card 3):
        # it is the model's ONLY way back to an elided item -- a `jev_compact.py compact`
        # document (scripts/lib/jev_compaction.py::compose) always ends with this one fixed
        # line, and a naive byte-slice truncation (the old `raw[:room]`, which just cut
        # wherever `room` landed) could and did drop it whenever the compacted context ran
        # long. Split it off FIRST and re-attach it unconditionally, so the budget cut can only
        # ever eat into the body above it. A plain llm-ext-style string (no such trailing line,
        # kept for callers that still pass one) falls through unchanged -- `trailer` is "".
        body_text, trailer = _split_trailing_pointer_line(summary)
        trailer_block = f"\n\n{trailer}" if trailer else ""
        # The framing line is not decoration: this block is either MODEL OUTPUT or Jev-selected
        # VERBATIM transcript, and the next session reads the handoff as its own state. Without
        # it the reader cannot tell its own notes from injected data — the channel through
        # which the 2026-08-18 refusal was read as a finding about this plugin rather than as a
        # failed summary. `source` picks the TRUE header (see `_COMPACTED_CONTEXT_HEADS`) --
        # an unknown source is a caller bug and fails fast with a KeyError rather than silently
        # falling back to the wrong claim.
        head = _COMPACTED_CONTEXT_HEADS[source]
        # The truncation NOTICE is charged before slicing, not appended after. Appending it to
        # a body already filled to `room` overran by exactly its own length every time
        # (measured: +38 at every budget — a constant offset is the signature of a fixed-size
        # string added outside the accounting).
        reserved = (
            len(head.encode("utf-8")) + len(_TRUNCATION_NOTICE.encode("utf-8"))
            + len(trailer_block.encode("utf-8")) + 8
        )
        room = max_bytes - used - reserved
        if room > 400:
            raw = body_text.encode("utf-8")
            body = raw[:room].decode("utf-8", "ignore").rstrip()
            if len(raw) > room:
                body += _TRUNCATION_NOTICE
            summary_part = head + body + trailer_block
        elif trailer:
            # Even under extreme budget pressure (no room for any body), the pointer line is
            # the model's only way back to everything elided — try to keep it. But this must
            # still respect `max_bytes` itself (the hard constraint above applies here too, not
            # just to the body slice): a facts section that alone already consumes the whole
            # budget (many findings/cards) leaves no room even for the pointer line, and adding
            # it anyway would silently blow the very budget this function exists to enforce.
            # MEASURED (this file's own test suite): a 40-finding facts section overran a
            # 1400-byte budget by 258 bytes because this branch used to add the trailer
            # unconditionally. Drop the whole compacted-context section instead — the facts
            # already carry the load-bearing pointers (memgrep recall, cards, commits).
            minimal = head.rstrip("\n") + trailer_block
            if used + len(minimal.encode("utf-8")) <= max_bytes:
                summary_part = minimal

    parts = [facts]
    if summary_part:
        parts.append(summary_part)
    if kept:
        dropped = len(tail) - len(kept)
        note = f" — {dropped} earlier message(s) dropped" if dropped else ""
        parts.append(f"\n## Recent turns{note}\n\n" + "\n".join(kept))
    return "\n".join(parts)


# --- pure policy ------------------------------------------------------------


def seconds_until_next_fire(cron: str, now: int) -> int | None:
    """Seconds from `now` until the next `*/N * * * *` fire, or None when the cron is not that
    shape. PURE apart from reading the LOCAL timezone (cron fires on local wall-clock).

    Only the minute-step form the janitor arms is understood — anything else returns None so the
    caller falls back to "unknown headroom" rather than inventing a schedule from a cron it
    cannot actually read (the same contract as `orphaned_resume.cadence_seconds`).

    The wrap is computed over the real minute-of-hour set, not by adding the step: cron's `*/7`
    fires at minutes 0,7,…,56 and then 0, a FOUR-minute gap. `cur_min + step` would report 7
    there and we would think we had headroom we do not have.
    """
    field_min = (cron or "").strip().split(" ")[0] if cron else ""
    if not field_min.startswith("*/"):
        return None
    step_raw = field_min[2:]
    if not step_raw.isdigit():
        return None
    step = int(step_raw)
    if step <= 0 or step > 59:
        return None
    tm = time.localtime(now)
    fire_minutes = [m for m in range(60) if m % step == 0]
    later = [m for m in fire_minutes if m > tm.tm_min]
    if later:
        minutes_ahead = later[0] - tm.tm_min
    else:
        minutes_ahead = (60 - tm.tm_min) + fire_minutes[0]
    return minutes_ahead * 60 - tm.tm_sec


def _log_clear_decision(label: str, verdict: ClearVerdict, *, context_tokens: int | None) -> None:
    """Card 1 items 2+7 (TRDD-L32WC0H7): every clear decision — fire OR decline — gets ONE log
    line naming the context-token reading it used (`context=unmeasurable` when the transcript
    couldn't be measured) and the harness's live `autoCompactEnabled` setting.

    WHY THIS LIVES HERE, NOT INSIDE THE DECIDE FUNCTIONS: `_should_clear_on_resume_decide` /
    `_should_clear_externally_decide` are exercised directly, by name, as PURE functions over
    injected facts across the whole existing test suite (`test_external_clear.py`'s own module
    docstring: "every gate here is a PURE function over injected facts, so the tests call it
    directly") — an I/O side effect inside them would contradict that contract without changing
    a single assertion, which is exactly the kind of silent regression this project's mutation
    tests exist to catch. Putting the log write in the thin `should_clear_*` wrappers instead
    keeps the decision pure and testable while still guaranteeing every REAL caller (there is
    exactly one production entry point per gate) gets the log line — a root-cause fix in the one
    place both callers route through, not a copy pasted into each.

    Best-effort: a log failure must never break the decision it only records.
    """
    try:
        ctx = "unmeasurable" if context_tokens is None else str(context_tokens)
        state.log_line(
            label,
            f"{'fire' if verdict.fire else 'decline'} trigger={verdict.trigger or '-'} "
            f"context={ctx} autoCompactEnabled={harness_auto_compacts()} why={verdict.why}",
        )
    except Exception:  # noqa: BLE001 -- logging must never break the caller's decision
        pass


def next_fire_misses_cache(
    *,
    last_turn_age_s: int | None,
    seconds_to_next_fire: int | None,
    ttl_minutes: int,
) -> bool:
    """PURE. Will the NEXT heartbeat fire land on an EXPIRED prompt cache (and so pay the full
    cache-creation write on this session's whole context)?

    This is the card's trigger, expressed as the question that actually costs money. Asking
    instead whether the cache is *already* cold makes the lever unreachable whenever the cadence
    is faster than the TTL — which is the normal, healthy configuration (see the module
    docstring's measurement).

    Unknown inputs return False: an unknown schedule or an unmeasurable transcript is not
    evidence that a miss is coming, and the long-idle trigger still covers the abandoned case.
    """
    if last_turn_age_s is None or seconds_to_next_fire is None:
        return False
    if ttl_minutes <= 0:
        return False
    return (last_turn_age_s + seconds_to_next_fire) >= ttl_minutes * 60


def _should_clear_on_resume_decide(
    *,
    source: str,
    cache_expired: bool | None,
    context_tokens: int | None,
    min_context: int,
    in_cooldown: bool,
    already_fired_this_session: bool,
    recovery_pending: bool = False,
) -> ClearVerdict:
    """PURE. Shrink a session that was RESUMED onto a dead prompt cache, before its first turn.

    A SEPARATE predicate from `should_clear_externally`, not a relaxation of it, because the two
    protect different things and the difference is the whole safety argument.

    `should_clear_externally` vetoes on `user_present` and on an unknown `idle_seconds`: it
    hunts ABANDONED sessions, and `/clear` is unrecoverable, so it must never fire into a pane
    somebody is working in. On a resume BOTH of those vetoes are structurally true — the user
    just launched the thing, idle is zero — so reusing that gate here would refuse every time.
    That is exactly why this path was never finished.

    What makes clearing legitimate here is not that the vetoes were inconvenient, it is that
    the hazard they guard against does not exist yet: at SessionStart NO turn has run in this
    session. There is no in-flight work to destroy, no half-finished tool call, nothing the
    user is mid-sentence on. The transcript is on disk and the summary is composed from it.

    The cost of NOT firing is the reason the window matters: with a dead cache the very first
    turn re-reads the whole context at full price. On a ~700k session across a fleet of
    concurrent sessions that is the single most expensive event the janitor can prevent, and it
    is preventable only in the gap between "loaded" and "first turn" — a gap nothing else
    watches.

    The vetoes that DO survive, and why each one is load-bearing:

      * `source` — must be a genuine load-after-away (`RESUME_SOURCES`). `compact`/`clear` are
        re-entries into a just-shrunk session; acting on them loops forever.
      * `cache_expired is not True` — the ENTIRE point. `False` means the cache is warm and
        clearing would THROW AWAY a live cache to save nothing; `None` means agentlensPro could
        not answer, and an unknown must never authorize a destructive act (the same asymmetry
        `probe_cache_expired` documents).
      * `in_cooldown` — shared with every other clear lever, so whichever fired first stands
        the rest down.
      * `already_fired_this_session` — belt to the cooldown's braces, keyed on the session id:
        if SessionStart is ever delivered twice for one session, the second is a no-op.
      * `recovery_pending` (card 1 item 5, TRDD-L32WC0H7; owner: "beware of ... truncating
        other operations, like resuming after api error or model expired time limit window") —
        a rate-limit / API-error / compact / clear resume cue is still armed, unconsumed, on
        disk. The "no in-flight work to destroy" premise this whole gate rests on (see above)
        is FALSE exactly then: a `SessionStart` can land while `dispatch.py`'s own heartbeat has
        not yet run the phase that would replay the interrupted task to the model. Clearing in
        that window destroys the context the pending resume cue is about to need, before the
        cue is ever read — silently truncating the recovery the owner named. The CALLER (this
        gate's only production entry point, `scripts/hooks/on-session-start-cold-cache-clear.py`)
        computes this from the same three flag files `dispatch._cadence_active_waiting` checks;
        it is a plain bool here so the gate itself stays free of filesystem I/O.

    SUPERSEDED 2026-09-22 (TRDD-L32WC0H7 card 1 item 1): `context_tokens is None` used to NOT
    veto here either, "matching" the sibling gate's now-reversed shape. Both flip together: an
    unmeasurable transcript vetoes on the floor exactly like a too-small one. A KNOWN-small
    context still vetoes — under `min_context` there is nothing worth reclaiming and a clear
    would cost the user their scrollback for no gain.
    """
    if source not in RESUME_SOURCES:
        return ClearVerdict(False, why=f"source={source or '?'} — not a load-after-away")
    if already_fired_this_session:
        return ClearVerdict(False, why="already fired for this session")
    if recovery_pending:
        return ClearVerdict(False, why="recovery cue pending — not truncating the resume")
    if in_cooldown:
        return ClearVerdict(False, why="cooldown")
    if cache_expired is not True:
        return ClearVerdict(
            False,
            why="cache warm" if cache_expired is False else "cache state unknown — not clearing",
        )
    # INVERTED alongside `should_clear_externally` (card 1 item 1) — see that function's own
    # comment for the why; the two gates must not diverge on the same question.
    if context_tokens is None or context_tokens < min_context:
        return ClearVerdict(
            False,
            why=(
                "context unmeasurable — treated as below floor"
                if context_tokens is None
                else f"context {context_tokens} < {min_context} — nothing worth reclaiming"
            ),
        )
    return ClearVerdict(
        True,
        TRIGGER_RESUMED_COLD,
        f"resumed on a dead cache (context={context_tokens if context_tokens is not None else '?'})"
        " — shrinking before the first turn pays full price for it",
    )


def should_clear_on_resume(
    *,
    source: str,
    cache_expired: bool | None,
    context_tokens: int | None,
    min_context: int,
    in_cooldown: bool,
    already_fired_this_session: bool,
    recovery_pending: bool = False,
) -> ClearVerdict:
    """PUBLIC entry point. Decides via `_should_clear_on_resume_decide` (kept PURE — see its own
    docstring for the whole policy) then logs the decision (card 1 items 2+7). Review note: THIS
    wrapper is NOT the pure function the "tests call directly with injected facts" claim is
    about — `_should_clear_on_resume_decide` is, and it stays free of the log write. This wrapper
    is the ONE place the real SessionStart caller routes through, so it is also the one place
    that needs to know how to log.

    `recovery_pending` DEFAULTS FALSE, deliberately: `external_handoff_clear.py::_decide` (the
    watcher's own confirmatory re-check, spawned only AFTER the SessionStart hook's own call to
    this same function already vetoed on it) calls this without the argument, and must keep
    working unchanged — it is not this repo's file to edit for card 1. The hook is the real gate.
    """
    verdict = _should_clear_on_resume_decide(
        source=source,
        cache_expired=cache_expired,
        context_tokens=context_tokens,
        min_context=min_context,
        in_cooldown=in_cooldown,
        already_fired_this_session=already_fired_this_session,
        recovery_pending=recovery_pending,
    )
    _log_clear_decision("clear-on-resume", verdict, context_tokens=context_tokens)
    return verdict


def cache_certainly_expired(project_dir: str | Path | None = None) -> bool | None:
    """The REACTIVE trigger's input: is this project's prompt cache ALREADY cold?

    Tri-state, straight through from `agentlens_probe.probe_cache_expired` — `None` means
    "no signal" (agentlensPro absent, disabled, or unable to answer) and MUST NOT be read as
    `False`. Impure and injectable-free by design: the decision itself stays pure, and this is
    the one I/O call feeding it.

    Why this exists next to `next_fire_misses_cache` rather than instead of it: the predictive
    path can only see expiries the SCHEDULE implies. The card names the ones it cannot — an API
    error that ended a turn, an AskUser prompt nobody answered, a network gap — where no fire
    happened at all and the cache died unobserved. Conversely this one cannot pre-empt the
    restart case, because by the time it says "expired" the miss is already unavoidable on the
    next turn. Each covers the other's blind spot; either alone is a partial feature.
    """
    command = os.environ.get(CACHE_EXPIRED_COMMAND_ENV, alp.DEFAULT_CACHE_EXPIRED_COMMAND)
    return alp.probe_cache_expired(command, project=str(project_dir) if project_dir else None)


def recovery_pending(state_dir: Path) -> bool:
    """True iff a rate-limit / API-error / compact / clear resume cue is still armed,
    unconsumed, on disk for this state dir (card 1 item 5 follow-up, TRDD-L32WC0H7).

    SHARED HELPER (TRDD-L32WC0H7 card 1 follow-up item 2): this used to be three separate
    inline copies of the same three-flag check -- the SessionStart hook
    (on-session-start-cold-cache-clear.py), dispatch.py's own _cadence_active_waiting, and
    (missing entirely, the actual bug this closes) external_handoff_clear.py's own _decide.
    One shared helper means the allow-list of pending-recovery flags can never drift between
    callers, and a caller that forgets it (as _decide did) is no longer possible by omission.

    WHY these three flags name the "recovery is in flight" window: state.RATE_LIMITED_FLAG
    covers both a rate-limit and a generic API error (StopFailure writes one flag for both);
    resume-after-compact.flag / resume-after-clear.flag are the post-shrink resume directives
    dispatch.py's own _phase_compact_resume / _phase_clear_resume consume. Each is unlinked by
    its own phase, so a caller that finds one here knows the interrupted task has NOT yet been
    replayed to the model, and a /clear right now would destroy the context that replay is
    about to need before it is ever read.

    Best-effort, fail-open (a read error reads as "nothing pending") -- the SAME asymmetry
    _fire_recorded already documents: a missed veto costs one wrongly-cleared session, a false
    one costs the whole lever, silently, on every resume.
    """
    try:
        return any(
            (state_dir / flag).is_file()
            for flag in (state.RATE_LIMITED_FLAG, "resume-after-compact.flag", "resume-after-clear.flag")
        )
    except OSError:
        return False


def cache_expired_from_harness_payload(payload: Mapping[str, object]) -> bool | None:
    """PURE. The FIRST-PARTY answer to `cache_certainly_expired`'s question (TRDD-GK35MOXU).

    CC >= 2.1.251's SessionStart resume payload carries `prompt_cache_likely_expired` — the
    harness's OWN verdict, computed with information (its internal cache bookkeeping) that no
    external probe can see. When present it OUTRANKS `cache_certainly_expired`'s agentlensPro
    subprocess: no probe latency, no third-party dependency, and it is the harness answering
    about itself rather than a heuristic re-derivation of the same fact from the outside.

    Field name is UNDOCUMENTED in the CC changelog — bound from a live 2.1.251+ resume payload
    observed on disk (`.janitor/state/session-staleness.json`, written defensively by
    `on-session-start.py` since it shipped). Missing or non-bool => `None` (no signal; the
    caller falls back to the agentlensPro probe, exactly as it did before this existed).
    """
    v = payload.get("prompt_cache_likely_expired")
    return v if isinstance(v, bool) else None


def cache_expired_by_age(last_turn_age_s: int | None, *, ttl_minutes: int) -> bool | None:
    """PURE. `True` when elapsed time ALONE makes cache expiry certain; `None` when it does not.

    THE DEFECT THIS CLOSES (TRDD-CEWVQ8DG, measured): `should_clear_on_resume` demands
    `cache_expired is True`, and its only source was `cache_certainly_expired` — a probe of the
    OPTIONAL agentlensPro CLI. On any host without it the probe abstains, the gate refuses
    (`why=cache state unknown — not clearing`), and a fleet of cold resumes each pays a full
    cache-creation write on its first turn. A lever reachable only when a third-party tool happens
    to be installed is the shape this codebase has already shipped twice and warns about twice:
    "a threshold high enough to never be met is a feature that does not exist".

    Elapsed time answers the same question without asking anyone: past `CERTAIN_EXPIRY_FLOOR_MINUTES`
    no prompt cache survives, so the age IS the verdict.

    **It never returns `False`**, and that is the load-bearing asymmetry rather than an oversight.
    "Not yet certainly dead" is not "alive": a `False` here would override a probe that said the
    cache HAD expired, converting a working signal into a refusal — the very failure being fixed.
    Only `True` (certain) and `None` (unknown) are expressible, so this can add certainty and can
    never remove it.
    """
    if last_turn_age_s is None:
        return None
    floor = max(int(ttl_minutes), CERTAIN_EXPIRY_FLOOR_MINUTES)
    return True if last_turn_age_s >= floor * 60 else None


def resolve_cache_expired(
    probe: bool | None, *, last_turn_age_s: int | None, ttl_minutes: int
) -> bool | None:
    """The cache-expiry verdict: the probe when it can answer, elapsed time when it cannot.

    ORDER IS THE SAFETY ARGUMENT. A probe that answered — `True` OR `False` — is taken verbatim,
    because it observes the cache directly and this arithmetic only bounds it. In particular a
    `False` (warm) survives an ancient transcript mtime: clearing there would throw away a LIVE
    cache and destroy the context for nothing. Only a `None` falls through.

    So the composition is strictly ADDITIVE — it can turn "unknown" into "certainly expired", and
    can never turn "warm" into a clear.
    """
    if probe is not None:
        return probe
    return cache_expired_by_age(last_turn_age_s, ttl_minutes=ttl_minutes)


@dataclass(frozen=True)
class ClearVerdict:
    """Whether to clear, which rule decided it, and a human-readable why.

    `why` is populated on BOTH branches on purpose. A refusal that cannot explain itself is how
    a silently-dead lever looks from the outside, and this project has shipped that twice.
    """

    fire: bool
    trigger: str = ""
    why: str = ""


def _should_clear_externally_decide(
    *,
    idle_seconds: int | None,
    last_turn_age_s: int | None,
    ttl_minutes: int,
    seconds_to_next_fire: int | None,
    context_tokens: int | None,
    min_context: int,
    min_idle_s: int,
    headroom_s: int,
    active_waiting: bool,
    in_cooldown: bool,
    awaiting_user: bool,
    cache_expired: bool | None = None,
    context_high_water: int = 0,
    recovery_pending: bool = False,
) -> ClearVerdict:
    """PURE. The whole external-clear decision, with the deciding rule named.

    THE USER'S PRESENCE IS NOT AN INPUT HERE, AND MUST NOT BE RE-ADDED (owner, 2026-08-13:
    *"my presence must not even be mentioned"*). It used to be the first veto -- `user_present`
    -> refuse -- which is what left this whole lever dead: the injection layer migrated to the
    three ratified rules on 2026-08-02 (`terminal_trigger.inject_until_sent`: inject only into
    an empty field, STOP the moment a key is typed, retry 8 s later, never cancel), but the
    DECISION layer never followed. So the gate kept answering "user-present" and the injector
    that would have politely deferred was never even asked. Presence is now handled in exactly
    one place -- the injector -- where it DELAYS by 8 s per keystroke and never refuses. A veto
    here would silently re-break that, because a refusal at this layer never reaches the
    injector at all.

    Vetoes, in the order they are cheapest to establish:

      * `recovery_pending` (TRDD-L32WC0H7 card 1 follow-up item 2; owner: "beware of ...
        truncating other operations, like resuming after api error or model expired time
        limit window") -- a rate-limit / API-error / compact / clear resume cue is still
        armed, unconsumed, on disk (`external_clear.recovery_pending`). This is the DAEMON
        lane's own copy of the guard `should_clear_on_resume` already had: the abandoned-
        session watcher runs from a SEPARATE process with no relationship to this session's
        own heartbeat phase order, so it can fire WHILE dispatch.py has not yet replayed an
        interrupted task to the model. Clearing into that window destroys the context the
        pending cue is about to need before it is ever read.
      * `in_cooldown`    -- a clear already fired recently. Shared with the in-model lever via
        `cold_cache_compact`'s `idle-clear-fired.ts`, so whichever path fires first stands the
        other down. That sharing IS the coexistence contract while both exist.
      * `active_waiting` -- a resume or a background agent is in flight. NOT about the user:
        this is machine state, and firing into it would type over a chain already running.
      * `awaiting_user`   -- the transcript tail ends on an unanswered HUMAN-FACING `tool_use`
        (`ExitPlanMode` / `AskUserQuestion` -- see `fleet_scan.awaiting_user_decision`). This is
        NOT the removed `user_present` veto: that one refused on the user's mere presence and
        broke the whole lever (2026-08-13). This one refuses only when the session is parked on
        a QUESTION addressed to a person -- idle by construction, satisfies the long-idle trigger,
        and would otherwise be `/clear`ed with the pending decision lost (TRDD-OO301H7D). `--force`
        must NOT be able to override this: it is a SAFETY veto, not a trigger term.
      * `idle_seconds is None` -- an UNKNOWN idle age must never authorize a destructive action.
        Note the deliberate asymmetry with `context_tokens`, below.
      * headroom -- a fire is imminent, so the chain would be typing into a session mid-turn.
        Wait for the next gap; nothing is lost, the gap recurs every cadence period. An UNKNOWN
        headroom (a cron shape we cannot read) does NOT veto -- that would make an unreadable
        cron silently disable the lever.

    Then the three triggers, OR'd (see the module docstring for why none subsumes the others).
    `cache_expired` is the agentlensPro MEASUREMENT and is checked first, ahead of the
    prediction that models the same cost -- when both agree, attributing the fire to the
    measurement is what makes the log line worth reading. Its `None` is "no signal", never
    `False`: an absent CLI must leave the other two triggers exactly as they were.

    SUPERSEDED 2026-09-22 (TRDD-L32WC0H7 card 1 item 1): `context_tokens is None` USED TO skip
    the size clause and let the idle/miss terms decide alone (owner directive 2026-08-04, dated
    correction -- that directive was about the SEPARATE `should_clear_when_long_idle` idle-time
    lever, not this size floor, and reusing its reasoning here was the bug). An unmeasurable
    context now VETOES on the floor exactly like a too-small one: "we don't know if there is
    anything worth reclaiming" and "there is nothing worth reclaiming" both mean the same thing
    to a gate that must justify a destructive `/clear`.
    """
    if recovery_pending:
        return ClearVerdict(False, why="recovery cue pending -- not truncating the resume")
    if in_cooldown:
        return ClearVerdict(False, why="cooldown")
    if active_waiting:
        return ClearVerdict(False, why="active-waiting")
    if awaiting_user:
        return ClearVerdict(False, why="awaiting-user")
    if idle_seconds is None:
        return ClearVerdict(False, why="idle-unknown")
    if seconds_to_next_fire is not None and seconds_to_next_fire < headroom_s:
        return ClearVerdict(
            False, why=f"no-headroom ({seconds_to_next_fire}s < {headroom_s}s to next fire)"
        )
    # CONTEXT PRESSURE FIRST -- its alternative is not a wasted cache write, it is a session that
    # STOPS. With `autoCompactEnabled: false` the harness no longer rescues a full window; it
    # errors. Every other trigger here is an economy (avoid paying for a cold cache); this one is
    # survival, so it outranks them. It is also the only trigger that can fire on a BUSY session,
    # which is precisely the case the other four structurally cannot reach.
    # `context_high_water == 0` now means BOTH "not configured" and "the harness still owns
    # compaction" -- the caller resolves ownership (`harness_auto_compacts`) and passes 0 when the
    # janitor must stay out of the way. Keeping that decision in the CALLER leaves this function
    # pure and keeps the two questions separate: this one asks "is the context too big", never
    # "whose job is it".
    #
    # IT MUST SIT ABOVE THE `min_context` FLOOR, and "FIRST" in the paragraph above was not
    # rhetoric -- it used to be checked BELOW it and was therefore unreachable on every 200 K
    # model. The floor is 300 K (`DEFAULT_MIN_CONTEXT_TOKENS`) while `context_high_water`
    # resolves from `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, which is under 200 K there: a session at
    # 170 K with auto-compact off -- exactly the case this trigger exists for -- was refused with
    # "nothing worth reclaiming" and rode on into the hard context-limit error. The floor asks
    # "is this big enough to be worth a clear"; a context at or above the high-water mark has
    # already answered that, and the two can only disagree when the floor is the higher number.
    if (
        context_high_water > 0
        and context_tokens is not None
        and context_tokens >= context_high_water
    ):
        return ClearVerdict(
            True,
            TRIGGER_CONTEXT_PRESSURE,
            f"context {context_tokens} >= high-water {context_high_water} and the harness no "
            "longer auto-compacts -- without a clear this session stops at the context limit",
        )
    # INVERTED, card 1 item 1 (owner, 2026-09-22 spec, superseding the 2026-08-04 directive this
    # branch used to cite in its own name): an UNMEASURABLE context must NOT skip the min-context
    # floor, it must FAIL it. The old `context_tokens is not None and ...` shape let a transcript
    # that could not be measured slide past the floor and decide on `cache_expired`/idle alone --
    # exactly backwards for a gate whose whole job is "is there enough here to be worth a
    # destructive `/clear`": not knowing the size is the ONE case where the honest answer is
    # "assume no". `context_tokens is None` now reads as "unmeasurable => below the floor".
    #
    # CARD 1 FOLLOW-UP item 1 (TRDD-L32WC0H7): the "unmeasurable" a caller passes here is never
    # a raw None straight off `token_meter` any more -- every production caller now derives it
    # from the transcript first (`cold_cache_compact.context_tokens_for` / the resume-lane
    # widened reader in the SessionStart hook) before conceding "genuinely unmeasurable". This
    # gate stays pure and keeps refusing on a TRUE None; it is the callers' job to have already
    # tried the transcript.
    if context_tokens is None or context_tokens < min_context:
        return ClearVerdict(
            False,
            why=(
                "context unmeasurable -- treated as below floor"
                if context_tokens is None
                else f"context {context_tokens} < {min_context} -- nothing worth reclaiming"
            ),
        )

    if cache_expired is True:
        return ClearVerdict(
            True,
            TRIGGER_CACHE_CERTAIN_EXPIRED,
            "agentlensPro reports this session's prompt cache is ALREADY expired -- the next "
            "turn pays a full cache-creation write on the whole context",
        )
    if next_fire_misses_cache(
        last_turn_age_s=last_turn_age_s,
        seconds_to_next_fire=seconds_to_next_fire,
        ttl_minutes=ttl_minutes,
    ):
        return ClearVerdict(
            True,
            TRIGGER_NEXT_FIRE_MISSES,
            f"next fire lands {last_turn_age_s}+{seconds_to_next_fire}s after the last turn, "
            f"past the {ttl_minutes}min cache TTL -- it would pay a full miss",
        )
    if idle_seconds >= min_idle_s:
        return ClearVerdict(
            True,
            TRIGGER_LONG_IDLE,
            f"nothing but heartbeats for {idle_seconds}s (>= {min_idle_s}s)",
        )
    return ClearVerdict(
        False, why=f"idle {idle_seconds}s < {min_idle_s}s and the next fire is still warm"
    )


def should_clear_externally(
    *,
    idle_seconds: int | None,
    last_turn_age_s: int | None,
    ttl_minutes: int,
    seconds_to_next_fire: int | None,
    context_tokens: int | None,
    min_context: int,
    min_idle_s: int,
    headroom_s: int,
    active_waiting: bool,
    in_cooldown: bool,
    awaiting_user: bool,
    cache_expired: bool | None = None,
    context_high_water: int = 0,
    recovery_pending: bool = False,
) -> ClearVerdict:
    """PUBLIC entry point. Decides via `_should_clear_externally_decide` (kept PURE -- see its
    own docstring for the whole policy) then logs the decision (card 1 items 2+7). Review note:
    THIS wrapper is NOT the pure function the "tests call directly with injected facts" claim is
    about -- `_should_clear_externally_decide` is, and it stays free of the log write. This
    wrapper is the ONE place the real watcher caller routes through, so it is also the one place
    that needs to know how to log.

    `recovery_pending` DEFAULTS FALSE (card 1 follow-up item 2, TRDD-L32WC0H7) -- mirrors
    `should_clear_on_resume`'s own default, and for the same reason: any test or caller that
    constructs this call without the argument keeps the pre-existing behaviour. The ONE
    production caller, `external_handoff_clear.py::_decide`, now always passes the real reading
    from the shared `external_clear.recovery_pending` helper.
    """
    verdict = _should_clear_externally_decide(
        idle_seconds=idle_seconds,
        last_turn_age_s=last_turn_age_s,
        ttl_minutes=ttl_minutes,
        seconds_to_next_fire=seconds_to_next_fire,
        context_tokens=context_tokens,
        min_context=min_context,
        min_idle_s=min_idle_s,
        headroom_s=headroom_s,
        active_waiting=active_waiting,
        in_cooldown=in_cooldown,
        awaiting_user=awaiting_user,
        cache_expired=cache_expired,
        context_high_water=context_high_water,
        recovery_pending=recovery_pending,
    )
    _log_clear_decision("external-clear", verdict, context_tokens=context_tokens)
    return verdict


def terminal_from_record(record: Mapping[str, str]) -> dict[str, str]:
    """PURE adapter: the FLEET-shaped pane identity a session records at start →
    the `terminal_trigger` shape (`kind` + channel key).

    Two dict shapes for one concept exist in this codebase and they are NOT interchangeable:
    `session_liveness.capture_terminal_identity` / `fleet_restart.recorded_terminal` emit
    `{iterm_session_id, tmux_pane}`, while `terminal_trigger.self_terminal` (used throughout the
    trigger scripts) consumes `{kind, pane|session_id}`. Handing the former straight to the
    latter yields `kind=""`, which every builder treats as "unsupported channel" — a silent
    no-op.

    tmux is preferred over iTerm for the same reason `terminal_trigger.self_terminal` prefers
    it: its pane can be read back cheaply, which is what lets the chain VERIFY a command before
    submitting it.

    `ITERM_SESSION_ID` is recorded verbatim and is `<tty>:<UUID>`; the UUID must be split off
    here or `terminal_trigger.valid_iterm_session_id` rejects the whole string.
    """
    pane = (record.get("tmux_pane") or "").strip()
    if pane:
        return {"kind": "tmux", "pane": pane}
    iterm = (record.get("iterm_session_id") or "").strip()
    if iterm:
        return {"kind": "iterm", "session_id": iterm.split(":")[-1].strip()}
    return {"kind": "unknown"}


# --- best-effort readers (never raise) --------------------------------------


def read_ttl_minutes(state_dir: Path) -> int:  # noqa: ARG001 -- kept for caller compat
    """Always `DEFAULT_TTL_MINUTES` — the TTL-regime probe was retired by TRDD-BRHJHWW0.

    Nothing writes a regime file any more, so there is nothing left to read; this stays a
    function (not an inlined constant) because `scripts/hooks/on-session-start-cold-cache-clear.py`
    still calls it and is out of this change's scope.
    """
    return DEFAULT_TTL_MINUTES


# --- the zero-token handoff (template fallback) ------------------------------


@dataclass
class HandoffInputs:
    """Everything the template composer needs, already gathered from disk.

    A dataclass rather than a pile of keyword args because the automatic lane's compacted-context
    composer consumes the same inputs (`summarize_previous_session.py` builds one of these and
    passes it straight through to `compose_handoff` below — it used to be filled from an llm-ext
    summary, now from Jev compaction) — it is handed these PATHS (never their contents;
    `use-llm-externalizer.md`), and this template is what runs when that composition is absent
    or fails.
    """

    cards: Sequence[tuple[str, str, str]] = field(default_factory=list)  # (id, column, title)
    commits: Sequence[tuple[str, str]] = field(default_factory=list)  # (sha, subject)
    findings: Sequence[str] = field(default_factory=list)
    memory_dir: str = ""
    trigger: str = ""
    idle_seconds: int | None = None
    context_tokens: int | None = None


def compose_template_handoff(
    inputs: HandoffInputs, *, now_iso: str, max_bytes: int = HANDOFF_MAX_BYTES
) -> str:
    """PURE. Build a link-only handoff from on-disk facts, with ZERO model tokens.

    It must satisfy `clear_trigger.check_handoff_concise` BY CONSTRUCTION, because the thing it
    is handed to is unrecoverable and nobody reviews it first:
      * under `max_bytes` — enforced by trimming the tail of each list (see below), not hoped for;
      * carries a reference — the `memgrep recall` line is unconditional, so even a handoff with
        no cards, no commits and no findings still points at the payload store;
      * no fenced blocks at all — so the `inlined-block` check cannot trip.

    Trimming drops list ITEMS from the tail rather than truncating the text mid-line: a handoff
    cut mid-sentence can leave a half-written TRDD id, which reads as a real pointer and resolves
    to nothing. Losing a whole low-priority line is recoverable; a corrupted pointer is not.
    """
    cards = list(inputs.cards)
    commits = list(inputs.commits)
    findings = list(inputs.findings)

    def render(n_cards: int, n_commits: int, n_findings: int) -> str:
        idle_h = "unknown" if inputs.idle_seconds is None else f"~{inputs.idle_seconds // 3600}h"
        ctx = "unknown" if inputs.context_tokens is None else f"~{inputs.context_tokens // 1000}k"
        out = [
            f"# Handoff — {now_iso} (auto-composed, no model turn — TRDD-PXP08ZQC)",
            "",
            f"Written by the janitor's EXTERNAL watcher, not by the model: trigger "
            f"`{inputs.trigger}`, idle {idle_h}, context {ctx}. Link-only by construction — "
            "every pointer below is resolved on demand, nothing is inlined.",
            "",
            "## NEXT ACTION (one step, runnable)",
            "",
            "Read the `## STATE` block of the first in-flight card below, then continue its "
            "NEXT ACTION. A card's STATE block is authoritative; this handoff is only an index.",
        ]
        if cards[:n_cards]:
            out += ["", "## In-flight cards (open work)", ""]
            out += [f"- TRDD-{cid} (`{col}`) — {title}" for cid, col, title in cards[:n_cards]]
        if commits[:n_commits]:
            out += ["", "## Recent commits (the WHY lives in the messages — `git show <sha>`)", ""]
            out += [f"- {sha} {subject}" for sha, subject in commits[:n_commits]]
        if findings[:n_findings]:
            out += ["", "## Open findings", ""]
            out += [f"- {f}" for f in findings[:n_findings]]
        recall_dir = inputs.memory_dir or ".claude/project/memory"
        out += [
            "",
            "## Recall",
            "",
            f'Deep knowledge is in the wiki, not here: `memgrep recall "<symptom>" {recall_dir}`.',
            "",
        ]
        return "\n".join(out)

    n_cards, n_commits, n_findings = len(cards), len(commits), len(findings)
    text = render(n_cards, n_commits, n_findings)
    # Drop the least load-bearing section first (findings are re-derivable from the ledger every
    # session; commits from git; the CARDS are the only thing that says what was being worked on).
    while len(text.encode("utf-8")) > max_bytes and (n_findings or n_commits or n_cards > 1):
        if n_findings:
            n_findings -= 1
        elif n_commits:
            n_commits -= 1
        else:
            n_cards -= 1
        text = render(n_cards, n_commits, n_findings)
    return text


# ── TRDD-2F3I2P18: the prefix-invalidating events the schedule cannot imply ──────────────────
#
# `cache_certainly_expired` answers "did the cache time out?" and `next_fire_misses_cache`
# answers "will it?". Neither can see the third family: events that kill the prefix OUTRIGHT,
# instantly, regardless of the clock — a model switch, an effort switch, a plugin or skill
# reload. At that instant the prefix is ALREADY dead, so a clear is free; one turn later it costs
# a full re-write. These are the cheapest wins available and nothing was watching for them.
#
# NO NEW API IS NEEDED, which is why this ships now rather than waiting on the announced
# agentlens cache-state verb: `agentlenspro statusline-history raw` already prints model and
# effort per turn per session. Verified by running it, not by reading the help text.
_STATUSLINE_MAX_ROWS = 40


def prefix_invalidated(session_id: str | None = None) -> bool | None:
    """Did MODEL or EFFORT change between this session's two most recent turns?

    Tri-state, and the `None` is load-bearing in the same way `cache_certainly_expired`'s is: it
    means "no signal", NEVER `False`. An absent CLI, an unparseable table, or fewer than two rows
    for this session must leave the other triggers exactly as they were. A trigger that
    synthesizes `False` out of an unreadable input does not merely fail to fire — it reports
    健康 where there is no information, which is how a silent gate disables a whole lever.
    """
    sid = (session_id or os.environ.get("CLAUDE_CODE_SESSION_ID", ""))[:8]
    if not sid:
        return None
    # Honour the SAME disable the cache probe already has, rather than minting a second one.
    # `CACHE_EXPIRED_COMMAND_ENV` set to empty means "no agentlens on this host" — the suite uses
    # it to keep the whole class of machine-touching calls out of tests, and a second, differently
    # named switch would mean a host could disable one probe and silently keep the other.
    if os.environ.get(CACHE_EXPIRED_COMMAND_ENV, "unset") == "":
        return None
    if shutil.which("agentlenspro") is None:
        return None
    # `state.run_subprocess`, NOT a raw `subprocess.run`. The repo's test guard refuses raw
    # machine-touching calls by design — "deliberate friction — it makes a real machine-touching
    # call visible in code review instead of an invisible default" — and it caught this function
    # on its first run. The wrapper is the sanctioned path: it carries the detector name into the
    # logs and the timeout scale the suite relaxes, so the same code is honest in production and
    # inert under test.
    proc = state.run_subprocess(
        ["agentlenspro", "statusline-history", "raw"],
        timeout=15,
        detector_name="external-clear",
    )
    if proc is None or proc.returncode != 0 or not (proc.stdout or "").strip():
        return None

    # Rows are newest-first: `time  session  model  effort  ctx%  ctx  $`. Only this session's
    # rows are comparable — another session switching models says nothing about this prefix.
    seen: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines()[:_STATUSLINE_MAX_ROWS]:
        parts = line.split()
        if len(parts) < 4 or not line[:2].isdigit():
            continue
        if not parts[1].startswith(sid):
            continue
        # The model name contains spaces ("Opus 5"), so index from the RIGHT of the fixed tail
        # (ctx%, ctx, $) rather than the left: a left-indexed split silently reads the model's
        # second word as the effort.
        if len(parts) < 6:
            continue
        seen.append((" ".join(parts[2:-4]), parts[-4]))
        if len(seen) == 2:
            break
    if len(seen) < 2:
        return None
    return seen[0] != seen[1]


# The reload half of the same trigger family (TRDD-2F3I2P18). A `/reload-plugins` or
# `/reload-skills` re-injects CLAUDE.md, skills and tool schemas into the prefix, killing it as
# surely as a model switch — but neither appears in the statusline series (a built-in reload takes
# no API turn), so `prefix_invalidated` cannot see them. The janitor's own per-project ack stamps
# are the signal: `dispatch.py` advances `reload-acked.ts` / `skills-reload-acked.ts` in the very
# turn that tells the session to reload, so an ack the watcher has not yet processed IS the event.
_RELOAD_SEEN_FILE = "prefix-reload-seen.json"
# An ack older than this is CONSUMED SILENTLY, never fired on: the prefix rewrite it caused was
# paid by whatever turn ran since, so a late clear would throw away a freshly warm cache — the
# exact "clear a warm session for nothing" failure the rest of this gate is built to avoid.
_RELOAD_EVENT_FRESH_S = 600
# A transcript-mtime bump within this many seconds of an ack stamp is the switch/reload's own
# non-API bookkeeping append, not a paying turn — see the paid-detector comment below.
_PAID_TURN_SLACK_S = 10


def _read_reload_state(state_dir: Path) -> tuple[dict[str, tuple[int, int]], dict[str, object]]:
    """(acked gens+mtimes, seen cursor). Raises on a broken stamp; heals a corrupt cursor to {}."""
    acked: dict[str, tuple[int, int]] = {}
    # "model" (TRDD-GK35MOXU): the PostModelSwitch hook (CC ≥ 2.1.251) advances
    # model-switch-acked.ts on every switch — same generation-int shape, same consume-on-fire
    # semantics as the reload stamps, because a switch and a reload kill the prefix the same
    # way. `prefix_invalidated` (the statusline poll) stays as the pre-2.1.251 fallback; the
    # in_cooldown veto dedupes when both see one event.
    for name, stamp in (
        ("plugins", "reload-acked.ts"),
        ("skills", "skills-reload-acked.ts"),
        ("model", "model-switch-acked.ts"),
    ):
        p = state_dir / stamp
        try:
            gen = int(p.read_text(encoding="utf-8").strip() or "0")
            mtime = int(p.stat().st_mtime)
        except FileNotFoundError:
            gen, mtime = 0, 0
        acked[name] = (gen, mtime)
    try:
        raw = json.loads((state_dir / _RELOAD_SEEN_FILE).read_text(encoding="utf-8"))
        seen = raw if isinstance(raw, dict) else {}
    except (FileNotFoundError, ValueError):
        seen = {}
    return acked, seen


def reload_invalidated(
    state_dir: Path, *, now: int, last_turn_ts: int | None = None
) -> bool | None:
    """Did this session ack a plugin/skills reload the watcher has not yet processed?

    Tri-state like `prefix_invalidated`: `None` means "no signal", never `False`. An ABSENT ack
    stamp is a readable fact (no reload has ever been acked here) and reads `False`; a stamp that
    EXISTS but does not parse is a broken signal and reads `None`, so it can never overwrite a
    verdict another trigger reached.

    THE PROBE DOES NOT CONSUME A FRESH EVENT (review-fork finding, 2026-09-01): the first cut
    advanced the cursor on every read, so a `--dry-run`, a gate veto after the probe, or the
    NO_RECORDED_PANE decline ate the event without firing — and the daemon's next real pass was
    blind to a prefix that was still dead. Now a FRESH event stays pending until
    `consume_reload_events` is called on the FIRE path; re-probing while it is fresh keeps
    reporting True, and once it ages past the window it is consumed silently below (a late clear
    would only dump a warm cache). A corrupt cursor self-heals to empty rather than reading
    `None`: the freshness window bounds the worst case to a single spurious fire, while a dead
    cursor would disable the trigger permanently and silently.
    """
    try:
        acked, seen = _read_reload_state(state_dir)
        fired = False
        consumable: dict[str, int] = {}
        for name, (gen, mtime) in acked.items():
            prev = seen.get(name)
            if gen > (prev if isinstance(prev, int) else 0):
                # A TURN NEWER THAN THE STAMP means the re-cache was ALREADY PAID (review-fork,
                # 2026-09-01): the invariant that makes a clear free is "no turn ran since the
                # prefix died", not "the prefix died recently". A /model switch mid-conversation
                # is the norm — the user switches and keeps chatting, the very next turn (or a
                # heartbeat fire) rebuilds the new prefix — and firing then would clear a WARM
                # session, the exact failure the stale path exists to avoid.
                #
                # THE SLACK: `last_turn_ts` is raw transcript mtime, and transcripts gain
                # NON-API appends (measured: `queue-operation`, `system`, `attachment` event
                # types in a live .jsonl) — the switch itself plausibly appends one right after
                # the hook stamps. Counting such an append as "payment" would silently kill the
                # trigger's PRIMARY case (an idle switch). So a turn pays only when it lands
                # clearly AFTER the stamp; anything within the slack is treated as the switch's
                # own bookkeeping. A user who switches and messages within the slack is covered
                # anyway: active_waiting vetoes while busy, and by the next probe the turn's
                # END has moved past the slack.
                paid = (
                    last_turn_ts is not None
                    and last_turn_ts - mtime > _PAID_TURN_SLACK_S
                )
                if now - mtime <= _RELOAD_EVENT_FRESH_S and not paid:
                    fired = True
                else:
                    consumable[name] = gen
        if not fired and consumable:
            # Only stale/paid events pending: consume them now so they stop re-probing forever.
            # Never while a firing event is also pending — one cursor write covers all names,
            # and consuming the set here would eat the fresh event the fire path still needs.
            new_seen = {**{k: v for k, v in seen.items() if isinstance(v, int)}, **consumable}
            state.atomic_write(state_dir / _RELOAD_SEEN_FILE, json.dumps(new_seen) + "\n")
        return fired
    except (OSError, ValueError, TypeError):
        return None


def consume_reload_events(state_dir: Path) -> None:
    """Mark every currently-acked reload generation as processed — FIRE-PATH ONLY.

    Called after the clear chain is actually spawned, never from the probe: the event must
    survive a dry-run, a veto, or a declined pane so the next beat can still act on it.
    Best-effort — a failed write only means the same reload may fire one more clear, and the
    cooldown veto already bounds that.
    """
    try:
        acked = _read_reload_state(state_dir)[0]
        new_seen = {name: gen for name, (gen, _) in acked.items()}
        state.atomic_write(state_dir / _RELOAD_SEEN_FILE, json.dumps(new_seen) + "\n")
    except (OSError, ValueError, TypeError):
        pass
