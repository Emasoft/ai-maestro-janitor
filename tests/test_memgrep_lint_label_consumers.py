"""TRDD-3HLI7DMK (C21): `memgrep lint` now appends ` (FAMILY-NNN[ · safe-fix])` to the message,
BEFORE the trailing `⟦anchor:…⟧`. Every consumer that parses lint stdout must still match.

The sample lines below were copied from real `memgrep lint --no-fix --min-severity info` output of
the built binary (a leading local directory is shortened to `/m/`). The `…-no-anchor` variants are
the same real line with its ` ⟦anchor:…⟧` suffix removed: every registered finding carries an
anchor today, and the consumers are written to tolerate its absence.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS / "lib"))

import memory_content_precheck as mcp  # noqa: E402


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_LINE_RE = _load(_SCRIPTS / "wikimem_syntax_lint.py", "wikimem_syntax_lint_c21")._LINE_RE

SAFE_FIX = (
    "ERROR /m/p.md:0 [page-no-notes-section] — missing `## Notes and lessons learned` section "
    "(WMPAGE-010 · safe-fix) ⟦anchor:page⟧"
)
OVERSIZED = (
    "INFO /m/claude-code-plugin-rollout-staleness.md:126 [atom-oversized] — atom body is 1616 chars "
    "(> 1500) — decompose it into smaller atoms (one fact each) (WMATOM-015) ⟦anchor:atom:ATOM-ARO4-DFBY⟧"
)
ENRICH = (
    'ERROR /m/q"x.md:0 [page-description-too-few-phrases] — page `description:` carries 1 `/`-separated '
    "phrase(s), below the 4 minimum — it is the recall surface for EVERY fact on this page, so add the "
    "alternative phrasings a future session will arrive with (WMPAGE-004) ⟦anchor:field:description⟧"
)
UNCITED = (
    "INFO /m/janitor-architecture-detectors-and-resilience.md:231 [lesson-uncited] — page-level lesson "
    "`[^5]:` — cite it from an atom (`[^5]` in the atom body) if it should travel with one (WMLESS-002) "
    "⟦anchor:lesson:5⟧"
)
INERT = (
    "INFO /m/memory-system-editor-gotchas.md:219 [lesson-uncited] — page-level lesson `[^4]:` — a `[^4]` "
    "is present at line 234 but sits INSIDE a code span/fence, so markdown renders it as literal text, "
    "not a reference; move the closing backtick so the citation falls outside the code span (WMLESS-002) "
    "⟦anchor:lesson:4⟧"
)


def _no_anchor(line: str) -> str:
    head, _, _ = line.rpartition(" ⟦anchor:")
    return head


def test_line_re_parses_labelled_lines_with_and_without_anchor() -> None:
    """`_LINE_RE` keeps the label inside `msg` and still splits code, path, line and anchor."""
    cases = [
        (SAFE_FIX, "ERROR", "/m/p.md", "0", "page-no-notes-section", "(WMPAGE-010 · safe-fix)", "page"),
        (OVERSIZED, "INFO", "/m/claude-code-plugin-rollout-staleness.md", "126", "atom-oversized", "(WMATOM-015)", "atom:ATOM-ARO4-DFBY"),
        (_no_anchor(SAFE_FIX), "ERROR", "/m/p.md", "0", "page-no-notes-section", "(WMPAGE-010 · safe-fix)", None),
        (_no_anchor(OVERSIZED), "INFO", "/m/claude-code-plugin-rollout-staleness.md", "126", "atom-oversized", "(WMATOM-015)", None),
    ]
    for line, sev, path, lineno, code, label, anchor in cases:
        m = _LINE_RE.match(line)
        assert m, line
        assert (m["sev"], m["path"], m["line"], m["code"], m["anchor"]) == (sev, path, lineno, code, anchor), line
        assert m["msg"].endswith(label), (m["msg"], label)
        assert "⟦" not in m["msg"], m["msg"]


def test_oversized_atom_re_matches_the_labelled_line() -> None:
    """`_OVERSIZED_ATOM_RE` still extracts path and line, and only for `[atom-oversized]`."""
    for line in (OVERSIZED, _no_anchor(OVERSIZED)):
        m = mcp._OVERSIZED_ATOM_RE.match(line)
        assert m, line
        assert (m["path"], m["line"]) == ("/m/claude-code-plugin-rollout-staleness.md", "126")
    assert mcp._OVERSIZED_ATOM_RE.match(SAFE_FIX) is None


def test_enrich_finding_re_matches_the_labelled_line() -> None:
    """`_ENRICH_FINDING_RE` still yields the slug and the path (a `"` in it included) and the line."""
    for line in (ENRICH, _no_anchor(ENRICH)):
        m = mcp._ENRICH_FINDING_RE.match(line)
        assert m, line
        assert (m["path"], m["line"], m["slug"]) == ('/m/q"x.md', "0", "page-description-too-few-phrases"), line


def test_relocate_lesson_re_matches_the_labelled_line() -> None:
    """`_RELOCATE_LESSON_RE` still reads the footnote id straight after the em-dash message start."""
    for line in (UNCITED, _no_anchor(UNCITED)):
        m = mcp._RELOCATE_LESSON_RE.match(line)
        assert m, line
        assert (m["path"], m["line"], m["footnote"]) == ("/m/janitor-architecture-detectors-and-resilience.md", "231", "5"), line
    assert mcp._RELOCATE_LESSON_RE.match(OVERSIZED) is None


def test_relocate_inert_re_matches_only_the_code_span_variant() -> None:
    """`_RELOCATE_INERT_RE` still spots the inside-a-code-span message with the label and anchor after it."""
    for line in (INERT, _no_anchor(INERT)):
        assert mcp._RELOCATE_INERT_RE.match(line), line
    assert mcp._RELOCATE_INERT_RE.match(UNCITED) is None
