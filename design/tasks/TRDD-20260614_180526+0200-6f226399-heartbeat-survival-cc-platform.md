---
trdd-id: 6f226399-1e6f-4d25-8132-f6ab8c332548
title: Heartbeat survival on Claude Code 2.1.x — durable downgrade + PLUGIN_DATA load-source instability
column: backburner
created: 2026-06-14T18:05:26+0200
updated: 2026-07-04T05:14:00+0200
current-owner: ai-maestro-janitor
task-type: infra
priority: 4
severity: MEDIUM
effort: M
labels: [heartbeat, survival, cron, plugin-data, upstream]
release-via: publish
test-requirements: []
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/23"]
---

# Heartbeat survival on Claude Code 2.1.x — durable downgrade + PLUGIN_DATA load-source instability

## ⏵ STATE — READ FIRST

**Verified 2026-06-14 on CC 2.1.177 (issue #23, originally reported on 2.1.173):
both findings still reproduce.** The SAFE, shippable parts are DONE (v0.8.7);
two parts remain OPEN and need a decision, not autonomous code.

- **DONE (v0.8.7):** `janitor-arm` skill now reads back durability and reports
  session-only HONESTLY (no false "survives restarts"); both limitations
  documented in `skills/janitor-arm/references/janitor-architecture.md#known-limitations`
  and the SKILL.md.
- **OPEN — Finding 1 (upstream):** `CronCreate(durable:true)` is silently
  downgraded to session-only (verified: `~/.claude/scheduled_tasks.json` absent,
  `CronList` shows `[session-only]`). The janitor CANNOT make it durable — this
  is a Claude Code runtime gap. NEXT: escalate upstream to Anthropic/Claude Code
  if it persists past 2.1.177. Mitigation already in place: SessionStart re-arm
  (heartbeat re-armed each session; only a mid-session restart is exposed).
- **OPEN — Finding 2 (USER DECISION):** `${CLAUDE_PLUGIN_DATA}` resolves to
  `…-inline` vs `…-ai-maestro-plugins` by load source, orphaning stub dirs and
  leaving an armed cron on a stale path. The report's fix — anchor the stub at a
  source-independent fixed path (`~/.claude/plugins/data/ai-maestro-janitor/`,
  no suffix) — **conflicts with the project principle to prefer
  `${CLAUDE_PLUGIN_DATA}`** (the suffixed dir is the only one the harness backs
  up, preserves across updates, and purges on uninstall). This is a deliberate
  trade-off for the USER, NOT an autonomous change to the survival path.

**2026-07-04 board-reconciliation (TRDD-GB3Z9U9J) — absorbed TRDD-3ab0397e (now superseded by this TRDD):** both covered the same issue-#23 pair of findings; this file is the more current (knows the v0.8.7 state, verified on CC 2.1.177). Unique fact folded in from the absorbed TRDD: its 2026-06-11 issue-#23 triage had already RECORDED a maintainer direction for Finding 2 — REJECT the fixed unofficial data-dir path; implement (2a) stub-path drift-detect (record the armed cron's stub path at arm time, e.g. `<state>/heartbeat-stub-path.txt`; on mismatch with the live `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` emit the renew marker to silently re-arm) + (2b) orphan data-dir retirement on re-arm (byte-identical sibling stubs → safe-delete/tombstone). That direction matches option 1 below; the USER call on making it final remains open.

## The decision the USER must make (Finding 2)

Pick one:

1. **Keep `${CLAUDE_PLUGIN_DATA}` (status quo + self-correct).** Accept that
   re-arm self-corrects the active cron and orphan dirs are harmless; optionally
   add a SessionStart drift-detector that auto-rearms when the live
   `${CLAUDE_PLUGIN_DATA}` differs from the active cron's baked path, and an
   orphan-dir cleanup on re-arm. Pro: stays on the backed-up/preserved/purged
   official path. Con: orphans accumulate; a load-source flip mid-life needs a
   re-arm to repoint.
2. **Anchor at a fixed janitor-controlled path** (`~/.claude/plugins/data/ai-maestro-janitor/dispatcher-stub.py`).
   Pro: cron target never moves across load-source changes. Con: unofficial
   folder — backups may miss it and purge-on-uninstall orphans it; contradicts
   the prefer-`${CLAUDE_PLUGIN_DATA}` principle. Would need a migration + re-arm.

Recommendation (janitor): option 1 + a SessionStart drift-auto-rearm — keeps the
official path AND closes the stale-path gap without an unofficial folder. But it
is the USER's call because it touches both the survival path and the stated
data-dir principle.

## Acceptance criteria (when resumed)

- A decision recorded for Finding 2; the chosen mitigation implemented + tested
  (drift-detector test, or migration test) without breaking arming.
- Finding 1 escalated upstream (or confirmed fixed on a newer CC) and the
  Known-limitations doc updated to match reality.

## Durable artifacts

- Issue #23 (the full report + verified current-state response).
- `skills/janitor-arm/references/janitor-architecture.md#known-limitations`.
