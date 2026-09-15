"""Tests for scripts/lib/memory_outcome.py — the shared janitor-outcome marker parser.

Regression coverage for the divergence found in review 2026-09-15: memory-maintenance.py's
own copy of this regex pinned the reason to `[a-z-]+`, so a marker with an underscore or a
quoted reason failed the WHOLE regex, not just the reason group, silently turning a present
marker into "no marker found".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import memory_outcome  # noqa: E402


def test_bare_noop_marker_has_no_reason():
    """A bare `noop` marker with no reason suffix parses to (noop, None)."""
    assert memory_outcome.parse_outcome("<!-- janitor-outcome: noop -->") == ("noop", None)


def test_noop_reason_no_work():
    """`noop reason=no-work` parses to the REASON_NO_WORK constant."""
    result = memory_outcome.parse_outcome("<!-- janitor-outcome: noop reason=no-work -->")
    assert result == ("noop", memory_outcome.REASON_NO_WORK)


def test_noop_reason_failed():
    """`noop reason=failed` parses to the REASON_FAILED constant."""
    result = memory_outcome.parse_outcome("<!-- janitor-outcome: noop reason=failed -->")
    assert result == ("noop", memory_outcome.REASON_FAILED)


def test_underscore_reason_is_not_silently_dropped():
    """A reason with an underscore (not the old `[a-z-]+` shape) still parses, verbatim —
    this is exactly the divergence memory-maintenance.py's old regex missed."""
    result = memory_outcome.parse_outcome("<!-- janitor-outcome: noop reason=no_work -->")
    assert result == ("noop", "no_work")


def test_quoted_reason_is_unquoted():
    """A reason wrapped in quotes is stripped down to the bare token."""
    result = memory_outcome.parse_outcome('<!-- janitor-outcome: noop reason="no-work" -->')
    assert result == ("noop", "no-work")


def test_mutation_with_reason():
    """A `mutation` outcome may also carry a reason suffix."""
    result = memory_outcome.parse_outcome("<!-- janitor-outcome: mutation reason=partial -->")
    assert result == ("mutation", "partial")


def test_last_marker_wins_over_a_quoted_example_earlier_in_the_body():
    """A report may quote the marker syntax in prose before the real, appended verdict —
    the LAST occurrence in the text must win, never the first."""
    text = (
        "This pass emits `<!-- janitor-outcome: mutation -->` when pages are merged. "
        "This pass found nothing.\n"
        "<!-- janitor-outcome: noop reason=no-work -->\n"
    )
    assert memory_outcome.parse_outcome(text) == ("noop", memory_outcome.REASON_NO_WORK)


def test_absent_marker_returns_none():
    """A report with no marker at all returns None, not a false match."""
    assert memory_outcome.parse_outcome("# pass report\n\nnothing here\n") is None
