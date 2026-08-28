#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""claudemd-migration-queue — records CLAUDE.md wikimem-index drift without writing it.

Any write to CLAUDE.md invalidates the prompt-cache prefix for EVERY Claude session on the
machine (TRDD-LFSWY0C6) — the diff size is irrelevant. So this detector is READ-ONLY: it
only queues the free-rider write for `scripts/hooks/post-compact-resume.py` to perform at a
moment that is already paying the invalidation. It never touches CLAUDE.md itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parent / "lib"))

import claudemd_queue  # noqa: E402
import repomap_generate as rg  # noqa: E402
import state  # noqa: E402


def main() -> int:
    state.init_state()
    root = rg._resolve_root(None)
    if claudemd_queue.queue_if_stale(root):
        print("[claudemd-migration-queue] CLAUDE.md wikimem index is stale — queued, will drain on next compaction")
    return 0


if __name__ == "__main__":
    sys.exit(main())
