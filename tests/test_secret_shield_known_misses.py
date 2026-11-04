"""hooks/secret-shield/KNOWN-MISSES.md and the KNOWN test titles name each other (TRDD-Q6LPJTPO).

The tests of the shield run only under `claude plugin test` in a plugin shell, so they cannot read the
Markdown file, and no release gate runs them yet. This check runs in the normal suite and compares NAMES
only, never results: it fails when an entry has no test, a test has no entry, a defect title cites a card
other than the entry's, or a KNOWN title is built with a template marker (a title that is not a static string
cannot be matched by name).
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SHIELD = _REPO / "hooks" / "secret-shield"
MISSES_MD = _SHIELD / "KNOWN-MISSES.md"
TEST_DIR = _SHIELD / "tests"

_SLUG = r"[a-z0-9-]+"
_HEADING = re.compile(r"^## (.*?)\s*$", re.MULTILINE)
_MISS_TITLE = re.compile(rf"^KNOWN MISS ({_SLUG}): ")
_DEFECT_TITLE = re.compile(rf"^KNOWN DEFECT TRDD-([0-9A-Z]{{8}}) ({_SLUG}): ")
# test( + optional whitespace/newline + a quote; the title runs to the closing quote of the SAME kind, so a title
# built as a template literal is read whole and its `${` is seen.
_TEST_TITLE = re.compile(r"\btest\(\s*(?P<quote>['\"`])(?P<title>(?:\\.|(?!(?P=quote)).)*)(?P=quote)", re.DOTALL)
_CARD_LINE = re.compile(r"^Card: (.+?)\s*$", re.MULTILINE)
_TEST_LINE = re.compile(r"^Test: (.+?)\s*$", re.MULTILINE)


class Entry(NamedTuple):
    """One `## <slug>` section of KNOWN-MISSES.md."""

    slug: str
    card: str | None
    test: str | None


class Title(NamedTuple):
    """One KNOWN test title found in a *.test.ts file."""

    text: str
    file: str
    slug: str | None
    card: str | None  # None for a MISS title


def _headings() -> list[str]:
    return _HEADING.findall(MISSES_MD.read_text(encoding="utf-8"))


def _entries() -> list[Entry]:
    text = MISSES_MD.read_text(encoding="utf-8")
    parts = re.split(r"^## .*$", text, flags=re.MULTILINE)[1:]
    found: list[Entry] = []
    for slug, body in zip(_headings(), parts, strict=True):
        card = _CARD_LINE.search(body)
        test = _TEST_LINE.search(body)
        found.append(Entry(slug, card.group(1) if card else None, test.group(1) if test else None))
    return found


def _titles() -> list[Title]:
    found: list[Title] = []
    for path in sorted(TEST_DIR.glob("*.test.ts")):
        for match in _TEST_TITLE.finditer(path.read_text(encoding="utf-8")):
            title = match.group("title")
            if not title.startswith("KNOWN"):
                continue
            miss = _MISS_TITLE.match(title)
            defect = _DEFECT_TITLE.match(title)
            if miss:
                found.append(Title(title, path.name, miss.group(1), None))
            elif defect:
                found.append(Title(title, path.name, defect.group(2), "TRDD-" + defect.group(1)))
            else:
                found.append(Title(title, path.name, None, None))
    return found


def test_files_exist() -> None:
    """The entries file and at least one test file are there to be compared."""
    assert MISSES_MD.is_file(), f"{MISSES_MD} is missing"
    assert list(TEST_DIR.glob("*.test.ts")), f"no *.test.ts in {TEST_DIR}"


def test_every_heading_is_a_slug() -> None:
    """Every second-level heading of KNOWN-MISSES.md is a slug of lowercase letters, digits and hyphens."""
    bad = [h for h in _headings() if not re.fullmatch(_SLUG, h)]
    assert not bad, f"headings that are not a slug: {bad}"


def test_every_entry_has_card_and_test_lines() -> None:
    """Every entry carries a Card: line and a Test: line."""
    missing = [f"{e.slug}: " + ("Card" if e.card is None else "Test") for e in _entries() if e.card is None or e.test is None]
    assert not missing, f"entries without their Card: or Test: line: {missing}"


def test_no_duplicate_heading() -> None:
    """No slug heads two entries."""
    dup = [s for s, n in Counter(_headings()).items() if n > 1]
    assert not dup, f"slugs with more than one entry: {dup}"


def test_every_known_title_is_well_formed() -> None:
    """Every title starting with KNOWN has the MISS or DEFECT form with a slug."""
    bad = [t.text for t in _titles() if t.slug is None]
    assert not bad, f"KNOWN titles that fit neither 'KNOWN MISS <slug>: ' nor 'KNOWN DEFECT TRDD-<id> <slug>: ': {bad}"


def test_slugs_are_a_bijection() -> None:
    """Each entry has exactly one test title and each KNOWN test title has an entry."""
    heads = Counter(_headings())
    titled = Counter(t.slug for t in _titles() if t.slug is not None)
    problems = [f"{s}: {heads[s]} entry, {titled[s]} titles" for s in sorted(set(heads) | set(titled)) if heads[s] != 1 or titled[s] != 1]
    assert not problems, f"entries and titles do not pair one to one: {problems}"


def test_defect_title_id_equals_entry_card() -> None:
    """A KNOWN DEFECT title cites the card named by its entry's Card: line."""
    cards = {e.slug: e.card for e in _entries()}
    wrong: list[str] = []
    for title in _titles():
        if title.slug is None or title.card is None:
            continue
        if cards.get(title.slug) != title.card:
            wrong.append(f"{title.slug}: title {title.card}, entry {cards.get(title.slug)}")
    assert not wrong, f"defect titles whose card differs from the entry's: {wrong}"


def test_entry_without_card_has_a_miss_title() -> None:
    """An entry whose Card: is none is pinned by a KNOWN MISS title, and one with a card by a KNOWN DEFECT title."""
    by_slug = {t.slug: t for t in _titles()}
    wrong: list[str] = []
    for entry in _entries():
        title = by_slug.get(entry.slug)
        if title is None:
            continue  # reported by the bijection check
        if (entry.card == "none") != (title.card is None):
            wrong.append(f"{entry.slug}: Card: {entry.card} but the title is a {'MISS' if title.card is None else 'DEFECT'}")
    assert not wrong, f"entries whose Card: does not match the kind of their title: {wrong}"


def test_test_line_equals_the_title() -> None:
    """Each entry's Test: line is its test title, character for character."""
    by_slug = {t.slug: t.text for t in _titles()}
    wrong = [e.slug for e in _entries() if e.slug in by_slug and e.test != by_slug[e.slug]]
    assert not wrong, f"entries whose Test: line differs from the title: {wrong}"


def test_no_known_title_contains_a_template_marker() -> None:
    """No KNOWN title contains ${, so every title is a static string that can be matched by name."""
    bad = [t.slug or t.text[:40] for t in _titles() if "${" in t.text]
    assert not bad, f"KNOWN titles with a template marker: {bad}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
