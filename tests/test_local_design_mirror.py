"""Tests for the LOCAL design/ TRDD backup mirror (scripts/lib/memory_scopes.py).

Real fixtures, no mocks: HOME / CLAUDE_PROJECT_DIR are redirected to tmp dirs, and the
function under test (``sync_local_design_mirror``) runs unmodified against real files on
disk. Models the same primary<->mirror sync/restore contract as the USER-memory mirror
(``sync_user_memory_mirror``), applied to the CC ``cleanupPeriodDays`` gap in
``~/.claude/projects/<slug>/design/`` (no carve-out, unlike ``memory/``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import memory_scopes as msc  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Redirect HOME + CLAUDE_PROJECT_DIR so the real ~/.claude tree is never touched."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/Users/me/proj")
    return home


def _write(p: Path, text: str = "content") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_sync_primary_to_mirror_copies_trdd_files(_isolate):
    """A primary design/tasks/*.md is copied into the mirror and 'mirrored' is returned."""
    primary = msc.resolve_local_design_dir()
    _write(primary / "tasks" / "TRDD-1-foo.md", "task one")

    result = msc.sync_local_design_mirror()

    mirror = msc.resolve_local_design_mirror_dir()
    assert result == "mirrored"
    assert (mirror / "tasks" / "TRDD-1-foo.md").read_text(encoding="utf-8") == "task one"


def test_restore_mirror_to_primary_when_primary_empty(_isolate):
    """An empty (wiped) primary is repopulated from the mirror and 'restored' is returned."""
    mirror = msc.resolve_local_design_mirror_dir()
    _write(mirror / "proposals" / "TRDD-2-bar.md", "proposal two")

    result = msc.sync_local_design_mirror()

    primary = msc.resolve_local_design_dir()
    assert result == "restored"
    assert (primary / "proposals" / "TRDD-2-bar.md").read_text(encoding="utf-8") == "proposal two"


def test_mirror_only_file_is_never_deleted_when_primary_also_has_content(_isolate):
    """A file present only in the mirror survives a primary->mirror sync — additive only,
    even when the primary has content of its own (so the sync direction is 'mirror')."""
    primary = msc.resolve_local_design_dir()
    mirror = msc.resolve_local_design_mirror_dir()
    _write(primary / "tasks" / "TRDD-1-foo.md", "task one")
    _write(mirror / "tasks" / "TRDD-9-only-in-mirror.md", "mirror only")

    result = msc.sync_local_design_mirror()

    assert result == "mirrored"
    assert (mirror / "tasks" / "TRDD-1-foo.md").exists()
    assert (mirror / "tasks" / "TRDD-9-only-in-mirror.md").read_text(
        encoding="utf-8"
    ) == "mirror only"


def test_nested_lifecycle_subdir_structure_is_preserved(_isolate):
    """All four lifecycle subdirs (proposals/tasks/archived/refused) round-trip intact."""
    primary = msc.resolve_local_design_dir()
    for sub, name in (
        ("proposals", "TRDD-a.md"),
        ("tasks", "TRDD-b.md"),
        ("archived", "TRDD-c.md"),
        ("refused", "TRDD-d.md"),
    ):
        _write(primary / sub / name, sub)

    result = msc.sync_local_design_mirror()

    mirror = msc.resolve_local_design_mirror_dir()
    assert result == "mirrored"
    for sub, name in (
        ("proposals", "TRDD-a.md"),
        ("tasks", "TRDD-b.md"),
        ("archived", "TRDD-c.md"),
        ("refused", "TRDD-d.md"),
    ):
        assert (mirror / sub / name).read_text(encoding="utf-8") == sub


def test_unwritable_mirror_fails_open_without_raising(_isolate, monkeypatch):
    """A copy failure (mirror dir unwritable) is swallowed — session start must not break."""
    primary = msc.resolve_local_design_dir()
    _write(primary / "tasks" / "TRDD-1-foo.md", "task one")

    def _boom(*_a, **_k):
        raise OSError("simulated unwritable mirror")

    monkeypatch.setattr(msc, "_copy_design_subdirs", _boom)

    result = msc.sync_local_design_mirror()

    assert result is None


def test_neither_side_has_content_returns_none(_isolate):
    """A brand-new project with no LOCAL design/ TRDDs anywhere does nothing."""
    assert msc.sync_local_design_mirror() is None
