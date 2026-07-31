---
name: janitor-github-issues-monitor-on
description: Turn ON live GitHub reply monitoring for THIS project - you get notified when someone replies to an issue, PR, or comment that THIS project's Claude opened, on any repo. Keeps a per-project registry of what it opened so it watches only those threads, not your whole notification feed. Use when the user says "watch the github issues", "monitor replies to my issues", "notify me when someone answers", "turn on the issue monitor", "janitor-github-issues-monitor-on".
---

# GitHub issues monitor — ON

## Overview

Notifies you when someone replies to a GitHub thread **this project's Claude opened** —
an issue it filed, a PR it raised, a comment it left — on **any** repository.

The hard part is not polling GitHub; it is knowing which threads are *this project's*.
A shared `gh` identity means the human owner's own open-source traffic carries the same
`reason: author` / `reason: comment` as the agent's work. Measured on this account, a
reason-only filter emitted 6 threads of which 5 were the owner's personal activity on
pytorch, openinterpreter and Humanizer. So the filter is a **registry intersection**:
a thread is watched because this project opened it, never because GitHub thinks you
are interested.

```
[gh] Emasoft/ai-maestro-janitor#128 A ticket proven to be a FALSE POSITIVE… -- @someone: Fixed in a777cda [opened-here] :: https://github.com/…/issues/128#issuecomment-51044
```

One `gh api notifications` call per tick regardless of registry size — GitHub already
computes "someone replied to a thread you are in".

**Not the same as `/janitor-issues-watch-on`.** That one is a heartbeat detector that
reports NEW issues and comments on THIS project's own repo — "did anyone file
something?". This one asks "did anyone answer ME?", across every repo, and runs as a
persistent `Monitor`. They share no state; enabling one does not enable the other.

## Prerequisites

`gh` installed and authenticated (`gh auth status`). Without it the monitor emits one
`MONITOR DEGRADED` line and stays quiet — say so rather than reporting it as live.

Notifications must reach the account: GitHub only creates them for repos you are
subscribed to. Opening an issue auto-subscribes you, so anything this project files is
covered automatically.

## Instructions

1. **Baseline first, then look at the registry.** Baselining is what stops the first
   tick from dumping every already-read notification into context.

   ```bash
   POLL="${CLAUDE_PLUGIN_ROOT}/scripts/gh_issues_monitor/gh_notify_poll.py"
   uv run --script --quiet "$POLL" --baseline
   uv run --script --quiet "$POLL" --list
   ```

2. **Register anything already open that the hook has not seen.** The auto-register
   hook ships with the plugin (below), so from here on this is only needed for threads
   opened before the janitor was installed. Accepts a browser URL, an API URL, or
   `owner/repo#123`:

   ```bash
   uv run --script --quiet "$POLL" --note manual \
     --register https://github.com/owner/repo/issues/12 \
     --register owner/repo#34
   ```

   To seed from threads the authenticated user already authored on a repo — opt-in,
   because on a shared identity it cannot tell agent-authored from human-authored:

   ```bash
   uv run --script --quiet "$POLL" --backfill --repo owner/repo
   ```

3. **Start the monitor.** Use the `Monitor` tool with `persistent: true` and a
   `description` naming the project, so its notifications are self-explaining:

   ```bash
   while true; do
     uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/gh_issues_monitor/gh_notify_poll.py" \
       || echo "[gh] MONITOR DEGRADED -- poller exited $?"
     sleep 120
   done
   ```

   120 s is deliberate: GitHub advertises `X-Poll-Interval: 60` as the floor for this
   endpoint. Only stdout becomes a notification; the per-tick `poll ok: N threads`
   accounting goes to stderr, which lands in the monitor's output file instead.

4. **Record the task id so `/janitor-github-issues-monitor-off` can find it**, then
   report:

   ```bash
   uv run --script --quiet "$POLL" --state-dir   # the per-project state directory
   ```

   Write the id returned by `Monitor` into `<state-dir>/monitor-task-id.txt`.

5. **Report in three lines:** how many threads are registered, the poll interval, and —
   if `gh` is unauthenticated — that the monitor is NOT live.

## The auto-register hook

`scripts/gh_issues_monitor/gh_register_hook.py` is a **plugin** `PostToolUse(Bash)`
hook, declared in the janitor's own `hooks/hooks.json`. Nothing to install and nothing
to ask permission for: it is live wherever the janitor is, it never touches
`~/.claude/settings.json`, and it is removed with the plugin.

It fires on GitHub-**creating** commands only (`gh issue create`, `gh pr create`,
`gh issue comment`, `gh pr comment`, `gh pr review`, `gh api -X POST …/comments`) and
registers the URL those commands print, into the registry of whichever project was
current. Reading commands (`gh issue list`, `gh issue view`) deliberately do NOT
register — otherwise the monitor would watch every thread the agent merely read.

Because it runs in every project, its first gate is one regex over the command string,
before any file or subprocess work. A Bash call that is not a gh-creating command costs
that regex and nothing else.

## Honest limitations — state these, do not paper over them

- **The monitor is session-scoped.** `Monitor` runs until `TaskStop` or the session ends;
  it does not survive a Claude restart. Re-run this skill in the new session. The
  registry is on disk and does survive.
- A thread the project opened but that nobody replies to produces no notification — that
  is correct behaviour, not a fault.
- The registry cannot distinguish *which* agent opened a thread, only which project's
  cwd was current when the creating command ran.

## Output

Starts one persistent `Monitor`. Writes a per-project state directory under
`~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/gh-issues-monitor/<project-slug>/`
containing `registry.json` (threads to watch), `state.json` (poll cursor + dedupe map)
and `monitor-task-id.txt`. A registry left by the pre-port standalone skill under
`~/.claude/state/github-issues-monitor/<project-slug>/` is COPIED across on first use —
copied, not moved, so a rollback still finds it.

## Scope

Read-only against GitHub — it never comments, labels, closes, or edits anything. The
registry is per-project, so two projects watch disjoint thread sets. Disable with
`/janitor-github-issues-monitor-off`.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/gh_issues_monitor/gh_notify_poll.py` — one poll; also
  `--register`, `--list`, `--backfill`, `--baseline`, `--state-dir`.
- `${CLAUDE_PLUGIN_ROOT}/scripts/gh_issues_monitor/gh_register_hook.py` — the
  `PostToolUse(Bash)` auto-register hook.
- `GH_ISSUES_MONITOR_STATE_DIR` — override the state directory (used by the tests).
- `/janitor-issues-watch-on` — the OTHER GitHub watcher: new issues on this project's
  own repo, via the heartbeat.
