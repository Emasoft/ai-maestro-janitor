"""jevctx -- cache-preserving agent context compaction and memory, gated by Jev.

The short version: context is ``[frozen prefix] + [work area]``, the
prefix is append-only so the KV cache over it is never invalidated, and content the
gate removes is relocated to a store behind an expandable pointer rather than
deleted.

Trimmed 2026-09-22 (TRDD-541CBN36 card 2 follow-ups) to what card 3 (the compacted-context
scorer/CLI) actually needs: ``check``, ``context``, ``ledger`` and ``store`` (the live
agent-loop / context-buffer / persistent-store half of upstream) are NOT vendored here --
see VENDORED.md for the omission list and re-vendor pointer. ``segments``, ``shadow`` and
``pipeline`` were re-vendored 2026-09-23 (TRDD-RAEGS1D5 card 4) for their lossless
tool-output segmentation, decision-log calibration, and pointer/question-wording primitives.
"""

from jevctx.budget import Batch, BudgetPlanner
from jevctx.jev import HttpJevClient, RateLimiter, RetryPolicy
from jevctx.pipeline import (
    ADMIT_QUESTION,
    DEFAULT_GATE_CONFIG,
    EXPAND_TOOL_SCHEMA,
    RETRIEVE_QUESTION,
    AdmitResult,
    GateConfig,
    admit,
    expand,
    find_pointers,
    format_pointer,
    parse_pointer,
    reconstruct,
    retrieve,
)
from jevctx.scorer import build_state, score_items, score_map
from jevctx.segments import detect_kind, find_trace_regions, segment
from jevctx.shadow import PREVIEW_CHARS, ShadowLog, ShadowStats
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

__version__ = "3.6.2"

__all__ = [
    "ADMIT_QUESTION", "AdmitResult", "Batch", "Block", "BudgetPlanner",
    "Choice", "CommitPolicy", "DEFAULT_GATE_CONFIG", "DigestEntry",
    "EXPAND_TOOL_SCHEMA",
    "FakeJevClient", "GateConfig", "HttpJevClient", "JevClient",
    "JevError", "MemoryStore", "Noul", "Origin",
    "PREVIEW_CHARS", "Pointer", "RETRIEVE_QUESTION", "RateLimiter", "Record",
    "RetryPolicy", "Score", "ScoreItem",
    "ScoreResult", "Segment", "ShadowLog", "ShadowStats", "TurnSignals",
    "admit", "build_state", "detect_kind", "estimate_tokens", "expand",
    "find_pointers", "find_trace_regions", "format_pointer", "parse_pointer",
    "reconstruct", "retrieve", "score_items", "score_map", "segment",
]
