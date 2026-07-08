#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""SubagentStart hook — record a spawned background agent (TRDD-82OP4EN9 W1).

WHY: the pending-agents manifest is what lets a night-run session
deterministically resume its BACKGROUND agents after a session-limit /
rate-limit kill — dispatch's resume phases read it and list each entry as a
SendMessage-resume line. Without this record the main session can only *hope*
to remember its forks (2026-07-08: four forks died at the 5h cap and needed a
manual "resume").

Payload contract (hook reference, verified 2026-07-08): SubagentStart carries
``agent_id`` (plus session_id/transcript_path/cwd/permission_mode). There is
NO description field in the documented schema — we store the best label
present (``agent_type``/``description`` when a build supplies one, else "")
and key everything on the id.

A hook fault must NEVER break an agent spawn: everything is wrapped and the
hook ALWAYS exits 0 (matching every other janitor hook's discipline).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    raw = ""
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
    except (OSError, ValueError):
        raw = ""

    agent_id = ""
    desc = ""
    cwd_fallback = ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
        if isinstance(payload, dict):
            agent_id = str(payload.get("agent_id", "") or "")
            # Not in the documented schema — tolerated best-effort extras only.
            desc = str(payload.get("agent_type", "") or payload.get("description", "") or "")
            cwd_fallback = str(payload.get("cwd", "") or "")
    except (ValueError, TypeError):
        return 0
    if not agent_id.strip():
        return 0

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if not plugin_root:
        return 0
    # scripts/ (not scripts/lib/) on sys.path + package import — the idiom every
    # janitor hook uses so the CPV validator recognises the local-sibling import.
    sys.path.insert(0, str(Path(plugin_root) / "scripts"))
    try:
        from lib import pending_agents, state  # noqa: E402 - local package, not PyPI
    except Exception:  # noqa: BLE001 - a broken lib must not break the spawn
        return 0

    # Guarded cwd fallback (never clobber the reserved env var session-wide).
    if cwd_fallback and not os.environ.get("CLAUDE_PROJECT_DIR", "").strip():
        state.set_project_dir_override(cwd_fallback)

    try:
        state.init_state()
        pending_agents.add(agent_id, desc)
    except Exception as exc:  # noqa: BLE001 - fail-open, always exit 0
        try:
            state.log_line("subagent-start", f"manifest add failed: {exc}")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    # Bare main() — side effects live inside it so the module is import-safe,
    # matching the other janitor hooks.
    main()
