"""closeable-candidate ignores design/-only citing commits (janitor#332, TRDD-8BNV75TV, round 2).

Pure over a parsed record and fake seams — no real git.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import trdd_common as tc  # noqa: E402

_TODAY = date(2026, 10, 7)


def _verdict(*, task_type: str = "bugfix", body: str = "", ships_code=lambda sha: True):
    text = (
        f"---\ntrdd-id: TESTID01\ntitle: T\ncolumn: dev\ntask-type: {task_type}\nblocked-by: []\n"
        "implementation-commits: [abc1234]\nupdated: 2026-10-01T00:00:00+0200\n---\n"
        f"\nplain body\n{body}\n"
    )
    rec = tc.parse_record_text(text, uid="TESTID01")
    return tc.reconcile(
        rec, lambda sha: True, lambda uid: "", today=_TODAY, commit_ships_code=ships_code
    )


def test_design_only_citing_commit_is_not_closeable():
    assert "closeable-candidate" not in _verdict(ships_code=lambda sha: False).fired


def test_code_commit_is_still_closeable():
    assert "closeable-candidate" in _verdict(ships_code=lambda sha: True).fired


def test_docs_card_with_a_design_only_commit_is_still_closeable():
    assert "closeable-candidate" in _verdict(task_type="docs", ships_code=lambda sha: False).fired


def test_card_writing_a_spec_with_a_design_only_commit_is_still_closeable():
    body = "Writes (exclusive): design/specs/foo-spec.md, its tests"
    assert "closeable-candidate" in _verdict(body=body, ships_code=lambda sha: False).fired


def test_card_writing_only_code_paths_gets_no_design_exemption():
    body = "Writes (exclusive): scripts/lib/x.py"
    assert "closeable-candidate" not in _verdict(body=body, ships_code=lambda sha: False).fired
