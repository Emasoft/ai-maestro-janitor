---
name: janitor-show-global-status
description: Show a whole-host HTML dashboard of EVERY running Claude Code instance and its janitor health — project, model, git, armed/active state, cron liveness, what each is waiting for, version, uncommitted files, wikimem page counts, last job/error, security-scan and PRRD status. Diagnoses each janitor (healthy / frozen / cron_dead / unarmed) from outside, renders one wide HTML table, and opens it in the default browser. Read-only. Use when the user asks to see the global fleet status / all running claude instances / which janitors are broken, or when you need a machine-wide view of every session's janitor health.
---

# Janitor show-global-status

## Overview

The whole-host fleet dashboard. It scans every running `claude` process, maps each to its
`.janitor` project via its working directory, and diagnoses that janitor's health from OUTSIDE the
session using the **transcript** as the liveness signal (every heartbeat fire and unit of work
appends to the session's `.jsonl`, so a stale transcript means the heartbeat is dead AND no work is
in flight — the one signal that is reliable AND works on old instances, unlike `dispatch.log` which
is silent on quiet fires).

Diagnoses:
- **healthy** — transcript advancing (working OR heartbeat-firing). Never touched.
- **frozen** — stale transcript + a `rate-limited.flag` (the overnight-freeze shape). Recovery: the 7-rung ladder.
- **cron_dead** — stale transcript, no rate-limit. Recovery: re-arm.
- **unarmed** — a `disarmed.flag` is present (the user opted out). Sacrosanct.

## When to use

- The user asks to see the fleet / all running claude instances / which janitors are broken / the global status.
- You want a machine-wide health view before diagnosing a stuck or burning session.

## Instructions

Run the backing script and surface its stdout (the one-line summary + the dashboard path) verbatim.
Pass whatever flags the user asked for (none by default):

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/fleet_status.py"
# include CI conclusion, GitHub code-scanning alerts, and up-to-date (network; slower):
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/fleet_status.py" --ci
# print the plain-text summary instead of opening a browser (CI / headless):
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/fleet_status.py" --text
```

It renders a single wide HTML table (page-level horizontal scroll — no nested scrollbars),
color-codes each row by health (red = broken, green = busy, grey = disarmed), writes it to a temp
file, and opens it in the default browser. Columns: pid, project, model, git branch, github repo,
armed, active, cron, waiting-for, dispatch age, started, uptime, uncommitted, CI, gh-security,
local-sec-scan, PRRD, wikimem proj/local, last job, last error. The summary line carries the shared
facts: janitor version + up-to-date, daemon alive/down, last marketplace refresh, global wikimem
page count. Some columns are honestly `—` when not externally observable or not yet instrumented —
the in-page legend explains each.

## Scope

Read-only — it never writes to any project, never injects into any session, never changes plugin
config. It only observes and renders.
