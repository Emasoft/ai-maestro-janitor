"""Regression tests for the wikimem-audit libs LOW findings (L-2..L-10, L-13).

Each test reproduces the exact false-fail / silent-loss the audit documented
(reports/wikimem-audit/20260707_181500+0200-libs-and-clis.md) and proves the
fix. Real code paths, no mocks.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import memory_edit_verify as verify  # noqa: E402
import memory_migrate  # noqa: E402
import memory_txn  # noqa: E402
import memory_txn_cli as cli  # noqa: E402

# --------------------------------------------------------------------------- #
# L-2 — extract_lessons must stop a def's body at the next full-line heading
# --------------------------------------------------------------------------- #

def test_l2_trailing_section_not_swallowed_into_last_lesson():
    """A `## See also` section after the lessons pool is NOT part of the last
    lesson's body (it used to contaminate lessons_preserved comparisons)."""
    page = (
        "body fact\n\n## Notes and lessons learned\n"
        "[^1]: the lesson body that matters here\n\n"
        "## See also\n- [[other-page]]\n"
    )
    lessons = verify.extract_lessons(page)
    assert len(lessons) == 1
    assert "see also" not in lessons[0].lower()
    assert "other-page" not in lessons[0]


def test_l2_multiline_lesson_continuation_still_folded():
    """Indented continuation lines still belong to the lesson (no regression)."""
    page = "## Notes and lessons learned\n[^1]: first line\n  second line\n"
    lessons = verify.extract_lessons(page)
    assert lessons == ["first line second line"]


# --------------------------------------------------------------------------- #
# L-3 — _body_minus_lessons must match the heading as a FULL LINE
# --------------------------------------------------------------------------- #

def test_l3_inline_heading_mention_does_not_truncate_body():
    """A meta-page mentioning `## Notes and lessons learned` mid-sentence keeps
    its later facts in the body haystack (they used to vanish → false-fails)."""
    fact = "this substantive fact line must remain visible to the verifier"
    page = (
        "---\nname: meta\n---\n"
        "every page carries a `## Notes and lessons learned` section by rule.\n"
        f"{fact}\n\n"
        "## Notes and lessons learned\n[^1]: a lesson\n"
    )
    ok, missing = verify.body_facts_preserved([page], page)
    assert ok, missing  # the fact is found in the result's own body


# --------------------------------------------------------------------------- #
# L-4 — footnote refs inside code fences are documentation, not references
# --------------------------------------------------------------------------- #

def test_l4_fenced_footnote_syntax_is_not_a_dangling_ref():
    page = (
        "body\n\n```markdown\ncite a lesson as [^9] and define it as [^9]: text\n```\n"
        "\n## Notes and lessons learned\n"
    )
    ok, unresolved = verify.footnote_refs_resolve(page)
    assert ok, unresolved


def test_l4_real_dangling_ref_outside_fence_still_caught():
    ok, unresolved = verify.footnote_refs_resolve("a fact[^3]\n")
    assert not ok and unresolved == ["3"]


# --------------------------------------------------------------------------- #
# L-5 — per-id comparison: fixing one dangling ref must not licence a new one
# --------------------------------------------------------------------------- #

def test_l5_new_orphan_id_flagged_even_when_total_count_constant():
    source = "fact[^1]\n"                       # [^1] dangling in the source
    result = "fact\n[^1]: now defined\nother[^2]\n"  # fixes 1, orphans 2
    ok, offenders = verify.no_new_dangling_footnote_refs([source], [result])
    assert not ok and offenders == ["[^2]"]


def test_l5_carried_forward_dangling_ref_still_tolerated():
    source = "fact[^1]\n"
    ok, offenders = verify.no_new_dangling_footnote_refs([source], [source])
    assert ok, offenders


# --------------------------------------------------------------------------- #
# L-6 — duplicate-line check must skip fence CONTENTS, not just the ``` line
# --------------------------------------------------------------------------- #

def test_l6_same_command_in_two_code_examples_is_not_a_duplicate():
    cmd = "uv run scripts/memory_txn_cli.py begin SCOPE merge page.md"
    page = f"```bash\n{cmd}\n```\nprose\n```bash\n{cmd}\n```\n"
    ok, dups = verify.no_new_duplicate_lines(page)
    assert ok, dups


def test_l6_duplicate_prose_line_still_caught():
    line = "a substantive fact line repeated verbatim across sections"
    ok, dups = verify.no_new_duplicate_lines(f"{line}\nmiddle\n{line}\n")
    assert not ok and dups


# --------------------------------------------------------------------------- #
# L-7 / L-10 — cmd_commit op cross-check + abort-on-shape-error (real txns)
# --------------------------------------------------------------------------- #

def _seed_page(scope: Path, name: str = "a.md") -> Path:
    p = scope / name
    p.write_text(
        "---\nname: a\nocd: 2026-01-01\nlmd: 2026-01-01\n---\nbody fact line\n\n"
        "## Notes and lessons learned\n",
        encoding="utf-8",
    )
    return p


def _journal(scope: Path, txn_id: str) -> Path:
    return memory_txn.MemoryTxn._staging_root(scope) / f"{txn_id}.json"


def test_l7_op_mismatch_refused_without_destroying_the_txn(tmp_path):
    """`begin merge` + `commit --op repair` is a CALLER error: exit 2, and the
    journal must SURVIVE (a typo'd flag must not abort a valid staged edit)."""
    _seed_page(tmp_path)
    txn = memory_txn.MemoryTxn.begin(tmp_path, "merge", ["a.md"])
    staged = txn.staging_dir / "a.md"
    staged.write_text(staged.read_text(encoding="utf-8") + "edited\n", encoding="utf-8")
    args = SimpleNamespace(scope_root=str(tmp_path), txn_id=txn.txn_id, op="repair", unsplittable=None)
    rc = cli.cmd_commit(args)
    assert rc == 2
    assert _journal(tmp_path, txn.txn_id).exists(), "op mismatch must NOT abort the txn"
    memory_txn.MemoryTxn._load(_journal(tmp_path, txn.txn_id)).abort()  # cleanup


def test_l10_shape_error_aborts_the_txn(tmp_path):
    """A repair-shaped violation (two sources) raised from _verify_repair must
    ABORT — before the fix, staging+journal lingered for the 30-min sweep."""
    _seed_page(tmp_path, "a.md")
    _seed_page(tmp_path, "b.md")
    txn = memory_txn.MemoryTxn.begin(tmp_path, "repair", ["a.md", "b.md"])
    staged = txn.staging_dir / "a.md"
    staged.write_text(staged.read_text(encoding="utf-8") + "edited\n", encoding="utf-8")
    args = SimpleNamespace(scope_root=str(tmp_path), txn_id=txn.txn_id, op="repair", unsplittable=None)
    with pytest.raises(memory_txn.MemoryTxnError):
        cli.cmd_commit(args)
    assert not _journal(tmp_path, txn.txn_id).exists(), "shape error must abort the txn"


# --------------------------------------------------------------------------- #
# L-9 — overview identification when the split retires the source slug
# --------------------------------------------------------------------------- #

def test_l9_ambiguous_overview_is_refused_not_guessed(tmp_path):
    """Source slug retired + no `<stem>-overview` write → explicit refusal, never
    the alphabetical guess that crowned a sub-page as the overview."""
    # A LEGAL split source (hub, ≥2 sections) so the run reaches the overview
    # pick instead of dying earlier at the is_legal_split gate.
    (tmp_path / "plat.md").write_text(
        "---\nname: plat\nocd: 2026-01-01\nlmd: 2026-01-01\n"
        "metadata:\n  tier: hub\n---\n## One\nx\n## Two\ny\n\n"
        "## Notes and lessons learned\n",
        encoding="utf-8",
    )
    txn = memory_txn.MemoryTxn.begin(tmp_path, "split", ["plat.md"])
    # A split-shaped staging: retire plat.md, write two subs with NO overview.
    (txn.staging_dir / "aaa-sub.md").write_text("---\nname: aaa-sub\n---\nx\n", encoding="utf-8")
    (txn.staging_dir / "bbb-sub.md").write_text("---\nname: bbb-sub\n---\ny\n", encoding="utf-8")
    (txn.staging_dir / "plat.md").unlink()
    args = SimpleNamespace(scope_root=str(tmp_path), txn_id=txn.txn_id, op="split", unsplittable=None)
    with pytest.raises(memory_txn.MemoryTxnError, match="cannot identify the overview"):
        cli.cmd_commit(args)


# --------------------------------------------------------------------------- #
# L-13 — classify_corpus must record skipped notes in the plan
# --------------------------------------------------------------------------- #

def test_l13_oversized_note_appears_in_plan_as_skipped(tmp_path):
    (tmp_path / "small.md").write_text("---\nname: small\n---\nfine\n", encoding="utf-8")
    (tmp_path / "huge.md").write_text("x" * (256 * 1024 + 1), encoding="utf-8")
    verdicts = memory_migrate.classify_corpus(tmp_path)
    by_rel = {v.rel_path: v for v in verdicts}
    assert "huge.md" in by_rel, "oversized note must not vanish from the plan"
    assert by_rel["huge.md"].verdict == "LOCAL"
    assert "skipped" in by_rel["huge.md"].reason
