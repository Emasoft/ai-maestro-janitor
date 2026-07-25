"""Tests for the MEMORY.md ↔ wikimem bridge line (owner directive 2026-07-25).

`MEMORY.md` is the HARNESS's file; the janitor maintains exactly ONE line in it — a
link to the project's `<project>-overview.md` wiki page — and interferes with nothing
else. These tests pin that contract from both sides:

  * the ONE line is added when missing and re-added after deletion, and
  * every OTHER byte of the file is preserved, because the previous model "stubbed"
    MEMORY.md and destroyed harness-written pointer lines. That regression is the
    reason this module is append-only, so the preservation assertions below are the
    real point of the file — not the happy path.

Real filesystem throughout (tmp_path), no mocks: the whole contract is about what
actually lands on disk.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import memory_bridge as mbr  # noqa: E402  -- local module, needs the sys.path above

# A realistic harness-written MEMORY.md: pointer lines the janitor must never touch.
HARNESS_CONTENT = """# MEMORY

- [Some fact the harness recorded](some-fact.md) — a hook
- [Another harness memory](another.md) — another hook
"""


def _scope(tmp_path: Path, *, memory_md: str | None = HARNESS_CONTENT,
           overview: str | None = "demo-overview.md") -> Path:
    """Build a scope root with an optional MEMORY.md and an optional overview page."""
    root = tmp_path / "memory"
    (root / "wiki").mkdir(parents=True)
    if memory_md is not None:
        (root / mbr.MEMORY_MD).write_text(memory_md, encoding="utf-8")
    if overview is not None:
        (root / "wiki" / overview).write_text("# Overview\n", encoding="utf-8")
    return root


# --------------------------------------------------------------------------- #
# find_overview_page
# --------------------------------------------------------------------------- #

def test_finds_overview_page_recursively_under_wiki(tmp_path: Path) -> None:
    """The entry page is found recursively — a curated corpus keeps it under wiki/."""
    root = _scope(tmp_path)
    found = mbr.find_overview_page(root)
    assert found is not None and found.parent.name == "wiki"


def test_overview_found_by_suffix(tmp_path: Path) -> None:
    """Matches memgrep's own rule: basename ends with `-overview.md`."""
    root = _scope(tmp_path, overview="ai-maestro-janitor-overview.md")
    found = mbr.find_overview_page(root)
    assert found is not None and found.name == "ai-maestro-janitor-overview.md"


def test_overview_absent_returns_none(tmp_path: Path) -> None:
    """A corpus that was never bootstrapped has no entry page."""
    assert mbr.find_overview_page(_scope(tmp_path, overview=None)) is None


def test_overview_match_is_case_insensitive(tmp_path: Path) -> None:
    """memgrep lowercases before matching, so a capitalised page must still resolve."""
    root = _scope(tmp_path, overview="Demo-Overview.md")
    assert mbr.find_overview_page(root) is not None


def test_multiple_overviews_pick_is_deterministic(tmp_path: Path) -> None:
    """Two candidates must not make the bridge flap between runs."""
    root = _scope(tmp_path, overview="b-overview.md")
    (root / "a-overview.md").write_text("# A\n", encoding="utf-8")
    first = mbr.find_overview_page(root)
    second = mbr.find_overview_page(root)
    assert first == second
    assert first is not None and first.name == "a-overview.md"  # shallower path wins


# --------------------------------------------------------------------------- #
# ensure_bridge_line — the contract
# --------------------------------------------------------------------------- #

def test_adds_the_bridge_line_when_missing(tmp_path: Path) -> None:
    """The ONE line the janitor owns is appended when absent."""
    root = _scope(tmp_path)
    assert mbr.ensure_bridge_line(root) == mbr.OUTCOME_ADDED
    text = (root / mbr.MEMORY_MD).read_text(encoding="utf-8")
    assert "demo-overview.md" in text


def test_harness_content_is_preserved_byte_for_byte(tmp_path: Path) -> None:
    """THE regression guard: appending the bridge must not disturb harness lines."""
    root = _scope(tmp_path)
    mbr.ensure_bridge_line(root)
    text = (root / mbr.MEMORY_MD).read_text(encoding="utf-8")
    assert text.startswith(HARNESS_CONTENT)
    for line in HARNESS_CONTENT.splitlines():
        assert line in text


def test_exactly_one_line_is_added(tmp_path: Path) -> None:
    """'Exactly ONE line' is literal — count them."""
    root = _scope(tmp_path)
    before = len((root / mbr.MEMORY_MD).read_text(encoding="utf-8").splitlines())
    mbr.ensure_bridge_line(root)
    after = len((root / mbr.MEMORY_MD).read_text(encoding="utf-8").splitlines())
    assert after == before + 1


def test_is_idempotent(tmp_path: Path) -> None:
    """A second run reports PRESENT and leaves the file byte-identical."""
    root = _scope(tmp_path)
    assert mbr.ensure_bridge_line(root) == mbr.OUTCOME_ADDED
    once = (root / mbr.MEMORY_MD).read_bytes()
    assert mbr.ensure_bridge_line(root) == mbr.OUTCOME_PRESENT
    assert (root / mbr.MEMORY_MD).read_bytes() == once


def test_re_adds_after_deletion(tmp_path: Path) -> None:
    """'Re-add if it is deleted' — the explicit duty in the owner's directive."""
    root = _scope(tmp_path)
    mbr.ensure_bridge_line(root)
    (root / mbr.MEMORY_MD).write_text(HARNESS_CONTENT, encoding="utf-8")  # user deleted it
    assert mbr.ensure_bridge_line(root) == mbr.OUTCOME_ADDED
    assert "demo-overview.md" in (root / mbr.MEMORY_MD).read_text(encoding="utf-8")


def test_never_creates_memory_md(tmp_path: Path) -> None:
    """Creation is the harness's business; a janitor-made MEMORY.md would be a
    second system claiming the same filename."""
    root = _scope(tmp_path, memory_md=None)
    assert mbr.ensure_bridge_line(root) == mbr.OUTCOME_NO_MEMORY_MD
    assert not (root / mbr.MEMORY_MD).exists()


def test_no_overview_leaves_file_untouched(tmp_path: Path) -> None:
    """With no entry page there is nothing to point at — never write a broken link."""
    root = _scope(tmp_path, overview=None)
    before = (root / mbr.MEMORY_MD).read_bytes()
    assert mbr.ensure_bridge_line(root) == mbr.OUTCOME_NO_OVERVIEW
    assert (root / mbr.MEMORY_MD).read_bytes() == before


def test_respects_a_hand_written_link(tmp_path: Path) -> None:
    """A human who wrote their own link to the same page must not get a duplicate."""
    root = _scope(tmp_path, memory_md="# MEMORY\n\nSee [the wiki](wiki/demo-overview.md).\n")
    before = (root / mbr.MEMORY_MD).read_bytes()
    assert mbr.ensure_bridge_line(root) == mbr.OUTCOME_PRESENT
    assert (root / mbr.MEMORY_MD).read_bytes() == before


def test_file_without_trailing_newline_is_not_mangled(tmp_path: Path) -> None:
    """Appending to a file whose last line lacks \\n must not join two lines."""
    root = _scope(tmp_path, memory_md="# MEMORY\n\n- [a](a.md) — hook")
    mbr.ensure_bridge_line(root)
    lines = (root / mbr.MEMORY_MD).read_text(encoding="utf-8").splitlines()
    assert lines[-2] == "- [a](a.md) — hook"
    assert "demo-overview.md" in lines[-1]


def test_link_is_relative_not_absolute(tmp_path: Path) -> None:
    """PROJECT-scope MEMORY.md is PUSHED — an absolute path would leak one machine's
    layout into every contributor's clone."""
    root = _scope(tmp_path)
    mbr.ensure_bridge_line(root)
    text = (root / mbr.MEMORY_MD).read_text(encoding="utf-8")
    assert "(wiki/demo-overview.md)" in text
    assert str(tmp_path) not in text


def test_never_raises_on_unreadable_scope(tmp_path: Path) -> None:
    """Runs on the SessionStart path — it must fail OPEN, never cost a session."""
    assert mbr.ensure_bridge_line(tmp_path / "does-not-exist") == mbr.OUTCOME_NO_MEMORY_MD
