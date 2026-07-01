"""Tests for the adaptive token-usage baseline + anomaly primitives (TRDD-EDSFEQ5C).

Real, no mocks. The classify_recent cases are grounded in the measured shape of the
live meter log (heavy-tailed + bursty): a normal burst must NOT alarm, a true outlier
MUST, and — the subtle one — a huge spike in a PERFECTLY FLAT history (MAD=0) must still
alarm (the bug the max(floor, z-band, median*ratio) threshold fixes).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import token_baseline as tb  # noqa: E402


def _rec(ts: int, output: int = 0, inp: int = 0, cache_read: int = 0, cache_creation: int = 0) -> dict:
    return {"ts": ts, "output": output, "input": inp,
            "cache_read": cache_read, "cache_creation": cache_creation}


def _buckets_records(values: list[int], bucket_s: int = 300) -> list[dict]:
    """One record per bucket: bucket index i holds a record of `values[i]` output tokens."""
    return [_rec(i * bucket_s, output=v) for i, v in enumerate(values)]


# ── weighted_tokens ────────────────────────────────────────────────────────────
def test_weighted_output_only():
    assert tb.weighted_tokens(_rec(1, output=100)) == 100


def test_weighted_all_fields_cache_read_tenth():
    # 100 + 50 + 20 + 100//10 = 180
    assert tb.weighted_tokens(_rec(1, output=100, inp=50, cache_creation=20, cache_read=100)) == 180


def test_weighted_missing_fields_zero():
    assert tb.weighted_tokens({"ts": 1}) == 0


# ── bucketize ──────────────────────────────────────────────────────────────────
def test_bucketize_groups_and_sums():
    recs = [_rec(0, output=10), _rec(100, output=5), _rec(300, output=7)]  # bucket 0: 15, bucket 1: 7
    assert tb.bucketize(recs, 300) == {0: 15, 1: 7}


def test_bucketize_nonpositive_bucket_empty():
    assert tb.bucketize([_rec(0, output=1)], 0) == {}


def test_bucketize_skips_missing_ts():
    assert tb.bucketize([{"output": 5}, _rec(0, output=3)], 300) == {0: 3}


# ── robust_baseline / anomaly_score / percentile ────────────────────────────────
def test_robust_baseline_empty():
    assert tb.robust_baseline([]) == (0.0, 0.0)


def test_robust_baseline_flat_zero_mad():
    assert tb.robust_baseline([100, 100, 100]) == (100.0, 0.0)


def test_robust_baseline_mad():
    med, mad = tb.robust_baseline([1, 2, 3, 4, 5])
    assert med == 3.0 and mad == 1.0  # |x-3| = [2,1,0,1,2] → median 1


def test_anomaly_score_zero_mad_is_zero():
    assert tb.anomaly_score(9999.0, 100.0, 0.0) == 0.0


def test_anomaly_score_normal():
    assert abs(tb.anomaly_score(189.0, 100.0, 10.0) - 6.0) < 0.05


def test_percentile_edges():
    assert tb.percentile([], 95) == 0
    assert tb.percentile([5], 95) == 5
    assert tb.percentile([1, 2, 3, 4, 5], 50) == 3


# ── classify_recent ─────────────────────────────────────────────────────────────
def test_classify_too_little_history_none():
    assert tb.classify_recent(_buckets_records([100] * 5)) is None


def test_classify_normal_burst_not_anomaly():
    # 19 history buckets ~100 (mild spread), newest-complete = 130 (a normal wobble)
    hist = [90, 110, 95, 105, 100, 120, 88, 112, 99, 101, 97, 103, 108, 92, 100, 106, 94, 111, 100]
    v = tb.classify_recent(_buckets_records(hist + [130]))
    assert v is not None and not v.is_anomaly


def test_classify_true_outlier_is_anomaly():
    hist = [90, 110, 95, 105, 100, 120, 88, 112, 99, 101, 97, 103, 108, 92, 100, 106, 94, 111, 100]
    v = tb.classify_recent(_buckets_records(hist + [5000]))
    assert v is not None and v.is_anomaly
    assert v.current == 5000 and v.n_history == len(hist)


def test_classify_flat_history_huge_spike_is_anomaly():
    """The degenerate case: MAD=0 (flat history) + a 1000x spike must STILL flag."""
    v = tb.classify_recent(_buckets_records([100] * 12 + [100_000]))
    assert v is not None and v.is_anomaly


def test_classify_flat_history_tiny_bump_not_anomaly():
    """Flat history + a 1% bump must NOT flag (multiplicative bar protects it)."""
    v = tb.classify_recent(_buckets_records([100] * 12 + [101]))
    assert v is not None and not v.is_anomaly


def test_classify_now_excludes_in_progress_bucket():
    # buckets 0..12 present; bucket 12 is a huge in-progress spike. With now in bucket 12,
    # it is excluded → tests bucket 11 (normal) → not anomaly. Without now → tests bucket 12.
    recs = _buckets_records([100] * 12 + [99_999])
    excl = tb.classify_recent(recs, now=12 * 300 + 10)
    incl = tb.classify_recent(recs)
    assert excl is not None and not excl.is_anomaly  # in-progress spike excluded
    assert incl is not None and incl.is_anomaly       # newest bucket tested → flagged


# ── rolling_sum / per_minute / max_window_sum ───────────────────────────────────
def test_rolling_sum_window_filter():
    recs = [_rec(0, output=1000), _rec(5000, output=50), _rec(5900, output=70)]
    # window = last 1000s up to now=5900 → includes ts 5000 and 5900, excludes ts 0
    assert tb.rolling_sum(recs, 1000, 5900) == 120


def test_per_minute():
    assert tb.per_minute(600, 300) == 120.0  # 600 tokens over 5 min = 120/min


def test_max_window_sum_finds_busiest():
    # a quiet stretch then a burst clustered within one 300s window
    recs = [_rec(0, output=10), _rec(10_000, output=100), _rec(10_100, output=100),
            _rec(10_200, output=100)]
    assert tb.max_window_sum(recs, 300) == 300  # the 3 burst records land in one 300s window


def test_max_window_sum_empty():
    assert tb.max_window_sum([], 300) == 0


# ── estimate_window_cap / project_exhaustion_minutes ────────────────────────────
def test_estimate_cap_from_utilization():
    # spent 8M at 40% utilization → cap ≈ 20M
    assert tb.estimate_window_cap(40.0, 8_000_000) == 20_000_000


def test_estimate_cap_nonpositive_util_none():
    assert tb.estimate_window_cap(0.0, 8_000_000) is None
    assert tb.estimate_window_cap(None, 8_000_000) is None


def test_project_exhaustion_minutes():
    assert tb.project_exhaustion_minutes(1000, 10.0) == 100.0


def test_project_exhaustion_none_when_idle():
    assert tb.project_exhaustion_minutes(1000, 0.0) is None
    assert tb.project_exhaustion_minutes(0, 10.0) is None
