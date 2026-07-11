"""Tests for the SessionStart memory breadcrumb (TRDD-98ISATJZ S2, janitor#62).

Two things are under test:

  1. The breadcrumb itself — the ONE line that tells a fresh session its memory
     corpus exists (counts per scope + the `memgrep overview` entry point).

  2. The manifest-vs-code default ratchet. The breadcrumb's sibling surface, the
     autorecall hook, was flipped to ON-by-default in CODE (issue #45) but its
     `plugin.json` userConfig kept `"default": false` and an "(OPT-IN)" title for
     seven releases. Claude Code does not export a userConfig default into the hook
     env (verified empirically: autorecall fires in live sessions with no user
     config set), so the code default governed and the feature really was on — but
     the MANIFEST, which is what a user reads and what the config UI renders, said
     the opposite. `post_mcp_sanitizer_enabled` had the identical drift. The ratchet
     below compares every boolean option's manifest default against the default the
     code passes to `is_truthy_env`, so the two can never disagree again.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import memory_breadcrumb as mb  # noqa: E402  -- local module, needs the sys.path above

# --------------------------------------------------------------------------- #
# format_breadcrumb — pure
# --------------------------------------------------------------------------- #

def test_empty_corpus_emits_no_breadcrumb() -> None:
    """An install with zero notes in every scope prints nothing at all."""
    assert mb.format_breadcrumb({"LOCAL": 0, "PROJECT": 0, "USER": 0}, None) is None


def test_no_overview_dir_emits_no_breadcrumb() -> None:
    """Without a scope to navigate to, the line would name a command with no corpus."""
    assert mb.format_breadcrumb({"LOCAL": 5}, None) is None


def test_breadcrumb_names_every_non_empty_scope_and_the_entry_point() -> None:
    """The line carries the per-scope counts and the `memgrep overview <dir>` entry."""
    line = mb.format_breadcrumb(
        {"LOCAL": 12, "PROJECT": 3, "USER": 8}, Path("/tmp/mem")
    )
    assert line is not None
    assert "12 local" in line
    assert "3 project" in line
    assert "8 user-global" in line
    assert "memgrep overview /tmp/mem" in line
    assert "markdown-memory-recall.md" in line


def test_empty_scopes_are_omitted_not_printed_as_zero() -> None:
    """A project whose only notes are USER-global must not read '0 local + 0 project'."""
    line = mb.format_breadcrumb({"LOCAL": 0, "PROJECT": 0, "USER": 8}, Path("/tmp/mem"))
    assert line is not None
    assert "8 user-global" in line
    assert "0 local" not in line
    assert "0 project" not in line


def test_breadcrumb_carries_counts_never_note_content() -> None:
    """The privacy/injection boundary: the line is integers + a path, nothing else.

    A PROJECT-scope page is untrusted git input from any contributor. If the
    breadcrumb ever inlined titles or descriptions, a poisoned note would ride into
    the session PREFIX on every session start. The autorecall hook is the content
    path and sanitizes; this one must stay content-free.
    """
    line = mb.format_breadcrumb({"LOCAL": 2}, Path("/tmp/mem"))
    assert line is not None
    # Only the fixed template words, the count, and the dir — no interpolation slot
    # exists for a note's text.
    assert "2 local" in line
    assert "/tmp/mem" in line


# --------------------------------------------------------------------------- #
# count_notes — the SSOT / privacy boundary
# --------------------------------------------------------------------------- #

def test_count_notes_excludes_private_user_mem_and_generated_files(tmp_path: Path) -> None:
    """Counting means exactly what recall means: real notes only.

    The private `user-mem/` store is agent-invisible by design (TRDD-4334aad0), and
    MEMORY.md / memory-index.md / *-proposed.md are generated files, not notes. All
    are excluded because `count_notes` delegates to the `memory_scopes` SSOT rather
    than globbing `*.md` itself.
    """
    (tmp_path / "real-note.md").write_text("a note", encoding="utf-8")
    (tmp_path / "another-note.md").write_text("a note", encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text("deprecated stub", encoding="utf-8")
    (tmp_path / "memory-index.md").write_text("generated", encoding="utf-8")
    (tmp_path / "memory-reorg-proposed.md").write_text("detector report", encoding="utf-8")
    private = tmp_path / "user-mem"
    private.mkdir()
    (private / "0001.md").write_text("a PRIVATE user memory", encoding="utf-8")

    assert mb.count_notes(tmp_path) == 2


def test_count_notes_on_an_absent_dir_is_zero_not_a_crash(tmp_path: Path) -> None:
    """It runs inside SessionStart — an unreadable scope must never break the session."""
    assert mb.count_notes(tmp_path / "does-not-exist") == 0


# --------------------------------------------------------------------------- #
# breadcrumb() — the I/O entry point
# --------------------------------------------------------------------------- #

def test_opt_out_env_suppresses_the_breadcrumb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_MEMORY_BREADCRUMB", "false")
    assert mb.breadcrumb() is None


def test_breadcrumb_composes_all_three_live_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end over REAL dirs: LOCAL + PROJECT + USER are all counted, and the
    overview command points at the PROJECT scope (where bootstrap seeds the
    `<project>-overview.md` entry-point page)."""
    home = tmp_path / "home"
    project = tmp_path / "proj"
    project.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_MEMORY_BREADCRUMB", raising=False)

    import memory_scopes

    local = memory_scopes.resolve_local_dir()
    local.mkdir(parents=True)
    for i in range(3):
        (local / f"local-{i}.md").write_text("note", encoding="utf-8")
    # The private store must NOT be counted even though it lives under LOCAL.
    (local / "user-mem").mkdir()
    (local / "user-mem" / "0001.md").write_text("private", encoding="utf-8")

    proj_mem = project / ".claude" / "project" / "memory"
    proj_mem.mkdir(parents=True)
    (proj_mem / "arch.md").write_text("note", encoding="utf-8")

    user = memory_scopes.resolve_user_dir()
    user.mkdir(parents=True)
    (user / "pref-a.md").write_text("note", encoding="utf-8")
    (user / "pref-b.md").write_text("note", encoding="utf-8")

    line = mb.breadcrumb()
    assert line is not None
    assert "3 local" in line
    assert "1 project" in line
    assert "2 user-global" in line
    assert f"memgrep overview {proj_mem}" in line


def test_breadcrumb_is_silent_when_every_scope_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A janitor install with no memory corpus prints nothing — zero noise, zero cost."""
    home = tmp_path / "home"
    project = tmp_path / "proj"
    project.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_MEMORY_BREADCRUMB", raising=False)

    assert mb.breadcrumb() is None


# --------------------------------------------------------------------------- #
# The ratchet: a boolean option's MANIFEST default must equal its CODE default
# --------------------------------------------------------------------------- #

_OPTION_READ = re.compile(
    r'CLAUDE_PLUGIN_OPTION_(\w+)"\s*,\s*(?:default\s*=\s*)?(True|False)\b', re.S
)


def test_no_boolean_option_manifest_default_contradicts_its_code_default() -> None:
    """Every `plugin.json` boolean default must equal the default its code passes to
    `is_truthy_env`.

    This is the guard for a real, seven-release-old bug: `memory_autorecall` and
    `post_mcp_sanitizer_enabled` were switched ON by default in code (issues #45 /
    the narthex sweep) while the manifest still declared `"default": false` and an
    "(OPT-IN)" title. Claude Code only exports `CLAUDE_PLUGIN_OPTION_*` when the user
    has SET the option, so the code default won and the features were genuinely on —
    but every user reading the manifest (or the config UI rendering it) was told the
    opposite, and nobody could discover the opt-OUT. A manifest that lies about
    behaviour is a bug even when the behaviour is right.
    """
    manifest = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    options = manifest["userConfig"]

    mismatches: list[str] = []
    checked = 0
    for path in sorted((REPO / "scripts").rglob("*.py")):
        src = path.read_text(encoding="utf-8", errors="replace")
        for match in _OPTION_READ.finditer(src):
            name = match.group(1).lower()
            spec = options.get(name)
            if not spec or spec.get("type") != "boolean":
                continue  # not a declared boolean option (e.g. an int/str knob)
            checked += 1
            code_default = match.group(2) == "True"
            if code_default != spec.get("default"):
                mismatches.append(
                    f"{name}: plugin.json default={spec.get('default')!r} but "
                    f"{path.relative_to(REPO)} passes default={code_default!r}"
                )

    assert not mismatches, "manifest/code default drift:\n  " + "\n  ".join(mismatches)
    # Sanity: the scan must actually be finding option reads, or it proves nothing.
    assert checked >= 15, f"only {checked} boolean option reads found — the scan regressed"


def test_the_two_recall_surfaces_are_on_by_default_in_the_manifest() -> None:
    """The memory system's value is realized at RECALL time, so both push-surfaces
    (autorecall + the breadcrumb) must ship ON — and the manifest must say so."""
    options = json.loads(
        (REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["userConfig"]
    for name in ("memory_autorecall", "memory_breadcrumb"):
        assert options[name]["default"] is True, f"{name} must default ON"
        assert "OPT-IN" not in options[name]["title"], f"{name} title still says OPT-IN"
