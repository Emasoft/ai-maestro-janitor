"""Adaptive token-usage baseline + anomaly primitives (TRDD-EDSFEQ5C).

Pure functions over the `token-meter.jsonl` records (the same
`{ts, output, input, cache_read, cache_creation, tool_calls}` the Stop-hook meter logs).
They power a heartbeat anomaly detector (is the most-recent 5-min bucket a SUDDEN spike
vs the session's learned normal?), the `/janitor-token-report` window view (rolling
5h/7d weighted sums + per-min rate), and absolute 5h/7d cap ESTIMATION when a
utilization% sample is available.

Grounded in the REAL distribution (measured 2026-07-01, 11.1 days): per-5-min usage is
HEAVY-TAILED + BURSTY — the top 10% of buckets hold ~61% of all tokens. So the baseline
is ROBUST (median for location, MAD for scale), never mean/stddev, which the tail wrecks;
and an anomaly must clear BOTH a robust-z bar AND an absolute floor so a normal
agent-spawn burst does not false-alarm. Stdlib only; no I/O beyond the caller's input.
"""

from __future__ import annotations

from dataclasses import dataclass


# cache_read is the cheap ~0.1x context re-read; output/input are full price; cache_creation
# is a PREMIUM write — 2x at the main agent's default 1-hour cache TTL (1.25x at the default
# 5-minute TTL a subagent, or a session in usage overage, gets) — but these are only the
# harness DEFAULTS: `promptCacheTtl`/`subagentPromptCacheTtl` let an org raise either TTL to
# 1 hour, which flips that multiplier to 2x too. This proxy deliberately counts it 1x anyway:
# every learned baseline and every empirical cap estimate below is calibrated against THIS
# formula, so re-weighting one component would silently invalidate them all. Read the result as
# a RELATIVE load index, not a bill — it under-counts a cache-miss turn by ~2x, which is exactly
# the turn `cold_cache_compact` exists to prevent.
def weighted_tokens(rec: dict) -> int:
    return int(rec.get("output", 0) or 0) + int(rec.get("input", 0) or 0) + int(rec.get("cache_creation", 0) or 0) + int(rec.get("cache_read", 0) or 0) // 10


def bucketize(records: list[dict], bucket_s: int) -> dict[int, int]:
    """`{bucket_index: summed weighted tokens}` over `records` (each needs a numeric `ts`).
    `bucket_index = ts // bucket_s`. A non-positive `bucket_s` yields {}."""
    out: dict[int, int] = {}
    if bucket_s <= 0:
        return out
    for r in records:
        ts = r.get("ts")
        if not isinstance(ts, (int, float)):
            continue
        b = int(ts) // bucket_s
        out[b] = out.get(b, 0) + weighted_tokens(r)
    return out


def _median(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    return float(s[mid]) if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def robust_baseline(values: list[int]) -> tuple[float, float]:
    """(median, MAD) — MAD = median(|v - median|), the robust scale. Empty → (0, 0)."""
    if not values:
        return (0.0, 0.0)
    med = _median([float(v) for v in values])
    mad = _median([abs(v - med) for v in values])
    return (med, mad)


def anomaly_score(value: float, median: float, mad: float) -> float:
    """Robust z-score `(value - median) / (1.4826 * MAD)`. The 1.4826 makes MAD a
    consistent estimator of stddev for normal data. Returns 0 when MAD is 0 (no dispersion
    to normalise by — the caller relies on the absolute FLOOR gate instead)."""
    if mad <= 0:
        return 0.0
    return (value - median) / (1.4826 * mad)


def percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    if n == 1:
        return s[0]
    k = int(round((pct / 100.0) * (n - 1)))
    return s[max(0, min(n - 1, k))]


@dataclass
class AnomalyVerdict:
    """The classification of the most-recent complete bucket vs the trailing baseline."""

    is_anomaly: bool
    bucket: int  # the tested bucket's index (ts // bucket_s) — a stable per-bucket dedupe key
    current: int  # the tested bucket's weighted tokens
    score: float  # robust z vs the trailing baseline
    median: float
    mad: float
    threshold: float  # the effective bar `current` had to clear to be an anomaly
    n_history: int


def classify_recent(
    records: list[dict],
    *,
    bucket_s: int = 300,
    z: float = 6.0,
    floor_pct: float = 95.0,
    ratio: float = 4.0,
    now: int | None = None,
) -> AnomalyVerdict | None:
    """Classify the most-recent COMPLETE bucket as anomalous vs the trailing history.

    When `now` is given, the bucket it falls in is the IN-PROGRESS one and is excluded
    (it may still be filling); the tested bucket is the newest one strictly older than it.
    The bar is the MAX of three complementary gates, so `current` must clear the highest:
      * `percentile(history, floor_pct)` — an absolute-magnitude floor (never alarm on a
        bucket that is small relative to the session's own recent history);
      * `median + z * 1.4826 * MAD` — the robust-z band (a sudden jump vs normal dispersion);
      * `median * ratio` — a multiplicative bar that stays meaningful when MAD≈0 (a
        perfectly-flat history), where the z-band collapses to the median and a genuine
        10x spike would otherwise score 0 and slip through.
    Returns None when there is too little history to judge (need the tested bucket + >= 8
    prior buckets).
    """
    if bucket_s <= 0:
        return None  # a 0/negative knob must disable, not ZeroDivisionError every heartbeat
    buckets = bucketize(records, bucket_s)
    all_b = sorted(buckets)
    if now is not None:
        cur_b = int(now) // bucket_s
        complete = [b for b in all_b if b < cur_b]
    else:
        complete = all_b
    if len(complete) < 9:  # 1 tested + >= 8 history
        return None
    test_b = complete[-1]
    history = [buckets[b] for b in complete[:-1]]
    current = buckets[test_b]
    med, mad = robust_baseline(history)
    score = anomaly_score(current, med, mad)
    threshold = max(
        float(percentile(history, floor_pct)),
        med + z * 1.4826 * mad,
        med * ratio,
    )
    is_anom = current > threshold
    return AnomalyVerdict(is_anom, test_b, current, score, med, mad, threshold, len(history))


def rolling_sum(records: list[dict], window_s: int, now: int) -> int:
    """Summed weighted tokens whose `ts` is within the last `window_s` up to `now`."""
    lo = now - window_s
    return sum(weighted_tokens(r) for r in records if isinstance(r.get("ts"), (int, float)) and lo <= int(r["ts"]) <= now)


def max_window_sum(records: list[dict], window_s: int) -> int:
    """The largest weighted-token sum over ANY `window_s`-wide time window in `records`
    (a sliding window ending at each record). This is the BUSIEST observed window — an
    empirical LOWER BOUND on the account's real cap for that window length (you sustained
    at least this much). Stdlib O(n log n) sort + O(n) sweep; {} → 0."""
    if window_s <= 0:
        return 0
    pts = sorted((int(r["ts"]), weighted_tokens(r)) for r in records if isinstance(r.get("ts"), (int, float)))
    best = 0
    cur = 0
    lo = 0
    for hi in range(len(pts)):
        cur += pts[hi][1]
        while pts[hi][0] - pts[lo][0] >= window_s:  # evict points older than the window
            cur -= pts[lo][1]
            lo += 1
        best = max(best, cur)
    return best


def per_minute(total: int, window_s: int) -> float:
    """Average weighted tokens per minute over a window of `window_s` seconds."""
    return (total / (window_s / 60.0)) if window_s > 0 else 0.0


def estimate_window_cap(util_pct: float | None, window_weighted: int) -> int | None:
    """Estimate a window's ABSOLUTE weighted-token cap from a utilization% sample paired
    with the weighted tokens spent in that window: `cap ≈ spent / (util/100)`. Returns
    None when `util_pct` is not a usable positive percent (can't divide by ~0)."""
    if util_pct is None or util_pct <= 0:
        return None
    return int(window_weighted / (util_pct / 100.0))


def project_exhaustion_minutes(remaining_weighted: int, recent_rate_per_min: float) -> float | None:
    """Minutes until the remaining budget is exhausted at `recent_rate_per_min`. None when
    the rate is ~0 (never exhausts) or the remaining budget is non-positive."""
    if recent_rate_per_min <= 0 or remaining_weighted <= 0:
        return None
    return remaining_weighted / recent_rate_per_min


# ── Window burn-rate (TRDD-OY0W6LX5) ─────────────────────────────────────────
# A subscription window (5h rolling / 7d) has a HARD reset boundary, and the OAuth
# usage payload reports `resets_at` + a `utilization`% — enough to know whether the
# account is burning FASTER than the even pace that would land it at 100% exactly at
# the reset. These are pure ratio/projection primitives; the caller owns the alarm
# thresholds (RATIO bar, min-util / min-elapsed floors so a barely-used window never
# false-alarms). No I/O; the util%/reset come from the read-only rotator usage probe.
def elapsed_fraction_from_reset(resets_at_epoch: int, window_s: int, now: int) -> float | None:
    """Fraction [0.0, 1.0] of a FIXED-reset usage window that has elapsed at `now`.

    The window STARTED at `resets_at − window_s` (the payload gives `resets_at`), so
    elapsed fraction = `(now − start) / window_s`, clamped to [0, 1]. This is the
    linear "budget" a perfectly-even pace would have burned by now — the denominator
    the burn-rate compares against. Fail-safe None (never raises) on nonsense inputs:
    a non-positive `window_s` or `resets_at_epoch`, or a `now` a full window PAST the
    reset (`now >= resets_at + window_s` — the window should already have rolled over,
    so the sample is stale/wrong)."""
    if window_s <= 0 or resets_at_epoch <= 0:
        return None
    if now >= resets_at_epoch + window_s:
        return None
    start = resets_at_epoch - window_s
    frac = (now - start) / window_s
    if frac < 0.0:
        return 0.0
    if frac > 1.0:
        return 1.0
    return frac


def burn_ratio(util_pct: float | None, elapsed_fraction: float | None) -> float | None:
    """How fast a window is burning vs its even-pace budget: `(util%/100) / elapsed`.

    1.0 = exactly on the linear pace to hit 100% right at the reset; >1.0 = AHEAD of
    pace (will exhaust EARLY — the alarm case); <1.0 = coasting. None when either
    input is None, `util_pct` is negative, or `elapsed_fraction` is <= 0 (the div
    guard). A brand-new window has a tiny elapsed that inflates the ratio toward
    infinity — that is the CALLER's min-elapsed / min-util floor concern, deliberately
    NOT clamped here so this stays a pure ratio."""
    if util_pct is None or elapsed_fraction is None:
        return None
    if util_pct < 0 or elapsed_fraction <= 0:
        return None
    return (util_pct / 100.0) / elapsed_fraction


def projected_exhaustion_epoch(resets_at_epoch: int, window_s: int, util_pct: float | None, now: int) -> int | None:
    """Epoch when this window reaches 100% util at its current AVERAGE pace.

    At `elapsed_s` seconds into the window we have spent `util_pct`%; holding that
    average, reaching 100% takes `elapsed_s × (100 / util_pct)` from the window
    START, so exhaustion = `start + elapsed_s × (100 / util_pct)`. MAY land AFTER
    `resets_at` — that means the window will NOT exhaust early (the caller compares
    the two to decide the lead time). None when `util_pct` is not a usable positive
    percent, or the elapsed fraction is invalid (inherits
    `elapsed_fraction_from_reset`'s fail-safes)."""
    if util_pct is None or util_pct <= 0:
        return None
    frac = elapsed_fraction_from_reset(resets_at_epoch, window_s, now)
    if frac is None:
        return None
    start = resets_at_epoch - window_s
    elapsed_s = frac * window_s
    return int(start + elapsed_s * (100.0 / util_pct))


def worst_window_burn(windows: list[dict], *, now: int) -> dict | None:
    """The single most-alarming usage window across a fleet of windows.

    Each input dict carries `{label, util_pct, resets_at_epoch, window_s}`. For every
    COMPUTABLE window (one that yields a real `burn_ratio`) a COPY is augmented with
    `burn_ratio`, `exhaustion_epoch`, and `early_by_s` (= `resets_at_epoch −
    exhaustion`; POSITIVE means it exhausts BEFORE its reset — the bad case). The
    winner is the window that exhausts EARLIEST in wall-clock time among those
    exhausting early (the nearest rate-limit is what to warn about); if NONE exhaust
    early, the one with the HIGHEST burn ratio. None when no window is computable at
    all (empty input, or every window has an invalid util/elapsed)."""
    augmented: list[dict] = []
    for w in windows:
        resets_at = w.get("resets_at_epoch")
        window_s = w.get("window_s")
        if not isinstance(resets_at, int) or not isinstance(window_s, int):
            continue
        util = w.get("util_pct")
        ratio = burn_ratio(util, elapsed_fraction_from_reset(resets_at, window_s, now))
        if ratio is None:
            continue
        exhaustion = projected_exhaustion_epoch(resets_at, window_s, util, now)
        early_by = (resets_at - exhaustion) if exhaustion is not None else None
        aug = dict(w)
        aug["burn_ratio"] = ratio
        aug["exhaustion_epoch"] = exhaustion
        aug["early_by_s"] = early_by
        augmented.append(aug)
    if not augmented:
        return None
    early = [a for a in augmented if a["early_by_s"] is not None and a["early_by_s"] > 0]
    if early:
        return min(early, key=lambda a: a["exhaustion_epoch"])
    return max(augmented, key=lambda a: a["burn_ratio"])
