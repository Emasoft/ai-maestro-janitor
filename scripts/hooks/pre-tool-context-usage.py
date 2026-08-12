#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PreToolUse hook — context-size runaway guard (TRDD-31095269, TRDD-SMZFJVZ3).

The token bleed the user named is per-turn CONTEXT SIZE, NOT tool count: a session
bloated near the window cap re-reads ~that many tokens EVERY turn (agent turns AND every
~5-min heartbeat fire), so cost ≈ turns × context — ~20 turns at ~999k = ~20M tokens
regardless of output. The ONLY thing that shrinks per-turn cost is a COMPACTION, so this
hook reads the live context occupancy on every tool call and FORCES one near the cap.

Two tiers:
  * ADVISORY (≥ SUGGEST_PCT, default 80%) — inject the context % + a nudge to run
    /janitor-compact-context while there's still headroom. additionalContext only, NO
    permissionDecision, so the tool's normal permission flow is untouched. Default 80
    (was 60) per the token-quietness audit (ARCHITECTURE.md §3, ratified 2026-07-17):
    the Claude Code harness already warns near-full, so the janitor's routine mid-band
    (60/70) capacity chatter duplicated it; one advisory band remains directly below
    enforcement as the compact-at-a-natural-boundary runway. Restore the old behavior
    with CLAUDE_PLUGIN_OPTION_CONTEXT_COMPACT_SUGGEST_PCT=60.
  * ENFORCEMENT (≥ HARDSTOP_PCT, default 85%, gated by AUTOCOMPACT_ENABLED) — run
    compact_trigger.py (records a resume directive + queues ESC+/compact on the pane)
    and DENY this tool call so the turn ends cleanly for /compact; post-compact-resume
    then continues the work at a reduced context. Native auto-compact under-fires on the
    1M window, so the janitor enforces the compaction here.

Context source (robust, statusline-INDEPENDENT):
  1. the statusline snapshot <project>/.claude/janitor/context-usage.<sid>.json (carries
     the real window → accurate %), else
  2. token_meter.latest_context_size(transcript) — the latest assistant message's
     input+cache_read+cache_creation = live occupancy — over a configurable default
     window (1M). The latest message is at the tail end, so this is always findable
     (unlike a turn boundary, which can fall past the tail window).

SAFETY (this hook fires on EVERY tool call in EVERY session — USER scope):
  * DEFAULT-ON, but every error path FAILS OPEN (return 0 → allow the tool).
  * The enforcement DENY fires ONLY when compact_trigger actually queued a compact
    (COMPACT_FIRED). With no automatable terminal (NO_ITERM) or any error it degrades to
    the advisory — NEVER a stuck "denied with no way to compact". A short dedupe window
    means it triggers/denies at most once per compaction episode (no deny-after-resume
    loop, no /compact spam).

issue #79 (2026-07): agentlensPro's raw-body cache-break measurement showed the janitor's
no-matcher PreToolUse `additionalContext` nudges as the #2 cause of prompt-cache
invalidation — every injected block is later STRIPPED by Claude Code retroactively,
mid-transcript, and that strip re-bills everything after it as cache_creation. The %-band
ADVISORY already only announces on a genuine climb (TRDD-K1RJUYGK), never periodically —
that part already matched the fix. PREPARE now gets the same "transition, plus a periodic
re-nudge while it persists" treatment as the sibling token-budget hook's hard tier (see
`_prepare_should_emit`), since it is the one tier here close enough to a forced compaction
to be worth repeating. ENFORCEMENT (the deny above) is untouched — a decision field is
never stripped, so it was never part of the problem.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent  # scripts/hooks/
sys.path.insert(0, str(_HERE.parent / "lib"))

import state  # noqa: E402  # atomic_write — the latch + prepare-renudge state files (issue #79)
import token_meter  # noqa: E402  # latest_context_size — transcript-based occupancy

# 80, not 60 (token-quietness audit 2026-07-17): the harness's own near-full warning
# covers the mid band; the janitor adds exactly ONE pre-enforcement runway band.
_DEFAULT_SUGGEST_PCT = 80
_DEFAULT_HARDSTOP_PCT = 85
_DEFAULT_WINDOW = 1_000_000
# Trigger/deny at most once per compaction episode: after a compact fires, the next turn
# (post-resume) is normally well below the cap; the window also stops a /compact spam loop
# AND a deny-after-resume stuck loop (if compaction didn't drop us below the cap we fall
# through to the advisory, never deny-forever).
_AUTOCOMPACT_DEDUPE_S = 180

# Cap the advisory latch file (TRDD-K1RJUYGK). One line per (session, tier); a long-lived
# project dir accumulates sessions, so trim to the newest N rather than growing unbounded.
_LATCH_MAX_LINES = 200
# PREPARE tier (TRDD-TKNSTP82 C): once we are within this many tokens of the predicted
# auto-compact point, warn the agent to finish + hand off BEFORE the forced compaction.
_DEFAULT_PREPARE_TOKENS = 30_000
# issue #79: the %-band advisory below (60/70/80) already only nudges on a genuine climb
# (never periodically) — that part already matched the "no re-nudge at a steady tier"
# invariant. PREPARE is the one additionalContext tier in THIS hook that is genuinely
# urgent (imminent forced compaction) and has NO other channel reminding the agent while
# it lingers — unlike ENFORCEMENT (a `deny`, unaffected here) or a runaway (the sibling
# token-budget hook's hard tier). So PREPARE is this hook's analog of "hard": it gets a
# periodic re-nudge while it persists, on a SEPARATE, shorter interval than the old
# once-per-climb latch alone would give it. Default matches the sibling hook (10 min).
_DEFAULT_PREPARE_RENUDGE_S = 600


def _truthy(raw: str | None, *, default: bool) -> bool:
    """Empty/unset → default; `false`/`0`/`no`/`off` → False; anything else → True."""
    if raw is None or raw == "":
        return default
    return raw.strip().lower() not in ("false", "0", "no", "off", "")


def _coerce_int(raw: str | None, default: int) -> int:
    """Best-effort non-negative int; any junk → default (a typo must not crash a hook).

    Delegates to the shared parser (one source of truth) so a knob set the way Claude
    Code documents its own int env vars — `1e6`, `64_000` (CC 2.1.208/2.1.211) — is
    honored here too, not silently reverted to the default."""
    if not raw:
        return default
    parsed = state.parse_nonneg_int(raw.strip())
    return parsed if parsed is not None else default


def _bucket_tokens(n: int) -> str:
    """Floor `n` to the nearest 10k and render it as a cache-STABLE label.

    TRDD-YRPUSIFY (cache-stability): this hook injects its context-window line into
    model context on EVERY tool call above the suggest threshold. A raw per-call token
    count ("650k") makes each injection a unique string that can never share the prompt
    cache and compounds across a session. Flooring to a 10k bucket collapses a whole
    band of raw counts to ONE label ("~650k"), so consecutive tool calls at the same
    occupancy emit byte-identical text. Pure + deterministic (unit-tested): same bucket
    → same string, always. `~1.3M` for >=1M, `~40k` otherwise, `~0k` for <10k.
    """
    if n < 0:
        n = 0
    b = (n // 10_000) * 10_000
    if b >= 1_000_000:
        return f"~{b / 1_000_000:.1f}M"
    return f"~{b // 1_000}k"


def _bucket_pct(p: int) -> str:
    """Floor a percentage to a 5-point step and render it as a cache-STABLE label.

    TRDD-YRPUSIFY: same rationale as `_bucket_tokens` — the live occupancy % drifts a
    point or two between tool calls, so a raw "71%" makes each injected line unique.
    Flooring to a 5-point band ("~70%") keeps the line byte-identical across a band of
    occupancies. Gating still uses the RAW %; only the DISPLAYED value is bucketed.
    """
    if p < 0:
        p = 0
    return f"~{(p // 5) * 5}%"


def _resolve_context(project_dir: str, session_id: str, transcript: str, window_default: int, *, now: int) -> tuple[int | None, int | None, int | None, bool]:
    """Thin wrapper — the implementation lives in token_meter.resolve_context (TRDD-TKNSTP82
    A4), shared with `/janitor-token-report --live`. This hook's OWN behavior is UNCHANGED;
    only the implementation moved, so it can never silently drift from the report's view.

    Passes the compaction high-water stamp so a transcript reading that PREDATES the last
    compaction is omitted rather than reported as live (TRDD-G043V3V0)."""
    last_compact_ts = state.read_int_state(Path(project_dir) / ".janitor" / "state" / state.LAST_COMPACT_STAMP, 0) if project_dir else 0
    return token_meter.resolve_context(project_dir, session_id, transcript, window_default, now=now, last_compact_ts=last_compact_ts)


def _format_line(pct: int, tokens, window, stale: bool, suggest_pct: int) -> str:
    # TRDD-YRPUSIFY (cache-stability): render the pct + token counts through the BUCKETING
    # helpers so two tool calls at nearly-the-same occupancy inject the byte-identical
    # line (cache-shareable). The `pct >= suggest_pct` gate below still uses the RAW pct,
    # so the trip point is unchanged; only the displayed numbers are bucketed. The
    # `suggest_pct` in the nudge is a fixed config threshold (an exact boundary, already
    # constant every call), so it stays exact rather than bucketed.
    pct_b = _bucket_pct(pct)
    usage = pct_b
    if isinstance(tokens, int) and isinstance(window, int) and window > 0:
        usage = f"{pct_b} ({_bucket_tokens(tokens)}/{_bucket_tokens(window)})"
    elif isinstance(tokens, int):
        usage = f"{pct_b} ({_bucket_tokens(tokens)})"
    line = f"Context window: {usage} used."
    if stale:
        line += " (snapshot may lag)"
    if pct >= suggest_pct:
        line += f" ⚠ At/above {suggest_pct}% — run /janitor-compact-context to compact now while there's headroom: every turn re-reads the WHOLE context, so a bloated session burns ~its size in tokens PER TURN (native auto-compact is unreliable on this window; wait too long and /compact itself can fail)."
    return line


def _format_prepare_line(pct: int, pred: token_meter.CompactPrediction) -> str:
    """The PREPARE-for-auto-compact alert (TRDD-TKNSTP82 C). Keyed on the EXACT predicted
    auto-compact point (window − the routine's ~34k summary cost), not a %, so it warns just
    before the forced compaction — while the agent can still finish its step and hand off."""
    # TRDD-YRPUSIFY (cache-stability): bucket every count + the % so the PREPARE line
    # (injected on every tool call while in the pre-compact zone) is byte-identical across
    # the band. `effective_compact_point`, `auto_window`, `overhead` are already
    # per-session constants; bucketing them is harmless and keeps one uniform surface.
    # (`_bucket_tokens` already prefixes "~", so the literal "~" before `until` is gone.)
    eff = _bucket_tokens(pred.effective_compact_point)
    until = pred.tokens_until_compact
    if until > 0:
        head = f"⚠ PREPARE for auto-compact: {_bucket_tokens(until)} until the auto-compact point ({eff})."
    else:
        head = f"⚠ Auto-compact IMMINENT — {_bucket_tokens(-until)} PAST the auto-compact point ({eff})."
    return (
        f"Context window: {_bucket_pct(pct)} used. {head} "
        f"(point = CLAUDE_CODE_AUTO_COMPACT_WINDOW {_bucket_tokens(pred.auto_window)} − {_bucket_tokens(pred.overhead)} summary cost.) "
        "Finish the current step and run /janitor-write-handoff (or /janitor-compact-context to "
        "compact NOW on your terms) so the compaction summary captures your plan."
    )


def _dedupe_path(project_dir: str) -> Path:
    return Path(project_dir) / ".janitor" / "state" / "context-autocompact.ts"


def _recently_compacted(project_dir: str, now: int) -> bool:
    try:
        last = int(_dedupe_path(project_dir).read_text(encoding="utf-8").strip() or "0")
    except (FileNotFoundError, OSError, ValueError):
        return False
    return (now - last) < _AUTOCOMPACT_DEDUPE_S


def _mark_compacted(project_dir: str, now: int) -> None:
    p = _dedupe_path(project_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".tmp.{os.getpid()}")
        tmp.write_text(str(now), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass


def _latch_path(project_dir: str) -> Path:
    return Path(project_dir) / ".janitor" / "state" / "context-advisory-latch.txt"


def _claim_advisory(project_dir: str, session_id: str, tier: str) -> bool:
    """True iff this (session, tier) advisory has NOT been injected yet → emit it ONCE.

    TRDD-K1RJUYGK. An `additionalContext` block is neither free nor idempotent. Claude Code
    STRIPS stale system-reminder blocks retroactively, in place, mid-transcript, and that
    mutation lands inside the cached PREFIX — so every token after it re-bills as
    cache_creation.

    This hook DID emit `additionalContext` on every tool call above the suggest threshold
    (verified in source), and per-tool-call injection is hazardous on that mechanism alone —
    which is reason enough to bound it. NOTE: an earlier version of this docstring blamed this
    hook for a specific measured cost ("the #1 cache-break cause on the machine, $23.05").
    That attribution is RETRACTED (see the TRDD): agentlensPro's `hook: <Event>` label names
    the event BOUNDARY at which a changed block was observed, NOT the component that emitted
    it — it labels breaks at `StopFailure`, whose output the spec says is ignored, and at
    `PostToolBatch`, which no hook on the machine even registers. Do not restore a $ figure
    here without proving the emitter twice (the code emits, AND it was non-silent at the
    moment of the break).

    TRDD-YRPUSIFY tried to fix this by BUCKETING the injected numbers so the text is
    byte-identical across a band. That cannot work, and the data falsified it: bucketing was
    live in every cached version (0.31.0…0.41.0) and the breaks continued. The block is
    DELETED later regardless of what it said — stable text does not survive a strip.

    So the thing to bound is the injection BUDGET, not its TEXT: announce each tier at most
    once per session. The ENFORCEMENT tier (permissionDecision deny + auto-compact) is
    deliberately untouched — it is a decision field, not an injected block, and it fires at
    most once per compaction episode.

    Fails CLOSED (returns False → stay silent) whenever the latch cannot be read or written:
    an unwritable state dir must never degrade back into injecting on every tool call, which
    is the exact bug this guard exists to stop. The >=85% enforcement tier is the backstop.
    """
    if not project_dir or not session_id:
        return False  # cannot latch → cannot bound → do not inject
    key = f"{session_id} {tier}"
    p = _latch_path(project_dir)
    try:
        seen = p.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        seen = []
    except OSError:
        return False
    if key in seen:
        return False
    try:
        # issue #79: reuse the shared atomic-write helper (write tmp, os.replace into
        # place) instead of hand-rolling it here — same atomicity guarantee, one fewer
        # bespoke implementation to keep in sync with the other hook's state files.
        state.atomic_write(p, "\n".join([*seen[-_LATCH_MAX_LINES:], key]) + "\n")
    except OSError:
        return False  # could not record the claim → do not inject (fail closed)
    return True


def _release_advisory(project_dir: str, session_id: str) -> None:
    """Re-arm this session's advisory latch. Called when context has fallen back BELOW the
    suggest threshold — which, within a live session, means a COMPACTION (or an equivalent
    context shrink) just happened.

    Without this the latch is a one-way door for the whole session: `session_id` does NOT
    change across a compaction, so once a session claimed `prepare` and the 60/70/80 bands,
    it could never announce them again — and EVERY SUBSEQUENT auto-compaction would arrive
    with no warning at all, which is precisely the event the `prepare` tier exists to warn
    about. A long session compacts many times; only the first one was covered.

    Re-arming on the way DOWN (rather than tracking a compaction counter) keeps the guarantee
    the injection budget needs: the bands can only be re-claimed after a genuine descent below
    the threshold, so the ceiling is ~3 blocks per CLIMB, not per tool call. Climbing 60→85%
    takes a long time, so this stays bounded.

    Only THIS session's claims are released — a shared project latch file must not re-arm
    other sessions. Best-effort: any I/O error leaves the latch as-is (the safe direction —
    it stays claimed, so we stay silent).
    """
    if not project_dir or not session_id:
        return
    p = _latch_path(project_dir)
    try:
        seen = p.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return  # nothing latched (or unreadable) → nothing to release
    kept = [ln for ln in seen if not ln.startswith(f"{session_id} ")]
    if len(kept) == len(seen):
        return  # this session holds no claims — do not rewrite the file
    try:
        state.atomic_write(p, "".join(f"{ln}\n" for ln in kept))
    except OSError:
        pass  # could not release → stays claimed → stays silent (fail closed, as above)


def _prepare_renudge_path(project_dir: str) -> Path:
    return Path(project_dir) / ".janitor" / "state" / "context-prepare-last-nudge.ts"


def _mark_prepare_nudge(project_dir: str, now: int) -> None:
    """Best-effort stamp of the last PREPARE emission. A failed write just means the next
    call re-derives from a stale/missing stamp — worst case one extra nudge, never a
    suppressed real one (mirrors the token-budget hook's `_write_last_tier`)."""
    try:
        state.atomic_write(_prepare_renudge_path(project_dir), str(now))
    except OSError:
        pass


def _prepare_should_emit(project_dir: str, session_id: str, now: int, renudge_s: int) -> bool:
    """issue #79 — TRUE iff the PREPARE alert should fire now: either this is a fresh claim
    of the 'prepare' band (a genuine transition — see `_claim_advisory`), or PREPARE has
    persisted for >= `renudge_s` seconds since it was last announced. Unlike the %-band
    advisory (which never periodically re-nudges — see module docstring), PREPARE is close
    enough to a forced compaction that a lingering warning is worth repeating; this is the
    hook's analog of the sibling token-budget hook's "hard tier persists" clause.

    `renudge_s <= 0` disables ONLY the periodic half — the transition half (`_claim_advisory`)
    is untouched by that knob, matching the "0 = documented full opt-out" convention used
    throughout these hooks.
    """
    if _claim_advisory(project_dir, session_id, "prepare"):
        _mark_prepare_nudge(project_dir, now)
        return True
    if renudge_s <= 0:
        return False
    try:
        last = int(_prepare_renudge_path(project_dir).read_text(encoding="utf-8").strip() or "0")
    except (FileNotFoundError, OSError, ValueError):
        return False  # cannot read the stamp → cannot bound the interval → stay silent
    if now - last >= renudge_s:
        _mark_prepare_nudge(project_dir, now)
        return True
    return False


def _advisory_tier(pct: int) -> str:
    """The latch key for the %-band advisory: one announcement per 10-point band.

    Bands (not a single once-per-session latch) so an escalating session still gets an
    escalating nudge (60 → 70 → 80) before the >=85% enforcement fires — at a cost of AT MOST
    three injected blocks per session instead of the measured 712.
    """
    return f"suggest:{(pct // 10) * 10}"


def _run_compact_trigger(pct: int) -> str:
    """Queue ESC+/compact on this session's pane via compact_trigger.py. Returns its
    one-word result ('COMPACT_FIRED' | 'NO_ITERM') or 'ERROR'. argv subprocess (NOT the
    agent's Bash) → lean-ctx never gates it; the terminal env is inherited so the trigger
    can target this very pane."""
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if not plugin_root:
        return "ERROR"
    script = Path(plugin_root) / "scripts" / "compact_trigger.py"
    if not script.is_file():
        return "ERROR"
    # TRDD-YRPUSIFY: bucket the % here too — this directive is later surfaced as a
    # [janitor-resume] injection, so keep it on the same cache-stable surface.
    directive = f"resume your in-flight task — the context-size guard auto-compacted at {_bucket_pct(pct)} to stop the per-turn token bleed; re-check the TRDD board / your handoff first."
    try:
        # --hard: this is the >=85% EMERGENCY tier — the deny below is already cutting
        # the turn, and the ESC is the point (compact NOW, before the context wall).
        # The trigger's CLI default is soft/enqueue since TRDD-0GPQROC1, so the
        # emergency semantics must be requested explicitly.
        r = subprocess.run(
            ["uv", "run", "--script", "--quiet", str(script), "--hard", "--directive", directive],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return "ERROR"
    out = (r.stdout or "").strip().upper()
    if "COMPACT_FIRED" in out:
        return "COMPACT_FIRED"
    if "NO_ITERM" in out:
        return "NO_ITERM"
    return "ERROR"


def _deny(pct: int, tokens) -> dict:
    # TRDD-YRPUSIFY (cache-stability): bucket the % + token size so the deny reason is
    # byte-identical for any tool call in the same occupancy band. The dedupe window
    # already limits this to ~once per compaction episode, but bucketing keeps it uniform
    # with the advisory/prepare surfaces. (`_bucket_tokens` already prefixes "~".)
    pct_b = _bucket_pct(pct)
    size = _bucket_tokens(tokens) if isinstance(tokens, int) else pct_b
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"[context-guard] Context is at {pct_b} ({size}) — every turn now re-reads the "
                "whole context, burning ~its size in tokens PER TURN. Auto-compacting now to "
                "stop the bleed: END THIS TURN so /compact can run; post-compact-resume will "
                "continue your task at a reduced context. (Disable: "
                "CLAUDE_PLUGIN_OPTION_CONTEXT_AUTOCOMPACT_ENABLED=false; move the trip point: "
                "CLAUDE_PLUGIN_OPTION_CONTEXT_HARDSTOP_PCT.)"
            ),
        },
    }


def _advisory(line: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": line}}


def _maybe_enforce(pct: int, tokens, project_dir: str, *, hardstop_pct: int, autocompact: bool, now: int) -> dict | None:
    """Near the cap, FORCE a compaction and return the DENY dict; else None (→ advisory).

    Triggers + denies at most ONCE per compaction episode: if a compact was already queued
    in the dedupe window (or compaction didn't drop us below the cap) it returns None so the
    caller falls through to the advisory — never deny-forever, never stuck. The DENY is
    returned ONLY when compact_trigger actually queued a compact (COMPACT_FIRED); a missing
    terminal (NO_ITERM) / any error → None. Fail-open by construction."""
    if not (autocompact and hardstop_pct > 0 and pct >= hardstop_pct):
        return None
    try:
        if _recently_compacted(project_dir, now):
            return None
        if _run_compact_trigger(pct) == "COMPACT_FIRED":
            _mark_compacted(project_dir, now)
            return _deny(pct, tokens)
    except Exception:  # noqa: BLE001 — enforcement must never crash/block the tool
        return None
    return None


def main() -> int:
    # DEFAULT-ON (was opt-in): the context-size guard is the user's primary token guard.
    if not _truthy(os.environ.get("CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED"), default=True):
        return 0

    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return 0
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    session_id = str(payload.get("session_id", "") or "")
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip() or str(payload.get("cwd", "") or "")
    transcript = str(payload.get("transcript_path", "") or "")
    now = int(time.time())

    window_default = _coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_CONTEXT_WINDOW_TOKENS"), _DEFAULT_WINDOW)
    try:
        pct, tokens, window, stale = _resolve_context(project_dir, session_id, transcript, window_default, now=now)
    except Exception:  # noqa: BLE001 — fail-open: a reading error must never block a tool
        return 0
    if pct is None:
        return 0

    suggest_pct = _coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_CONTEXT_COMPACT_SUGGEST_PCT"), _DEFAULT_SUGGEST_PCT)
    hardstop_pct = _coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_CONTEXT_HARDSTOP_PCT"), _DEFAULT_HARDSTOP_PCT)
    autocompact = _truthy(os.environ.get("CLAUDE_PLUGIN_OPTION_CONTEXT_AUTOCOMPACT_ENABLED"), default=True)

    # ENFORCEMENT tier — near the cap, force a compaction (returns the DENY when a compact
    # was actually queued, else None → advisory; never a stuck deny).
    enforced = _maybe_enforce(pct, tokens, project_dir, hardstop_pct=hardstop_pct, autocompact=autocompact, now=now)
    if enforced is not None:
        sys.stdout.write(json.dumps(enforced))
        return 0

    # PREPARE tier (TRDD-TKNSTP82 C) — when CLAUDE_CODE_AUTO_COMPACT_WINDOW is set we can
    # predict the EXACT auto-compact point (window − the routine's ~34k summary cost) and warn
    # just BEFORE it fires, so the agent finishes its step + hands off and the compaction
    # summary captures the plan. More precise + more urgent than the %-band advisory, so it
    # takes precedence when in the zone; with the env var unset, `pred` is None and we fall
    # through to the existing %-of-window advisory (no behavior change).
    prediction = token_meter.predict_auto_compact(tokens)
    if prediction is not None:
        prepare_tokens = _coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_CONTEXT_PREPARE_TOKENS"), _DEFAULT_PREPARE_TOKENS)
        if prediction.tokens_until_compact <= prepare_tokens:
            # TRDD-K1RJUYGK + issue #79: the prepare alert is announced on a genuine
            # transition into the zone, THEN periodically re-fires while it lingers (this
            # tier is close enough to a forced compaction that a stale, unrepeated warning
            # is a real risk) — never on every tool call inside the zone. Re-emitting on
            # every call would seed a fresh strippable system-reminder block per call, and
            # Claude Code's retroactive strip of those blocks is what re-bills the cached
            # prefix (see `_prepare_should_emit`).
            renudge_s = _coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_CONTEXT_PREPARE_RENUDGE_S"), _DEFAULT_PREPARE_RENUDGE_S)
            if _prepare_should_emit(project_dir, session_id, now, renudge_s):
                sys.stdout.write(json.dumps(_advisory(_format_prepare_line(pct, prediction))))
            return 0

    # ADVISORY tier — stay SILENT below the suggest threshold so the guard costs ZERO
    # context until you are actually approaching the cap. An additionalContext line rides
    # forward in the transcript and is re-read every subsequent turn, so injecting one on
    # every low-% tool call would itself add to the very per-turn bleed this guard exists
    # to cut. Below the threshold the statusline already shows the %; we add nothing.
    if pct < suggest_pct:
        # Back below the threshold ⇒ the context shrank ⇒ a compaction happened. Re-arm this
        # session's advisories so the NEXT climb is warned about too. Without this the latch
        # is a one-way door and every compaction after the first arrives unannounced — see
        # `_release_advisory`.
        _release_advisory(project_dir, session_id)
        return 0

    # TRDD-K1RJUYGK: above the threshold the advisory is LATCHED — one announcement per
    # 10-point band, per climb. This hook injected `additionalContext` on EVERY tool call
    # above 60%, and an injected block is neither free nor idempotent: Claude Code later
    # STRIPS it retroactively, in place, and that mutation lands inside the cached PREFIX, so
    # every token after it re-bills as cache_creation. Bucketing the TEXT (TRDD-YRPUSIFY)
    # cannot help — a stripped block costs the same whatever it said; only NOT injecting does.
    # Hence: bound the injection COUNT, never its text.
    if _claim_advisory(project_dir, session_id, _advisory_tier(pct)):
        sys.stdout.write(json.dumps(_advisory(_format_line(pct, tokens, window, stale, suggest_pct))))
    return 0


if __name__ == "__main__":
    # Bare main() — side effects inside it so the module is import-safe (no module-scope
    # sys.exit), matching the other janitor hooks.
    main()
