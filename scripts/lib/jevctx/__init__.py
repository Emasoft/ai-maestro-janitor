"""jevctx -- cache-preserving agent context compaction and memory, gated by Jev.

The short version: context is ``[frozen prefix] + [work area]``, the
prefix is append-only so the KV cache over it is never invalidated, and content the
gate removes is relocated to a store behind an expandable pointer rather than
deleted.

Trimmed 2026-09-22 (TRDD-541CBN36 card 2 follow-ups) to what card 3 (the compacted-context
scorer/CLI) actually needs: ``check``, ``context``, ``ledger``, ``pipeline``, ``segments``,
``shadow`` and ``store`` (the agent-loop / context-buffer half of upstream) are NOT vendored
here -- see VENDORED.md for the omission list and re-vendor pointer.
"""

from jevctx.budget import Batch, BudgetPlanner
from jevctx.jev import HttpJevClient, RateLimiter, RetryPolicy
from jevctx.scorer import build_state, score_items, score_map
from jevctx.testing import FakeJevClient
from jevctx.tokens import estimate_tokens
from jevctx.types import (
    Block,
    Choice,
    CommitPolicy,
    DigestEntry,
    JevClient,
    JevError,
    MemoryStore,
    Noul,
    Origin,
    Pointer,
    Record,
    Score,
    ScoreItem,
    ScoreResult,
    Segment,
    TurnSignals,
)

__version__ = "0.1.0"

__all__ = [
    "Batch", "Block", "BudgetPlanner",
    "Choice", "CommitPolicy", "DigestEntry",
    "FakeJevClient", "HttpJevClient", "JevClient",
    "JevError", "MemoryStore", "Noul", "Origin",
    "Pointer", "RateLimiter", "Record", "RetryPolicy", "Score", "ScoreItem",
    "ScoreResult", "Segment", "TurnSignals",
    "build_state", "estimate_tokens", "score_items", "score_map",
]
