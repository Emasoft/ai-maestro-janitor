"""A `[[ATOM-…]]` link resolves to the page that DEFINES the atom (TRDD-JKJHV19B).

`memgrep links --broken` answers "does a target FILE exist", so every atom link comes
back `[BROKEN]` — correct for the question it was asked, wrong for the question the
finding then claims to answer. Before this fix the ids were also absent from the
librarian's corpus index, so `_classify_broken_link` fell to its unresolved branch and
advised the reader to write the missing page: four live findings across the real corpus,
each proposing a page named after an atom that already exists.

These tests pin the resolution, both atom spellings, and the fence exclusion — plus the
two shapes the card measured as producing FALSE defects in the real run (a page in a
subdirectory, and a page whose frontmatter `name:` differs from its filename stem), which
are the ones a fixture built from the duty text alone would miss.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "memory_librarian", _ROOT / "scripts" / "detectors" / "memory-librarian.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["memory_librarian"] = mod  # dataclasses resolves via sys.modules
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def lib():
    return _load()


def _page(body: str, name: str = "somepage") -> str:
    return f"---\nname: {name}\ndescription: \"x\"\n---\n\n{body}\n"


def test_a_body_atoms_id_resolves_to_its_page(lib) -> None:
    """A `^ATOM-… [props]` anchor makes that id a slug the page answers to."""
    text = _page('^ATOM-AAAA-BBBB [desc: "a body atom", keywords: k, ocd: 2026-08-26]')
    assert "ATOM-AAAA-BBBB" in lib._note_slugs(Path("somepage.md"), text)


def test_a_lesson_id_resolves_to_its_page_in_both_spellings(lib) -> None:
    """`id: X` and `id:X` both ship in the corpus, so both must index."""
    spaced = _page('[^1]: [id: ATOM-CCCC-DDDD, status: valid, keywords: "k"]\n  DO NOT x.')
    tight = _page('[^1]: [id:ATOM-EEEE-FFFF, status:valid, keywords:"k"]\n  DO NOT x.')
    assert "ATOM-CCCC-DDDD" in lib._note_slugs(Path("somepage.md"), spaced)
    assert "ATOM-EEEE-FFFF" in lib._note_slugs(Path("somepage.md"), tight)


def test_an_atom_marker_inside_a_fence_defines_nothing(lib) -> None:
    """A doc EXAMPLE is not a definition — blessing it would resolve a link to nowhere."""
    text = _page('```\n^ATOM-FAKE-9999 [desc: "example only"]\n```')
    assert "ATOM-FAKE-9999" not in lib._note_slugs(Path("somepage.md"), text)


def test_the_page_still_answers_to_its_stem_and_its_frontmatter_name(lib) -> None:
    """The `name:` half is the identity blind spot the card measured — keep it pinned.

    A page's identity is its frontmatter `name:`, NOT its filename; resolving by filename
    turned 1 live link into a phantom hole in the real run.
    """
    text = _page("no atoms here", name="security-act-dont-ask")
    slugs = lib._note_slugs(Path("feedback_security_act_dont_ask.md"), text)
    assert {"feedback_security_act_dont_ask", "security-act-dont-ask"} <= slugs


def test_a_page_in_a_subdirectory_indexes_the_same_way(lib) -> None:
    """The recursion blind spot: 4 real pages live in `wikimem/` subdirs.

    A pass that missed them would have CREATED duplicates of pages that already exist —
    the most destructive outcome available, reached by trying to help.
    """
    text = _page('^ATOM-SUBD-0001 [desc: "in a subdir"]', name="deep-page")
    slugs = lib._note_slugs(Path("wikimem/deep-page.md"), text)
    assert {"deep-page", "ATOM-SUBD-0001"} <= slugs


def test_an_atom_link_is_not_reported_as_an_unresolved_page(lib) -> None:
    """The end-to-end point: an EXISTING atom must not be advised as a page to write."""
    corpus = lib.CorpusIndex(
        slug_scope={"ATOM-AAAA-BBBB": lib._SCOPE_RANK["PROJECT"]}, referenced_from={}
    )
    finding = lib._classify_broken_link(
        "some.md", "ATOM-AAAA-BBBB", lib._SCOPE_RANK["PROJECT"], corpus
    )
    # Same-scope + resolvable ⇒ the advisory shape, never the "write the page" one.
    # Asserted on the ADVICE, not on `is None`: the point is that no reader is ever
    # told to create a page named after an atom that already exists.
    assert finding is None or "marks a page worth writing" not in finding


def test_a_genuinely_missing_atom_is_still_surfaced(lib) -> None:
    """The guard must not become a blanket exemption for anything shaped like an id."""
    corpus = lib.CorpusIndex(slug_scope={}, referenced_from={})
    finding = lib._classify_broken_link(
        "some.md", "ATOM-9999-9999", lib._SCOPE_RANK["PROJECT"], corpus
    )
    assert finding is not None and "unresolved" in finding
