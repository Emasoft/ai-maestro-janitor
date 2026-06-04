"""Tests for the project-map marker/splice surgery (TRDD-e247a349 P2, pure half).

The maintainer detector + /janitor-auto-repomap-on|off commands all route
through these functions, so the safety invariants are pinned here: touch ONLY
the fenced region, preserve every human-narrative byte, and bail (not guess) on
malformed fences. No I/O, no mocks — pure string fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import pytest  # noqa: E402
from repomap import (  # noqa: E402
    FENCE_END,
    FENCE_START,
    FileMap,
    MalformedFences,
    has_map_block,
    insert_map_block,
    read_fence_header,
    remove_map_block,
    render_block,
    replace_map_block,
)

_HUMAN = "# My Project\n\nHand-written narrative the janitor must NEVER touch.\n\n## Gotchas\n\n- be careful\n"


def _block(sha_body: str = "x.py") -> str:
    return render_block([FileMap(path=sha_body, role="r", symbols=[])],
                        generated_iso="2026-05-29T00:00:00+0200", digest="deadbeef")


def test_no_block_detection():
    """A clean CLAUDE.md has no block; header is None; remove is a no-op."""
    assert has_map_block(_HUMAN) is False
    assert read_fence_header(_HUMAN) is None
    assert remove_map_block(_HUMAN) == _HUMAN


def test_insert_appends_after_narrative():
    """insert puts the block at the end with a blank-line separator; narrative is byte-identical above it."""
    out = insert_map_block(_HUMAN, _block())
    assert out.startswith(_HUMAN.rstrip("\n") + "\n\n")
    assert FENCE_START in out and out.rstrip().endswith(FENCE_END)
    assert has_map_block(out)


def test_insert_refuses_when_block_exists():
    """insert raises if a block already exists (caller must replace instead)."""
    once = insert_map_block(_HUMAN, _block())
    with pytest.raises(MalformedFences):
        insert_map_block(once, _block())


def test_replace_swaps_block_preserving_narrative():
    """replace swaps only the fenced region; the human narrative above is untouched byte-for-byte."""
    v1 = insert_map_block(_HUMAN, _block("alpha.py"))
    v2 = replace_map_block(v1, _block("beta.py"))
    # narrative prefix identical
    assert v2.startswith(_HUMAN.rstrip("\n") + "\n\n")
    assert "beta.py" in v2 and "alpha.py" not in v2
    # exactly one block remains
    assert v2.count(FENCE_START) == 1 and v2.count(FENCE_END) == 1


def test_remove_restores_narrative_exactly():
    """remove returns the CLAUDE.md to its pre-insert state (round-trip)."""
    inserted = insert_map_block(_HUMAN, _block())
    assert remove_map_block(inserted) == _HUMAN


def test_header_parse():
    """read_fence_header extracts sha/digest/generated/schema from the START fence."""
    h = read_fence_header(insert_map_block(_HUMAN, _block()))
    assert h is not None
    assert h["digest"] == "deadbeef"
    assert h["generated"] == "2026-05-29T00:00:00+0200"
    assert len(h["sha"]) == 12
    assert h["schema"] == "v1"


def test_malformed_duplicate_start_raises():
    """Two START fences → MalformedFences (never guess which block is real)."""
    twice = insert_map_block(_HUMAN, _block()) + "\n" + _block()
    with pytest.raises(MalformedFences):
        has_map_block(twice)


def test_malformed_end_before_start_raises():
    """END appearing before START → MalformedFences."""
    inverted = f"{FENCE_END}\nstuff\n{FENCE_START} v1 sha=abc digest=d generated=g\nbody\n"
    with pytest.raises(MalformedFences):
        _ = read_fence_header(inverted)


def test_replace_requires_existing_block():
    """replace on a block-less file raises (use insert) — absence must be explicit."""
    with pytest.raises(MalformedFences):
        replace_map_block(_HUMAN, _block())


def test_block_at_top_of_file_round_trips():
    """A block with no preceding narrative removes cleanly (no stray leading newline)."""
    top = _block() + "\n" + _HUMAN
    assert has_map_block(top)
    restored = remove_map_block(top)
    assert restored == _HUMAN
