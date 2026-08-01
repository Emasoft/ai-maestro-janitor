"""The USER-memory mirror must shed REDUNDANT orphans without shedding KNOWLEDGE.

janitor#146/#156: `sync_user_memory_mirror` copies canonical in but never prunes, so a
page canonical deleted during a consolidation stays in the mirror forever. It then
duplicates the successor's atom ids — `recall <id>` cannot say which page was meant —
and a restore injects that ambiguity straight back into canonical, undoing the
consolidation the mirror was supposed to be protecting.

The naive fix ("prune anything not in canonical") is worse than the bug: #156 measured
five orphans on a live host and only ONE was superseded; the other four were the only
surviving copies of their knowledge. So these tests are mostly about what must NOT be
touched.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
msc = importlib.import_module("memory_scopes")


def _page(*atom_ids: str, body: str = "a fact worth keeping") -> str:
    head = "---\nname: p\ndescription: \"d\"\n---\n\n"
    atoms = "".join(f"^{a} [desc:\"x\", keywords: k]\n{body}\n\n" for a in atom_ids)
    return head + atoms


# ---------------------------------------------------------------- pure classifier


def test_a_page_whose_every_atom_survives_in_canonical_is_superseded() -> None:
    """The one safe case: consolidation folded it into a successor that carries all
    of its atom ids, so the orphan is a pure duplicate and its knowledge is not at
    risk."""
    orphans = {"old.md": _page("securityd-relocks", "securityd-order")}
    canonical = {"securityd-relocks", "securityd-order", "other-atom"}
    superseded, unknown = msc.classify_mirror_orphans(orphans, canonical)
    assert superseded == ["old.md"]
    assert unknown == []


def test_a_page_with_one_unmatched_atom_is_unknown() -> None:
    """PARTIAL overlap is not supersession. If a single atom has no home in canonical,
    that atom's fact exists nowhere else — quarantining the page would lose it."""
    orphans = {"half.md": _page("kept-atom", "orphaned-atom")}
    superseded, unknown = msc.classify_mirror_orphans(orphans, {"kept-atom"})
    assert superseded == []
    assert unknown == ["half.md"]


def test_a_page_with_no_atoms_is_unknown_not_vacuously_superseded() -> None:
    """THE trap. `set() <= anything` is True, so a plain subset test silently marks
    every atom-less page prunable — deleting exactly the knowledge the mirror exists
    to hold. #156's four keeper orphans were of this shape."""
    orphans = {"prose-only.md": "---\nname: p\ndescription: \"d\"\n---\n\nplain prose\n"}
    superseded, unknown = msc.classify_mirror_orphans(orphans, {"anything", "at-all"})
    assert superseded == []
    assert unknown == ["prose-only.md"]


def test_an_empty_canonical_set_quarantines_nothing() -> None:
    """The restore-direction guard. If canonical is empty (the data-dir-loss case) then
    every mirror page is 'not in canonical' — and this must mean nothing, not
    everything."""
    orphans = {"a.md": _page("x"), "b.md": _page("y"), "c.md": "no atoms here"}
    superseded, unknown = msc.classify_mirror_orphans(orphans, set())
    assert superseded == []
    assert sorted(unknown) == ["a.md", "b.md", "c.md"]


def test_an_atom_id_inside_a_fence_does_not_vouch_for_an_orphan() -> None:
    """janitor#152's lesson, applied the other way: markdown code can contain text that
    LOOKS like corpus syntax. A canonical page merely DOCUMENTING `^some-atom` in a
    fence has not defined it, and must not license quarantining the page that did."""
    documenting = "---\nname: d\n---\n\n```markdown\n^real-atom [desc:\"x\"]\n```\n"
    assert msc.page_atom_ids(documenting) == set()

    orphans = {"real.md": _page("real-atom")}
    superseded, unknown = msc.classify_mirror_orphans(
        orphans, msc.page_atom_ids(documenting)
    )
    assert superseded == []
    assert unknown == ["real.md"]


def test_a_caret_opening_a_regex_in_prose_is_not_an_atom_id() -> None:
    """`^foo` at line start is only an atom marker when followed by space or `[`.
    Without the lookahead, prose about regexes mints phantom ids — which could make a
    genuinely-unique orphan look covered."""
    assert msc.page_atom_ids("^foo|bar matches a prefix\n") == set()
    assert msc.page_atom_ids("^real-id [desc:\"x\"]\n") == {"real-id"}


# ------------------------------------------------------------------ the I/O step


@pytest.fixture
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    primary, mirror = tmp_path / "canonical", tmp_path / "mirror"
    primary.mkdir()
    mirror.mkdir()
    monkeypatch.setattr(msc, "resolve_user_dir", lambda: primary)
    monkeypatch.setattr(msc, "resolve_user_mirror_dir", lambda: mirror)
    return primary, mirror


def test_a_superseded_orphan_is_relocated_not_deleted(stores: tuple[Path, Path]) -> None:
    """RELOCATE, never unlink. The page leaves the corpus but stays on disk, one `mv`
    from recovery — the mirror's whole promise is that nothing is ever lost."""
    primary, mirror = stores
    (primary / "successor.md").write_text(_page("shared-atom"), encoding="utf-8")
    (mirror / "successor.md").write_text(_page("shared-atom"), encoding="utf-8")
    orphan_text = _page("shared-atom", body="the consolidated-away duplicate")
    (mirror / "old.md").write_text(orphan_text, encoding="utf-8")

    unknown = msc._quarantine_superseded_orphans(primary, mirror)

    assert unknown == []
    assert not (mirror / "old.md").exists(), "orphan must leave the corpus"
    parked = mirror / msc.SUPERSEDED_DIRNAME / "old.md"
    assert parked.is_file(), "orphan must still exist on disk"
    assert parked.read_text(encoding="utf-8") == orphan_text, "byte-identical"


def test_an_unexplained_orphan_is_left_exactly_where_it_is(
    stores: tuple[Path, Path],
) -> None:
    """The four keepers from #156. No canonical page covers them, so the mirror holds
    the only copy; they are reported, never moved."""
    primary, mirror = stores
    (primary / "unrelated.md").write_text(_page("unrelated-atom"), encoding="utf-8")
    (mirror / "unrelated.md").write_text(_page("unrelated-atom"), encoding="utf-8")
    (mirror / "only-copy.md").write_text(_page("nowhere-else"), encoding="utf-8")

    unknown = msc._quarantine_superseded_orphans(primary, mirror)

    assert unknown == ["only-copy.md"], "must be surfaced to a human"
    assert (mirror / "only-copy.md").is_file(), "must NOT be moved"
    assert not (mirror / msc.SUPERSEDED_DIRNAME).exists()


def test_a_parked_page_is_invisible_to_the_corpus_scanner(
    stores: tuple[Path, Path],
) -> None:
    """Why the attic is a dot-dir in EXCLUDED_DIRNAMES rather than a flag each caller
    checks: one constant makes it invisible to lint, recall, the librarian and the
    content-precheck simultaneously. If it were still scanned, the atom-id collision
    would survive the quarantine and nothing would have been fixed."""
    _, mirror = stores
    attic = mirror / msc.SUPERSEDED_DIRNAME
    attic.mkdir()
    (attic / "parked.md").write_text(_page("ghost-atom"), encoding="utf-8")
    (mirror / "live.md").write_text(_page("live-atom"), encoding="utf-8")

    names = [p.name for p in msc.iter_note_files(mirror)]
    assert names == ["live.md"]
    assert msc.is_note_file(attic / "parked.md") is False


def test_the_sync_does_not_quarantine_on_the_restore_path(
    stores: tuple[Path, Path],
) -> None:
    """Data-dir loss: canonical is empty, the mirror is the ONLY corpus. The sync must
    restore it wholesale and quarantine nothing — a mass-quarantine here would destroy
    the corpus at the exact moment it is the last copy."""
    primary, mirror = stores
    (mirror / "a.md").write_text(_page("atom-a"), encoding="utf-8")
    (mirror / "b.md").write_text(_page("atom-b"), encoding="utf-8")

    assert msc.sync_user_memory_mirror() == "restored"

    assert not (mirror / msc.SUPERSEDED_DIRNAME).exists()
    assert (mirror / "a.md").is_file() and (mirror / "b.md").is_file()
    assert (primary / "a.md").is_file() and (primary / "b.md").is_file()


def test_the_sync_prunes_a_superseded_orphan_end_to_end(
    stores: tuple[Path, Path],
) -> None:
    """The whole point, through the real entry point: canonical consolidates two pages
    into one, and the mirror stops carrying the dead duplicate."""
    primary, mirror = stores
    (primary / "merged.md").write_text(_page("id-1", "id-2"), encoding="utf-8")
    (mirror / "merged.md").write_text(_page("id-1", "id-2"), encoding="utf-8")
    (mirror / "was-folded-in.md").write_text(_page("id-2"), encoding="utf-8")

    assert msc.sync_user_memory_mirror() == "mirrored"

    assert not (mirror / "was-folded-in.md").exists()
    assert (mirror / msc.SUPERSEDED_DIRNAME / "was-folded-in.md").is_file()
    assert (mirror / "merged.md").is_file()


def test_the_attic_is_never_copied_back_into_canonical(
    stores: tuple[Path, Path],
) -> None:
    """A parked page must not ride a later restore back into the canonical store —
    that would resurrect the duplicate and re-open janitor#146. Hence
    SUPERSEDED_DIRNAME in _MIRROR_IGNORE as well as in EXCLUDED_DIRNAMES."""
    primary, mirror = stores
    attic = mirror / msc.SUPERSEDED_DIRNAME
    attic.mkdir()
    (attic / "ghost.md").write_text(_page("ghost-atom"), encoding="utf-8")
    (mirror / "real.md").write_text(_page("real-atom"), encoding="utf-8")

    assert msc.sync_user_memory_mirror() == "restored"

    assert (primary / "real.md").is_file()
    assert not (primary / msc.SUPERSEDED_DIRNAME).exists(), "attic must not restore"


def test_parking_twice_does_not_clobber_the_first_copy(
    stores: tuple[Path, Path],
) -> None:
    """Two different pages can carry the same basename across time. Overwriting the
    older one would be the deletion this whole function exists to avoid."""
    primary, mirror = stores
    (primary / "keeper.md").write_text(_page("shared"), encoding="utf-8")
    attic = mirror / msc.SUPERSEDED_DIRNAME
    attic.mkdir()
    (attic / "dupe.md").write_text("FIRST PARKED CONTENT", encoding="utf-8")
    (mirror / "dupe.md").write_text(_page("shared"), encoding="utf-8")

    msc._quarantine_superseded_orphans(primary, mirror)

    assert (attic / "dupe.md").read_text(encoding="utf-8") == "FIRST PARKED CONTENT"
    parked = sorted(p.name for p in attic.glob("dupe*.md"))
    assert len(parked) == 2, f"both copies must survive, got {parked}"
