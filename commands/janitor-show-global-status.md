---
description: Show a whole-host HTML dashboard of EVERY running Claude Code instance and its janitor health — project, model, git, armed/active state, cron liveness, what each is waiting for, version, uncommitted files, wikimem page counts, last job/error, security-scan and PRRD status. Diagnoses each janitor (healthy / frozen / cron_dead / unarmed) from outside, renders one wide HTML table, and opens it in the default browser. Read-only. Trigger with /janitor-show-global-status or by asking to see the global fleet status / all running claude instances / which janitors are broken.
---

# /janitor-show-global-status

Run the backing script and surface its output verbatim to the user:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/fleet_status.py" $ARGUMENTS
```

It scans the whole host — every running `claude` process, mapped to its
`.janitor` project via its working directory — and for each diagnoses the
janitor's health from OUTSIDE the session, using the **transcript** as the
liveness signal (every heartbeat fire and every unit of work appends to the
session's `.jsonl`, so a stale transcript means the heartbeat is dead AND no work
is in flight — the one signal that is reliable AND works on old instances, unlike
`dispatch.log` which is silent on quiet fires). Diagnoses:

- **healthy** — transcript advancing (working OR heartbeat-firing). Never touched.
- **frozen** — stale transcript + a `rate-limited.flag` (the overnight-freeze
  shape). Recovery: the 7-rung ladder.
- **cron_dead** — stale transcript, no rate-limit. Recovery: re-arm.
- **unarmed** — a `disarmed.flag` is present (the user opted out). Sacrosanct.

It renders a single wide HTML table (page-level horizontal scroll — no nested
scrollbars), color-codes each row by health (red = broken, green = busy, grey =
disarmed), writes it to a temp file, and opens it in the default browser. Columns:
pid, project, model, git branch, github repo, armed, active, cron, waiting-for,
dispatch age, started, uptime, uncommitted, CI, gh-security, local-sec-scan, PRRD,
wikimem proj/local, last job, last error. The summary line carries the shared
facts: janitor version + up-to-date, daemon alive/down, last marketplace refresh,
global wikimem page count.

Flags:

```bash
# include CI conclusion, GitHub code-scanning alerts, and up-to-date (network; slower)
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/fleet_status.py" --ci
# print the plain-text summary instead of opening a browser (CI / headless)
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/fleet_status.py" --text
```

Surface the script's stdout (the one-line summary + the dashboard path) to the
user. Some columns are honestly `—` when not externally observable or not yet
instrumented (per-run security outcome, plugin-validation status, last-nudge,
next-job-in-queue, memgrep errors, last-push) — the in-page legend explains each.

Read-only — it never writes to any project, never injects into any session, never
changes plugin config. It only observes and renders.
