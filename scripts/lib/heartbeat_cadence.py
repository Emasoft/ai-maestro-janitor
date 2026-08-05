"""TTL-aware heartbeat cadence tiers (TRDD-0QQX9H0G, issue #83).

The janitor heartbeat fired a fixed ``*/5`` cron. Every fire is a full
main-conversation turn that re-reads the whole session prefix at the 0.1x
cache-read rate, so on a large session ``*/5`` costs ~$6/h JUST to keep the
cache warm — ~12x more often than the 1-hour subscription cache-TTL requires.
But the fire also drives latency-sensitive duties (rate-limit auto-resume,
post-compact resume, the 7-day cron renew, drift detection), so a naive
slowdown regresses recovery time.

This module is the PURE decision layer for a DYNAMIC cadence: pick a fast
cadence when the session is actively waiting, a slow one (bounded by the real
cache-TTL) when idle. The dispatcher cannot change its own cron (CronCreate is a
model tool), so a tier change is applied by re-using the existing
``[janitor-renew]`` marker -> ``/janitor-arm``; this module only DECIDES which
tier is wanted and (with the one thin probe helper) how slow "idle" may go.

Every non-probe function here is I/O-free and unit-tested. The dispatcher does
the file reads/writes and the marker emission — this module classifies.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass

# Tiers, ordered slow -> fast. The numeric rank makes "faster than" comparisons
# (the promote/demote direction in commit_tier) explicit and total.
FAST = "fast"
MID = "mid"
SLOW = "slow"
_TIER_RANK = {SLOW: 0, MID: 1, FAST: 2}

# Default cron per tier in the SLOW-TTL regime (each config-overridable). Chosen
# from MEASURED per-fire cost (the janitor's own token-meter: a quiet fire on a
# ~510k-context session ≈ 507k cache_read ≈ $0.76):
#   FAST=*/5  — keep the pre-#83 cadence for an ACTIVELY-WAITING session (rate-limit
#               / resume pending): recovery latency matters most exactly then, and the
#               FIRING FREQUENCY is unchanged vs pre-#83. The worst-case GAP is NOT
#               "5 minutes": a scheduled fire lands late by a documented jitter, and
#               the two sources disagree — the CronCreate tool says ≤10% of the
#               period (max 15 min), the CC docs page says up to HALF the interval
#               for sub-hourly tasks (both checked 2026-08-02) — so quote */5 as
#               "5 min + 0.5–2.5 min jitter", never a bare period. Real distribution:
#               measure FIRE times (`.janitor/logs/heartbeat-fires.log`, stamped by
#               dispatch.main), never token-meter turn-END times (TRDD-LI7ENU2A).
#   MID=*/15  — recent user activity: 3x cheaper than */5, still timely.
#   SLOW=*/30 — idle keep-warm: 6x cheaper than */5, 30-min gaps under the 1h TTL.
# */30 is the SAFE FLOOR for a uniform cadence: any `*/N` with 30<=N<60 fires
# EXACTLY twice an hour (minutes 0 and N), so */45 is no cheaper than */30 — only
# a single-minute hourly cron beats 2/h, and its 60-min gap == the TTL (too tight).
_DEFAULT_CRON = {FAST: "*/5 * * * *", MID: "*/15 * * * *", SLOW: "*/30 * * * *"}

# In the FAST-TTL regime (cache TTL < 30 min: subscription over-plan credits, or
# API key without ENABLE_PROMPT_CACHING_1H) there is NO safe slowdown — warmth
# needs a fire at least every ~5 min — so every tier collapses to */5 and the
# whole feature becomes a correct no-op.
_FAST_TTL_CRON = "*/5 * * * *"

# Boundary between the two regimes. The only two real TTLs are 60 and 5, so any
# threshold in (5, 60] separates them; 30 is a comfortable midpoint.
_SLOW_TTL_MIN = 30

# TTL fallbacks (minutes) when the authoritative agentlensPro probe is
# unavailable. Mirrors the doc matrix (AgentlensPro src/shared/cacheTtl.ts):
# an API-key session rides the 5-min tier, a subscription the 1-hour tier. This
# fallback is deliberately coarse — it cannot see the over-plan-credits case
# (which auto-drops to 5 min with NO API key set); the probe is what gets that
# right, which is exactly why the probe is preferred and this is only a fallback.
_TTL_SUBSCRIPTION_MIN = 60
_TTL_API_KEY_MIN = 5

# Default minimum gap (seconds) between two ACTUAL re-arms (issue #89 half 2,
# TRDD-CI6ZTNB9's sibling). A re-arm is a full billed model turn — a cron
# divergence is necessary but not sufficient to re-emit [janitor-renew]; the
# last re-arm must also be at least this old, unless the fire is PROMOTING to a
# faster tier (see `should_emit_renew`). Public (not `_`-prefixed) so the
# dispatcher's env-default and this module share one source of truth instead of
# two copies of the same magic number drifting apart. 20 min: long enough that
# a few fires of tier noise settle before another re-arm is paid for, short
# enough that a genuinely-persistent tier change is not stuck behind it for long.
DEFAULT_DWELL_S = 1200


@dataclass(frozen=True)
class Signals:
    """The two booleans the dispatcher resolves from state files each fire.

    ``active_waiting`` — the session is waiting on something time-sensitive
    (rate-limited, a pending resume directive, a post-compact resume, pending
    background agents, or an explicit keep-going opt-in): fire FAST.
    ``recent_activity`` — a genuine user prompt landed within the MID window
    (the user-presence breadcrumb's ``last_user_input_epoch``): fire MID so
    chores/drift surface reasonably promptly. Neither -> SLOW (idle keep-warm).
    """

    active_waiting: bool
    recent_activity: bool


@dataclass(frozen=True)
class CadenceState:
    """Persisted (``.janitor/state/cadence-state.json``) hysteresis state.

    ``raw_tier`` — last fire's un-smoothed tier (from ``raw_tier``).
    ``stable_count`` — consecutive fires the raw tier has held (drives demote
    hysteresis).
    ``committed_tier`` — the tier actually in force (what maps to the cron).
    ``last_rearm_ts`` — epoch of the last fire that actually emitted
    [janitor-renew] (0 = never), the anchor `should_emit_renew` dwells against
    (issue #89 half 2). Defaults to 0 so every pre-existing caller/test that
    builds a `CadenceState` without naming this field keeps working.
    """

    raw_tier: str
    stable_count: int
    committed_tier: str
    last_rearm_ts: int = 0


def raw_tier(signals: Signals) -> str:
    """The un-smoothed tier this fire's signals ask for. Pure."""
    if signals.active_waiting:
        return FAST
    if signals.recent_activity:
        return MID
    return SLOW


def commit_tier(raw: str, prev: CadenceState | None, demote_fires: int) -> CadenceState:
    """Apply hysteresis: promote to a faster tier IMMEDIATELY, demote to a slower
    one only after ``demote_fires`` consecutive fires at the slower raw tier.

    Asymmetric on purpose. Promoting late would delay exactly the recovery the
    fast tier exists for (a rate-limited session must speed up the instant the
    flag appears). Demoting eagerly would flap the cron — a single idle fire
    between active ones would trigger a needless re-arm — so a slower raw tier
    must persist for ``demote_fires`` fires before it commits. Pure.

    ``last_rearm_ts`` is carried forward UNCHANGED from ``prev`` (0 when
    ``prev`` is None) — this function decides which tier WINS, never whether a
    re-arm is actually emitted. `should_emit_renew` + `stamp_rearm` own that;
    keeping the two concerns in separate functions is what makes the dwell
    layer (issue #89 half 2) testable independent of the tier hysteresis.
    """
    if prev is None:
        return CadenceState(raw_tier=raw, stable_count=1, committed_tier=raw, last_rearm_ts=0)
    count = prev.stable_count + 1 if prev.raw_tier == raw else 1
    committed = prev.committed_tier
    if _TIER_RANK[raw] > _TIER_RANK[committed]:
        committed = raw  # faster -> commit now
    elif _TIER_RANK[raw] < _TIER_RANK[committed] and count >= max(1, demote_fires):
        committed = raw  # slower and stable long enough -> demote
    return CadenceState(
        raw_tier=raw, stable_count=count, committed_tier=committed, last_rearm_ts=prev.last_rearm_ts
    )


def should_emit_renew(
    *,
    desired_differs: bool,
    committed: CadenceState,
    prev: CadenceState | None,
    now: int,
    dwell_s: int,
) -> bool:
    """Decide whether THIS fire may emit ``[janitor-renew]`` (issue #89 half 2).

    A re-arm is a full billed model turn (CronDelete + CronCreate + state
    writes) — so a differing desired cron is NECESSARY but not SUFFICIENT to
    re-emit the marker; the last ACTUAL re-arm must also be at least
    ``dwell_s`` old. The one exception is a tier PROMOTION (the committed tier
    ranks faster than the previous fire's committed tier, or this is the very
    first commit) — that always bypasses the dwell, matching `commit_tier`'s
    own "promote immediately" philosophy: after the TRDD-CI6ZTNB9 self-exclusion
    fix, a promotion can only be driven by a genuine time-sensitive signal
    (resume / keep-going / directive / a USER-spawned background agent), never
    the janitor's own housekeeping, so there is nothing left to damp there.

    A DEMOTION (or a same-tier cron change, e.g. an override edited) is
    therefore gated by TWO independent hysteresis layers that damp different
    things: `demote_fires` (inside `commit_tier`) decides WHICH tier wins;
    this dwell decides how OFTEN the winning tier may actually pay for a
    re-arm. Neither alone stops a controller that flips its committed tier
    every `demote_fires`-th fire from re-arming every time it does. Pure.
    """
    if not desired_differs:
        return False
    prev_rank = _TIER_RANK.get(prev.committed_tier, -1) if prev is not None else -1
    if _TIER_RANK[committed.committed_tier] > prev_rank:
        return True  # promotion (incl. the very first commit) — never dwell-gated
    if dwell_s <= 0 or committed.last_rearm_ts <= 0:
        return True  # dwell disabled, or no re-arm has ever landed to dwell against
    return (now - committed.last_rearm_ts) >= dwell_s


def stamp_rearm(state: CadenceState, now: int) -> CadenceState:
    """Return `state` with `last_rearm_ts` set to `now`.

    Call this ONLY on a fire that actually emits [janitor-renew] — the next
    fire's dwell check must measure from a REAL re-arm, not from every fire
    that merely computed a differing desired cron (issue #89 half 2)."""
    return CadenceState(
        raw_tier=state.raw_tier,
        stable_count=state.stable_count,
        committed_tier=state.committed_tier,
        last_rearm_ts=now,
    )


def tier_to_cron(tier: str, ttl_minutes: int, overrides: Mapping[str, str] | None = None) -> str:
    """Map (tier, real cache-TTL) -> a 5-field cron. Pure.

    In the FAST-TTL regime (ttl < 30 min) every tier returns */5 and overrides
    are ignored — a slower cron would let the cache die between fires, so there
    is nothing safe to override to.
    """
    if ttl_minutes < _SLOW_TTL_MIN:
        return _FAST_TTL_CRON
    if overrides:
        ov = (overrides.get(tier) or "").strip()
        if ov:
            return ov
    return _DEFAULT_CRON[tier]


def _as_int(value: object, default: int) -> int:
    """Coerce a JSON-decoded value (typed ``object``) to int, or ``default``.

    Accepts int/float/numeric-string; rejects bool (a stray ``true`` must not read
    as 1) and anything non-numeric — so a corrupt state file degrades to the
    default instead of raising inside a fire.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value.strip()))
        except (TypeError, ValueError):
            return default
    return default


def _env_fallback_minutes(env: Mapping[str, str]) -> int:
    """Coarse TTL guess when the probe is unavailable: API key -> 5, else 60."""
    if (env.get("ANTHROPIC_API_KEY") or "").strip():
        return _TTL_API_KEY_MIN
    return _TTL_SUBSCRIPTION_MIN


def _parse_ttl_minutes(stdout: str) -> int | None:
    """Extract ``cacheTtl.minutes`` from ``agentlenspro get_account_status`` JSON.

    Returns None on anything unexpected — the caller treats None as "probe
    failed" and falls back, so a schema change in the CLI degrades gracefully
    instead of crashing the fire.
    """
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError):
        return None
    ttl = data.get("cacheTtl") if isinstance(data, dict) else None
    if not isinstance(ttl, dict):
        return None
    minutes = ttl.get("minutes")
    if isinstance(minutes, (int, float)) and minutes > 0:
        return int(minutes)
    return None


def probe_account_status(command: str, *, timeout: float = 5.0) -> int | None:
    """Run the configured account-status command and return ``cacheTtl.minutes``.

    Fail-open by construction: an empty command, a missing binary, a non-zero
    exit, a timeout, or unparseable output all return None. The janitor never
    hard-depends on the machine-local agentlensPro CLI (same contract as the
    issue-#78 heartbeat-cost command).
    """
    command = (command or "").strip()
    if not command:
        return None
    try:
        proc = subprocess.run(  # noqa: S603 - argv from config, split with shlex, no shell
            shlex.split(command),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return _parse_ttl_minutes(proc.stdout)


def resolve_ttl_minutes(
    *,
    now: int,
    regime_config: str,
    cached: Mapping[str, object] | None,
    probe_interval: int,
    probe: Callable[[], int | None],
    env: Mapping[str, str],
) -> tuple[int, dict | None]:
    """Resolve the authoritative cache-TTL (minutes) for the SLOW ceiling.

    Returns ``(minutes, cache_to_write)``; ``cache_to_write`` is None when the
    fresh cache was reused (nothing to persist) and a dict to write to
    ``ttl-regime.json`` when a (re)probe happened.

    - ``regime_config`` ``subscription``/``api-key`` -> the fixed TTL, no probe.
    - ``auto`` -> reuse ``cached`` while younger than ``probe_interval``; else
      run ``probe()``. A successful probe is cached with its minutes; a FAILED
      probe caches the env fallback too (bounding the probe to ~one per
      interval even during an agentlensPro outage, so a hung server can't
      5s-block every fire). The next post-interval probe self-corrects.
    """
    if regime_config == "subscription":
        return _TTL_SUBSCRIPTION_MIN, None
    if regime_config == "api-key":
        return _TTL_API_KEY_MIN, None

    if cached is not None:
        probed_at = _as_int(cached.get("probed_at", 0), 0)
        minutes = _as_int(cached.get("minutes", 0), 0)
        if minutes > 0 and probed_at > 0 and (now - probed_at) < max(0, probe_interval):
            return minutes, None  # fresh — reuse, no subprocess, no write

    probed = probe()
    if probed and probed > 0:
        return probed, {"minutes": int(probed), "probed_at": int(now), "source": "probe"}

    # PROBE FAILED. A stale MEASUREMENT beats a fresh GUESS (TRDD-VXFNDHXT).
    #
    # The probe is a network call: measured 2.89s / 6.29s / 9.18s across three consecutive
    # runs against its 5s bound, so it loses on latency alone, intermittently, on a
    # correctly-configured host. Overwriting a real reading with `_env_fallback_minutes` on
    # every such miss is what produced janitor#190: the env guess returns 60 for a
    # non-API-key session, and `tier_to_cron`'s FAST guard fires only BELOW 30 — so the guess
    # is precisely the value at which the guard can never trigger. A session whose true TTL
    # was 5 then ran */15 with a cache dying between fires, paying a full cold prefix WRITE
    # (~1.25x) per fire instead of a warm read (0.1x).
    #
    # Reuse regardless of age: `probe_interval` bounds how often we ASK, not how long an
    # answer stays usable, and a reading from an hour ago is still evidence about this
    # account. `stale-probe` keeps that distinguishable from both a live probe and a guess —
    # provenance is what made this diagnosable at all.
    if cached is not None:
        prior = _as_int(cached.get("minutes", 0), 0)
        if prior > 0 and str(cached.get("source", "")) in ("probe", "stale-probe"):
            return prior, {"minutes": prior, "probed_at": int(now), "source": "stale-probe"}

    fallback = _env_fallback_minutes(env)
    return fallback, {"minutes": fallback, "probed_at": int(now), "source": "fallback"}


def state_to_dict(state: CadenceState) -> dict:
    """Serialize CadenceState for ``cadence-state.json``."""
    return {
        "raw_tier": state.raw_tier,
        "stable_count": int(state.stable_count),
        "committed_tier": state.committed_tier,
        "last_rearm_ts": int(state.last_rearm_ts),
    }


def state_from_dict(data: Mapping[str, object] | None) -> CadenceState | None:
    """Parse CadenceState from disk. None on absent/malformed input (treated as
    "no prior state" by commit_tier — the first fire simply commits its raw tier).

    ``last_rearm_ts`` defaults to 0 when absent — a pre-dwell (issue #89 half 2)
    state file has no such key, and 0 means "no re-arm to dwell against yet",
    which is the safe direction (the next differing cron re-arms immediately
    rather than being wrongly held back by a dwell window that never started).
    """
    if not isinstance(data, Mapping):
        return None
    raw = data.get("raw_tier")
    committed = data.get("committed_tier")
    if raw not in _TIER_RANK or committed not in _TIER_RANK:
        return None
    count = _as_int(data.get("stable_count", 1), 1)
    last_rearm = max(0, _as_int(data.get("last_rearm_ts", 0), 0))
    return CadenceState(
        raw_tier=str(raw), stable_count=max(1, count), committed_tier=str(committed), last_rearm_ts=last_rearm
    )
