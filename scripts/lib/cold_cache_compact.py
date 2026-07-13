"""Cold-cache auto-compact policy + readers (TRDD-EUWIHP0G).

After a >1h stop (rate limit; the user exits + relaunches; a logout/login) the 1h prompt-cache
TTL has expired, so the first resumed turn re-writes the WHOLE context as a cache-creation
(~600k avg, ~1.25×), burning the 5h window. This module decides WHEN to auto-inject `/compact`
so the large context is shrunk — after which the rest of the window runs cheap (~50k) and every
future cold resume costs ~50k instead of ~600k. (It cannot avoid the IMMEDIATE cold write — any
first turn pays that — see the TRDD; the win is ongoing + future.)

Split like the rest of the codebase (pure policy vs I/O):
  * `should_compact_on_resume` / `should_compact_after_idle` are PURE + unit-testable.
  * the reader helpers do best-effort filesystem I/O and never raise.

The CALLERS (the SessionStart hook + dispatch's rate-limit path) fire `/compact` via the existing
`scripts/compact_trigger.py` (SOFT — the resumed REPL is idle). This module only decides + reads.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import memory_scopes  # noqa: E402  -- sibling lib
import state  # noqa: E402  -- sibling lib
import token_meter  # noqa: E402  -- sibling lib

# --- config knobs (userConfig → env; read via the shared coercers) ----------
ENABLED_ENV = "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_ENABLED"
MIN_CONTEXT_ENV = "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_MIN_CONTEXT_TOKENS"
MIN_IDLE_ENV = "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_MIN_IDLE_SECONDS"
COOLDOWN_ENV = "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_COOLDOWN_SECONDS"

DEFAULT_MIN_CONTEXT_TOKENS = 270_000  # the user's number: compact a resumed context at/above this
DEFAULT_MIN_IDLE_SECONDS = 3_600      # the 1h prompt-cache TTL — below this the cache is still warm
DEFAULT_COOLDOWN_SECONDS = 600        # don't re-fire within 10 min (before the compact lands)

_FIRED_STAMP = "cold-compact-fired.ts"


def enabled() -> bool:
    return state.is_truthy_env(ENABLED_ENV, True)


def min_context_tokens() -> int:
    return state.coerce_int(os.environ.get(MIN_CONTEXT_ENV), DEFAULT_MIN_CONTEXT_TOKENS)


def min_idle_seconds() -> int:
    return state.coerce_int(os.environ.get(MIN_IDLE_ENV), DEFAULT_MIN_IDLE_SECONDS)


def cooldown_seconds() -> int:
    return state.coerce_int(os.environ.get(COOLDOWN_ENV), DEFAULT_COOLDOWN_SECONDS)


# --- pure policy ------------------------------------------------------------

def should_compact_on_resume(context_tokens: int | None, *, min_context_tokens: int) -> bool:
    """SessionStart (startup/resume) gate: a resumed context at/above the threshold. PURE.

    No idle gate: a SessionStart carrying a large context means a FRESH process loaded it — the
    cold/large case by construction (relaunch-after-exit / --continue / --resume / relaunch after a
    logout+login all land here). A brand-new empty session has a tiny context and never trips this.
    """
    return context_tokens is not None and context_tokens >= min_context_tokens


def should_compact_after_idle(
    idle_seconds: int, context_tokens: int | None, *, min_idle_s: int, min_context_tokens: int
) -> bool:
    """Heartbeat gate for an IN-SESSION gap (rate limit): the cache is cold (idle past the TTL) AND
    the context is large. PURE. Both conditions required — compacting a warm cache (idle < TTL) just
    wastes a write, and compacting a small context saves nothing."""
    return (
        idle_seconds >= min_idle_s
        and context_tokens is not None
        and context_tokens >= min_context_tokens
    )


# --- best-effort readers (never raise) --------------------------------------

def context_tokens_for(transcript_path: str | os.PathLike[str] | None) -> int | None:
    """Live context occupancy for a transcript, or None when unknown. Thin, never-raising wrapper
    over token_meter.latest_context_size (which sums input+cache_read+cache_creation of the last
    assistant message)."""
    if not transcript_path:
        return None
    try:
        return token_meter.latest_context_size(transcript_path)
    except Exception:  # noqa: BLE001 -- a bad transcript must never break a resume path
        return None


def newest_transcript(project_dir: str | os.PathLike[str] | None) -> Path | None:
    """The newest `*.jsonl` transcript for a project, or None. For the dispatch path, which gets no
    hook payload: transcripts live at `~/.claude/projects/<slug>/<session>.jsonl` (slug via the
    shared memory_scopes.project_slug). Best-effort; never raises."""
    if not project_dir:
        return None
    try:
        slug = memory_scopes.project_slug(str(project_dir))
        tdir = Path.home() / ".claude" / "projects" / slug
        transcripts = list(tdir.glob("*.jsonl"))
        if not transcripts:
            return None
        return max(transcripts, key=lambda p: p.stat().st_mtime)
    except OSError:
        return None


# --- cooldown (shared by both callers) --------------------------------------

def in_cooldown(state_dir: Path, *, now: int) -> bool:
    """True iff a cold-compact was fired within the cooldown window — so a repeat trigger before the
    compact actually lands cannot double-fire. Best-effort: a read error reads as 'not in cooldown'
    (fail toward acting, since missing a needed compact is the failure this feature exists to fix)."""
    stamp = state_dir / _FIRED_STAMP
    try:
        last = int(stamp.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return False
    return (now - last) < cooldown_seconds()


def mark_fired(state_dir: Path, *, now: int) -> None:
    """Record that a cold-compact was fired now (atomic). Best-effort."""
    try:
        state.atomic_write(state_dir / _FIRED_STAMP, str(now))
    except OSError:
        pass
