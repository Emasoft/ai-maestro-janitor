"""Guardrail: the shipped memory-recall shell snippets must be zsh-safe.

Regression test for the silent-recall bug (2026-06-14): the recall rule + skills
built `ROOTS` as a space-joined string and passed it UNQUOTED
(`memgrep recall "$SYMPTOM" $ROOTS`), relying on word-splitting. bash word-splits
an unquoted expansion; **zsh (the macOS default shell) does NOT** — so the whole
`ROOTS` string reached memgrep as ONE bogus path-with-spaces and recall returned
zero results with exit 0 (a silent failure). Every agent copy-pasting the
documented recall command on a zsh box got an empty memory.

The fix is the bash/zsh-portable ARRAY form: `ROOTS+=("$d")` built, `"${ROOTS[@]}"`
expanded. These tests assert the broken string form is GONE from every shipped
doc and the array form is present — cheap protection against a regression that
unit tests of the Python resolvers can never catch (the bug lived in markdown).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Every shipped surface that documents the multi-root recall snippet.
SNIPPET_DOCS = [
    REPO / "rules" / "markdown-memory-recall.md",
    REPO / "skills" / "janitor-memory-recall" / "SKILL.md",
    REPO / "skills" / "janitor-memory-update" / "SKILL.md",
]

# The exact broken construct: a space-joined string build `ROOTS="$ROOTS ...`.
BROKEN_BUILD = re.compile(r'ROOTS="\$ROOTS\b')
# The zsh-safe array build.
ARRAY_BUILD = re.compile(r'ROOTS\+=\("\$d"\)')


@pytest.mark.parametrize("doc", SNIPPET_DOCS, ids=lambda p: p.parent.name + "/" + p.name)
def test_recall_snippet_doc_exists(doc: Path) -> None:
    """Each shipped recall-snippet doc is present (so the other asserts aren't vacuous)."""
    assert doc.is_file(), f"expected shipped recall-snippet doc missing: {doc}"


@pytest.mark.parametrize("doc", SNIPPET_DOCS, ids=lambda p: p.parent.name + "/" + p.name)
def test_no_broken_word_split_string_build(doc: Path) -> None:
    """No doc may build ROOTS as a space-joined string (the zsh silent-recall bug)."""
    text = doc.read_text(encoding="utf-8")
    hits = [
        f"{doc.name}:{i}: {ln.strip()}"
        for i, ln in enumerate(text.splitlines(), 1)
        # ignore the autopsy comment that quotes the anti-pattern as prose
        if BROKEN_BUILD.search(ln) and "word-split" not in ln and "ARRAY" not in ln
    ]
    assert not hits, "broken zsh-unsafe ROOTS string-build resurfaced:\n" + "\n".join(hits)


@pytest.mark.parametrize("doc", SNIPPET_DOCS, ids=lambda p: p.parent.name + "/" + p.name)
def test_uses_zsh_safe_array_build(doc: Path) -> None:
    """Each doc builds ROOTS as a bash/zsh-portable array."""
    text = doc.read_text(encoding="utf-8")
    assert ARRAY_BUILD.search(text), f"{doc.name} lost the zsh-safe `ROOTS+=(\"$d\")` array build"


@pytest.mark.parametrize("doc", SNIPPET_DOCS, ids=lambda p: p.parent.name + "/" + p.name)
def test_no_unquoted_dollar_roots_usage(doc: Path) -> None:
    """No bare unquoted `$ROOTS` usage remains (must be `"${ROOTS[@]}"`)."""
    text = doc.read_text(encoding="utf-8")
    bad = [
        f"{doc.name}:{i}: {ln.strip()}"
        for i, ln in enumerate(text.splitlines(), 1)
        if re.search(r"\$ROOTS\b", ln)
        # allowed only inside the explanatory comment (prose), not as a command arg
        and not ("word-split" in ln or "ARRAY" in ln or 'unquoted "$ROOTS"' in ln)
    ]
    assert not bad, 'bare unquoted `$ROOTS` usage remains (use "${ROOTS[@]}"):\n' + "\n".join(bad)
