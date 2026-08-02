"""Tests for the pure burn-rate rotation gate (TRDD-FQXBURNR).

The FAIL-OPEN contract is the load-bearing half: with no samples, too few, flat/declining
slope, stale samples, or no learned caps, every function returns its neutral value —
`cmd_auto` must behave byte-for-byte as the pure threshold did. The incident shapes
(fast burn below threshold; effective cap below the configured bar; rotating onto a
fast-burning alternate) are the positive half.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "oauth_rotator"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import burn_gate as bg  # noqa: E402

NOW = 1_700_000_000.0


def _ring(*pairs):
    return [[NOW + dt, u] for dt, u in pairs]


# ---------- slope / projection ----------


def test_slope_needs_three_fresh_samples_spanning_two_minutes() -> None:
    assert bg.slope_pct_per_min([], NOW) is None
    assert bg.slope_pct_per_min(_ring((-60, 50), (0, 51)), NOW) is None  # 2 samples
    assert bg.slope_pct_per_min(_ring((-60, 50), (-30, 51), (0, 52)), NOW) is None  # 1 min span
    s = bg.slope_pct_per_min(_ring((-240, 50), (-120, 52), (0, 54)), NOW)
    assert s is not None and abs(s - 1.0) < 0.01  # 4% over 4 min


def test_flat_or_declining_slope_is_none() -> None:
    """A window reset (declining) or an idle account (flat) has no wall to project."""
    assert bg.slope_pct_per_min(_ring((-240, 60), (-120, 60), (0, 60)), NOW) is None
    assert bg.slope_pct_per_min(_ring((-240, 60), (-120, 40), (0, 20)), NOW) is None


def test_stale_samples_are_dead() -> None:
    """Samples past the max age vanish from the slope — a ring bridging a 5h reset must
    not manufacture a projection."""
    old = _ring((-7200, 10), (-7000, 20), (-6800, 30))
    assert bg.slope_pct_per_min(old, NOW) is None
    assert bg.minutes_to_wall(old, NOW) is None


def test_minutes_to_wall_projects_the_incident_shape() -> None:
    """6%/min at 61% → the 100% wall is ~6.5 min out — inside any sane horizon, while the
    97% threshold gate still reads 'within limits'. This IS the 2026-07-17 failure."""
    ring = _ring((-180, 43), (-120, 49), (-60, 55), (0, 61))
    m = bg.minutes_to_wall(ring, NOW)
    assert m is not None and 5.0 < m < 8.0
    assert bg.projected_near(ring, [], NOW, horizon_min=15.0) is True
    assert bg.projected_near(ring, [], NOW, horizon_min=3.0) is False  # horizon respected


def test_already_at_cap_projects_zero() -> None:
    ring = _ring((-240, 90), (-120, 95), (0, 100))
    assert bg.minutes_to_wall(ring, NOW, cap_pct=100.0) == 0.0


def test_nonmonotonic_timestamps_drop_the_older_prefix() -> None:
    ring = bg.record_sample(_ring((-60, 50), (0, 55)), NOW - 120, 40)
    assert ring == [[NOW - 120, 40.0]], "a clock step back must not interleave"


def test_record_sample_bounds_the_ring_and_skips_unknown() -> None:
    ring: list = []
    for i in range(50):
        ring = bg.record_sample(ring, NOW + i, 50.0 + i)
    assert len(ring) == bg.SAMPLE_KEEP
    assert bg.record_sample(ring, NOW + 99, None) == ring  # unknown records nothing


# ---------- learned cap ----------


def test_cap_learned_from_freshest_sample_and_bounded() -> None:
    ring = _ring((-120, 58), (-60, 60), (0, 63))
    caps = bg.record_cap_sample([], ring, NOW)
    assert caps == [63.0]
    for _ in range(10):
        caps = bg.record_cap_sample(caps, ring, NOW)
    assert len(caps) == bg.CAP_KEEP


def test_cap_not_learned_from_stale_or_empty_ring() -> None:
    assert bg.record_cap_sample([], [], NOW) == []
    stale = _ring((-7200, 61))
    assert bg.record_cap_sample([], stale, NOW) == []


def test_effective_switch_at_lowers_bar_with_margin_and_floor() -> None:
    assert bg.effective_switch_at(97.0, []) == 97.0  # fail-open
    assert bg.effective_switch_at(97.0, [63.0]) == 58.0  # 63 − 5
    assert bg.effective_switch_at(97.0, [63.0, 70.0]) == 58.0  # min wins
    assert bg.effective_switch_at(97.0, [12.0]) == bg.EFFECTIVE_FLOOR_PCT  # absurd sample floored
    assert bg.effective_switch_at(55.0, [80.0]) == 55.0  # never RAISES the bar


# ---------- the composed verdict + state plumbing ----------


def test_live_burn_verdict_fail_open_on_empty_state() -> None:
    """The byte-for-byte contract: an account with no history gets None — the caller's
    threshold behavior stands unchanged."""
    assert bg.live_burn_verdict({}, "a@x", NOW) is None


def test_live_burn_verdict_fires_on_fast_burn() -> None:
    state: dict = {}
    for dt, u in ((-180, 43), (-120, 49), (-60, 55), (0, 61)):
        bg.observe(state, "a@x", NOW + dt, u, 10.0)  # 7d flat — must not interfere
    why = bg.live_burn_verdict(state, "a@x", NOW)
    assert why is not None and "5h wall projected" in why


def test_live_burn_verdict_fires_on_learned_cap() -> None:
    """After a debounced 429 taught us the wall sits at ~63%, a later steady 61% reading
    (below every configured threshold, too slow to project) must still rotate."""
    state: dict = {}
    for dt, u in ((-240, 62), (-180, 62.5), (-120, 63)):
        bg.observe(state, "a@x", NOW + dt, u, 10.0)
    bg.observe_wall(state, "a@x", NOW - 100)  # the 429 — learns cap ≈ 63
    for dt, u in ((-60, 61), (-30, 61), (0, 61)):  # flat: no slope projection possible
        bg.observe(state, "a@x", NOW + dt, u, 10.0)
    why = bg.live_burn_verdict(state, "a@x", NOW)
    assert why is not None and "learned cap" in why


def test_observe_wall_without_fresh_samples_learns_nothing() -> None:
    state: dict = {}
    bg.observe_wall(state, "a@x", NOW)
    assert bg.account_caps(state, "a@x").get("5h", []) == []


def test_state_plumbing_survives_corrupt_shapes() -> None:
    """Corrupt state.json content degrades to fail-open, never raises — matching the
    rotator's corruption-recovery posture."""
    state = {"usage_samples": "garbage", "learned_caps": 7}
    assert bg.account_rings(state, "a@x") == {}
    assert bg.account_caps(state, "a@x") == {}
    assert bg.live_burn_verdict(state, "a@x", NOW) is None
    # observe() on the corrupt shape must not raise; it may or may not repair, but the
    # verdict path stays fail-open either way.
    bg.observe(state, "a@x", NOW, 50.0, 10.0)


def test_candidate_walls_soon_fail_open_on_sparse_history() -> None:
    """Alternates are only probed while rotation is considered — one sample must never
    disqualify a candidate."""
    assert bg.candidate_walls_soon(_ring((0, 42)), [], NOW) is False
    ring = _ring((-180, 42), (-120, 48), (-60, 54), (0, 61))  # the rotated-onto incident shape
    assert bg.candidate_walls_soon(ring, [], NOW) is True
