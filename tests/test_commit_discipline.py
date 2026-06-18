"""Tests for the commit-discipline rule + wikimem provenance fields (TRDD-9e4851fc).

These are the deliverables of a docs/rule TRDD: a shipped global rule and the
model's provenance documentation. There is no runtime logic to unit-test, so the
test pins the LOAD-BEARING content — the four obligations + the WHY-resolution
chain — so a future edit cannot silently delete the substance that the wikimem
conflict / fact-verification pass depends on (it sources every superseded-memory
WHY from this chain and refuses to delete a memory with no provenance).
"""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_commit_discipline_rule_ships_with_its_four_obligations():
    """rules/commit-discipline.md ships and carries all four obligations."""
    rule = _PROJECT_ROOT / "rules" / "commit-discipline.md"
    assert rule.is_file(), "rules/commit-discipline.md must ship (rules_installer copies rules/*.md)"
    text = rule.read_text(encoding="utf-8")
    assert "Commit often" in text                      # obligation 1
    assert "after every memory write" in text.lower()  # obligation 2
    assert "in the commit message" in text.lower()     # obligation 3 (WHY in message)
    assert "code comments" in text                      # obligation 4 (WHY in code)


def test_commit_discipline_rule_demands_trdd_in_subject():
    """The rule requires the governing TRDD-<8hex> in the commit subject (the
    blame -> commit -> TRDD greppable chain)."""
    text = (_PROJECT_ROOT / "rules" / "commit-discipline.md").read_text(encoding="utf-8")
    assert "TRDD-<8hex>" in text
    assert "implementation-commits:" in text  # corroborated from the TRDD side


def test_commit_discipline_rule_explains_the_memory_provenance_link():
    """The rule states its raison d'etre: it is the memory system's WHY-provenance
    substrate, and absent provenance the maintainer must NOT delete."""
    text = (_PROJECT_ROOT / "rules" / "commit-discipline.md").read_text(encoding="utf-8")
    assert "never invent" in text.lower() or "never fabricate" in text.lower() or "hallucinated" in text.lower()
    assert "must NOT delete" in text or "un-prunable" in text


def test_wikimem_model_documents_provenance_fields_and_chain():
    """The wikimem model documents the commits:/trdd: fields + the fixed-order
    WHY-resolution chain consumed by the conflict pass."""
    model = _PROJECT_ROOT / "skills" / "janitor-memory-write" / "references" / "wikimem-model.md"
    text = model.read_text(encoding="utf-8")
    assert "commits:" in text and "trdd:" in text
    assert "WHY-resolution chain" in text
    assert "implementation-commits:" in text
    # provenance is the precondition for the destructive (delete) path
    assert "provenance is the precondition" in text.lower()
