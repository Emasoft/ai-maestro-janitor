"""Auto-maintained project-map extractor/renderer (TRDD-e247a349).

P0: the language-agnostic extractor interface + the Python adapter. The
renderer, the change-gated maintainer detector, and the
`/janitor-auto-repomap-on|off` commands land in later phases.

Public surface:
  - `Symbol`, `FileMap`  — the extracted-structure data model.
  - `extract_python(path)` — the Python adapter (stdlib `ast`, no deps).
  - `EXTRACTORS`         — language → extractor registry the renderer drives.
  - `render_block`, `render_body`, `structure_hash`, `FENCE_START`,
    `FENCE_END` — the renderer (FileMaps → the fenced CLAUDE.md block).
"""

from __future__ import annotations

from .extractor import EXTRACTORS, FileMap, Symbol, extract_python
from .markers import (
    MalformedFences,
    has_map_block,
    insert_map_block,
    read_fence_header,
    remove_map_block,
    replace_map_block,
)
from .renderer import (
    FENCE_END,
    FENCE_START,
    render_block,
    render_body,
    structure_hash,
)

__all__ = [
    "EXTRACTORS",
    "FENCE_END",
    "FENCE_START",
    "FileMap",
    "MalformedFences",
    "Symbol",
    "extract_python",
    "has_map_block",
    "insert_map_block",
    "read_fence_header",
    "remove_map_block",
    "render_block",
    "render_body",
    "replace_map_block",
    "structure_hash",
]
