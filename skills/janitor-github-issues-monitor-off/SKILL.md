---
name: janitor-github-issues-monitor-off
description: Turn OFF live GitHub reply monitoring for THIS project - stops notifying you when someone replies to issues, PRs, or comments this project's Claude opened. Use when the user says "stop watching the github issues", "turn off the issue monitor", "disable github notifications", "too many github notifications", "janitor-github-issues-monitor-off".
---

# GitHub issues monitor — OFF

## Overview

Stops the persistent monitor started by `/janitor-github-issues-monitor-on`. The registry
of threads this project opened is **kept** — it is a record of work, not a cache, and
re-enabling later resumes watching the same threads instead of losing them.

## Instructions

1. **Find the recorded task id.**

   ```bash
   POLL="${CLAUDE_PLUGIN_ROOT}/scripts/gh_issues_monitor/gh_notify_poll.py"
   STATE_DIR="$(uv run --script --quiet "$POLL" --state-dir)"
   cat "$STATE_DIR/monitor-task-id.txt" 2>/dev/null || echo "NO_RECORDED_ID"
   ```

2. **Stop it** with the `TaskStop` tool, passing that id as `task_id`.

   - `NO_RECORDED_ID`, or `TaskStop` reports it is not running → the monitor is already
     gone (most often because the session restarted, which ends it). Say that plainly
     rather than implying you stopped something.
   - If the id is missing but a monitor is clearly still firing, ask the user to check
     `/tasks` for the running monitor id and stop that one.

3. **Clear the stale id** so a later `off` does not point at a dead task:

   ```bash
   rm -f "$STATE_DIR/monitor-task-id.txt"
   ```

4. **Report one line:** monitoring is off for this project, and the registry of N watched
   threads is retained.

## Registration keeps running, and that is deliberate

Turning the monitor off leaves the auto-register hook in place, so threads this project
opens keep accumulating and are all waiting when monitoring is re-enabled.

There is no command to stop registering, because there is nothing installed to uninstall:
the hook ships inside the janitor plugin (`hooks/hooks.json`), not in the user's
`~/.claude/settings.json`. It writes only to this project's registry file, and only when
a `gh` **creating** command runs. If the user wants it gone entirely, that is a plugin
uninstall — say so rather than implying a per-project switch exists.

## Output

One line to the user. Stops the monitor task and removes
`<state-dir>/monitor-task-id.txt`. Leaves `registry.json` and `state.json` intact.

## Scope

ONLY this project's monitor. Does not touch other projects' registries or monitors, does
not change anything on GitHub, and does not remove the auto-register hook. Re-enable with
`/janitor-github-issues-monitor-on`.

## Resources

- `/janitor-github-issues-monitor-on` — the enabling half; documents the scripts.
- `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/gh-issues-monitor/<project-slug>/`
  — this project's state.
- `/janitor-issues-watch-off` — the OTHER GitHub watcher's off switch (new issues on this
  project's own repo, via the heartbeat). Stopping one does not stop the other.
