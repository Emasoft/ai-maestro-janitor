---
trdd-id: 82OP4EN9
title: Night-continuity hardening — maintenance mode must guarantee unattended all-night work at minimum token cost
column: dev
created: 2026-07-08T14:08:50+0200
updated: 2026-07-08T14:08:50+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 0
severity: CRITICAL
effort: M
labels: [heartbeat, maintenance-mode, continuity, token-economy]
task-type: feature
parent-trdd: null
npt: []
eht: []
blocked-by: []
release-via: publish
test-requirements: [unit, integration, lint]
review-requirements: []
runtime-targets: [macos]
impacts: [install-script]
implementation-commits: []
---

# Night-continuity hardening (TRDD-82OP4EN9)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-08

**USER HARD REQUIREMENT (2026-07-08, verbatim intent):** "if the agents stop
midnight I'm ruined … the maintenance mode must ensure continuity at all costs
in the user absence … make this work reliably and without consuming much
tokens." Maintenance mode = the night posture: minimum tokens, only the
strictly-necessary survival chores; full chores return only when maintenance
is switched off.

**Current state:** design approved, implementation fanning out (2 worktree forks).

**NEXT ACTION:** land W1-W4 below, merge, full gate, then publish + arm
maintenance (publish/arm = USER-confirmed step).

## Verified baseline (dispatch.py main(), read 2026-07-08)

Maintenance fires already run, IN ORDER, before the 1.5b early-return:
mode-resolve (maintenance WINS over global disarm) → paused → user-presence →
log-retention → **rate-limit recovery [janitor-resume]** → **post-compact
resume** → **heartbeat auto-renew** → **keep-going nudge** → early-return
(no detectors, no daemon). Cost baseline (fork-D report
reports/janitor-health-audit/20260708_012013+0200-heartbeat-token-review.md):
~945 tok input/fire (fat 3,779-char baked prompt), ~87k-eq cache_read/fire,
one >5-min-drift fire ≈ 1.09M-eq miss.

## Work items

- **W1 — pending-agents resume manifest (deterministic fork resume).**
  New hooks (SubagentStart/SubagentStop in hooks/hooks.json) maintain
  `.janitor/state/pending-agents.json`: Start appends {agentId, description,
  ts}; Stop removes. `_phase_rate_limit_recovery` + `_phase_compact_resume`
  extend the emitted directive: "resume EACH of these background agents via
  SendMessage: <id> — <desc>". A resume ping to an already-complete agent is
  harmless (verified empirically 2026-07-08: completed fork restated its
  result and stopped). Manifest bounded: entries carry ts; sweep >7d.
- **W2 — cron-liveness nudge at SessionStart.** on-session-start emits (once
  per session, additionalContext) when `.janitor/state/heartbeat-armed-at.ts`
  exists: "verify the janitor heartbeat exists via CronList; if missing
  (durable-downgrade/expiry), silently re-run /janitor-arm". Closes the
  CC-restart-eats-the-cron hole without needing session tools in hooks.
- **W3 — slim cron prompt + rule-file marker protocol + zero-output contract**
  (fork-D proposals 1+2). New shipped rule `rules/janitor-heartbeat-protocol.md`
  (installed by the existing rules_installer glob into every session's cached
  prefix at 0.1×) carrying the FULL marker-handling protocol + the zero-output
  contract (silent fire → empty reply; drift lines quoted verbatim, ≤2 lines
  commentary). janitor-arm SKILL bakes a ~300-char prompt: marker
  `[janitor-heartbeat]`, stub path, "apply the janitor-heartbeat-protocol
  rule; fall back to surfacing stdout verbatim if the rule is absent".
  Fallback keeps old-cron compatibility; no legacy code paths in dispatch.
- **W4 — keep-going nudge carries the work pointer.** The nudge line
  references `.janitor/state/resume-directive.txt` and the W1 manifest count
  when non-empty, so an idle-but-armed session is re-pointed at the ACTUAL
  pending work every fire, not just told "continue".

## Out of scope (explicit)

- OAuth rotation / daemon revive (global disarm is a USER flag; rotation
  remains opt-in — window exhaustion = stall-until-reset + auto-resume).
- Hard-restart rungs enablement (separate USER flag, TRDD-56d24c02).
- Publishing + arming (USER-confirmed step after merge).

## Approval log

- 2026-07-08T14:08:50+0200 — USER directive (hard requirement) authorizes
  implementation "no matter what"; Tier 0 (own scope, project-internal).
