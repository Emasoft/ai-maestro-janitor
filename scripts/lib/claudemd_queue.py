#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""claudemd_queue — free-rider scheduling for the CLAUDE.md wikimem-index write (TRDD-LFSWY0C6).

Any write to CLAUDE.md invalidates the prompt-cache prefix for EVERY Claude session on the
machine, and re-bills it at 1.25x regardless of diff size. So this module never writes
CLAUDE.md on its own cadence: `queue_if_stale` only RECORDS that a write is owed (a marker
file), and `drain_if_queued` performs the deferred write, but only when called from a moment
that is ALREADY paying the invalidation (e.g. PostCompact, which rebuilds the prefix anyway).
"""

from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent
_SCRIPTS = _LIB.parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_LIB))

import claudemd_slim as cms  # noqa: E402
import state  # noqa: E402

_MARKER_REL = Path(".janitor") / "state" / "claudemd-migration-pending.flag"


def queue_if_stale(root: Path) -> bool:
    """READ-ONLY: detect CLAUDE.md wikimem-index drift and record it. Never writes CLAUDE.md."""
    claude_md = root / "CLAUDE.md"
    if not claude_md.is_file():
        return False
    text = claude_md.read_text(encoding="utf-8")
    opted_in = (root / ".janitor" / "state" / "repomap-opt-in.flag").is_file()
    pages = cms.scan_pages(cms._memdir(root))
    stale = cms.index_is_stale(text, pages)
    violations = cms.slim_violations(text, require_map=opted_in)
    if not stale and not violations:
        return False
    state.atomic_write(root / _MARKER_REL, "1\n")
    return True


def drain_if_queued(root: Path) -> bool:
    """If a pending marker exists, perform the deferred write now and clear the marker."""
    marker = root / _MARKER_REL
    if not marker.is_file():
        return False
    cms.cmd_index(root, to_stdout=False)
    marker.unlink(missing_ok=True)
    return True
