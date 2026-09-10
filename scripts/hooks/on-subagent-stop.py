#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""SubagentStop hook — clear a finished background agent (TRDD-82OP4EN9 W1).

Counterpart of on-subagent-start.py: removes the agent's entry from the
pending-agents manifest so the resume directive only lists agents that are
plausibly still in flight.

Payload reality (hook reference, verified 2026-07-08): SubagentStop's
DOCUMENTED schema carries no ``agent_id`` (only session_id/transcript_path/
cwd/permission_mode/stop_hook_active). We read ``agent_id`` best-effort — some
builds do send it — and NO-OP when absent. That asymmetry is safe by design:
the manifest's time sweep (pending_agents.MAX_AGE_S) is the guaranteed cleanup
for entries whose Stop carried no id, and an over-listed agent in a resume
directive is harmless ONLY when it finished normally (a ping just restates its
result). It is NOT harmless for one a session deliberately ``TaskStop``-killed
(TRDD-PGN5XSHA) — this hook is never invoked by a kill (there is no janitor
TaskStop hook), so the resume directive is worded advisory rather than
imperative to cover that gap; see ``pending_agents.mark_stopped``.

A hook fault must NEVER block a subagent stop: everything is wrapped and the
hook ALWAYS exits 0 with empty output (never a "block" decision).
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
    cwd_fallback = ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
        if isinstance(payload, dict):
            agent_id = str(payload.get("agent_id", "") or "")
            cwd_fallback = str(payload.get("cwd", "") or "")
    except (ValueError, TypeError):
        return 0
    if not agent_id.strip():
        # Documented schema has no id — the manifest's age sweep handles it.
        return 0

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if not plugin_root:
        return 0
    sys.path.insert(0, str(Path(plugin_root) / "scripts"))
    try:
        from lib import pending_agents, state  # noqa: E402 - local package, not PyPI
    except Exception:  # noqa: BLE001 - a broken lib must not block the stop
        return 0

    if cwd_fallback and not os.environ.get("CLAUDE_PROJECT_DIR", "").strip():
        state.set_project_dir_override(cwd_fallback)

    try:
        state.init_state()
        pending_agents.remove(agent_id)
    except Exception as exc:  # noqa: BLE001 - fail-open, always exit 0
        try:
            state.log_line("subagent-stop", f"manifest remove failed: {exc}")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    # Bare main() — side effects live inside it so the module is import-safe,
    # matching the other janitor hooks.
    main()
