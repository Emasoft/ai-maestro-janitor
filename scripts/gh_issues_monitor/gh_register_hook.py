#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PostToolUse(Bash) hook: register GitHub threads THIS project's Claude opens.

`gh issue create` / `gh issue comment` / `gh pr create` / ... all print the
resulting github.com URL on stdout, so the URL is read out of `tool_response`
rather than reconstructed from the command line (a command carries a repo and
maybe a number, never the number of a thread it is about to create).

Gated on CREATING verbs. `gh issue list` and `gh issue view` also print URLs,
and registering those would watch every thread the agent merely READ -- the
opposite of "threads this project opened".

Contract: never block, never fail the tool, never write to stdout. Any
unexpected input is a silent no-op; a monitor that breaks `gh` is worse than a
monitor that misses a registration.

SHIPPED AS A PLUGIN HOOK, not installed into ~/.claude/settings.json. The
standalone skill this was ported from had to edit the user's global settings,
which meant a vendored transactional config editor, an "ask before installing"
step, and a restart-required caveat. It also baked an ABSOLUTE path to this file
into that settings entry — and inside a plugin that path is the EPHEMERAL
versioned cache dir, so the hook would have died silently at the next janitor
update, when the version dir is GC'd. A plugin hook has `${CLAUDE_PLUGIN_ROOT}`
resolved at load time, so it always points at the running version, and it is
removed cleanly on uninstall.

Because it now runs in EVERY project, the first gate is deliberately the
cheapest one available: a single regex over `tool_input.command`, before any
file or subprocess work. A Bash call that is not a gh-creating command costs one
regex.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

# A creating verb -- the command must MAKE a thread or a comment, not read one.
CREATE_VERB = re.compile(
    r"""\bgh\s+(?:
          (?:issue|pr)\s+(?:create|comment)
        | pr\s+review
        | (?:issue|pr)\s+(?:edit|reopen)
        | api\b(?=.*(?:-X\s*POST|--method\s+POST))(?=.*(?:/comments|/issues|/pulls))
    )""",
    re.VERBOSE,
)

THREAD_URL = re.compile(
    r"https?://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/(?:issues|pull|discussions)/\d+"
)


def response_text(payload) -> str:
    """Flatten a tool_response of unknown shape (str | dict | list) to text."""
    out: list[str] = []

    def walk(node) -> None:
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return "\n".join(out)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(event, dict):
        return 0

    command = ((event.get("tool_input") or {}).get("command")) or ""
    if not isinstance(command, str) or not CREATE_VERB.search(command):
        return 0

    urls = list(dict.fromkeys(THREAD_URL.findall(response_text(event.get("tool_response")))))
    if not urls:
        return 0

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gh_notify_poll.py")
    env = dict(os.environ)
    # The registry is per-project; the hook payload's cwd is the authority.
    cwd = event.get("cwd")
    if isinstance(cwd, str) and cwd:
        env.setdefault("CLAUDE_PROJECT_DIR", cwd)

    args = [sys.executable, script, "--note", "opened-here"]
    for url in urls:
        args += ["--register", url]
    try:
        subprocess.run(args, env=env, capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass  # a failed registration must never surface as a failed gh command
    return 0


if __name__ == "__main__":
    sys.exit(main())
