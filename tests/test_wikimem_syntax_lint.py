"""Tests for the wikimem syntax linter + its heartbeat detector (TRDD-VPTQ4067).

The linter's rules are ported 1:1 from memgrep's `memory.rs` parser, so these tests pin the
exact CRITICAL/WARN taxonomy an authoring path must satisfy: an atom memgrep cannot index (a
`⟦`-bracket, no `keywords:`) or a corpus-wide duplicate atom id is CRITICAL (recall-invisible or
ambiguous); a lean lesson / missing date is WARN. The detector is the wiring that surfaces the
CRITICALs on the heartbeat, deduped per finding-set.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so `@dataclass` (which looks up cls.__module__ in sys.modules)
    # and any typing resolution can find the module.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lint = _load(_SCRIPTS / "wikimem_syntax_lint.py", "wikimem_syntax_lint")


def _codes(findings) -> set[str]:
    return {f.code for f in findings}


def _crit(findings) -> set[str]:
    return {f.code for f in findings if f.sev == "CRITICAL"}


# ── parse_block_props (the props grammar, ported from memory.rs:1314) ─────────────
def test_parse_block_props_basic():
    p = lint.parse_block_props("keywords: a b c, ocd: 2026-07-21, lmd: 2026-07-21")
    assert p["keywords"] == ["a", "b", "c"]
    assert p["ocd"] == ["2026-07-21"]


def test_parse_block_props_quoted_desc_protects_comma():
    """A comma inside a "…"-quoted value must NOT split the property list (memory.rs:150)."""
    p = lint.parse_block_props('desc:"first, second", keywords: x y')
    assert p["keywords"] == ["x", "y"]
    assert "desc" in p  # the quoted value survived as one property


def test_split_top_level_commas_protects_wikilink_bracket():
    parts = lint._split_top_level_commas("keywords: a b, see: [[one, two]], ocd: 2026-07-21")
    # the comma inside [[one, two]] does not split → 3 top-level items, not 4
    assert len(parts) == 3


# ── lint_page: the CRITICAL taxonomy ──────────────────────────────────────────────
def _page(body: str, *, description: str = "a real page") -> str:
    return f"---\nname: p\ndescription: {description}\nocd: 2026-07-21\nlmd: 2026-07-21\n---\n\n{body}\n\n## Notes and lessons learned\n"


def test_clean_page_has_no_findings():
    text = _page("^good [keywords: recall me, ocd: 2026-07-21, lmd: 2026-07-21]\nbody.")
    assert lint.lint_page(Path("p.md"), text) == []


def test_mangled_bracket_atom_is_critical():
    text = _page("^bad ⟦keywords: x, ocd: 2026-07-21⟧\nbody.")
    assert "atom-bad-bracket" in _crit(lint.lint_page(Path("p.md"), text))


def test_atom_without_keywords_is_critical():
    text = _page("^nokw [desc: has_no_keywords, ocd: 2026-07-21, lmd: 2026-07-21]\nbody.")
    assert "atom-no-keywords" in _crit(lint.lint_page(Path("p.md"), text))


def test_page_without_description_is_critical():
    text = "---\nname: p\nocd: 2026-07-21\nlmd: 2026-07-21\n---\n\n## Notes and lessons learned\n"
    assert "page-no-description" in _crit(lint.lint_page(Path("p.md"), text))


def test_atom_missing_dates_is_warn_not_critical():
    text = _page("^d [keywords: x]\nbody.")
    findings = lint.lint_page(Path("p.md"), text)
    assert _crit(findings) == set()
    assert {"atom-no-ocd", "atom-no-lmd"} <= _codes(findings)


# ── atom-dropped-props (silently discarded keyword phrases) ───────────────────────
#
# The highest-value structural check on an atom: `keywords` IS the recall surface, and the
# natural hand-authored `keywords: a phrase, another phrase` deletes every phrase after the
# first (comma separates FIELDS, space separates KEYWORDS). Measured on the benchmark corpus:
# repairing it moved hit@1 from 21.7% to 95.7%. These tests pin the rule to `parse_block_props`'s
# OWN two silent `continue`s, so the linter can never flag more or less than the parser drops.


def test_dropped_props_flags_comma_separated_phrases():
    """The live-corpus defect: phrases after the first comma are discarded."""
    t = "^a1 [keywords: alpha one, beta two, gamma three, ocd: 2026-07-20, lmd: 2026-07-20]\nbody\n"
    f = lint.lint_page(Path("x.md"), t)
    assert "atom-dropped-props" in _crit(f)


def test_dropped_props_silent_on_underscore_joined_phrases():
    """The correct form must NOT fire, or the check would punish the fix it recommends."""
    t = "^a1 [keywords: alpha_one beta_two gamma_three, ocd: 2026-07-20, lmd: 2026-07-20]\nbody\n"
    assert "atom-dropped-props" not in _codes(lint.lint_page(Path("x.md"), t))


def test_dropped_props_silent_on_quoted_value_containing_commas():
    """A quoted value may legitimately contain commas (TRDD-AP2X9A0H prose desc). Splitting it
    would false-positive on exactly the pages already using the sanctioned grammar."""
    t = '^a1 [desc: "a summary, with commas", keywords: x_y, ocd: 2026-07-20, lmd: 2026-07-20]\nbody\n'
    assert "atom-dropped-props" not in _codes(lint.lint_page(Path("x.md"), t))


def test_dropped_props_silent_on_trailing_comma():
    """A trailing comma yields an empty segment — punctuation, not lost content."""
    t = "^a1 [keywords: alpha_one, ocd: 2026-07-20, lmd: 2026-07-20,]\nbody\n"
    assert "atom-dropped-props" not in _codes(lint.lint_page(Path("x.md"), t))


def test_dropped_props_flags_empty_key_segment():
    """`parse_block_props` also drops a segment whose key is empty — mirror that branch too."""
    t = "^a1 [keywords: alpha_one, : orphaned, ocd: 2026-07-20, lmd: 2026-07-20]\nbody\n"
    assert "atom-dropped-props" in _crit(lint.lint_page(Path("x.md"), t))


def test_dropped_props_matches_what_the_parser_actually_loses():
    """The oracle: whatever the linter flags must be text `parse_block_props` cannot see."""
    props = "keywords: alpha one, beta two, ocd: 2026-07-20"
    parsed = lint.parse_block_props(props)
    assert parsed["keywords"] == ["alpha", "one"]      # shredded
    assert "beta two" not in str(parsed)               # and the rest is simply gone
    t = f"^a1 [{props}, lmd: 2026-07-20]\nbody\n"
    assert "atom-dropped-props" in _crit(lint.lint_page(Path("x.md"), t))


# ── lint_page: the lesson taxonomy (the 3-schema drift the corpus carries) ─────────
def test_lean_lesson_flags_no_keywords_and_no_id():
    text = _page("^a [keywords: k, ocd: 2026-07-21, lmd: 2026-07-21]\nbody.[^1]") + \
        "[^1]: [ocd:2026-07-21 lmd:2026-07-21] DO NOT x BECAUSE y DO z.\n"
    codes = _codes(lint.lint_page(Path("p.md"), text))
    assert {"lesson-no-keywords", "lesson-no-id"} <= codes


def test_rich_lesson_is_clean():
    text = _page("^a [keywords: k, ocd: 2026-07-21, lmd: 2026-07-21]\nbody.[^1]") + \
        '[^1]: [id:ATOM-AAAA-BBBB, status:valid, keywords:"foo bar", ocd:2026-07-21, lmd:2026-07-21] DO NOT x BECAUSE y DO z.\n'
    codes = _codes(lint.lint_page(Path("p.md"), text))
    assert not {"lesson-no-keywords", "lesson-no-id", "lesson-no-meta"} & codes


def test_superseded_lesson_without_pointer_is_warn():
    text = _page("^a [keywords: k, ocd: 2026-07-21, lmd: 2026-07-21]\nbody.[^1]") + \
        '[^1]: [id:ATOM-A, status:superseded, keywords:"k", ocd:2026-07-21, lmd:2026-07-21] DO NOT x BECAUSE y DO z.\n'
    assert "lesson-superseded-no-pointer" in _codes(lint.lint_page(Path("p.md"), text))


# ── extract_atom_ids + find_duplicate_atom_ids (the corpus-wide dup check) ─────────
def test_extract_atom_ids_skips_code_fences():
    text = _page("^real [keywords: k, ocd: 2026-07-21, lmd: 2026-07-21]\nb\n```\n^fake [keywords: x]\n```")
    ids = [aid for aid, _ln in lint.extract_atom_ids(text)]
    assert "real" in ids and "fake" not in ids


def test_find_duplicate_atom_ids_flags_cross_page_collision():
    a = _page("^SHARED [keywords: k, ocd: 2026-07-21, lmd: 2026-07-21]\nbody a.")
    b = _page("^SHARED [keywords: k, ocd: 2026-07-21, lmd: 2026-07-21]\nbody b.")
    dups = lint.find_duplicate_atom_ids({Path("a.md"): a, Path("b.md"): b})
    assert "SHARED" in dups and len(dups["SHARED"]) == 2


def test_find_duplicate_atom_ids_empty_when_unique():
    a = _page("^ONE [keywords: k, ocd: 2026-07-21, lmd: 2026-07-21]\nbody.")
    b = _page("^TWO [keywords: k, ocd: 2026-07-21, lmd: 2026-07-21]\nbody.")
    assert lint.find_duplicate_atom_ids({Path("a.md"): a, Path("b.md"): b}) == {}


# ── the detector (the heartbeat wiring) ───────────────────────────────────────────
det = _load(_SCRIPTS / "detectors" / "wikimem-syntax.py", "wikimem_syntax_detector")


def _scope_with(tmp_path: Path, monkeypatch, files: dict[str, str]):
    """Point the detector's scope resolution at a single temp memory root holding `files`."""
    root = tmp_path / "memory"
    root.mkdir()
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    monkeypatch.setattr(det.memory_scopes, "resolve_scope_dirs", lambda: [("TEST", root)])
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    return root


def test_detector_signatures_flag_broken_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _scope_with(tmp_path, monkeypatch, {
        "clean.md": _page("^ok [keywords: k, ocd: 2026-07-21, lmd: 2026-07-21]\nb."),
        "broken.md": _page("^bad ⟦keywords: x⟧\nb."),
    })
    sigs = det._critical_signatures()
    assert any(s.startswith("atom-bad-bracket@") for s in sigs)


def test_detector_silent_on_clean_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    _scope_with(tmp_path, monkeypatch, {
        "clean.md": _page("^ok [keywords: k, ocd: 2026-07-21, lmd: 2026-07-21]\nb."),
    })
    assert det.main() == 0
    assert capsys.readouterr().out == ""


def test_detector_emits_then_dedupes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    _scope_with(tmp_path, monkeypatch, {
        "broken.md": _page("^bad ⟦keywords: x⟧\nb."),
    })
    assert det.main() == 0
    first = capsys.readouterr().out
    assert "[wikimem-syntax]" in first and "CRITICAL" in first
    # second run on the UNCHANGED set → per-set dedupe → silent
    assert det.main() == 0
    assert capsys.readouterr().out == ""
