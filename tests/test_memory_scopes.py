"""Tests for the shared three-scope memory-root resolver (scripts/lib/memory_scopes.py).

Real fixtures, no mocks: HOME / CLAUDE_PROJECT_DIR are redirected to tmp dirs and a
real ``git init`` creates the PROJECT-scope repo, so the live ``~/.claude`` tree and
the real plugin-DATA dir are never touched. This module is the SSOT extracted from
memory-maintenance + memory-librarian (TRDD-87935f21 priority #2); these tests pin
the behavior both detectors now depend on — especially the USER-scope gotcha (the
fixed plugin-DATA path is used, NOT ``${CLAUDE_PLUGIN_DATA}``, which at heartbeat
time points at the wrong plugin).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import memory_scopes as msc  # noqa: E402


def _git_init(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # A bogus CLAUDE_PLUGIN_DATA that resolve_user_dir MUST ignore (the gotcha):
    # at heartbeat time this var points at whatever plugin owns the turn.
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "WRONG-plugin" / "data"))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return home


# ---- project_slug ----------------------------------------------------------

def test_project_slug_dashes_separators():
    """Every path separator becomes a dash; a leading sep yields a leading dash."""
    assert msc.project_slug("/Users/me/Code/proj") == "-Users-me-Code-proj"


def test_project_slug_is_literal_not_normalized():
    """The slug is built from the literal string, never a resolved/normalized path."""
    assert msc.project_slug("/a/b/../c") == "-a-b-..-c"


# ---- resolve_local_dir -----------------------------------------------------

def test_resolve_local_dir_uses_slug(monkeypatch, _isolate):
    """LOCAL = $HOME/.claude/projects/<slug>/memory for CLAUDE_PROJECT_DIR."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/Users/me/proj")
    got = msc.resolve_local_dir()
    assert got == _isolate / ".claude" / "projects" / "-Users-me-proj" / "memory"


# ---- resolve_user_dir (the hard-coded-path gotcha) -------------------------

def test_resolve_user_dir_ignores_claude_plugin_data(_isolate):
    """USER root is the FIXED janitor plugin-DATA path, NOT ${CLAUDE_PLUGIN_DATA}."""
    got = msc.resolve_user_dir()
    expected = (
        _isolate / ".claude" / "plugins" / "data"
        / "ai-maestro-janitor-ai-maestro-plugins" / "memory"
    )
    assert got == expected
    assert "WRONG-plugin" not in str(got)


# ---- resolve_project_dir ---------------------------------------------------

def test_resolve_project_dir_in_git_repo(tmp_path, monkeypatch):
    """Inside a git repo, PROJECT = <toplevel>/.claude/project/memory."""
    repo = tmp_path / "repo"
    _git_init(repo)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    got = msc.resolve_project_dir()
    assert got is not None
    # macOS /tmp symlinks through /private — compare resolved roots.
    assert got.resolve() == (repo.resolve() / ".claude" / "project" / "memory")


def test_resolve_project_dir_none_outside_repo(tmp_path, monkeypatch):
    """Outside any git repo, PROJECT resolves to None (never raises)."""
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(bare))
    assert msc.resolve_project_dir() is None


# ---- resolve_scope_dirs ----------------------------------------------------

def test_resolve_scope_dirs_existing_only_most_specific_first(
    monkeypatch, _isolate
):
    """Only scopes whose dir EXISTS are returned, in LOCAL → PROJECT → USER order.

    PROJECT is omitted here because CLAUDE_PROJECT_DIR is not a git repo (its cwd
    does not even exist) → resolve_project_dir returns None.
    """
    proj = "/Users/me/proj"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", proj)
    local = _isolate / ".claude" / "projects" / msc.project_slug(proj) / "memory"
    local.mkdir(parents=True)
    user = msc.resolve_user_dir()
    user.mkdir(parents=True)

    out = msc.resolve_scope_dirs()
    assert [label for label, _ in out] == ["LOCAL", "USER"]


def test_resolve_scope_dirs_empty_when_nothing_exists(monkeypatch):
    """No scope dirs on disk → an empty list (silent, never an error)."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/Users/me/nonexistent")
    assert msc.resolve_scope_dirs() == []


def test_resolve_scope_dirs_includes_project_in_git_repo(tmp_path, monkeypatch):
    """A real git repo whose .claude/project/memory EXISTS is returned as PROJECT.

    HOME is already redirected by the autouse fixture; the repo is a sibling tmp
    dir so LOCAL/USER do not exist and only PROJECT is on disk.
    """
    repo = tmp_path / "repo"
    _git_init(repo)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    (repo / ".claude" / "project" / "memory").mkdir(parents=True)

    out = msc.resolve_scope_dirs()
    assert [label for label, _ in out] == ["PROJECT"]


# ---- coexistence primitives (TRDD-ab232dbd) --------------------------------

def test_resolve_wiki_dir_is_the_wiki_subnamespace(tmp_path):
    """The curated wiki lives at ``<scope_root>/wiki`` — the buffer at the root, the
    wiki one level down, so memgrep recall (which recurses the root) covers both."""
    assert msc.resolve_wiki_dir(tmp_path / "memory") == tmp_path / "memory" / "wiki"
    assert msc.resolve_wiki_dir(tmp_path / "memory").name == msc.WIKI_SUBDIR


def test_is_curated_wiki_page_true_for_full_frontmatter():
    """A wikimem page (``node_type: memory`` and/or ``tier:``) reads as CURATED —
    harvest SKIPS it. Both nested-under-metadata and top-level keys are detected."""
    nested = "---\nname: x\nmetadata:\n  node_type: memory\n  tier: hub\n---\nbody\n"
    top_tier = "---\nname: x\ndescription: y\ntier: component\n---\nbody\n"
    assert msc.is_curated_wiki_page(nested)
    assert msc.is_curated_wiki_page(top_tier)


def test_is_curated_wiki_page_false_for_raw_harness_note():
    """A raw harness BUFFER note (minimal frontmatter: name/description/metadata.type,
    NO node_type/tier) reads as RAW — harvest MIRRORS it. The harness writes exactly
    this shape, so it must never be mistaken for an already-curated page."""
    raw = '---\nname: foo\ndescription: "a fact"\nmetadata:\n  type: feedback\n---\nbody\n'
    assert not msc.is_curated_wiki_page(raw)


def test_is_curated_wiki_page_false_without_frontmatter():
    """No frontmatter block at all (or an unclosed fence) → RAW (a bare note is a
    buffer artifact, not a curated wiki page)."""
    assert not msc.is_curated_wiki_page("just plain text, no frontmatter\n")
    assert not msc.is_curated_wiki_page("---\nname: x\ntier: hub\n(no closing fence)\n")
