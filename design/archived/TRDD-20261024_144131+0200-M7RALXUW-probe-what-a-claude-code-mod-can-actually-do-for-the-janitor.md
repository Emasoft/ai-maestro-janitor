---
trdd-id: M7RALXUW
title: Probe what a Claude Code mod can actually do for the janitor - built-ins, idle wake, agent spawn
column: complete
status: archived
created: 2026-10-24T14:41:31+0200
updated: 2026-10-24T15:01:41+0200
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
- 2026-10-24T15:01:41+0200 — COMPLETE by main-agent@ai-maestro-janitor. every probe has a recorded verdict with evidence.

## Results (2026-10-24)

Report (gitignored): reports/mods-feasibility/20261024_145813+0200-mods-probes.md. Throwaway mod in samples_dev/mods-probe/ (gitignored). Run on Claude Code 2.1.310, interactive, cwd outside the repo, janitor and context-harness disabled for that process (verified in its debug log). Main agent re-read the key probe.log lines.
P1 clear PASS (session.end reason clear, new session id). P1 model PASS (next turn ran on the new model) but /model also saves the model as the user's default, so a janitor must restore it. P1 reload-plugins runs exactly like a typed one, but it did not re-import the unchanged mod's own module; picking up a NEW janitor version through it is untested.
P2a PASS: a timer plus $.prompt.submit started a turn on an idle session. P2b: after a user Esc the submit resolves to {drop} at +2 s and +30 s (it does not reject) until the user's next input. P2c NOT-RUN: no 429 occurred and none was provoked. P2d PASS: a CronCreate fire reaches the mod's prompt.submit hook before the turn, with origin scheduled-trigger.
P3 PASS: $.agent.spawn from a timer started a background agent with zero parent turns, but the hand-back arrives as a peer prompt.submit and starts one parent turn unless the mod drops it (dropping untested). Also: a mod can call CronCreate and CronList through $.tool.call with no model turn. Open follow-ups: behaviour after a 429; whether reload-plugins picks up an updated installed mod; dropping a cron or peer prompt.

## Acceptance checklist

- [x] P1 (clear, reload-plugins, model) each has a verdict with raw log evidence
- [x] P2 (idle wake, after Esc, after 429, cron origin) each has PASS, FAIL or NOT-RUN with evidence or a reason
- [x] P3 (agent spawn without a model turn) has a verdict with evidence
- [x] The probe ran in a separate process that did not touch this repo's janitor state or the user's settings.json
