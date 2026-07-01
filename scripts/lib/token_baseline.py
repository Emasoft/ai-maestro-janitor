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


# cache_read is the cheap ~0.1x context re-read; output/input/cache_creation are full (or
# 1.25x) price. This weighted proxy tracks the effective billed load closely enough for
# RELATIVE anomaly detection AND, paired with the OAuth utilization%, for absolute cap
# estimation (the calibration absorbs the proxy's constant factor).
def weighted_tokens(rec: dict) -> int:
    return (
        int(rec.get("output", 0) or 0)
        + int(rec.get("input", 0) or 0)
        + int(rec.get("cache_creation", 0) or 0)
        + int(rec.get("cache_read", 0) or 0) // 10
    )


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
    return sum(
        weighted_tokens(r)
        for r in records
        if isinstance(r.get("ts"), (int, float)) and lo <= int(r["ts"]) <= now
    )


def max_window_sum(records: list[dict], window_s: int) -> int:
    """The largest weighted-token sum over ANY `window_s`-wide time window in `records`
    (a sliding window ending at each record). This is the BUSIEST observed window — an
    empirical LOWER BOUND on the account's real cap for that window length (you sustained
    at least this much). Stdlib O(n log n) sort + O(n) sweep; {} → 0."""
    if window_s <= 0:
        return 0
    pts = sorted(
        (int(r["ts"]), weighted_tokens(r))
        for r in records
        if isinstance(r.get("ts"), (int, float))
    )
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


def project_exhaustion_minutes(
    remaining_weighted: int, recent_rate_per_min: float
) -> float | None:
    """Minutes until the remaining budget is exhausted at `recent_rate_per_min`. None when
    the rate is ~0 (never exhausts) or the remaining budget is non-positive."""
    if recent_rate_per_min <= 0 or remaining_weighted <= 0:
        return None
    return remaining_weighted / recent_rate_per_min
