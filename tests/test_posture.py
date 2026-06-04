"""Tests for scripts/lib/posture.py — the heartbeat posture grade."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import posture  # type: ignore[import-not-found]  # noqa: E402

# ---------- Letter band boundaries --------------------------------------


def test_grade_a_clean_repo() -> None:
    g = posture.compute()
    assert g.letter == "A"
    assert g.score == 100
    assert g.critical == 0
    assert g.high == 0


def test_grade_a_one_major_ok() -> None:
    """A single MAJOR finding is tolerable for grade A."""
    g = posture.compute(major=1)
    assert g.letter == "A"


def test_grade_b_one_high() -> None:
    g = posture.compute(high=1)
    assert g.letter == "B"


def test_grade_b_two_major() -> None:
    g = posture.compute(major=2)
    assert g.letter == "B"


def test_grade_c_one_critical() -> None:
    g = posture.compute(critical=1)
    assert g.letter == "C"


def test_grade_c_two_high() -> None:
    g = posture.compute(high=2)
    assert g.letter == "C"


def test_grade_d_two_critical() -> None:
    g = posture.compute(critical=2)
    assert g.letter == "D"


def test_grade_d_seven_major() -> None:
    g = posture.compute(major=7)
    assert g.letter == "D"


def test_grade_f_three_critical() -> None:
    g = posture.compute(critical=3)
    assert g.letter == "F"


def test_grade_f_five_high() -> None:
    g = posture.compute(high=5)
    assert g.letter == "F"


# ---------- Numeric score behaviour -------------------------------------


def test_score_clamps_at_zero() -> None:
    """Many CRITICAL findings cannot drive score below 0."""
    g = posture.compute(critical=100)
    assert g.score == 0


def test_score_deducts_weighted() -> None:
    """One CRITICAL = 35 deduction → score 65."""
    g = posture.compute(critical=1)
    assert g.score == 65


def test_score_combines_severities() -> None:
    """1 HIGH + 2 MAJOR + 3 MINOR = 18 + 12 + 3 = 33; score 67."""
    g = posture.compute(high=1, major=2, minor=3)
    assert g.score == 67


# ---------- Daily-surfacing semantics -----------------------------------


def test_should_surface_today_first_call(tmp_path: Path) -> None:
    stamp = tmp_path / "posture-last-day.ts"
    assert posture.should_surface_today(stamp) is True


def test_mark_surfaced_then_skip(tmp_path: Path) -> None:
    stamp = tmp_path / "posture-last-day.ts"
    assert posture.should_surface_today(stamp) is True
    posture.mark_surfaced_today(stamp)
    assert posture.should_surface_today(stamp) is False


def test_atomic_stamp_persists(tmp_path: Path) -> None:
    """The stamp file is written atomically (tmp → replace), so a
    concurrent reader either sees the old value or the new value, never
    a partial write."""
    stamp = tmp_path / "posture-last-day.ts"
    posture.mark_surfaced_today(stamp)
    assert stamp.exists()
    assert len(stamp.read_text()) == 10  # YYYY-MM-DD = 10 chars


# ---------- Drift-line format -------------------------------------------


def test_drift_line_for_grade_a() -> None:
    g = posture.compute()
    line = posture.format_drift_line(g)
    assert "[posture-grade]" in line
    assert "A (score 100/100)" in line
    assert "keep it green" in line


def test_drift_line_for_grade_f() -> None:
    g = posture.compute(critical=5, high=10)
    line = posture.format_drift_line(g)
    assert "F" in line
    assert "untenable" in line.lower() or "stop" in line.lower()
    assert "5 CRITICAL" in line
    assert "10 HIGH" in line


# ---------- OSV-MAL distinct posture flag (Wave 8) ----------------------


def test_mal_advisory_forces_grade_f() -> None:
    """A single MAL-* (known-malicious package installed) → F even if
    every other severity count is zero."""
    g = posture.compute(mal_advisories=1)
    assert g.letter == "F"


def test_mal_advisory_overrides_otherwise_clean() -> None:
    """A repo that would normally score A drops to F when MAL-* is set."""
    g = posture.compute(critical=0, high=0, major=0, minor=0, mal_advisories=2)
    assert g.letter == "F"
    assert g.mal_advisories == 2
    assert g.score == 0  # 2 × 70 = 140 deduction, clamped to 0


def test_drift_line_for_mal_emergency() -> None:
    g = posture.compute(mal_advisories=1)
    line = posture.format_drift_line(g)
    assert "OSV MAL-*" in line
    assert "EMERGENCY" in line
    assert "known-malicious" in line.lower()
    # Surfacing the wiper/dead-man-switch advice — supply-chain-defense-skills
    # incident-response rule.
    assert "wiper" in line.lower() or "dead-man" in line.lower()


def test_mal_advisory_with_other_severities() -> None:
    """MAL count surfaces FIRST in the line; other severities follow."""
    g = posture.compute(critical=2, mal_advisories=1)
    line = posture.format_drift_line(g)
    # MAL section appears before CRITICAL section
    mal_pos = line.find("OSV MAL-*")
    crit_pos = line.find("CRITICAL")
    assert 0 <= mal_pos < crit_pos


def test_grade_with_no_mal_unchanged() -> None:
    """Default mal_advisories=0 preserves existing band semantics."""
    g = posture.compute(critical=1)
    assert g.letter == "C"
    assert g.mal_advisories == 0
