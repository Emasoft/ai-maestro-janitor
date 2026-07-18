"""Cold-cache auto-compact policy + readers (TRDD-EUWIHP0G).

After a >1h stop (rate limit; the user exits + relaunches; a logout/login) the 1h prompt-cache
TTL has expired, so the first resumed turn re-writes the WHOLE context as a cache-creation
(~600k avg) — and a write at the 1-hour TTL is billed at **2×**, the priciest token class there
is, so a cold resume costs ~1.2M weighted and can swallow a large slice of the 5h window in a
single turn. This module decides WHEN to auto-inject `/compact` so the large context is shrunk
— after which the rest of the window runs cheap (~50k) and every future cold resume costs ~50k
instead of ~600k. (It cannot avoid the IMMEDIATE cold write — any first turn pays that — see the
TRDD; the win is ongoing + future.)

Split like the rest of the codebase (pure policy vs I/O):
  * `should_compact_on_resume` / `should_compact_after_idle` are PURE + unit-testable.
  * the reader helpers do best-effort filesystem I/O and never raise.

The CALLERS (the SessionStart hook + dispatch's rate-limit path) fire `/compact` via the existing
`scripts/compact_trigger.py` (SOFT — the resumed REPL is idle). This module only decides + reads.
"""

from __future__ import annotations

import json
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
# TRDD-D3PROACT: the PREVENTIVE knob. The two gates above are REACTIVE — they shrink a large
# context only AFTER a cold event already paid the 2× write (rate-limit resume, SessionStart).
# This one shrinks a large context PROACTIVELY, during a cheap WARM idle heartbeat, so the
# context is already small when the next cold event (a >1h working turn, a rate limit, a
# restart) strikes — turning the "inevitable cold write" from ~600k into ~50k. Default ON.
PROACTIVE_IDLE_ENABLED_ENV = "CLAUDE_PLUGIN_OPTION_PROACTIVE_IDLE_COMPACT_ENABLED"
# TRDD-D3PROACT follow-up: how much a compaction must be able to RECLAIM before firing one is
# worth it. Guards the infinite-compact loop documented on `refresh_floor` — a size-only gate
# cannot close on a heavy install, because the post-compaction floor sits ABOVE the threshold.
MIN_GAIN_ENV = "CLAUDE_PLUGIN_OPTION_PROACTIVE_IDLE_COMPACT_MIN_GAIN_TOKENS"

# The janitor's compact threshold is HARNESS-RELATIVE (owner directive 2026-07-18): it must NEVER
# compete with Claude Code's own auto-compaction — it only backstops a harness compaction that
# FAILED. The harness auto-compacts at `CLAUDE_CODE_AUTO_COMPACT_WINDOW - summary_overhead` (the
# user's 700000 - 34000 = 666000), so the janitor fires only strictly ABOVE that point plus a
# margin. See `min_context_tokens()`. The previous FIXED 350k default fired at 35% of a 1M window —
# it compacted the user out from under a 488k (49%) context, well below the 666k the harness owns
# (incident 2026-07-18). `DEFAULT_MIN_CONTEXT_TOKENS` survives only as the ABSOLUTE FLOOR the
# harness-relative value can never drop below: it MUST sit above this install's POST-COMPACTION
# FLOOR (base CLAUDE.md + plugins + rules + skills + MCP schemas + summary; measured 308,644 here
# on 2026-07-17), so a pathologically small `CLAUDE_CODE_AUTO_COMPACT_WINDOW` can never make the
# janitor compact a context with nothing above the floor to reclaim.
DEFAULT_MIN_CONTEXT_TOKENS = 350_000
# How far ABOVE the harness's own effective compact point the janitor waits before backstopping.
# Keeps the two from racing at the exact boundary; a healthy session (which the harness holds under
# its compact point) never reaches janitor+margin, so the janitor stays silent in normal operation.
HARNESS_BACKSTOP_MARGIN_ENV = "CLAUDE_PLUGIN_OPTION_COMPACT_BACKSTOP_MARGIN_TOKENS"
DEFAULT_HARNESS_BACKSTOP_MARGIN = 50_000
# The context-window size, used ONLY when CLAUDE_CODE_AUTO_COMPACT_WINDOW is unset (the harness then
# compacts near the full window minus its own buffer, so the janitor backstop sits just below it).
# Shares the knob the context-watchdog hook reads, so both agree on the window.
CONTEXT_WINDOW_ENV = "CLAUDE_PLUGIN_OPTION_CONTEXT_WINDOW_TOKENS"
DEFAULT_CONTEXT_WINDOW_TOKENS = 1_000_000
DEFAULT_MIN_IDLE_SECONDS = 3_600      # the 1h prompt-cache TTL — below this the cache is still warm
DEFAULT_COOLDOWN_SECONDS = 600        # don't re-fire within 10 min (before the compact lands)
DEFAULT_MIN_GAIN_TOKENS = 150_000     # reclaimable tokens below which a lossy compact isn't worth it

_FIRED_STAMP = "cold-compact-fired.ts"
_FLOOR_STAMP = "compact-floor.json"
_LAST_COMPACT_STAMP = "last-compact.ts"  # high-water mark, written by the PostCompact hook


def enabled() -> bool:
    return state.is_truthy_env(ENABLED_ENV, True)


def min_context_tokens() -> int:
    """The context size at/above which the janitor may compact — HARNESS-RELATIVE so it never
    competes with Claude Code's own auto-compaction (owner directive 2026-07-18).

    Resolution order:
      1. An explicit `CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_MIN_CONTEXT_TOKENS` override wins.
      2. `CLAUDE_CODE_AUTO_COMPACT_WINDOW` set → the harness's effective compact point
         (`auto_window - summary_overhead`) + the backstop margin. The janitor fires ONLY if the
         context climbs above where the harness already compacts — i.e. the harness demonstrably
         failed. (User: 700000 → effective 666000 → threshold 716000.)
      3. Env unset → the harness compacts near the full window; the janitor backstop sits just
         below the window (`window - overhead + margin`), which the context can't exceed, so the
         janitor effectively never proactively compacts and the harness owns it entirely.

    The result is floored at `DEFAULT_MIN_CONTEXT_TOKENS` so a pathologically small auto-window can
    never push the threshold below this install's post-compaction floor (nothing to reclaim there).
    """
    raw = os.environ.get(MIN_CONTEXT_ENV)
    if raw is not None:
        parsed = state.parse_nonneg_int(raw)
        if parsed is not None:
            return parsed  # explicit operator override — trust it verbatim
    margin = state.coerce_int(
        os.environ.get(HARNESS_BACKSTOP_MARGIN_ENV), DEFAULT_HARNESS_BACKSTOP_MARGIN
    )
    # predict_auto_compact(0) returns the used-independent geometry when the env var is set (the
    # effective point is `auto_window - overhead`), and None when it is unset.
    pred = token_meter.predict_auto_compact(0)
    if pred is not None:
        return max(pred.effective_compact_point + margin, DEFAULT_MIN_CONTEXT_TOKENS)
    window = state.coerce_int(os.environ.get(CONTEXT_WINDOW_ENV), DEFAULT_CONTEXT_WINDOW_TOKENS)
    overhead = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_COMPACT_SUMMARY_TOKENS"),
        token_meter._DEFAULT_COMPACT_SUMMARY_OVERHEAD,
    )
    return max(window - overhead + margin, DEFAULT_MIN_CONTEXT_TOKENS)


def min_idle_seconds() -> int:
    return state.coerce_int(os.environ.get(MIN_IDLE_ENV), DEFAULT_MIN_IDLE_SECONDS)


def cooldown_seconds() -> int:
    return state.coerce_int(os.environ.get(COOLDOWN_ENV), DEFAULT_COOLDOWN_SECONDS)


def min_gain_tokens() -> int:
    return state.coerce_int(os.environ.get(MIN_GAIN_ENV), DEFAULT_MIN_GAIN_TOKENS)


def proactive_idle_enabled() -> bool:
    """The preventive path is gated by BOTH the master cold-compact switch AND its own knob, so
    disabling cold-compact wholesale (ENABLED_ENV=false) also disables prevention, and a user who
    wants only the reactive backstops can turn prevention off alone."""
    return enabled() and state.is_truthy_env(PROACTIVE_IDLE_ENABLED_ENV, True)


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


def should_compact_proactively_idle(
    context_tokens: int | None,
    *,
    user_present: bool,
    active_waiting: bool,
    min_context_tokens: int,
    floor_tokens: int | None,
    min_gain: int,
) -> bool:
    """PREVENTIVE gate (TRDD-D3PROACT): shrink a large context DURING a cheap warm idle
    heartbeat, so a future cold event reads ~50k, not ~600k. PURE — the runtime facts
    (`user_present`, `active_waiting`, `context_tokens`, `floor_tokens`) are injected.

    Deliberately NOT cold-aware: the whole point is to fire while the cache is still WARM
    (the shrink turn is then cheap) so no cold event is ever expensive. ALL FOUR must hold:

      * NOT user_present  — the user has not typed in THIS pane recently (>= the 5-min idle
        window). Compaction is lossy, so it must never fire out from under someone actively
        working; an absent user is the safe case (they left a big context behind).
      * NOT active_waiting — there is no pending resume, keep-going opt-in, resume directive,
        or in-flight background agent. Nothing is mid-flight to interrupt, and the session
        genuinely has nothing queued to "continue" this instant.
      * context_tokens >= threshold — small contexts save nothing; only a large one is worth
        the lossy compaction and is what makes a cold event expensive.
      * context_tokens - floor >= min_gain — a compaction can only reclaim what sits ABOVE this
        session's post-compaction floor, so this is the only gate that asks the real question:
        "would compacting actually free anything?" It is what makes the trigger TERMINATE —
        see `refresh_floor` for the measured loop it kills. A floor of None (none observed yet)
        skips this clause: the first fire is judged on size alone, and it is that fire's own
        result that teaches the floor.
    """
    if user_present or active_waiting or context_tokens is None:
        return False
    if context_tokens < min_context_tokens:
        return False
    if floor_tokens is not None and (context_tokens - floor_tokens) < min_gain:
        return False
    return True


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


# --- the post-compaction floor (what makes the preventive trigger terminate) -------

def mark_compacted(state_dir: Path, *, now: int) -> None:
    """Record that a compaction just happened — the PostCompact hook's only job here.

    A high-water TIMESTAMP, never a consume-once flag: a flag that some reader clears could let
    a compaction go unobserved, and an unobserved compaction is one whose floor is never learned
    — which silently re-opens the loop `refresh_floor` documents. Best-effort.
    """
    try:
        state.atomic_write(state_dir / _LAST_COMPACT_STAMP, str(now))
    except OSError:
        pass


def read_floor(state_dir: Path) -> tuple[int | None, int]:
    """`(floor_tokens, measured_after_compact_ts)` — the context size observed right AFTER the most
    recent compaction. `(None, 0)` when no floor has been measured yet. Never raises."""
    try:
        data = json.loads((state_dir / _FLOOR_STAMP).read_text(encoding="utf-8"))
        tokens = int(data["tokens"])
        ts = int(data.get("compact_ts", 0))
    except (FileNotFoundError, OSError, ValueError, KeyError, TypeError):
        return None, 0
    return (tokens if tokens > 0 else None), ts


def floor_needs_learning(state_dir: Path) -> bool:
    """True iff a compaction has LANDED that no floor measurement has observed yet.

    THE ORDERING CONTRACT (the v0.49.0 bug this exists to fix — TRDD-28XF77X6): callers MUST
    check this and record the floor BEFORE their action gates (cooldown / user-present /
    active-waiting), never after. Those gates veto the lossy COMPACT — but the compaction that
    makes the floor observable stamps every one of them itself (`mark_fired` starts the 600s
    cooldown, the compaction's auto-resume stamps `last-resume.ts` for 30 min, and a keep-going
    session never stops "waiting"), so a measurement placed behind them is unreachable in
    exactly the unattended sessions the proactive trigger targets. Verified live 2026-07-17:
    a real compaction, three fires and several Stops after it, floor never recorded — the
    loop-killing gain gate never engaged; only the 350k threshold held. Measuring is a passive
    read; no gate that exists to protect in-flight work applies to it.

    Two tiny state reads; never raises. False when no compaction ever landed, or once
    `refresh_floor` has recorded a floor for the newest one.
    """
    last_compact = state.read_int_state(state_dir / _LAST_COMPACT_STAMP, 0)
    floor_ts = read_floor(state_dir)[1]
    return last_compact > floor_ts


def refresh_floor(state_dir: Path, context_tokens: int | None) -> int | None:
    """Learn this session's POST-COMPACTION FLOOR from the live context, and return it.

    THE LOOP THIS KILLS (measured in this very repo, 2026-07-17): a real compaction took the
    context 343,007 -> 308,644. Only 10% — because the base (CLAUDE.md + ~10 plugins + rules +
    skills + MCP schemas + the summary itself) reloads after EVERY compaction and cannot be
    compacted away. 308,644 is ABOVE the 270,000 threshold, so a size-only gate NEVER closes:
    compact -> still over -> cooldown expires -> compact again, every 10 minutes, forever,
    destroying context each time. No threshold can fix that, because the floor is a property of
    the install, not a number we get to choose. Only measuring the floor can.

    So: once a compaction has happened since we last measured, the CURRENT context IS the floor
    — record it. `should_compact_proactively_idle` then requires `ctx - floor >= min_gain`, which
    is precisely "exclude the compaction case" (user, 2026-07-17): at the floor the reclaimable
    amount is 0, so the trigger is dead until genuinely new work has piled up above it.

    Measuring at a turn's end can only OVER-state the floor (that turn's own tokens are included),
    which under-states the gain and biases toward NOT firing — a missed optimization rather than a
    destroyed context. The safe direction.
    """
    last_compact = state.read_int_state(state_dir / _LAST_COMPACT_STAMP, 0)
    floor, floor_ts = read_floor(state_dir)
    if context_tokens is None or last_compact <= floor_ts:
        return floor  # no compaction since the last measurement → the known floor still stands
    try:
        state.atomic_write(
            state_dir / _FLOOR_STAMP,
            json.dumps({"tokens": int(context_tokens), "compact_ts": last_compact}),
        )
    except OSError:
        return floor
    return int(context_tokens)
