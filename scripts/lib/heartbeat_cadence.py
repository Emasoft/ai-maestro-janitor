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
#               / resume pending): recovery latency matters most exactly then, so
#               there is ZERO regression vs today for the state that needs speed.
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
    """

    raw_tier: str
    stable_count: int
    committed_tier: str


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
    """
    if prev is None:
        return CadenceState(raw_tier=raw, stable_count=1, committed_tier=raw)
    count = prev.stable_count + 1 if prev.raw_tier == raw else 1
    committed = prev.committed_tier
    if _TIER_RANK[raw] > _TIER_RANK[committed]:
        committed = raw  # faster -> commit now
    elif _TIER_RANK[raw] < _TIER_RANK[committed] and count >= max(1, demote_fires):
        committed = raw  # slower and stable long enough -> demote
    return CadenceState(raw_tier=raw, stable_count=count, committed_tier=committed)


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
    fallback = _env_fallback_minutes(env)
    return fallback, {"minutes": fallback, "probed_at": int(now), "source": "fallback"}


def state_to_dict(state: CadenceState) -> dict:
    """Serialize CadenceState for ``cadence-state.json``."""
    return {
        "raw_tier": state.raw_tier,
        "stable_count": int(state.stable_count),
        "committed_tier": state.committed_tier,
    }


def state_from_dict(data: Mapping[str, object] | None) -> CadenceState | None:
    """Parse CadenceState from disk. None on absent/malformed input (treated as
    "no prior state" by commit_tier — the first fire simply commits its raw tier).
    """
    if not isinstance(data, Mapping):
        return None
    raw = data.get("raw_tier")
    committed = data.get("committed_tier")
    if raw not in _TIER_RANK or committed not in _TIER_RANK:
        return None
    count = _as_int(data.get("stable_count", 1), 1)
    return CadenceState(raw_tier=str(raw), stable_count=max(1, count), committed_tier=str(committed))
