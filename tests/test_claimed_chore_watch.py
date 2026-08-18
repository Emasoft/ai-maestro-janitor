"""claimed_chore_watch — the PURE claimed-but-stale chore watchdog (TRDD-6CRC9SQQ item 1)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import claimed_chore_watch as ccw  # noqa: E402


def test_stale_threshold_uses_3x_when_it_exceeds_the_grace_floor() -> None:
    """A long cadence (6h) picks the 3x bound (18h) because it exceeds cadence+grace."""
    assert ccw.stale_threshold(21600) == 64800


def test_stale_threshold_uses_grace_floor_when_3x_is_smaller() -> None:
    """A short cadence (60s) picks the cadence+600s floor (660s), not the tiny 3x (180s)."""
    assert ccw.stale_threshold(60) == 660
    assert ccw.stale_threshold(60) != 180


def test_classify_ok_for_a_stamp_inside_the_bound() -> None:
    """A stamp younger than the threshold classifies as VERDICT_OK."""
    v = ccw.classify(chore="x", last_run=1000, cadence_s=60, now=1000 + 100)
    assert v.verdict == ccw.VERDICT_OK


def test_classify_stale_for_a_stamp_past_the_bound() -> None:
    """A stamp older than the threshold classifies as VERDICT_STALE."""
    v = ccw.classify(chore="x", last_run=1000, cadence_s=60, now=1000 + 700)
    assert v.verdict == ccw.VERDICT_STALE


def test_classify_ok_exactly_at_the_boundary() -> None:
    """Age equal to the threshold is NOT stale — the comparison is strictly greater-than."""
    threshold = ccw.stale_threshold(60)
    v = ccw.classify(chore="x", last_run=1000, cadence_s=60, now=1000 + threshold)
    assert v.verdict == ccw.VERDICT_OK
    assert v.age_s == threshold


def test_classify_no_evidence_when_last_run_not_positive() -> None:
    """A last_run of 0 (or negative) yields VERDICT_NO_EVIDENCE with age_s == -1."""
    v = ccw.classify(chore="x", last_run=0, cadence_s=60, now=1000)
    assert v.verdict == ccw.VERDICT_NO_EVIDENCE
    assert v.age_s == -1


def test_classify_clamps_a_future_stamp_to_zero_age() -> None:
    """A stamp newer than `now` (clock skew) clamps to age 0 and reports OK, never negative."""
    v = ccw.classify(chore="x", last_run=2000, cadence_s=60, now=1000)
    assert v.age_s == 0
    assert v.verdict == ccw.VERDICT_OK


def test_is_finding_false_only_for_ok() -> None:
    """Verdict.is_finding is False for VERDICT_OK and True for every other verdict."""
    ok = ccw.Verdict("x", ccw.VERDICT_OK, 10, 60, 660)
    stale = ccw.Verdict("x", ccw.VERDICT_STALE, 1000, 60, 660)
    no_evidence = ccw.Verdict("x", ccw.VERDICT_NO_EVIDENCE, -1, 60, 660)
    assert ok.is_finding is False
    assert stale.is_finding is True
    assert no_evidence.is_finding is True


def test_evaluate_empty_when_every_chore_is_fresh() -> None:
    """evaluate() returns no findings when every claimed chore is within its threshold."""
    out = ccw.evaluate(
        ["a", "b"],
        last_run_of=lambda c: 990,
        cadence_of=lambda c: 60,
        now=1000,
    )
    assert out == []


def test_evaluate_skips_chore_with_unknown_cadence() -> None:
    """A chore whose cadence_of returns None is skipped, never guessed at."""
    out = ccw.evaluate(
        ["unknown"],
        last_run_of=lambda c: 0,
        cadence_of=lambda c: None,
        now=1000,
    )
    assert out == []


def test_evaluate_skips_chore_with_nonpositive_cadence() -> None:
    """A chore whose cadence is 0 or negative is skipped, even though it would classify."""
    out = ccw.evaluate(
        ["zero", "negative"],
        last_run_of=lambda c: 0,
        cadence_of=lambda c: {"zero": 0, "negative": -60}[c],
        now=1000,
    )
    assert out == []


def test_evaluate_sorts_stale_before_no_evidence() -> None:
    """STALE findings sort ahead of NO_EVIDENCE findings regardless of chore order."""
    def last_run_of(c: str) -> int:
        return {"missing": 0, "wedged": 1000}[c]

    out = ccw.evaluate(
        ["missing", "wedged"],
        last_run_of=last_run_of,
        cadence_of=lambda c: 60,
        now=1000 + 700,
    )
    assert [v.chore for v in out] == ["wedged", "missing"]
    assert out[0].verdict == ccw.VERDICT_STALE
    assert out[1].verdict == ccw.VERDICT_NO_EVIDENCE


def test_evaluate_sorts_by_ratio_not_absolute_age() -> None:
    """A short-cadence chore with smaller absolute age but bigger overrun ratio outranks a
    long-cadence chore with larger absolute age but a smaller overrun ratio."""
    # short: cadence 60s -> threshold 660s; age 6600s -> ratio 10x
    # long: cadence 21600s (6h) -> threshold 64800s; age 129600s (36h) -> ratio 2x
    # long's absolute age (129600) is far bigger than short's (6600), but short's ratio wins.
    def last_run_of(c: str) -> int:
        return {"short": 129600 - 6600, "long": 129600 - 129600}[c]

    def cadence_of(c: str) -> int:
        return {"short": 60, "long": 21600}[c]

    out = ccw.evaluate(
        ["long", "short"],
        last_run_of=last_run_of,
        cadence_of=cadence_of,
        now=129600,
    )
    assert [v.chore for v in out] == ["short", "long"]


def test_describe_renders_both_verdict_shapes_distinctly() -> None:
    """describe() mentions minutes+bound for a stale chore and 'no completion stamp' for
    a no-evidence chore — the two shapes must not be confusable."""
    stale = ccw.Verdict("rot", ccw.VERDICT_STALE, 3600, 60, 660)
    no_evidence = ccw.Verdict("rot", ccw.VERDICT_NO_EVIDENCE, -1, 60, 660)
    stale_text = ccw.describe(stale)
    no_evidence_text = ccw.describe(no_evidence)
    assert "stale" in stale_text
    assert "bound" in stale_text
    assert "no completion stamp ever" in no_evidence_text
    assert stale_text != no_evidence_text


# --------------------------------------------------------------------------- #
# janitor#225 — the bound must describe the EXECUTOR, not the janitor's roster
# --------------------------------------------------------------------------- #


def test_observed_period_is_the_largest_gap_between_completions() -> None:
    """observed_period measures the executor's own rhythm from its distinct stamps."""
    now = 1_000_000
    assert ccw.observed_period([now - 4 * 3600 * k for k in range(4)]) == 4 * 3600


def test_observed_period_needs_two_completions_to_mean_anything() -> None:
    """A single stamp yields no gap, so the roster cadence must remain the bound."""
    assert ccw.observed_period([1_000_000]) == 0
    assert ccw.observed_period([]) == 0


def test_a_server_running_slower_than_our_roster_is_not_called_stale() -> None:
    """janitor#225: the server moved absorbed user-plugins-update 3h -> 4h; against our
    1h roster the old bound (3h) flagged a healthy server every cycle, forever."""
    now = 1_000_000
    observed = ccw.observed_period([now - 4 * 3600 * k for k in range(4)])
    assert 14400 > ccw.stale_threshold(3600), "precondition: the old bound did fire"
    assert 14400 <= ccw.stale_threshold(3600, observed_s=observed)


def test_calibration_can_only_widen_the_bound_never_narrow_it() -> None:
    """A measured rhythm must never make the detector MORE trigger-happy than the roster."""
    for cadence in (60, 600, 3600, 21600):
        roster = ccw.stale_threshold(cadence)
        for obs in (0, 1, cadence // 2, cadence, cadence * 10):
            assert ccw.stale_threshold(cadence, observed_s=obs) >= roster


def test_the_real_wedge_still_fires_after_calibration() -> None:
    """janitor#221's 3.7-day wedge must remain detected — calibration must not blind it."""
    observed = ccw.observed_period([1_000_000 - 4 * 3600 * k for k in range(4)])
    v = ccw.classify(
        chore="user-plugins-update", last_run=1_000_000 - 319_680, cadence_s=3600,
        now=1_000_000, observed_s=observed,
    )
    assert v.verdict == ccw.VERDICT_STALE


def test_a_wedged_chore_cannot_inflate_its_own_bound() -> None:
    """The anti-self-defeat property: a wedge produces NO new completions, so the measured
    period stops growing. A bound derived from observed AGE would climb forever instead."""
    comps = [1_000_000 - 4 * 3600 * k for k in range(4)]
    before = ccw.observed_period(comps)
    # hours pass with no new completion — the history is unchanged by definition
    assert ccw.observed_period(comps) == before


def test_declared_bound_widens_the_roster_bound() -> None:
    """An executor-declared bound LARGER than the roster default is adopted (rev-8
    contract §9.2: the executor knows its own rhythm)."""
    # cadence 3600 -> roster bound 10800; server declares 14400
    assert ccw.stale_threshold(3600, declared_s=14_400) == 14_400


def test_declared_bound_smaller_than_roster_is_ignored() -> None:
    """Widen-only: a declared bound NARROWER than the roster default is ignored —
    honouring it would let one side's config manufacture false positives (the
    janitor#225 failure in the opposite direction)."""
    # cadence 21600 -> roster bound 64800; a declared 14400 must NOT narrow it
    assert ccw.stale_threshold(21_600, declared_s=14_400) == 64_800


def test_declared_bound_composes_with_observed_widening() -> None:
    """declared and observed widening compose: the final bound is the max of all
    widen-only inputs, never less than the roster default."""
    # roster 10800; observed 7200 -> 3x = 21600; declared 30000 wins
    assert ccw.stale_threshold(3600, observed_s=7_200, declared_s=30_000) == 30_000
    # ...and when the observed widening is the largest, IT wins
    assert ccw.stale_threshold(3600, observed_s=10_000, declared_s=14_400) == 30_000


def test_evaluate_passes_declared_of_through_to_the_threshold() -> None:
    """The per-chore declared_of hook reaches classify: a stamp inside the declared
    (widened) bound is OK even though it is past the roster bound."""
    now = 1_000_000
    verdicts = ccw.evaluate(
        ["marketplace-refresh"],
        last_run_of=lambda c: now - 12_000,   # past roster 10800, inside declared 14400
        cadence_of=lambda c: 3600,
        now=now,
        declared_of=lambda c: 14_400,
    )
    assert verdicts == []  # no finding: the declared bound covered it
