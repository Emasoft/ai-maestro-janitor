"""Tests for state.parse_nonneg_int / state.coerce_int (CC-compat, TRDD-CCCOMPAT).

CC 2.1.208 fixed integer env vars silently using the mantissa of scientific notation
(`1e6` became `1`); CC 2.1.211 added digit-separator spellings (`64_000`). The janitor's
~50 `CLAUDE_PLUGIN_OPTION_*` int knobs flow through state.coerce_int, so it must accept
the SAME spellings — otherwise a knob a user set the way CC documents is silently ignored
and the default used. These pin the shared parser.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import state  # noqa: E402


def test_parse_nonneg_int_accepts_plain_and_separators() -> None:
    assert state.parse_nonneg_int("270000") == 270_000
    assert state.parse_nonneg_int("64_000") == 64_000      # digit separator (CC 2.1.211)
    assert state.parse_nonneg_int("270_000") == 270_000
    assert state.parse_nonneg_int("0") == 0


def test_parse_nonneg_int_accepts_scientific_whole_numbers() -> None:
    assert state.parse_nonneg_int("1e6") == 1_000_000      # CC 2.1.208 (not "1")
    assert state.parse_nonneg_int("2.7e5") == 270_000
    assert state.parse_nonneg_int("1.5e6") == 1_500_000


def test_parse_nonneg_int_rejects_non_integers_and_negatives() -> None:
    assert state.parse_nonneg_int("1.5") is None           # fractional → reject
    assert state.parse_nonneg_int("-5") is None            # negative → reject
    assert state.parse_nonneg_int("-1e6") is None
    assert state.parse_nonneg_int("0x10") is None          # hex never for a knob
    assert state.parse_nonneg_int("1__0") is None          # malformed separator
    assert state.parse_nonneg_int("inf") is None
    assert state.parse_nonneg_int("nan") is None
    assert state.parse_nonneg_int("900 seconds") is None   # the classic typo
    assert state.parse_nonneg_int("") is None


def test_coerce_int_uses_the_shared_spellings_and_falls_back() -> None:
    assert state.coerce_int("64_000", 60) == 64_000
    assert state.coerce_int("1e6", 60) == 1_000_000
    assert state.coerce_int("2.7e5", 60) == 270_000
    assert state.coerce_int(None, 60) == 60
    assert state.coerce_int("", 60) == 60
    assert state.coerce_int("1.5", 60) == 60               # fractional → default
    assert state.coerce_int("junk", 60) == 60
