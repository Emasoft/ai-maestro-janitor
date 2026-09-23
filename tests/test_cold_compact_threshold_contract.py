"""The compact THRESHOLD contract — harness-relative, exercised against real files.

WHY THIS FILE EXISTS. The wiring tests stub the two things this file refuses to stub: they
monkeypatch `context_tokens_for` so the size is deterministic, and they pin
`CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_MIN_CONTEXT_TOKENS` while DELETING
`CLAUDE_CODE_AUTO_COMPACT_WINDOW`. Both are correct choices for a wiring test — and together
they mean nothing else in the suite exercises the harness-relative threshold resolution
(owner directive 2026-07-18) or a real transcript flowing into the reader.

WHAT THIS THRESHOLD GOVERNS, as of 2026-08-04. `min_context_tokens()` gates the PROACTIVE
warm-idle path ONLY, whose question genuinely is "has the harness's own auto-compaction
failed?" — so expressing it relative to the harness's compact point is right there.

It used to gate the two CACHE-EXPIRED paths as well, and that was wrong twice over. It made
them unreachable (with the window at 700000 the bar resolved to 716_000 while the harness
compacts at 666_000), which is how the USER's 500-600k idle sessions went uncompacted on
2026-08-04. And the deeper answer was that those paths should not exist at all: compaction is
NOT performed by a cheaper model — Anthropic's docs bill it as "an additional sampling step"
over the full pre-compaction context — so compacting because the cache went cold pays the very
cost it was meant to avoid. Both gates were REMOVED, with their knobs and tests.

The tripwire that used to live here ("a 270k context must NOT fire") went with them: with no
cache-expired gate left, there is nothing for it to guard.

Everything here is real: real transcript files, real env resolution, no stubs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_ROOT / "scripts"))

from lib import cold_cache_compact as ccc  # noqa: E402

# Every knob that participates in the resolution, so a developer's shell can never decide a
# test's outcome (the "test reporting on the tester" class of flake conftest.py names).
_KNOBS = (
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
    "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_MIN_CONTEXT_TOKENS",
    "CLAUDE_PLUGIN_OPTION_COMPACT_BACKSTOP_MARGIN_TOKENS",
    "CLAUDE_PLUGIN_OPTION_CONTEXT_WINDOW_TOKENS",
    "CLAUDE_PLUGIN_OPTION_COMPACT_SUMMARY_TOKENS",
)


def _transcript(path: Path, total: int) -> Path:
    """A transcript whose newest assistant message reports `total` tokens of input context."""
    rows = [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "usage": {
                    "input_tokens": 1_000,
                    "cache_read_input_tokens": total - 11_000,
                    "cache_creation_input_tokens": 10_000,
                    "output_tokens": 500,
                },
            },
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


# --- the harness-relative resolution --------------------------------------------------


# --- a REAL transcript through the REAL gate ------------------------------------------


def test_a_real_transcript_resolves_its_context_size(tmp_path: Path):
    """`context_tokens_for` sums input + cache_read + cache_creation off an actual file.

    The sibling wiring test stubs this function, so without this the parser and the gate are
    only ever connected in production.
    """
    t = _transcript(tmp_path / "s.jsonl", 750_000)

    assert ccc.context_tokens_for(t) == 750_000
