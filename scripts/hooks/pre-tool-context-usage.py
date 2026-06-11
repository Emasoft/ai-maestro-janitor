#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PreToolUse hook — surface the live context-window % to the agent on every tool call.

Part of the context-compact watchdog (TRDD-31095269). Claude Code's native
auto-compact still under-fires on the 1M window for credit-bearing sessions
(they run past the configured threshold, sometimes to 999k where /compact
itself can no longer run). (CC 2.1.172 added an auto-compact-back, but only for
the 1M-WITHOUT-usage-credits stuck case — not this threshold overrun.) The
watchdog puts the agent in the loop instead: the statusline writes the live %
to a project-local snapshot, this hook injects that % before every tool call,
and the agent decides whether to keep going or invoke /janitor-compact-context.

This hook is the CONSUMER. It reads the snapshot the statusline writes —
  <project>/.claude/janitor/context-usage.<session_id>.json
  keys: session_id, pct (int %), tokens (int), window (int), iterm_session_id, ts (epoch)
— and emits `hookSpecificOutput.additionalContext` so the string reaches the
model next to the tool result. At or above the suggest threshold (default 60%)
it appends a nudge to run /janitor-compact-context while there's still headroom.

CRITICAL SAFETY PROPERTY: this hook emits NO `permissionDecision`. additionalContext
reaches the model regardless of permissionDecision, so omitting it keeps the tool's
normal permission flow completely untouched — the watchdog is purely advisory and
must never silently auto-approve (or block) a tool call.

OPT-IN: a no-op unless `CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED` is truthy.
Firing on every tool call is intrusive, so installs that don't want it pay nothing.
Self-contained (stdlib only) — no lib import, no CLAUDE_PLUGIN_ROOT dependency.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_DEFAULT_SUGGEST_PCT = 60
# During active tool-calling the statusline re-renders frequently, so the
# snapshot stays fresh; a stale reading mostly means the session is idle (no
# tool calls anyway). Beyond this age we still show the %, but flag it as lagging.
_STALE_AGE_S = 120


def _truthy(raw: str | None) -> bool:
    """Empty/unset → False; `false`/`0`/`no`/`off` → False; anything else → True."""
    if not raw:
        return False
    return raw.strip().lower() not in ("false", "0", "no", "off", "")


def _coerce_int(raw: str | None, default: int) -> int:
    """Best-effort non-negative int; any junk → default (a typo must not crash)."""
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


def _build_context_line(snap: dict, now: int, suggest_pct: int) -> str | None:
    """Render the advisory line, or None when the snapshot lacks a usable %."""
    pct = snap.get("pct")
    if not isinstance(pct, int):
        return None
    tokens = snap.get("tokens")
    window = snap.get("window")
    usage = f"{pct}%"
    if isinstance(tokens, int) and isinstance(window, int) and window > 0:
        usage = f"{pct}% ({_fmt_tokens(tokens)}/{_fmt_tokens(window)})"
    line = f"Context window: {usage} used."
    ts = snap.get("ts")
    age = now - ts if isinstance(ts, int) else None
    if age is not None and age > _STALE_AGE_S:
        line += f" (snapshot {age}s old — may lag)"
    if pct >= suggest_pct:
        line += (
            f" ⚠ At/above {suggest_pct}% — consider running /janitor-compact-context to "
            "compact now while there's headroom (native auto-compact is unreliable on this window; "
            "wait too long and /compact itself can fail)."
        )
    return line


def main() -> int:
    # OPT-IN — zero cost unless the user explicitly enabled the watchdog.
    if not _truthy(os.environ.get("CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED")):
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
    project_dir = (
        os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
        or str(payload.get("cwd", "") or "")
    )
    if not session_id or not project_dir:
        return 0

    snap_path = Path(project_dir) / ".claude" / "janitor" / f"context-usage.{session_id}.json"
    try:
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        # Producer not present / unreadable → stay silent (no injection).
        return 0
    if not isinstance(snap, dict):
        return 0

    suggest_pct = _coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_CONTEXT_COMPACT_SUGGEST_PCT"),
        _DEFAULT_SUGGEST_PCT,
    )
    line = _build_context_line(snap, int(time.time()), suggest_pct)
    if not line:
        return 0

    # additionalContext WITHOUT permissionDecision: advisory only, never alters
    # the tool's normal permission handling.
    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": line,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    # Bare main() — side effects inside it so the module is import-safe (no
    # module-scope sys.exit), matching the other janitor hooks.
    main()
