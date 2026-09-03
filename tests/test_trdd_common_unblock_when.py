"""Unit tests for `unblock_when_predicates` / `pre_block_column` (RTRS704K).

Pure text extraction only — trdd_common has no project-state access, so it
cannot evaluate a predicate, only parse the field. Evaluation is `trdd-drift`'s
job and is tested in `test_trdd_drift_unblock_when.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scripts" / "lib"))

import trdd_common as tc  # noqa: E402


def _head(*extra_lines: str) -> str:
    body = ["---", "trdd-id: ABCDEFGH", "title: a blocked card", "column: blocked"]
    body += list(extra_lines)
    body += ["---", "", "# body"]
    return "\n".join(body)


def test_no_field_yields_no_predicates():
    """The field is opt-in — absent means nothing to auto-unblock."""
    assert tc.unblock_when_predicates(_head()) == []


# ── DONE_COLUMNS / is_done_column (RTRS704K finding #2) ─────────────────────
#
# A `blocked-by:` hold and `unblock-when: trdd:<id> terminal` must only clear on a blocker
# that actually SHIPPED — `is_terminal_column` alone is too broad, since `failed`/`refused`/
# `cancelled`/`superseded` are terminal (closed) but the blocker never landed.


def test_is_done_column_true_for_shipped_states():
    """`complete`/`completed`/`published`/`live` all mean the blocker actually shipped."""
    for col in ("complete", "completed", "published", "live"):
        assert tc.is_done_column(col) is True


def test_is_done_column_false_for_terminal_but_not_shipped_states():
    """`failed`/`refused`/`cancelled`/`superseded` are terminal but never landed — not done."""
    for col in ("failed", "refused", "cancelled", "superseded"):
        assert tc.is_terminal_column(col) is True  # still terminal...
        assert tc.is_done_column(col) is False  # ...but not a shipped blocker


def test_is_done_column_false_for_open_states():
    assert tc.is_done_column("dev") is False
    assert tc.is_done_column("") is False


def test_single_predicate_extracted():
    head = _head("unblock-when: [trdd:ABCD1234 terminal]")
    assert tc.unblock_when_predicates(head) == ["trdd:ABCD1234 terminal"]


def test_multiple_predicates_extracted_in_order():
    head = _head("unblock-when: [date:>=2026-01-01, decision:owner]")
    assert tc.unblock_when_predicates(head) == ["date:>=2026-01-01", "decision:owner"]


def test_field_outside_frontmatter_is_ignored():
    """Line-anchored to the YAML block only — prose mentioning the field must not parse."""
    prose = _head() + "\n\nSee `unblock-when: [decision:x]` documented above.\n"
    assert tc.unblock_when_predicates(prose) == []


def test_pre_block_column_absent_is_empty_string():
    assert tc.pre_block_column(_head()) == ""


def test_pre_block_column_extracted():
    assert tc.pre_block_column(_head("pre-block-column: dev")) == "dev"
