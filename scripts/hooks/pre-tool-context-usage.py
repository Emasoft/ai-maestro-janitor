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
  * ADVISORY (≥ SUGGEST_PCT, default 60%) — inject the context % + a nudge to run
    /janitor-compact-context while there's still headroom. additionalContext only, NO
    permissionDecision, so the tool's normal permission flow is untouched.
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

import token_meter  # noqa: E402  # latest_context_size — transcript-based occupancy

_DEFAULT_SUGGEST_PCT = 60
_DEFAULT_HARDSTOP_PCT = 85
_DEFAULT_WINDOW = 1_000_000
# Trigger/deny at most once per compaction episode: after a compact fires, the next turn
# (post-resume) is normally well below the cap; the window also stops a /compact spam loop
# AND a deny-after-resume stuck loop (if compaction didn't drop us below the cap we fall
# through to the advisory, never deny-forever).
_AUTOCOMPACT_DEDUPE_S = 180
# PREPARE tier (TRDD-TKNSTP82 C): once we are within this many tokens of the predicted
# auto-compact point, warn the agent to finish + hand off BEFORE the forced compaction.
_DEFAULT_PREPARE_TOKENS = 30_000


def _truthy(raw: str | None, *, default: bool) -> bool:
    """Empty/unset → default; `false`/`0`/`no`/`off` → False; anything else → True."""
    if raw is None or raw == "":
        return default
    return raw.strip().lower() not in ("false", "0", "no", "off", "")


def _coerce_int(raw: str | None, default: int) -> int:
    """Best-effort non-negative int; any junk → default (a typo must not crash a hook)."""
    if not raw:
        return default
    try:
        val = int(raw.strip())
    except (ValueError, AttributeError):
        return default
    return val if val >= 0 else default


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}m"
    if n >= 1_000:
        return f"{n // 1000}k"
    return str(n)


def _resolve_context(project_dir: str, session_id: str, transcript: str, window_default: int, *, now: int) -> tuple[int | None, int | None, int | None, bool]:
    """Thin wrapper — the implementation lives in token_meter.resolve_context (TRDD-TKNSTP82
    A4), shared with `/janitor-token-report --live`. This hook's OWN behavior is UNCHANGED;
    only the implementation moved, so it can never silently drift from the report's view."""
    return token_meter.resolve_context(project_dir, session_id, transcript, window_default, now=now)


def _format_line(pct: int, tokens, window, stale: bool, suggest_pct: int) -> str:
    usage = f"{pct}%"
    if isinstance(tokens, int) and isinstance(window, int) and window > 0:
        usage = f"{pct}% ({_fmt_tokens(tokens)}/{_fmt_tokens(window)})"
    elif isinstance(tokens, int):
        usage = f"{pct}% (~{_fmt_tokens(tokens)})"
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
    eff = _fmt_tokens(pred.effective_compact_point)
    until = pred.tokens_until_compact
    if until > 0:
        head = f"⚠ PREPARE for auto-compact: ~{_fmt_tokens(until)} until the auto-compact point ({eff})."
    else:
        head = f"⚠ Auto-compact IMMINENT — {_fmt_tokens(-until)} PAST the auto-compact point ({eff})."
    return (
        f"Context window: {pct}% used. {head} "
        f"(point = CLAUDE_CODE_AUTO_COMPACT_WINDOW {_fmt_tokens(pred.auto_window)} − {_fmt_tokens(pred.overhead)} summary cost.) "
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
    directive = f"resume your in-flight task — the context-size guard auto-compacted at {pct}% to stop the per-turn token bleed; re-check the TRDD board / your handoff first."
    try:
        r = subprocess.run(
            ["uv", "run", "--script", "--quiet", str(script), "--directive", directive],
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
    size = f"~{_fmt_tokens(tokens)}" if isinstance(tokens, int) else f"{pct}%"
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"[context-guard] Context is at {pct}% ({size}) — every turn now re-reads the "
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
            sys.stdout.write(json.dumps(_advisory(_format_prepare_line(pct, prediction))))
            return 0

    # ADVISORY tier — stay SILENT below the suggest threshold so the guard costs ZERO
    # context until you are actually approaching the cap. An additionalContext line rides
    # forward in the transcript and is re-read every subsequent turn, so injecting one on
    # every low-% tool call would itself add to the very per-turn bleed this guard exists
    # to cut. Below the threshold the statusline already shows the %; we add nothing.
    if pct >= suggest_pct:
        sys.stdout.write(json.dumps(_advisory(_format_line(pct, tokens, window, stale, suggest_pct))))
    return 0


if __name__ == "__main__":
    # Bare main() — side effects inside it so the module is import-safe (no module-scope
    # sys.exit), matching the other janitor hooks.
    main()
