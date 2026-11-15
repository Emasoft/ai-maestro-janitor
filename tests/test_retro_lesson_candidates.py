"""Tests for `retro_lesson_page_defect` and `memory_candidates_cli.retro_lesson_candidates`
(TRDD-S41TV0I7): the drain's candidate list for the retro-lesson chore shares its per-page
predicate with the scheduler's `retro_lesson_has_work`, so the two cannot disagree.

Real files in tmp_path, no mocks. Tests (e) and (f) are PRE-PUSH-RUN ONLY (owner's
run-tests-only-before-push rule): they exercise `candidates_for` / `is_drained`, which are
not new functions, so the TDD exception does not cover running them during development.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import memory_candidates_cli as mcc  # noqa: E402
import memory_content_precheck as mcp  # noqa: E402
import memory_dispatch_claim as mdc  # noqa: E402
import orphaned_memory_maint as omm  # noqa: E402

_CANDIDATE = '^old-fact [desc: "the old claim", status:superseded, keywords: old symptom]\nThe old body.'
_CONVERTED = (
    '^old-fact [desc: "the old claim", status: superseded, superseded-by:ATOM-L1, '
    'keywords: old symptom]\nThe old body. [^1]'
)
_REASON = "superseded-atom-without-superseded-by"


def _curated_page(d: Path, name: str, body: str) -> Path:
    """A fully shaped CURATED wikimem page (same shape the precheck tests use)."""
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(
        "\n".join([
            "---", f"name: {name[:-3]}",
            "description: what breaks when X happens — symptom words",
            "ocd: 2026-07-01", "lmd: 2026-07-08",
            "metadata:", "  node_type: memory", "  type: project", "  tier: component",
            "---", "", body, "", "## Notes and lessons learned", "",
        ]) + "\n",
        encoding="utf-8",
    )
    return p


def _text(body: str, tmp_path: Path) -> str:
    return _curated_page(tmp_path, "t.md", body).read_text(encoding="utf-8")


def test_retro_candidates_lists_page_with_pointerless_superseded_atom(tmp_path):
    """(a) A curated page with a superseded atom and no superseded-by is listed, with the slug."""
    _curated_page(tmp_path, "a.md", _CANDIDATE)
    got = mcc.retro_lesson_candidates(tmp_path, scope="LOCAL", now=None, max_bytes=0)
    assert got == [("a.md", _REASON)]


def test_retro_candidates_omits_page_once_converted(tmp_path):
    """(b) The same atom with a superseded-by pointer is not listed."""
    _curated_page(tmp_path, "a.md", _CONVERTED)
    assert mcc.retro_lesson_candidates(tmp_path, scope="LOCAL", now=None, max_bytes=0) == []


def test_retro_candidates_names_an_unreadable_page(tmp_path):
    """(c) An unreadable page is listed as unreadable-page, never silently skipped."""
    if os.geteuid() == 0:
        pytest.skip("root can read a chmod 000 file")
    p = _curated_page(tmp_path, "a.md", _CANDIDATE)
    p.chmod(0)
    try:
        got = mcc.retro_lesson_candidates(tmp_path, scope="LOCAL", now=None, max_bytes=0)
    finally:
        p.chmod(0o644)
    assert got == [("a.md", "unreadable-page")]


def test_retro_candidates_names_an_unreadable_directory(tmp_path):
    """(g) A directory the walk cannot enter is listed as unreadable-dir: the underlying page
    lister returns [] silently on a walk failure, which the drain would read as "no work"."""
    if os.geteuid() == 0:
        pytest.skip("root can read a chmod 000 directory")
    sub = tmp_path / "sub"
    _curated_page(sub, "a.md", _CANDIDATE)
    sub.chmod(0)
    try:
        got = mcc.retro_lesson_candidates(tmp_path, scope="LOCAL", now=None, max_bytes=0)
    finally:
        sub.chmod(0o755)
    assert got == [("sub", "unreadable-dir")]


def test_retro_candidates_ignores_an_unreadable_excluded_directory(tmp_path):
    """(i) The private `user-mem` dir is never walked by the lister, so an unreadable one is not
    a measurement failure and must not be listed."""
    if os.geteuid() == 0:
        pytest.skip("root can read a chmod 000 directory")
    _curated_page(tmp_path, "a.md", _CONVERTED)
    private = tmp_path / "user-mem"
    private.mkdir()
    private.chmod(0)
    try:
        got = mcc.retro_lesson_candidates(tmp_path, scope="LOCAL", now=None, max_bytes=0)
    finally:
        private.chmod(0o755)
    assert got == []


def test_retro_candidates_raises_on_a_missing_root(tmp_path):
    """(h) A root that is not a directory raises instead of answering "no candidates"."""
    with pytest.raises(NotADirectoryError):
        mcc.retro_lesson_candidates(tmp_path / "nope", scope="LOCAL", now=None, max_bytes=0)


def test_retro_page_defect_true_for_pointerless_superseded_atom(tmp_path):
    """(d1) The retro-lesson candidate shape is a defect."""
    assert mcp.retro_lesson_page_defect(_text(_CANDIDATE, tmp_path)) is True


def test_retro_page_defect_false_with_pointer(tmp_path):
    """(d2) A superseded-by pointer clears the defect."""
    assert mcp.retro_lesson_page_defect(_text(_CONVERTED, tmp_path)) is False


def test_retro_page_defect_accepts_superseeded_misspelling(tmp_path):
    """(d3) memgrep's `superseeded` misspelling still counts as superseded."""
    body = '^old [desc: "d", status:superseeded, keywords: k]\nBody.'
    assert mcp.retro_lesson_page_defect(_text(body, tmp_path)) is True


def test_retro_page_defect_ignores_status_text_in_quoted_desc(tmp_path):
    """(d4) `status:superseded` quoted inside a desc value is prose, not a status."""
    body = '^live [desc: "memgrep excludes status:superseded atoms", keywords: k]\nBody.'
    assert mcp.retro_lesson_page_defect(_text(body, tmp_path)) is False


def test_retro_page_defect_false_for_raw_buffer_note():
    """(d5) A RAW buffer note (no curated frontmatter) is never a candidate."""
    raw = "---\nname: n\ndescription: d\n---\n" + _CANDIDATE + "\n"
    assert mcp.retro_lesson_page_defect(raw) is False


# --- (e)/(f): PRE-PUSH-RUN ONLY — not run during development (see module docstring). ---


def test_candidates_for_retro_lesson_on_clean_root_is_empty_list_not_none(tmp_path):
    """(e) retro-lesson is a read-only chore: a clean root answers [] (known empty), not None."""
    _curated_page(tmp_path, "a.md", _CONVERTED)
    got = mcc.candidates_for("retro-lesson", tmp_path, scope="PROJECT", now=2_000_000_000)
    assert got == []


def test_is_drained_true_for_aged_retro_lesson_record_on_clean_root(tmp_path):
    """(f) An aged pending retro-lesson record whose root is clean is drained."""
    sd, root = tmp_path / "state", tmp_path / "mem"
    sd.mkdir()
    _curated_page(root, "a.md", _CONVERTED)
    pending = sd / f"{mdc.PENDING_PREFIX}1000-abcd1234.json"
    pending.write_text(json.dumps({
        "marker": "[janitor-memory-retro-lesson]", "intervention": "retro-lesson",
        "scope": "LOCAL", "root": str(root), "stamped_at": 1000,
        "dispatch_id": "1000-abcd1234",
    }), encoding="utf-8")
    payload, malformed = omm.read_record(pending)
    assert not malformed and payload is not None
    assert mdc.is_drained(payload, 2_000_000_000) is True
