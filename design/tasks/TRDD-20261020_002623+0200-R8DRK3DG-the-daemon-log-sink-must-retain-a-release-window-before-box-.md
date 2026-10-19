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

(1) The per-project logs: scripts/dispatch.py's _phase_log_retention prunes .janitor/logs/ files older than CLAUDE_PLUGIN_OPTION_LOG_RETENTION_DAYS (default 30) and .janitor/state/ files older than CLAUDE_PLUGIN_OPTION_STATE_RETENTION_DAYS (default 45). CORRECTION — SINK (1) WAS MISDIAGNOSED, by a path distinction this card's first draft got wrong. The sweep does NOT reach the files it named: _sweep_old_files(state.log_dir(), ...) and state.state_dir() resolve under janitor_root() = project_root() / '.janitor', the PROJECT tree, while the plugin's own .janitor/logs/version-update.log and .janitor/state/last-run-version-update.ts live under the PLUGIN DATA dir, a different tree. So the 30-day and 45-day sweeps never touched them and no retention window binds them. What truncates them is something else this card has not identified. The measured evidence points at it: version-update.log spans 2026-09-13 11:55 to 16:00, about four hours, not thirty days, and a 30-day sweep would have left a 30-day span — so the cause is not a sweep. This sink is an OPEN QUESTION, not a diagnosed one, and identifying what truncates the per-chore log is part of this card's work.

(2) The machine-wide daemon log: scripts/daemon.py writes the version-update chore's lines to daemon.log in the plugin DATA global-state dir, and state.rotate_log_if_big rotates it by SIZE (1 MiB) to daemon.log.1, keeping exactly one previous generation. Measured on this host: daemon.log covered 2026-10-19 10:46:26 onward and daemon.log.1 covered 2026-10-18 12:34 to 2026-10-19 10:46. The version-update chore is not the only writer - the daemon logs every tick, so the file turns over quickly, and the 2026-10-07 night is long gone. The size-based rotation is the reason, and it is in THIS repo's code. TWO CORRECTIONS TO THIS PARAGRAPH, both from the review of fb1585be. First, the RETAINED WINDOW is what the numbers say, and they say about a DAY, not hours: daemon.log plus daemon.log.1 together cover 2026-10-18 12:34 to 2026-10-19 10:46, about 22 hours, and everything older is gone. Second, and more important for the fix: a size-based rotation at a FIXED byte threshold is NOT a configurable retention span at all - the window it retains depends on the write rate, and shrinks on a busier host. So 'raise the retention' does not apply to this sink: there is no knob for it. The only levers are the byte threshold and the number of generations kept.

WHY THIS IS A PREREQUISITE AND NOT A NICE-TO-HAVE: a future release that is installed while the janitor's own log sink has already turned over produces exactly the same unresolvable investigation. The observation needs the sink to span the release-to-install window, which means the retention must exceed the time between a publish and the observation of its install.

PREFERRED FIX (the review of fb1585be was right that this card led with the expensive option and never named the cheap one). THE PREFERRED FIX IS A DEDICATED, LOW-VOLUME LOG FOR THE VERSION-UPDATE CHORE, not a bigger daemon log. The daemon log is flooded: it records every tick, and the version-update chore's lines are a tiny fraction of it. Enlarging a flooded sink to preserve a handful of lines is the expensive way to solve it, and it costs every host disk. A separate file that only the version-update chore writes would survive the ordinary retention untouched, at negligible cost, and it is the direct answer to what A70YJLXN's investigation actually needed - the janitor's own auto-update lines for a given release window. The repo already has the precedent: per-chore logs exist for memory-guard and cold-cache-clear, and the version-update chore currently writes to the daemon-wide sink via state.log_line('daemon', ...). Splitting it out is the change. The alternatives, in order of cost: (a) a dedicated low-volume log (preferred, negligible cost, no change to daemon.log's size or generation count); (b) raising the byte threshold and keeping more generations of daemon.log (works, costs disk on every host, and the window stays rate-dependent); (c) reducing the daemon's per-tick logging (a much larger change, outside this card's scope). This card should implement (a), and only fall back to (b) if (a) is refused.

ACCEPTANCE: the daemon log sink retains a window that provably covers a publish-to-install interval (the two retention knobs and the rotation generation count are each adequate for the window), and the janitor's version-update log lines for a given release window are still on disk after that window has elapsed. THE GATE HAS A DETERMINISTIC PROXY AND A SLOW REAL-WORLD CONFIRMATION, and the first is what the card is actually verified against. The DETERMINISTIC PROXY: a test that asserts (i) the version-update chore's lines land in the dedicated log and NOT only in the daemon-wide sink, and (ii) that the dedicated log's retention covers a stated window - that the file survives a simulated age of the required window. The SLOW CONFIRMATION: release a version, let the observation window elapse, and read the janitor's own auto-update lines for that release. The card previously claimed the slow one was 'Measurable' while never naming an owner for the release or a threshold for the passing state, and it is weeks long - so it is recorded here as a confirmation, not as the gate.

CAREFUL: increasing the daemon log retention raises disk use on every machine with the plugin installed, and keeping more than one rotation generation multiplies that. The knob values are the user's configuration (CLAUDE_PLUGIN_OPTION_LOG_RETENTION_DAYS, CLAUDE_PLUGIN_OPTION_STATE_RETENTION_DAYS) as much as the code's, so the fix may be a documented recommendation rather than a default change - the user owns the choice, and this card must not silently change the default for every host. BUT THE TWO KNOBS HAVE DIFFERENT OWNERS AND DIFFERENT BLAST RADIOS, and the caution above treated them as one. CLAUDE_PLUGIN_OPTION_LOG_RETENTION_DAYS and CLAUDE_PLUGIN_OPTION_STATE_RETENTION_DAYS are read per PROJECT (the sweep runs in the project tree), so they are the user's per-installation configuration and raising them affects one project. The daemon log is MACHINE-WIDE and lives in the plugin DATA global-state dir, so its threshold and generation count are a DEFAULT IN THE CODE and a change to them lands for every host that has the plugin installed. So recommending the user raise a knob does nothing for the daemon log at all - there is no knob for that sink - and a code change to it is a fleet-wide change, which is exactly why the preferred fix above is the one that touches no fleet-wide default: a dedicated low-volume log, at negligible cost, changing nothing anyone else depends on.

## Approval log

- 2026-10-20T00:26:23+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
