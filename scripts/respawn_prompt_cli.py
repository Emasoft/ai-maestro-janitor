#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Turn a pending background agent's id into its RESPAWN PROMPT (TRDD-KTXZJC6E part B).

`pending_agents.py` has carried a fully-working respawn path since part A — the manifest
records a resolvable transcript handle for every spawned agent — but nothing outside its own
unit tests ever called it, so the fallback the docstrings describe could not fire. This is
that caller: the entry point a resume turn (human or the main Claude) runs the moment a
SendMessage-resume fails, since the library function itself is reachable only from Python.

    respawn_prompt_cli.py <agent-id>

Prints the full respawn prompt (idempotency preamble + the agent's original prompt, verbatim)
to stdout on success. Exits non-zero with a one-line diagnostic on stderr when the agent is
unknown or its transcript cannot be recovered — the caller must then say the job is
unrecoverable rather than invent a replacement prompt (see `pending_agents.respawn_prompt`).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import pending_agents  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print("usage: respawn_prompt_cli.py <agent-id>", file=sys.stderr)
        return 2
    agent_id = sys.argv[1].strip()
    entry = next((e for e in pending_agents.pending() if e.get("agentId") == agent_id), None)
    if entry is None:
        print(f"no pending-agent entry for {agent_id!r}", file=sys.stderr)
        return 1
    prompt = pending_agents.respawn_prompt_for(entry)
    if not prompt:
        print(f"no recoverable transcript for {agent_id!r} — the job is unrecoverable", file=sys.stderr)
        return 1
    print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
