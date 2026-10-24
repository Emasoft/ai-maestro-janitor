---
trdd-id: M7RALXUW
title: Probe what a Claude Code mod can actually do for the janitor - built-ins, idle wake, agent spawn
column: dev
status: tasked
created: 2026-10-24T14:41:31+0200
updated: 2026-10-24T14:41:31+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-24T14:41:31+0200
---

# Probe what a Claude Code mod can actually do for the janitor - built-ins, idle wake, agent spawn

USER, 2026-10-24, verbatim: "Yes, file a card and run the three mod probes with a throwaway mod."

Source: reports/mods-feasibility/20261024_141905+0200-mods-feasibility-report.md section 7 (gitignored).

P1 - can a mod run built-ins through $.command.run: clear, reload-plugins, model.
P2 - can a mod wake a session with $.prompt.submit from a $.clock timer: (a) idle, (b) after a user Esc, (c) after a 429 (only if one occurs naturally; never provoke one). Also: is a cron-fired prompt visible to prompt.submit hooks.
P3 - can a mod spawn a background agent without a model turn.

Method: a throwaway mod under samples_dev/mods-probe/, loaded with claude --plugin-dir in a SEPARATE session (never this one, since P1 clears it), driven from a tmux test harness; the mod logs every call and result to a file. Done when each probe has a recorded PASS, FAIL or NOT-RUN with the raw log line as evidence.

## Approval log

- 2026-10-24T14:41:31+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
