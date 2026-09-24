"""Tests for the shared cron-period parser (TRDD-D7RLXAN1 report §2).

`orphaned_resume.cadence_seconds` and `fleet_scan.stale_threshold_for` each used to carry
their own `field.startswith("*/")` copy of this check, so arm_prepare's per-project stagger
(`*/N` -> `{offset}-59/N`) silently broke both. This is the one parser both now import.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scripts" / "lib"))

import cron_period  # noqa: E402


def test_plain_minute_step_form():
    assert cron_period.period_minutes("*/5 * * * *") == 5
    assert cron_period.period_minutes("*/30 * * * *") == 30
    assert cron_period.period_minutes("*/60 * * * *") == 60


def test_staggered_arm_prepare_form_matches_its_plain_equivalent():
    assert cron_period.period_minutes("7-59/15 * * * *") == 15
    assert cron_period.period_minutes("0-59/5 * * * *") == 5
    assert cron_period.period_minutes("4-59/5 * * * *") == 5  # offset == step-1, still legal


def test_staggered_offset_outside_arm_prepare_range_is_rejected():
    """`_stagger()` only ever emits `0 <= offset < step` (`hash % step`) — an offset that
    could never have come from it (hand-edited/corrupted state) must not produce a
    plausible-looking period, per the module's own "fail to the stricter default" contract."""
    assert cron_period.period_minutes("5-59/5 * * * *") is None   # offset == step
    assert cron_period.period_minutes("59-59/5 * * * *") is None  # offset >> step


def test_garbage_and_out_of_shape_crons_return_none():
    assert cron_period.period_minutes("") is None
    assert cron_period.period_minutes(None) is None  # type: ignore[arg-type]
    assert cron_period.period_minutes("0 9 * * *") is None       # fixed-hour, not a step
    assert cron_period.period_minutes("*/0 * * * *") is None     # nonsense step
    assert cron_period.period_minutes("*/90 * * * *") is None    # >60 is not a minute step
    assert cron_period.period_minutes("7-58/15 * * * *") is None  # only a literal "-59/" tail is the janitor's stagger
    assert cron_period.period_minutes("*/bogus * * * *") is None
