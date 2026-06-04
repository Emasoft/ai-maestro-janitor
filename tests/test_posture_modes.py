"""Tests for scripts/lib/posture_modes.py — the 3-mode posture matrix.

Covers Proposal 1 (3-mode matrix + selection + grade application) and
Proposal 6 (DOC-only compliance cross-walk) from the
`deep-posture-metrics` deep-dive report.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import posture  # type: ignore[import-not-found]  # noqa: E402
import posture_modes  # type: ignore[import-not-found]  # noqa: E402

# --------------------------------------------------------------------- #
# Mode definitions                                                      #
# --------------------------------------------------------------------- #


def test_modes_tuple_has_exactly_three_entries() -> None:
    """The matrix MUST have Strict, Balanced, and Emergency-Exception — no more, no less."""
    assert len(posture_modes.MODES) == 3


def test_modes_ordered_strict_balanced_emergency() -> None:
    """Order matters: MODES[0] is strictest, MODES[-1] is most lenient."""
    names = tuple(m.name for m in posture_modes.MODES)
    assert names == ("strict", "balanced", "emergency-exception")


def test_strict_mode_severity_floor_is_major() -> None:
    """Strict surfaces MAJOR+ findings (tighter than Balanced's HIGH+)."""
    strict = posture_modes.select_mode("strict")
    assert strict.severity_floor == "MAJOR"


def test_balanced_mode_severity_floor_is_high() -> None:
    """Balanced surfaces HIGH+ findings — matches current janitor default."""
    balanced = posture_modes.select_mode("balanced")
    assert balanced.severity_floor == "HIGH"


def test_emergency_mode_severity_floor_is_high() -> None:
    """Emergency-Exception keeps the same heartbeat floor as Balanced."""
    em = posture_modes.select_mode("emergency-exception")
    assert em.severity_floor == "HIGH"


def test_strict_allows_only_narrow_overrides() -> None:
    """Strict refuses whole-detector mutes and env-var bypasses."""
    strict = posture_modes.select_mode("strict")
    assert "sha" in strict.allowed_overrides
    assert "glob" in strict.allowed_overrides
    assert "detector" not in strict.allowed_overrides
    assert "env" not in strict.allowed_overrides
    assert "first-run" not in strict.allowed_overrides


def test_balanced_allows_most_overrides_except_first_run() -> None:
    """Balanced honours the standard overrides; first-run stays guarded."""
    balanced = posture_modes.select_mode("balanced")
    assert set(balanced.allowed_overrides) == {"sha", "glob", "detector", "env"}


def test_emergency_allows_all_overrides() -> None:
    """Emergency-Exception is the carve-out mode — every override permitted."""
    em = posture_modes.select_mode("emergency-exception")
    assert set(em.allowed_overrides) == {
        "sha", "glob", "detector", "env", "first-run",
    }


def test_strict_waiver_window_is_seven_days() -> None:
    """Strict forces re-review of CRITICAL waivers within a week."""
    strict = posture_modes.select_mode("strict")
    assert strict.max_age_days_for_critical_waivers == 7


def test_balanced_waiver_window_is_thirty_days() -> None:
    """Balanced waivers last one sprint cadence."""
    balanced = posture_modes.select_mode("balanced")
    assert balanced.max_age_days_for_critical_waivers == 30


def test_emergency_waiver_window_is_ninety_days() -> None:
    """Emergency-Exception waivers cover a realistic incident-response window."""
    em = posture_modes.select_mode("emergency-exception")
    assert em.max_age_days_for_critical_waivers == 90


# --------------------------------------------------------------------- #
# default_mode() and select_mode()                                      #
# --------------------------------------------------------------------- #


def test_default_mode_is_balanced() -> None:
    """No-regression contract: the janitor's default mode is Balanced."""
    assert posture_modes.default_mode().name == "balanced"


def test_default_mode_returns_singleton_from_modes() -> None:
    """default_mode() returns one of the canonical MODES entries — identity match."""
    d = posture_modes.default_mode()
    assert d in posture_modes.MODES


def test_select_mode_strict() -> None:
    m = posture_modes.select_mode("strict")
    assert m.name == "strict"


def test_select_mode_balanced() -> None:
    m = posture_modes.select_mode("balanced")
    assert m.name == "balanced"


def test_select_mode_emergency_exception() -> None:
    m = posture_modes.select_mode("emergency-exception")
    assert m.name == "emergency-exception"


def test_select_mode_unknown_raises_keyerror() -> None:
    """A typo in `.janitor.toml` must be loud, not a silent default."""
    with pytest.raises(KeyError):
        posture_modes.select_mode("stict")  # typo of strict


def test_select_mode_keyerror_message_lists_legal_names() -> None:
    """Error message helps the user fix the typo without grep'ing docs."""
    with pytest.raises(KeyError) as excinfo:
        posture_modes.select_mode("unknown")
    msg = str(excinfo.value)
    assert "strict" in msg
    assert "balanced" in msg
    assert "emergency-exception" in msg


def test_select_mode_is_case_sensitive() -> None:
    """Capitalised names are user errors — fail loud."""
    with pytest.raises(KeyError):
        posture_modes.select_mode("Strict")


# --------------------------------------------------------------------- #
# apply_mode_to_grade() — letter-shift semantics                        #
# --------------------------------------------------------------------- #


def test_balanced_does_not_shift_grade() -> None:
    """Balanced preserves whatever posture.compute() returned."""
    g = posture.compute(critical=1)  # letter C, score 65
    out = posture_modes.apply_mode_to_grade(g, posture_modes.BALANCED)
    assert out.letter == "C"
    assert out.score == 65


def test_strict_tightens_a_to_b() -> None:
    """An A under Balanced becomes B under Strict — 1 band stricter."""
    g = posture.compute()  # clean repo, A
    out = posture_modes.apply_mode_to_grade(g, posture_modes.STRICT)
    assert out.letter == "B"


def test_strict_tightens_b_to_c() -> None:
    g = posture.compute(high=1)  # B
    out = posture_modes.apply_mode_to_grade(g, posture_modes.STRICT)
    assert out.letter == "C"


def test_strict_tightens_c_to_d() -> None:
    g = posture.compute(critical=1)  # C
    out = posture_modes.apply_mode_to_grade(g, posture_modes.STRICT)
    assert out.letter == "D"


def test_strict_tightens_d_to_f() -> None:
    g = posture.compute(critical=2)  # D
    out = posture_modes.apply_mode_to_grade(g, posture_modes.STRICT)
    assert out.letter == "F"


def test_strict_f_stays_f() -> None:
    """F is the floor — Strict cannot push past it."""
    g = posture.compute(critical=3)  # F
    out = posture_modes.apply_mode_to_grade(g, posture_modes.STRICT)
    assert out.letter == "F"


def test_emergency_loosens_f_to_d() -> None:
    """Emergency-Exception lifts F by 1 (to D) — the carve-out window."""
    g = posture.compute(critical=3)  # F
    out = posture_modes.apply_mode_to_grade(g, posture_modes.EMERGENCY_EXCEPTION)
    assert out.letter == "D"


def test_emergency_loosens_d_to_c() -> None:
    g = posture.compute(critical=2)  # D
    out = posture_modes.apply_mode_to_grade(g, posture_modes.EMERGENCY_EXCEPTION)
    assert out.letter == "C"


def test_emergency_loosens_c_to_b() -> None:
    g = posture.compute(critical=1)  # C
    out = posture_modes.apply_mode_to_grade(g, posture_modes.EMERGENCY_EXCEPTION)
    assert out.letter == "B"


def test_emergency_loosens_b_to_a() -> None:
    g = posture.compute(high=1)  # B
    out = posture_modes.apply_mode_to_grade(g, posture_modes.EMERGENCY_EXCEPTION)
    assert out.letter == "A"


def test_emergency_a_stays_a() -> None:
    """A is the ceiling — Emergency-Exception cannot lift past it."""
    g = posture.compute()  # A
    out = posture_modes.apply_mode_to_grade(g, posture_modes.EMERGENCY_EXCEPTION)
    assert out.letter == "A"


def test_apply_preserves_score_and_counts() -> None:
    """Score + counts pass through unchanged; only the letter shifts."""
    g = posture.compute(critical=1, high=2, major=3, minor=4)
    out = posture_modes.apply_mode_to_grade(g, posture_modes.STRICT)
    assert out.score == g.score
    assert out.critical == g.critical
    assert out.high == g.high
    assert out.major == g.major
    assert out.minor == g.minor
    assert out.mal_advisories == g.mal_advisories


def test_emergency_cannot_mask_mal_advisories() -> None:
    """MAL-* short-circuits: known-malicious package keeps F regardless of mode."""
    g = posture.compute(mal_advisories=1)  # F via short-circuit
    out = posture_modes.apply_mode_to_grade(g, posture_modes.EMERGENCY_EXCEPTION)
    assert out.letter == "F"
    assert out.mal_advisories == 1


def test_strict_does_not_double_punish_mal_advisories() -> None:
    """MAL-* is already F. Strict's downgrade is a no-op when letter is F."""
    g = posture.compute(mal_advisories=2)
    out = posture_modes.apply_mode_to_grade(g, posture_modes.STRICT)
    assert out.letter == "F"


def test_apply_returns_posturegrade_instance() -> None:
    """Output must be a PostureGrade so downstream code that calls
    posture.format_drift_line() etc. keeps working."""
    g = posture.compute(critical=1)
    out = posture_modes.apply_mode_to_grade(g, posture_modes.STRICT)
    assert isinstance(out, posture.PostureGrade)


def test_apply_balanced_returns_same_object() -> None:
    """Balanced is a no-op — returning the original keeps object identity."""
    g = posture.compute(high=1)
    out = posture_modes.apply_mode_to_grade(g, posture_modes.BALANCED)
    assert out is g


# --------------------------------------------------------------------- #
# compliance_map() — Proposal 6 DOC-only cross-walk                     #
# --------------------------------------------------------------------- #


def test_compliance_map_known_rule_returns_six_frameworks() -> None:
    """Every mapped rule has all six framework cells populated."""
    cm = posture_modes.compliance_map("osv_mal_advisories")
    assert set(cm.keys()) == {
        "OWASP_Agentic", "MITRE_ATTACK", "SOC2",
        "ISO27001", "HIPAA", "NIST_800_53",
    }


def test_compliance_map_osv_mal_advisories_soc2() -> None:
    cm = posture_modes.compliance_map("osv_mal_advisories")
    assert cm["SOC2"] == ["CC7.1"]


def test_compliance_map_osv_mal_advisories_mitre() -> None:
    cm = posture_modes.compliance_map("osv_mal_advisories")
    assert cm["MITRE_ATTACK"] == ["T1195.002"]


def test_compliance_map_osv_mal_advisories_nist_multi() -> None:
    """Some rules cite multiple NIST controls — must be returned in order."""
    cm = posture_modes.compliance_map("osv_mal_advisories")
    assert cm["NIST_800_53"] == ["SI-3", "SR-3"]


def test_compliance_map_secret_in_settings_json() -> None:
    cm = posture_modes.compliance_map("secret_in_settings_json")
    assert cm["OWASP_Agentic"] == ["A03 Sensitive info"]
    assert cm["HIPAA"] == ["§164.312(d)"]


def test_compliance_map_unknown_rule_returns_empty_dict() -> None:
    """Unmapped rule_id returns {} rather than raising — doctor report
    skips the compliance column gracefully."""
    cm = posture_modes.compliance_map("rule_that_does_not_exist")
    assert cm == {}


def test_compliance_map_returns_independent_copy() -> None:
    """Mutating the returned dict must NOT pollute later lookups."""
    cm1 = posture_modes.compliance_map("osv_mal_advisories")
    cm1["SOC2"].append("hacked")
    cm2 = posture_modes.compliance_map("osv_mal_advisories")
    assert cm2["SOC2"] == ["CC7.1"]


def test_compliance_map_covers_seven_canonical_rules() -> None:
    """The report's table lists exactly these 7 rule_ids."""
    expected = {
        "osv_mal_advisories",
        "mcp_lockfile_drift",
        "phantom_aiconfig",
        "cargo_vet_missing",
        "gh_actions_unpinned",
        "npm_ignore_scripts_off",
        "secret_in_settings_json",
    }
    for rule_id in expected:
        assert posture_modes.compliance_map(rule_id), (
            f"rule_id {rule_id!r} should be mapped but compliance_map "
            f"returned an empty dict"
        )
