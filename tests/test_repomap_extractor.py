"""Tests for the project-map Python extractor (TRDD-e247a349 P0).

Real fixtures, no mocks: each test writes a .py file to a tmp dir, runs the
stdlib-ast extractor, and asserts the FileMap. Covers both role conventions
(module docstring AND leading-comment fallback), public/private filtering,
class methods, signature shape, and the docstring-first-line quality bar.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

from repomap import extract_python  # noqa: E402


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "sample.py"
    p.write_text(body, encoding="utf-8")
    return p


def test_role_from_module_docstring(tmp_path):
    """Role is the first non-blank line of the module docstring."""
    fm = extract_python(_write(tmp_path, '"""First role line.\n\nMore detail.\n"""\n'))
    assert fm.role == "First role line."


def test_role_falls_back_to_leading_comment(tmp_path):
    """No docstring → role is the first substantive leading `#` comment, skipping shebang + PEP-723."""
    body = (
        "#!/usr/bin/env -S uv run --script --quiet\n"
        "# /// script\n"
        "# requires-python = \">=3.11\"\n"
        "# ///\n"
        "# The real role of this module.\n"
        "from __future__ import annotations\n"
    )
    fm = extract_python(_write(tmp_path, body))
    assert fm.role == "The real role of this module."


def test_public_only_top_level(tmp_path):
    """Private (_-prefixed) top-level functions/classes are omitted."""
    body = (
        "def public_fn():\n    pass\n\n"
        "def _private_fn():\n    pass\n\n"
        "class _Hidden:\n    pass\n"
    )
    fm = extract_python(_write(tmp_path, body))
    names = {s.name for s in fm.symbols}
    assert names == {"public_fn"}


def test_signature_and_doc_firstline(tmp_path):
    """Signature keeps param names + return annotation; doc is the docstring's first line only."""
    body = (
        "def atomic_write(path, text) -> None:\n"
        '    """Write atomically (tmp + rename).\n\n    Long detail ignored.\n    """\n'
        "    pass\n"
    )
    fm = extract_python(_write(tmp_path, body))
    sym = next(s for s in fm.symbols if s.name == "atomic_write")
    assert sym.signature == "atomic_write(path, text) -> None"
    assert sym.doc == "Write atomically (tmp + rename)."
    assert sym.kind == "func"


def test_class_and_public_methods(tmp_path):
    """A public class yields the class + its public methods (Class.method), private methods omitted."""
    body = (
        "class Task:\n"
        '    """A unit of work."""\n'
        "    def run(self) -> None:\n"
        '        """Run fn; finally-stamp last-run UNCONDITIONALLY."""\n'
        "        pass\n"
        "    def _private(self):\n"
        "        pass\n"
    )
    fm = extract_python(_write(tmp_path, body))
    kinds = {s.name: s for s in fm.symbols}
    assert "Task" in kinds and kinds["Task"].kind == "class"
    assert "Task.run" in kinds and kinds["Task.run"].kind == "method"
    assert kinds["Task.run"].signature == "Task.run(self) -> None"
    assert kinds["Task.run"].doc == "Run fn; finally-stamp last-run UNCONDITIONALLY."
    assert "Task._private" not in kinds


def test_vararg_kwarg_markers(tmp_path):
    """Signature renders * / ** markers for var-positional / var-keyword args."""
    body = "def f(a, *args, b, **kw):\n    pass\n"
    fm = extract_python(_write(tmp_path, body))
    assert next(s for s in fm.symbols).signature == "f(a, *args, b, **kw)"


def test_self_extraction_on_real_file():
    """Sanity: extract the janitor's own state.py — role via comment fallback, has public symbols."""
    fm = extract_python(_PROJECT_ROOT / "scripts" / "lib" / "state.py")
    assert fm.role  # non-empty (comment-block fallback works on a real file)
    assert any(s.name == "atomic_write" for s in fm.symbols)
