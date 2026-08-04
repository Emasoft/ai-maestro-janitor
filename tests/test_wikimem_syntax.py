"""Tests for the wikimem-syntax detector (scripts/detectors/wikimem-syntax.py).

Real fixtures, no mocks: the memory scope dirs used below are real directories on
disk that match memgrep's own `scope_layer` path-pattern discriminator (memory.rs),
and `memgrep lint` is the REAL binary — no lint output is faked. The pure
remedy/signature logic (`_remedy_for`, `_signatures`) is exercised directly with real
`lint.Finding` values; the end-to-end `main()` test points the detector's own
`lint.run_lint` call at these real fixture paths (instead of the live, env-resolved
corpus) so the test stays hermetic while still running the real linter.

Covers janitor#138: the drift line's remedy clause must be PER-RULE. A
`link-downward-cross-scope` ERROR has no editor chore that can fix it (no chore
re-homes a page across scopes), so the blanket "/janitor-memory-update" instruction
must not be the remedy offered for that rule.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _ROOT / "scripts" / "detectors" / "wikimem-syntax.py"

sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import wikimem_syntax_lint as lint  # noqa: E402

# Load the hyphenated detector module in-process (mirrors test_memory_librarian.py's
# pattern) so its PURE helpers (`_remedy_for`, `_signatures`, `main`) are directly
# callable, not just observable via a subprocess's stdout.
_spec = importlib.util.spec_from_file_location("wikimem_syntax_detector", _DETECTOR)
assert _spec is not None and _spec.loader is not None
wsyntax = importlib.util.module_from_spec(_spec)
sys.modules["wikimem_syntax_detector"] = wsyntax
_spec.loader.exec_module(wsyntax)

pytestmark = pytest.mark.skipif(shutil.which("memgrep") is None, reason="memgrep binary not on PATH")


def _make_cross_scope_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """A REAL PROJECT-scope page linking DOWN to a REAL LOCAL-scope page.

    Matches memgrep's `scope_layer` path patterns: `.claude/project/memory` = PROJECT
    (rank 1), `.claude/projects/<slug>/memory` = LOCAL (rank 0). PROJECT -> LOCAL is
    downward, so a real `memgrep lint` over these two dirs fires
    `link-downward-cross-scope` — no other rule this minimal fixture could trip.
    """
    project_dir = tmp_path / "repo" / ".claude" / "project" / "memory"
    local_dir = tmp_path / "home" / ".claude" / "projects" / "someslug" / "memory"
    project_dir.mkdir(parents=True)
    local_dir.mkdir(parents=True)
    (local_dir / "target.md").write_text(
        '---\nname: target\ndescription: "a machine-private fact"\nocd: 2026-06-01\n'
        "lmd: 2026-06-01\nmetadata:\n  node_type: memory\n---\n"
        "A machine-private fact.\n\n## Notes and lessons learned\n",
        encoding="utf-8",
    )
    (project_dir / "holder.md").write_text(
        '---\nname: holder\ndescription: "links down, illegally"\nocd: 2026-06-01\n'
        "lmd: 2026-06-01\nmetadata:\n  node_type: memory\n---\n"
        "See [[target]] for details.\n\n## Notes and lessons learned\n",
        encoding="utf-8",
    )
    return project_dir, local_dir


def test_cross_scope_code_constant_matches_real_memgrep_output(tmp_path):
    """Regression: `_CROSS_SCOPE_CODE` must equal the code memgrep's REAL `lint`
    emits for a downward cross-scope link, or the per-rule remedy silently stops
    firing for the one rule it exists to special-case."""
    project_dir, local_dir = _make_cross_scope_fixture(tmp_path)
    _code, stdout, findings = lint.run_lint([project_dir, local_dir])
    codes = {f.code for f in findings if f.sev == "ERROR"}
    assert wsyntax._CROSS_SCOPE_CODE in codes, (codes, stdout)


def test_remedy_for_generic_code_only_points_at_memory_update():
    """A code other than the cross-scope one keeps the blanket, generic remedy."""
    remedy = wsyntax._remedy_for({"atom-no-keywords"})
    assert "/janitor-memory-update" in remedy
    assert "scope decision is yours" not in remedy


def test_remedy_for_cross_scope_only_does_not_point_at_memory_update():
    """Issue #138: the blanket /janitor-memory-update remedy cannot fix a
    link-downward-cross-scope finding — no editor chore re-homes a page across
    scopes. With that as the ONLY code, the remedy must say the scope decision is
    the agent's own, and must NOT claim /janitor-memory-update fixes it."""
    remedy = wsyntax._remedy_for({wsyntax._CROSS_SCOPE_CODE})
    assert "/janitor-memory-update" not in remedy
    assert "scope decision is yours" in remedy


def test_remedy_for_mixed_codes_states_both_per_rule():
    """Mixed ERROR set: the cross-scope clause AND the generic clause both appear,
    each scoped to the codes they actually cover."""
    remedy = wsyntax._remedy_for({wsyntax._CROSS_SCOPE_CODE, "atom-no-keywords"})
    assert "scope decision is yours" in remedy
    assert "/janitor-memory-update" in remedy


def test_signatures_uses_basename_line_code():
    """A signature is `<basename>:<line>:<code>` — the check's stable identity, not
    the message text (a reworded message must not look like a new defect)."""
    findings = [lint.Finding("ERROR", "/abs/path/foo.md", 12, "some msg", "atom-dup-id")]
    assert wsyntax._signatures(findings) == ["foo.md:12:atom-dup-id"]


def test_main_prints_per_rule_remedy_for_cross_scope_only(tmp_path, monkeypatch, capsys):
    """End-to-end with the REAL linter: a corpus whose only ERROR is
    link-downward-cross-scope must print a drift line that does NOT tell the
    reader to fix it via /janitor-memory-update."""
    project_dir, local_dir = _make_cross_scope_fixture(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "repo"))
    # `wsyntax.lint` and this file's `lint` are literally the SAME module object
    # (both `import wikimem_syntax_lint as lint`, cached once in sys.modules), so
    # capture the REAL `run_lint` before patching — a lambda that calls
    # `lint.run_lint` from inside the patch would call the patch itself.
    real_run_lint = lint.run_lint
    monkeypatch.setattr(
        wsyntax.lint, "run_lint", lambda *a, **kw: real_run_lint([project_dir, local_dir])
    )
    rc = wsyntax.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "[wikimem-syntax]" in out, out
    assert "scope decision is yours" in out, out
    assert "/janitor-memory-update" not in out, out
