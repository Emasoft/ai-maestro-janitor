"""Plugin-root reference form guard (TRDD-JQLBZMMN).

Claude Code substitutes only the BRACED `${CLAUDE_PLUGIN_ROOT}` when it loads a skill,
command or agent Markdown. The bare `$CLAUDE_PLUGIN_ROOT` is never substituted and the
variable is empty in every Bash shell, so a bare form expands to `/scripts/...`. Files read
from disk (skills/*/references/*.md) get no substitution at all, in either form.
"""

from __future__ import annotations

import re
from pathlib import Path

_PATH_USE = re.compile(r"\$\{?CLAUDE_PLUGIN_ROOT\}?/")

_ROOT = Path(__file__).resolve().parent.parent
_BARE = re.compile(r"\$CLAUDE_PLUGIN_ROOT\b")


def _loaded_files() -> list[Path]:
    files = list((_ROOT / "skills").glob("**/SKILL.md"))
    files += (_ROOT / "commands").glob("**/*.md")
    files += (_ROOT / "agents").glob("**/*.md")
    return sorted(files)


def _reference_files() -> list[Path]:
    return sorted((_ROOT / "skills").glob("**/references/**/*.md"))


def test_no_bare_plugin_root_in_loaded_markdown() -> None:
    """Skill, command and agent Markdown never use the unsubstituted bare form."""
    hits = [
        f"{f.relative_to(_ROOT)}:{n}"
        for f in _loaded_files()
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if _BARE.search(line)
    ]
    assert not hits, f"bare $CLAUDE_PLUGIN_ROOT in loaded content: {hits}"


def test_no_plugin_root_in_disk_read_references() -> None:
    """Reference files read from disk never use the plugin root as a path, since neither form resolves."""
    hits = [
        f"{f.relative_to(_ROOT)}:{n}"
        for f in _reference_files()
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if _PATH_USE.search(line)
    ]
    assert not hits, f"CLAUDE_PLUGIN_ROOT used as a path in disk-read references: {hits}"
