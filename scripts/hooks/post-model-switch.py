#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PostModelSwitch hook — stamp the model switch so the external clear can act on it.

WHY (TRDD-GK35MOXU; USER directive 2026-09-01): a model (or effort) switch kills the
prompt-cache prefix OUTRIGHT — the next turn pays a full re-cache. Claude Code 2.1.251 added
this hook event, giving a FIRST-PARTY signal at the instant of the switch; before it the
janitor could only poll `agentlenspro statusline-history raw` and diff the two newest rows
(`external_clear.prefix_invalidated`, which stays as the pre-2.1.251 fallback).

This hook does ONE thing: advance `.janitor/state/model-switch-acked.ts` (a generation int,
the exact `reload-acked.ts` shape). `external_clear.reload_invalidated` treats an unprocessed
fresh ack as a dead prefix and the fire path consumes it — all the TRDD-2F3I2P18 semantics
(tri-state, probe-never-consumes, freshness window) apply unchanged because it IS the same
mechanism, just a third stamp name.

It deliberately does NOT fire the watcher itself: the daemon/heartbeat owns the clear
decision (vetoes, cooldown, pane resolution); a hook that cleared directly would bypass every
one of them. PreModelSwitch is deliberately unused — the janitor reacts to a switch, it never
vetoes the user's choice.

Safety: a hook fault must NEVER break the model switch. Everything exits 0.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    try:
        raw = sys.stdin.read()
    except OSError:
        raw = ""
    cwd_fallback = ""
    if raw.strip() and not os.environ.get("CLAUDE_PROJECT_DIR", "").strip():
        try:
            payload = json.loads(raw)
            cwd_fallback = str(payload.get("cwd", "") or "") if isinstance(payload, dict) else ""
        except (ValueError, TypeError):
            cwd_fallback = ""

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if not plugin_root:
        print("[post-model-switch] CLAUDE_PLUGIN_ROOT unset; skipping", file=sys.stderr)
        return 0

    sys.path.insert(0, str(Path(plugin_root) / "scripts"))
    try:
        from lib import state  # noqa: E402 - local package, not PyPI
    except Exception as exc:  # noqa: BLE001 -- a hook fault must never break the switch
        print(f"[post-model-switch] state import failed: {exc}", file=sys.stderr)
        return 0
    if cwd_fallback:
        state.set_project_dir_override(cwd_fallback)

    try:
        sd = state.state_dir()
        sd.mkdir(parents=True, exist_ok=True)
        stamp = sd / "model-switch-acked.ts"
        try:
            gen = int(stamp.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            gen = 0
        state.atomic_write(stamp, str(gen + 1))
        # Attribution for the log only — the payload schema is the harness's; read defensively.
        detail = ""
        try:
            p = json.loads(raw) if raw.strip() else {}
            if isinstance(p, dict):
                detail = " ".join(
                    f"{k}={p[k]}" for k in ("previous_model", "new_model", "model") if k in p
                )
        except (ValueError, TypeError):
            pass
        state.log_line("external-clear", f"model switch acked (gen {gen + 1}) {detail}".rstrip())
    except Exception as exc:  # noqa: BLE001
        print(f"[post-model-switch] stamp failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
