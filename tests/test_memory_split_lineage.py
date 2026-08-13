"""Tests for the split-lineage marker (TRDD-3QIQ2E6J).

The rule under test SILENCES a chore, so the tests are weighted toward proving it silences the
right thing and nothing else. A suppression rule that is too wide fails invisibly — the chore just
stops firing and there is no output to notice — so the negative cases here are the load-bearing
ones, and each is written to fail if the predicate were widened by the obvious "improvement".
"""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib"
sys.path.insert(0, str(_LIB))

import memory_split_lineage as msl  # noqa: E402
import memory_txn  # noqa: E402

_ID_A = "a" * 32
_ID_B = "b" * 32


def _page(*, extra: str = "", body: str = "body.") -> str:
    return (
        "---\n"
        "name: page\n"
        'description: "a page"\n'
        f"{extra}"
        "---\n"
        f"{body}\n"
    )


class TestLineageOf(unittest.TestCase):
    def test_a_page_without_the_field_has_no_lineage(self):
        """A page that declares no split-lineage reports the empty string."""
        self.assertEqual(msl.lineage_of(_page()), "")

    def test_a_well_formed_field_is_read_back(self):
        """A top-level split-lineage in the frontmatter is parsed out verbatim."""
        self.assertEqual(msl.lineage_of(_page(extra=f"split-lineage: {_ID_A}\n")), _ID_A)

    def test_a_malformed_id_reads_as_absent(self):
        """A malformed value is reported as NO lineage, never returned as an id.

        Two corrupt pages must not compare equal to each other — that would suppress a genuine
        conflict on the strength of shared corruption.
        """
        for bad in ("", "not-a-uuid", _ID_A[:31], _ID_A + "c", _ID_A.upper()):
            with self.subTest(bad=bad):
                self.assertEqual(msl.lineage_of(_page(extra=f"split-lineage: {bad}\n")), "")

    def test_an_indented_occurrence_is_not_a_top_level_field(self):
        """An indented `split-lineage:` is a value nested under another key, not the field."""
        page = _page(extra=f"metadata:\n  split-lineage: {_ID_A}\n")
        self.assertEqual(msl.lineage_of(page), "")

    def test_the_field_named_in_the_body_is_prose_not_a_declaration(self):
        """A page DOCUMENTING this mechanism must not thereby acquire a lineage.

        This is not hypothetical: the wikimem page describing split lineage would otherwise
        become a sibling of every other page that quotes the same example id.
        """
        page = _page(body=f"The split stamps `split-lineage: {_ID_A}` onto each child.")
        self.assertEqual(msl.lineage_of(page), "")

    def test_a_page_with_no_frontmatter_has_no_lineage(self):
        """A page with no leading `---` block reports no lineage rather than raising."""
        self.assertEqual(msl.lineage_of("# just a heading\n"), "")

    def test_an_unclosed_frontmatter_block_has_no_lineage(self):
        """An opened-but-never-closed block is malformed; no field is read out of it."""
        self.assertEqual(msl.lineage_of(f"---\nsplit-lineage: {_ID_A}\nstill open\n"), "")


class TestSameSplit(unittest.TestCase):
    def test_two_pages_from_one_split_are_siblings(self):
        """Matching valid ids ⇒ one split emitted both."""
        a = _page(extra=f"split-lineage: {_ID_A}\n")
        self.assertTrue(msl.same_split(a, a))

    def test_two_pages_from_different_splits_are_not_siblings(self):
        """Different ids ⇒ different split events ⇒ still judged."""
        self.assertFalse(
            msl.same_split(
                _page(extra=f"split-lineage: {_ID_A}\n"),
                _page(extra=f"split-lineage: {_ID_B}\n"),
            )
        )

    def test_two_pages_with_NO_lineage_are_not_siblings(self):
        """THE over-suppression guard: absent == absent must never read as "siblings".

        If it did, every page in a corpus that has never been split would suppress against every
        other page — total silence of the conflict chore, from a one-line bug, with no output
        anywhere to reveal it.
        """
        self.assertFalse(msl.same_split(_page(), _page()))

    def test_one_sided_lineage_is_not_a_sibling_relation(self):
        """A split child vs an unrelated page is still judged."""
        self.assertFalse(msl.same_split(_page(extra=f"split-lineage: {_ID_A}\n"), _page()))

    def test_two_pages_sharing_a_MALFORMED_lineage_are_not_siblings(self):
        """Shared corruption is not shared provenance."""
        bad = _page(extra="split-lineage: garbage\n")
        self.assertFalse(msl.same_split(bad, bad))


class TestStamp(unittest.TestCase):
    def test_the_field_lands_inside_the_frontmatter_and_is_readable(self):
        """Stamping a clean page makes `lineage_of` return the id."""
        out = msl.stamp(_page(), _ID_A)
        self.assertEqual(msl.lineage_of(out), _ID_A)

    def test_the_field_is_inserted_before_the_closing_delimiter(self):
        """Placement matches the `publish-globally` normalizer's, so both writers agree on shape."""
        out = msl.stamp(_page(), _ID_A).split("\n")
        self.assertEqual(out[out.index("---", 1) - 1], f"split-lineage: {_ID_A}")

    def test_stamping_twice_with_the_same_id_is_a_no_op(self):
        """Idempotent: a re-staged write must not accumulate duplicate keys."""
        once = msl.stamp(_page(), _ID_A)
        self.assertEqual(msl.stamp(once, _ID_A), once)
        self.assertEqual(once.count("split-lineage:"), 1)

    def test_a_re_split_replaces_the_older_id(self):
        """Grandchildren carry the NEWER split's id — they are siblings of that event."""
        out = msl.stamp(msl.stamp(_page(), _ID_A), _ID_B)
        self.assertEqual(msl.lineage_of(out), _ID_B)
        self.assertEqual(out.count("split-lineage:"), 1)

    def test_the_rest_of_the_page_is_preserved_byte_for_byte(self):
        """Stamping adds one line and changes nothing else."""
        src = _page(extra="tags: [x]\n", body="fact one.\nfact two.")
        out = msl.stamp(src, _ID_A)
        self.assertEqual(
            [ln for ln in out.split("\n") if not ln.startswith("split-lineage:")],
            src.split("\n"),
        )

    def test_a_malformed_id_is_refused_rather_than_written(self):
        """A value the reader would reject is never written — the page is returned untouched."""
        self.assertEqual(msl.stamp(_page(), "not-a-uuid"), _page())

    def test_a_page_without_frontmatter_is_returned_untouched(self):
        """No well-formed block to insert into ⇒ no damage. A stamp is never worth corrupting a page."""
        raw = "# heading\n\ntext\n"
        self.assertEqual(msl.stamp(raw, _ID_A), raw)

    def test_the_publish_globally_normalizer_would_preserve_the_stamp(self):
        """Coexistence, exercised rather than asserted in prose.

        `insert_frontmatter_field` (memgrep memory.rs:4260) splices ONE line before the closing
        `---` and copies every other line through. Reproducing that shape here proves a page
        carrying both fields still reads back correctly, so the two writers cannot fight.
        """
        stamped = msl.stamp(_page(), _ID_A)
        lines = stamped.split("\n")
        lines.insert(lines.index("---", 1), "publish-globally: false")
        both = "\n".join(lines)
        self.assertEqual(msl.lineage_of(both), _ID_A)
        self.assertIn("publish-globally: false", both)


class TestIsSplitChild(unittest.TestCase):
    def test_the_source_page_rewritten_as_the_overview_is_a_child(self):
        """The split's source path becomes the overview — it belongs to the split."""
        self.assertTrue(msl.is_split_child("big.md", sources={"big.md": "sha"}, exists_in_live=True))

    def test_a_brand_new_sub_page_is_a_child(self):
        """A path absent from the live tree was created by this split."""
        self.assertTrue(msl.is_split_child("big-a.md", sources={"big.md": "sha"}, exists_in_live=False))

    def test_a_pre_existing_unrelated_page_is_NOT_a_child(self):
        """THE box-2 guard: a backlink-redirect write must never be stamped.

        A split also repoints OTHER pages' `[[links]]` at the survivor. Stamping those would mark
        unrelated pages as siblings of the split's children and silence genuine conflicts against
        them — the same over-suppression as link-derived ancestry, arriving through the back door
        of "stamp everything this transaction wrote".
        """
        self.assertFalse(
            msl.is_split_child("elsewhere.md", sources={"big.md": "sha"}, exists_in_live=True)
        )


class TestStageWriteStamping(unittest.TestCase):
    """The producer, driven through the real transaction — no mocks."""

    def _scope(self, tmp: Path) -> Path:
        (tmp / "big.md").write_text(_page(body="big page."), encoding="utf-8")
        (tmp / "elsewhere.md").write_text(_page(body="links to [[big]]."), encoding="utf-8")
        return tmp

    def test_a_split_stamps_the_overview_and_the_new_subpages(self):
        """Both kinds of produced page carry the transaction's own id, and the SAME one."""
        with TemporaryDirectory() as d:
            root = self._scope(Path(d))
            txn = memory_txn.MemoryTxn.begin(root, "split", ["big.md"])
            txn.stage_write("big.md", _page(body="overview."))
            txn.stage_write("big-a.md", _page(body="part a."))
            txn.stage_write("big-b.md", _page(body="part b."))
            ids = {msl.lineage_of(txn.staged_text(r)) for r in ("big.md", "big-a.md", "big-b.md")}
            self.assertEqual(ids, {txn.txn_id})

    def test_a_split_does_NOT_stamp_a_backlink_redirect(self):
        """The pre-existing non-source page written for its links stays unstamped."""
        with TemporaryDirectory() as d:
            root = self._scope(Path(d))
            txn = memory_txn.MemoryTxn.begin(root, "split", ["big.md"])
            txn.stage_write("elsewhere.md", _page(body="links to [[big-a]]."))
            self.assertEqual(msl.lineage_of(txn.staged_text("elsewhere.md")), "")

    def test_a_NON_split_transaction_stamps_nothing(self):
        """Only `--op split` mints lineage; a merge/repair/atomize write is untouched."""
        with TemporaryDirectory() as d:
            root = self._scope(Path(d))
            for op in ("merge", "repair", "atomize"):
                with self.subTest(op=op):
                    txn = memory_txn.MemoryTxn.begin(root, op, ["big.md"])
                    txn.stage_write("big.md", _page(body="edited."))
                    self.assertEqual(msl.lineage_of(txn.staged_text("big.md")), "")
                    txn.abort()

    def test_the_stamp_survives_the_commit_onto_the_live_tree(self):
        """End to end: the field is on disk after commit, which is where the librarian reads it."""
        with TemporaryDirectory() as d:
            root = self._scope(Path(d))
            txn = memory_txn.MemoryTxn.begin(root, "split", ["big.md"])
            txn.stage_write("big.md", _page(body="overview."))
            txn.stage_write("big-a.md", _page(body="part a."))
            txn.commit()
            live = msl.lineage_of((root / "big-a.md").read_text(encoding="utf-8"))
            self.assertEqual(live, txn.txn_id)


if __name__ == "__main__":
    unittest.main()
