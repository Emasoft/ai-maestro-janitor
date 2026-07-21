#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""UserPromptSubmit hook — reload-context guard (F1, TRDD-Z582IKIR).

BLOCKS `/reload-plugins` (any suffix, e.g. `--force`) while the session's live
context is at/above a configurable token threshold (default 350000). This is
the mechanism verified against the Claude Code hooks docs (2026-07-21):
`UserPromptSubmit` fires on the RAW prompt text BEFORE built-in slash-command
expansion, and `decision: "block"` blocks + ERASES the prompt — so it can
intercept a built-in command the same way `on-prompt-submit-user-mem.py`
already intercepts the private user-memory commands.

WHY this matters: `/reload-plugins` changes tool schemas, which breaks the
prompt-cache prefix — the NEXT turn pays a full cache-CREATE (~1.25x) of the
WHOLE context instead of a cheap cache-read (~0.1x). On a large session that
single reload is a ~500k+ weighted-token tax; repeated janitor auto-reloads on
a big session were a top driver that exhausted 3 accounts over 2 days (the
incident that motivated this TRDD).

COVERAGE — why a single UserPromptSubmit hook catches BOTH a human typing
`/reload-plugins` themselves AND the janitor's own self-trigger: every path to
`/reload-plugins` ends the same way — the literal command text becomes a
submitted prompt. A human types it directly. The janitor's self-trigger
(`reload_trigger.py`, invoked by `/janitor-reload-plugins` or the heartbeat's
`[janitor-reload]` marker) works by typing `/reload-plugins --force` into
THIS session's own terminal pane via osascript/tmux/wtype — which Claude Code
then submits exactly like a human keystroke, through this same hook. There is
no third path that bypasses UserPromptSubmit; a built-in command cannot be
invoked by the model directly (that is why the self-trigger types into the
pane in the first place).

Coordination with the heartbeat (no defer-then-block loop): `dispatch.py`'s
`_phase_plugin_reload` independently reads the SAME live context through the
SAME shared predicate (`token_meter.reload_guard_should_block`) and DEFERS
emitting `[janitor-reload]` in the first place while context is at/above the
threshold — so the heartbeat's own self-trigger normally never fires while
this hook would block it. This hook is the authoritative backstop for every
OTHER path (a human typing the command, or `/janitor-reload-plugins` invoked
directly): a single source of truth (the shared predicate) means the two
gates can never disagree about the trip point.

FAIL-OPEN by construction: any read/parse error, an unresolvable context, or
the guard being disabled (threshold <= 0) allows the reload through unchanged
— a broken guard must never turn into a stuck block on a legitimate reload.

Per the Claude Code hooks docs, a blocked UserPromptSubmit prompt is ERASED —
the model receives NOTHING, only `systemMessage` reaches the human via the
CLI. That is the correct behavior here: the reload simply does not happen,
context stays intact, and the human (or a later turn re-reading the terminal
history) sees why via systemMessage and can compact/handoff first, then retry.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent  # scripts/hooks/
sys.path.insert(0, str(_HERE.parent / "lib"))

import state  # noqa: E402
import token_meter  # noqa: E402

_DEFAULT_WINDOW = 1_000_000
# Matches "/reload-plugins" at the start of the (lstripped) prompt, optionally
# followed by more text (e.g. " --force") or end-of-string. Anchored so a
# lookalike command sharing the prefix (there is none today, but a future
# `/reload-plugins-foo`) would NOT match — it requires a following space or EOS.
_RELOAD_RE = re.compile(r"^/reload-plugins(?:\s|$)")


def _truthy(raw: str | None, *, default: bool) -> bool:
    """Empty/unset → default; `false`/`0`/`no`/`off` → False; anything else → True."""
    if raw is None or raw == "":
        return default
    return raw.strip().lower() not in ("false", "0", "no", "off", "")


def _coerce_int(raw: str | None, default: int) -> int:
    """Best-effort non-negative int; junk/absent → default. Delegates to the shared
    parser so a knob set the way Claude Code documents its own int env vars (`1e6`,
    `64_000` — CC 2.1.208/2.1.211) is honored here too."""
    if not raw:
        return default
    parsed = state.parse_nonneg_int(raw.strip())
    return parsed if parsed is not None else default


def _block(reason: str) -> dict:
    """A UserPromptSubmit response that blocks + erases the `/reload-plugins` prompt.

    `reason` is internal/log-facing; `systemMessage` is what the human actually sees
    in the terminal (the docs: the model receives NOTHING once blocked, so this is
    the only surface that can explain the block at all)."""
    return {"decision": "block", "reason": reason, "systemMessage": reason}


def main() -> int:
    # DEFAULT-ON, like the sibling context-watchdog hook — opt out per-project/user.
    if not _truthy(os.environ.get("CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_ENABLED"), default=True):
        return 0

    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return 0
    if not raw or not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return 0

    # FAST PATH: every prompt that is not `/reload-plugins` costs one regex match.
    # This hook fires on EVERY submitted prompt, so this guard keeps it effectively
    # free except when the user (or the janitor's self-trigger) actually types it.
    head = prompt.lstrip()
    if not _RELOAD_RE.match(head):
        return 0

    threshold = _coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_THRESHOLD"),
        token_meter.RELOAD_GUARD_DEFAULT_THRESHOLD,
    )
    if threshold <= 0:
        return 0  # 0 = explicit opt-out of the guard (never block)

    # Resolve the live context exactly like pre-tool-context-usage.py: the statusline
    # snapshot when fresh, else the transcript's latest assistant-message occupancy.
    try:
        session_id = str(payload.get("session_id", "") or "")
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip() or str(payload.get("cwd", "") or "")
        transcript = str(payload.get("transcript_path", "") or "")
        window_default = _coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_CONTEXT_WINDOW_TOKENS"), _DEFAULT_WINDOW)
        now = int(time.time())
        _pct, tokens, _window, _stale = token_meter.resolve_context(project_dir, session_id, transcript, window_default, now=now)
    except Exception:  # noqa: BLE001 -- fail-open: a reading error must never block the reload
        return 0

    if not token_meter.reload_guard_should_block(tokens, threshold):
        return 0  # unknown or below-threshold context → allow the reload unchanged

    reason = (
        f"[reload-guard] Blocked /reload-plugins: context is ~{tokens:,} tokens "
        f"(>= the {threshold:,}-token guard, TRDD-Z582IKIR F1). A reload breaks the "
        "prompt-cache prefix, forcing a full cache-CREATE (~1.25x) of the WHOLE "
        "context on the next turn instead of a cheap cache-read (~0.1x) — on a "
        "session this size that is a large one-off token tax. Shrink the context "
        "first (/janitor-compact-context, or /janitor-write-handoff then /clear), "
        "then retry /reload-plugins. Disable: "
        "CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_ENABLED=false. Move the "
        "threshold: CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_THRESHOLD."
    )
    sys.stdout.write(json.dumps(_block(reason)))
    return 0


if __name__ == "__main__":
    # Bare main() — side effects inside it so the module is import-safe (no
    # module-scope sys.exit), matching the other janitor UserPromptSubmit hooks.
    main()
