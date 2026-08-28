"""Tests for the CLAUDE.md free-rider write queue (TRDD-LFSWY0C6).

Any write to CLAUDE.md invalidates the prompt-cache prefix for every session on the
machine, so `queue_if_stale` must NEVER write it — only `drain_if_queued`, called from a
moment (PostCompact) that already pays the invalidation. The RED test is the whole point
of this card: detecting drift must leave CLAUDE.md byte-identical.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import claudemd_queue as cq  # noqa: E402

_MARKER_REL = ".janitor/state/claudemd-migration-pending.flag"


def _drifted_repo(tmp_path: Path) -> Path:
    """A repo with one real wikimem page and a CLAUDE.md carrying no wikimem-index
    fence at all — `index_is_stale` is unconditionally True in that state."""
    memdir = tmp_path / ".claude" / "project" / "memory"
    memdir.mkdir(parents=True)
    (memdir / "some-page.md").write_text(
        '---\nname: some-page\ndescription: "a symptom"\nocd: 2026-08-01\nlmd: 2026-08-01\n'
        "metadata:\n  node_type: memory\n  type: project\n  tier: component\n---\nbody\n",
        encoding="utf-8",
    )
    (tmp_path / "CLAUDE.md").write_text(
        "# demo\n\nSee https://github.com/example/demo\n", encoding="utf-8"
    )
    return tmp_path


def test_queue_if_stale_marks_pending_without_touching_claude_md(tmp_path: Path) -> None:
    """RED case: drift is detected and recorded, but CLAUDE.md's bytes never move."""
    root = _drifted_repo(tmp_path)
    before = (root / "CLAUDE.md").read_bytes()
    assert cq.queue_if_stale(root) is True
    after = (root / "CLAUDE.md").read_bytes()
    assert after == before
    assert (root / _MARKER_REL).is_file()


def test_queue_if_stale_no_claude_md_is_a_noop(tmp_path: Path) -> None:
    """No CLAUDE.md at all -> nothing to queue, nothing marked."""
    root = tmp_path / "no-claude-md"
    root.mkdir()
    assert cq.queue_if_stale(root) is False
    assert not (root / _MARKER_REL).exists()


def test_drain_if_queued_without_marker_is_a_noop(tmp_path: Path) -> None:
    """No pending marker -> drain performs no write and reports False."""
    root = _drifted_repo(tmp_path)
    before = (root / "CLAUDE.md").read_bytes()
    assert cq.drain_if_queued(root) is False
    assert (root / "CLAUDE.md").read_bytes() == before


def test_drain_if_queued_with_marker_writes_and_clears(tmp_path: Path) -> None:
    """A pending marker -> drain performs the deferred write and removes the marker."""
    root = _drifted_repo(tmp_path)
    assert cq.queue_if_stale(root) is True
    marker = root / _MARKER_REL
    assert marker.is_file()

    assert cq.drain_if_queued(root) is True
    assert not marker.exists()
    written = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert "JANITOR-WIKIMEM-INDEX-START" in written


def test_round_trip_queue_drain_leaves_nothing_pending(tmp_path: Path) -> None:
    """queue -> drain -> queue_if_stale now sees a fresh index and reports no drift."""
    root = _drifted_repo(tmp_path)
    assert cq.queue_if_stale(root) is True
    assert cq.drain_if_queued(root) is True
    assert cq.queue_if_stale(root) is False
    assert not (root / _MARKER_REL).exists()
