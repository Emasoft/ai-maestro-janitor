# Project-map extractor — language-agnostic interface + Python adapter.
#
# The extractor turns a source file into a FileMap: its ROLE (one line) plus
# its PUBLIC symbols (name + compact signature + one-line doc). The renderer
# (later phase) formats FileMaps into the fenced CLAUDE.md block; the
# change-gated maintainer detector decides WHEN to re-render (TRDD-e247a349 §5).
#
# Principle (TRDD-e247a349): source structure from an AST, never regex. The
# Python adapter uses stdlib `ast` (no deps, deterministic, more reliable for
# Python than shelling to tldr); tldr/codegraph remain the path for ts/go/rust.
#
# Quality bar (AC9): each symbol's `doc` is the first line of the source
# docstring verbatim. The extractor faithfully surfaces what the source says —
# it does NOT invent behavior. A shallow source docstring yields a shallow map
# line; that is a source-docstring-quality problem, flagged separately, not
# something the extractor papers over.

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Leading lines that are NOT the file's "role" comment: shebang, encoding
# cookie, and the PEP 723 inline-script metadata block (`# /// script` … `# ///`).
_SHEBANG = "#!"
_ENCODING_MARKERS = ("# -*-", "# coding:", "# coding=")
_PEP723_OPEN = "# /// script"
_PEP723_CLOSE = "# ///"


@dataclass(frozen=True)
class Symbol:
    """One public symbol in a file.

    kind: "func" | "class" | "method". For a method, `name` is
    "Class.method" so the rendered line is self-describing.
    """

    name: str
    kind: str
    signature: str
    doc: str  # first line of the symbol's docstring, "" when absent


@dataclass
class FileMap:
    """Extracted structure of one source file."""

    path: str
    role: str  # first line of module docstring, else first leading comment
    symbols: list[Symbol] = field(default_factory=list)


def _first_line(text: Optional[str]) -> str:
    if not text:
        return ""
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s
    return ""


def _leading_comment_role(source: str) -> str:
    """Role fallback for files with a top-of-file `#` comment block instead of
    a module docstring (a common janitor convention, e.g. state.py).

    Returns the first substantive comment line, skipping the shebang, encoding
    cookie, and the whole PEP 723 `# /// script` … `# ///` metadata block.
    """
    in_pep723 = False
    for raw in source.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("#"):
            break  # first non-comment, non-blank line ends the leading block
        if line.startswith(_SHEBANG):
            continue
        if line.startswith(_ENCODING_MARKERS):
            continue
        if line.startswith(_PEP723_OPEN):
            in_pep723 = True
            continue
        if in_pep723:
            if line.startswith(_PEP723_CLOSE):
                in_pep723 = False
            continue
        body = line.lstrip("#").strip()
        if body:
            return body
    return ""


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Compact `name(params) -> Ret`. Param NAMES only (with */** markers) to
    stay terse; the return annotation is kept because it is high-signal.
    """
    a = node.args
    parts: list[str] = []
    parts.extend(p.arg for p in getattr(a, "posonlyargs", []))
    if getattr(a, "posonlyargs", []):
        parts.append("/")
    parts.extend(p.arg for p in a.args)
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        parts.append("*")
    parts.extend(p.arg for p in a.kwonlyargs)
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    ret = ""
    if node.returns is not None:
        try:
            ret = " -> " + ast.unparse(node.returns)
        except Exception:  # noqa: BLE001 - unparse failures must not abort extraction
            ret = ""
    return f"{node.name}({', '.join(parts)}){ret}"


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _func_symbol(node: ast.FunctionDef | ast.AsyncFunctionDef, qualname: str, kind: str) -> Symbol:
    sig = _signature(node)
    if qualname != node.name:  # method: prefix the class
        sig = qualname.rsplit(".", 1)[0] + "." + sig
    return Symbol(name=qualname, kind=kind, signature=sig, doc=_first_line(ast.get_docstring(node)))


def extract_python(path: Path) -> FileMap:
    """Extract a FileMap from a Python source file via stdlib `ast`.

    Role = first line of the module docstring, else the first substantive
    leading `#` comment. Symbols = public top-level functions and classes, plus
    the public methods of public classes (one level deep), so a rendered line
    like `Task.run() — …` is possible. Private (`_`-prefixed) names are omitted.
    """
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source)
    role = _first_line(ast.get_docstring(module)) or _leading_comment_role(source)

    symbols: list[Symbol] = []
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(node.name):
            symbols.append(_func_symbol(node, node.name, "func"))
        elif isinstance(node, ast.ClassDef) and _is_public(node.name):
            symbols.append(
                Symbol(name=node.name, kind="class", signature=node.name,
                       doc=_first_line(ast.get_docstring(node)))
            )
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(sub.name):
                    symbols.append(_func_symbol(sub, f"{node.name}.{sub.name}", "method"))
    return FileMap(path=str(path), role=role, symbols=symbols)


# Language → extractor registry the renderer drives. ts/go/rust adapters
# (tldr/codegraph-backed) land in P3.
EXTRACTORS: dict[str, Callable[[Path], FileMap]] = {
    ".py": extract_python,
}
