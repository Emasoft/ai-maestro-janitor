#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PreToolUse hook — deny a dependency CLI that writes agent-context files without consent.

Vector (Emasoft/ai-maestro-janitor#110, reported by the AgentlensPro Claude): a package such
as ``playwright`` ships a subcommand (``playwright init-agents``) that writes agent-context
files — ``.claude/agents/*.md``, ``.mcp.json``, and even ``.github/workflows/copilot-setup-steps.yml``
— into whatever repo it runs in, WITHOUT confirmation. That is a dependency-driven prompt-injection
vector: whoever controls the generated agents/prompts controls every future agent in the project.
Installing the package triggers nothing; the COMMAND is the only trigger, so this guard binds the
tool layer and stops an *agent* from silently running it (a human typing it is deliberate).

WHY THE JANITOR OWNS IT: the exposed population installs a CLI from npm and runs it in their own
projects — a repo-scoped hook reaches only the few who clone that one repo and protects no other
project on the machine, which is where the hazard is. The janitor is the only component installed
at USER scope, machine-wide, whose domain this is. AgentlensPro (a token/cost tool) deliberately
does NOT ship this — an observability installer must not carry unrelated security policy.

DEFAULT-ON (opt-out): the vector reaches every project, so the guard must protect by default.
  * Machine-wide off:  CLAUDE_PLUGIN_OPTION_AGENT_GENERATOR_GUARD_ENABLED=false
  * Per-project allow:  touch .janitor/state/allow-agent-generators   (a repo that genuinely
                        uses the generated agents says so, once, locally)

The two lessons the AgentlensPro reference impl already paid for:
  1. Match on TOKENS, never substrings — implemented in ``agent_context_writers`` (so the guard's
     own filename and a commit message that quotes the command are NOT blocked).
  2. An unreadable payload MUST allow — a guard that denied every Bash call because it could not
     parse its own stdin would be worse than the threat. Every failure path here returns 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import state  # noqa: E402
from agent_context_writers import AgentContextWriter, command_invokes_agent_writer  # noqa: E402

_ENABLE_KNOB = "CLAUDE_PLUGIN_OPTION_AGENT_GENERATOR_GUARD_ENABLED"
_OPT_OUT_FLAG = "allow-agent-generators"


def _project_opted_out() -> bool:
    """True iff THIS project placed the opt-out flag. Best-effort: any error means 'not opted
    out' so a stat failure can never silently DISABLE the guard."""
    try:
        return (state.state_dir() / _OPT_OUT_FLAG).exists()
    except Exception:
        return False


def _deny_reason(writer: AgentContextWriter) -> str:
    writes = ", ".join(writer.writes[:4])
    return (
        f"[agent-generator-guard] `{writer.package} {writer.subcommand}` writes agent-context "
        f"files ({writes}, …) into this project WITHOUT confirmation — a dependency-driven "
        "prompt-injection vector (an agent-generator being run by an AGENT, not you). Blocked "
        "by the ai-maestro-janitor. If you intend to generate these agents, run the command "
        "yourself outside the agent, or opt this project out with "
        f"`touch .janitor/state/{_OPT_OUT_FLAG}` (or set {_ENABLE_KNOB}=false to disable the "
        "guard machine-wide)."
    )


def main() -> int:
    if not state.is_truthy_env(_ENABLE_KNOB, True):
        return 0  # opted out machine-wide

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # LESSON 2: unreadable payload → allow, never block every Bash call
    if not isinstance(data, dict):
        return 0

    if data.get("tool_name", "") != "Bash":
        return 0
    tool_input = data.get("tool_input") or {}
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""

    writer = command_invokes_agent_writer(command or "")
    if writer is None:
        return 0  # silent allow — the vast majority of commands

    if _project_opted_out():
        return 0  # this repo genuinely uses the generated agents

    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": _deny_reason(writer),
        },
    }
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
