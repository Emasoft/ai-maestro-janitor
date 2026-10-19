---
trdd-id: R8DRK3DG
title: The daemon log sink must retain a release window before box 2 can be observed
column: todo
status: tasked
created: 2026-10-20T00:26:23+0200
updated: 2026-10-20T00:27:12+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-20T00:26:23+0200
parent-trdd: A70YJLXN
---

# The daemon log sink must retain a release window before box 2 can be observed

PREREQUISITE to TRDD-A70YJLXN's box 2, not part of it.

TRDD-A70YJLXN measures the publish-to-installed latency of a plugin release (box 2). To attribute an install to an actor, the janitor's own log lines for the release window must survive. On this host they do not, so the 2026-10-07 v3.8.11 investigation ended with the mechanism UNESTABLISHED: the janitor's own auto-update path was neither excluded nor implicated, because its log sink for that night is not retained.

TWO SEPARATE SINKS, TWO SEPARATE FIXES.

(1) The per-project logs: scripts/dispatch.py's _phase_log_retention prunes .janitor/logs/ files older than CLAUDE_PLUGIN_OPTION_LOG_RETENTION_DAYS (default 30) and .janitor/state/ files older than CLAUDE_PLUGIN_OPTION_STATE_RETENTION_DAYS (default 45). The plugin's own .janitor/logs/version-update.log and .janitor/state/last-run-version-update.ts are in those directories, so a 30-day window is the binding constraint for them.

(2) The machine-wide daemon log: scripts/daemon.py writes the version-update chore's lines to daemon.log in the plugin DATA global-state dir, and state.rotate_log_if_big rotates it by SIZE (1 MiB) to daemon.log.1, keeping exactly one previous generation. Measured on this host: daemon.log covered 2026-10-19 10:46:26 onward and daemon.log.1 covered 2026-10-18 12:34 to 2026-10-19 10:46. The version-update chore is not the only writer - the daemon logs every tick, so the file turns over in hours, and the 2026-10-07 night is long gone. The size-based rotation is the reason, and it is in THIS repo's code.

WHY THIS IS A PREREQUISITE AND NOT A NICE-TO-HAVE: a future release that is installed while the janitor's own log sink has already turned over produces exactly the same unresolvable investigation. The observation needs the sink to span the release-to-install window, which means the retention must exceed the time between a publish and the observation of its install.

ACCEPTANCE: the daemon log sink retains a window that provably covers a publish-to-install interval (the two retention knobs and the rotation generation count are each adequate for the window), and the janitor's version-update log lines for a given release window are still on disk after that window has elapsed. Measurable: release a version, let the observation window elapse, and read the janitor's own auto-update lines for that release.

CAREFUL: increasing the daemon log retention raises disk use on every machine with the plugin installed, and keeping more than one rotation generation multiplies that. The knob values are the user's configuration (CLAUDE_PLUGIN_OPTION_LOG_RETENTION_DAYS, CLAUDE_PLUGIN_OPTION_STATE_RETENTION_DAYS) as much as the code's, so the fix may be a documented recommendation rather than a default change - the user owns the choice, and this card must not silently change the default for every host.

## Approval log

- 2026-10-20T00:26:23+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
