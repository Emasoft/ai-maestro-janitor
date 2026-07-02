"""Shared 30-minute fleet-attribution cache (TRDD-OY0W6LX5).

`token_history.fleet_attribution` STREAMS every project's transcripts (100+ MB each), so
it must not run more than a couple of times per hour machine-wide. Both consumers — the
`window-burn-rate` detector (only when a burn trip fires) and `/janitor-token-report
--attribution` — read/write ONE cache file in the daemon's global-state dir so a fresh
result is reused across every project on the host.

The stored blob is `{"ts": <epoch>, "fleet": <fleet_attribution dict>}`; the fleet dict is
pure JSON (floats / ints / str / None), so it round-trips cleanly. Every filesystem access
is fail-soft: a missing/corrupt cache just triggers a recompute, and a write failure never
raises (the caller still gets the freshly-computed result)."""

from __future__ import annotations

import json
from pathlib import Path

import global_state
import token_history as th

# Reuse the widest window we ever report as the default scan lookback.
_7D = 7 * 86400
# Default freshness window: a cached fleet result younger than this is reused as-is.
DEFAULT_MAX_AGE_S = 1800


def cache_path() -> Path:
    """The single machine-wide cache file, in the daemon's global-state dir."""
    return global_state.global_state_dir() / "fleet-attribution.json"


def load_fresh(
    now: int,
    *,
    max_age_s: int = DEFAULT_MAX_AGE_S,
    w5_lo: int | None = None,
    w7_lo: int | None = None,
) -> dict | None:
    """The cached fleet dict iff it exists, is younger than `max_age_s`, AND was computed
    with the SAME window bounds the caller wants (`w5_lo`/`w7_lo`, None = trailing) — a
    fleet summed over different windows answers a different question, so a bounds mismatch
    is staleness, not reuse (TRDD-0NRVNDSZ). Bounds change once per window rollover, so
    the cache stays effective in practice.

    A future-dated `ts` (clock skew / a corrupt file) is treated as stale so a bad stamp
    can never pin an ancient result forever."""
    try:
        raw = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    ts = raw.get("ts")
    if not isinstance(ts, (int, float)) or ts > now or now - ts > max_age_s:
        return None
    fleet = raw.get("fleet")
    if not isinstance(fleet, dict):
        return None
    if fleet.get("scan") != th.SCAN_VERSION:
        return None  # produced by an older scanner (e.g. pre-subagent-recursion) — stale
    if fleet.get("w5_lo") != w5_lo or fleet.get("w7_lo") != w7_lo:
        return None  # computed for different windows — recompute, don't reuse
    return fleet


def compute(
    projects_root: Path,
    now: int,
    *,
    since_epoch: int | None = None,
    w5_lo: int | None = None,
    w7_lo: int | None = None,
) -> dict:
    """Scan the fleet fresh and persist the result to the cache. Returns the fleet dict.

    Persisting is best-effort: a write failure is swallowed so a read-only global-state dir
    never breaks the caller (it still gets the computed result, just uncached)."""
    if since_epoch is None:
        since_epoch = now - _7D
    fleet = th.fleet_attribution(Path(projects_root), now, since_epoch=since_epoch, w5_lo=w5_lo, w7_lo=w7_lo)
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ts": now, "fleet": fleet}, separators=(",", ":")), encoding="utf-8")
    except OSError:
        pass
    return fleet


def get(
    projects_root: Path,
    now: int,
    *,
    max_age_s: int = DEFAULT_MAX_AGE_S,
    w5_lo: int | None = None,
    w7_lo: int | None = None,
) -> dict:
    """A fleet attribution dict, reusing a cache entry younger than `max_age_s` (with
    MATCHING window bounds) or scanning fresh (and caching) otherwise — the entry point
    both consumers call. `w5_lo`/`w7_lo` = window-aligned starts from the live probe
    (`token_burn.window_starts`); None = trailing windows (the pre-0NRVNDSZ behavior)."""
    cached = load_fresh(now, max_age_s=max_age_s, w5_lo=w5_lo, w7_lo=w7_lo)
    if cached is not None:
        return cached
    return compute(Path(projects_root), now, w5_lo=w5_lo, w7_lo=w7_lo)
