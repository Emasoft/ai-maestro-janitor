---
trdd-id: 6F7F7D60
title: Audit Claude Code v2.1.170-191 changelog for ai-maestro-janitor plugin compatibility
column: dev
created: 2026-06-25T20:48:22+0200
updated: 2026-06-25T20:48:22+0200
current-owner: claude-go-on-yourself
assignee: claude-go-on-yourself
priority: 3
severity: LOW
effort: M
labels: [changelog, compatibility, audit, docs]
task-type: docs
parent-trdd: null
npt: []
eht: []
blocked-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, lint, typecheck]
audit-requirements: []
review-requirements: []
impacts: []
attempts: 1
last-test-result: not-run
implementation-commits: []
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/65"]
---

# TRDD-6F7F7D60 — Audit Claude Code v2.1.170-191 changelog for plugin compatibility

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-25

**Current state:** Audit COMPLETE. The janitor runs on CC **2.1.191** (so every change
in the window is live) and is **compatible** with the v2.1.170-191 changes — none of the
breaking changes touch its code. The one shipped change from this audit is a defensive
doc-note recording the 2.1.183 heartbeat-safety assessment. Bundled in the same release:
the fix for issue #65 (detector false-positives, commit 256aa2e).

**Trigger:** USER asked to read every changelog update v2.1.170 → v2.1.191 and "update the
plugin accordingly", plus read the open GitHub issues.

**Evidence (full report):**
`reports/changelog-update/20260625_192443+0200-cc-v2.1.170-191-plugin-impact.md` — verbatim
changelog + per-surface plugin-impact analysis. 22 version numbers: 15 ship notes,
v2.1.177 is a real release with empty notes, and 171/180/182/184/188/189 were never released.

**The breaking-change audit — all CLEAR (verified, not assumed):**

| CC change | janitor exposure | verdict |
|---|---|---|
| 2.1.178 `TeamCreate`/`TeamDelete` removed, `team_name` ignored | grep across scripts/skills/agents/commands/hooks → ZERO hits; the janitor spawns via `Agent({subagent_type})`, not the teams API | safe |
| 2.1.191 comma-separated hook matchers now fire (dormant hooks wake) | all 5 `hooks.json` matchers use `\|` alternation, never commas — nothing was dormant | safe |
| 2.1.183 auto-mode blocks `git reset --hard`/`clean -fd`/etc | the strings appear only in `safe_delete.py` COMMENTS; the janitor never RUNS them (RULE 0) | safe |
| 2.1.183 scheduled/webhook deliveries can't auto-approve or set title | EMPIRICAL: on 2.1.191 this session the heartbeat fired + executed the stub dozens of times with no stall; it does not rely on the delivery auto-approving a pending prompt — its tools are policy-approved | safe |

**Newly-adoptable (opportunities, NOT breakage):** `sandbox.credentials` (2.1.187 — block
sandboxed commands reading credential files / secret env; relevant to this credential-guarding
security plugin); `Tool(param:value)` permission rules (2.1.178); `claude mcp login/logout`
and `/config key=value` doc mentions.

**NEXT ACTION:** none required for compatibility. This release ships (a) the 2.1.183
heartbeat-safety doc-note in `skills/janitor-arm`, (b) the #65 fix (256aa2e). The
`sandbox.credentials` surfacing is a deferred polish follow-up (below).

**SUPERSEDED — do NOT carry forward:** the initial hypothesis that 2.1.183 might break the
CronCreate heartbeat — DISPROVEN empirically (the heartbeat demonstrably works on 2.1.191).

## Why this audit reached "compatible"

The USER reported "big changes to claude code, impacting the whole plugins and extensions
ecosystem." After reading every v2.1.170-191 note and cross-checking the janitor's code, the
honest finding is that the janitor's design already uses the patterns the breaking changes
left alone (`\|`-alternation hook matchers, `Agent({subagent_type})` spawns, no destructive
git, a heartbeat that does not depend on delivery-auto-approval). Manufacturing code changes
to "look updated" would violate the don't-over-engineer rule; the correct response to a
compatible audit is to RECORD it (this TRDD) and ship only the genuine improvements.

## Changes shipped in this release

1. **Defensive doc-note** in `skills/janitor-arm` "Known limitations (Claude Code platform)":
   records that CC 2.1.183 reclassified scheduled-task / webhook deliveries as task-notifications
   (they can no longer auto-approve a pending action or set the session title in auto mode), and
   that the heartbeat was verified UNAFFECTED on 2.1.191 because it does not rely on
   delivery-auto-approval. This is future-maintainer clarity for the next CC-version audit —
   the section already documents the durable→session-only and data-dir load-source quirks.
2. **Issue #65 fix** (bundled, commit 256aa2e): the `trdd-state-reconciliation` detector no
   longer false-flags terminal-column TRDDs nor mis-attributes commits to code-tag / script-name
   tokens. The shared citation-shape parsing now lives in `scripts/lib/trdd_common.py`.

## Deferred follow-ups (NOT done here; optional, need design judgment)

- **Surface `sandbox.credentials` (CC 2.1.187)** in the janitor's security guidance (the
  `janitor-security-agent` advice or the `remote-credentials` detector's mitigation hint). A
  genuine stewardship improvement for a credential-guarding security plugin, but optional and
  it needs a placement decision — captured here so the opportunity is not lost.
- A periodic "audit the latest CC changelog window for plugin-ecosystem impact" chore could
  formalize this; the next version-audit then has this TRDD as its baseline.

## Other open issues triaged (separate concerns; not in this release)

- **#66** PreCompact handoff git-sections show '(unavailable)' when the repo is a subdir of
  `$CLAUDE_PROJECT_DIR` — real bug in the handoff hook (#239). Good next-fix.
- **#63** report-to-trdd detector false-flags memory-subconscious abstain/no-op reports — detector FP.
- **#64** memory-consolidate re-spawns a ~226k-token agent every cadence on categorically-
  unmergeable candidates — real efficiency bug; warrants its own TRDD.
- **#62** memory-system discoverability for a fresh session — UX/design, larger.
- **#52** cross-project wikimem visibility — coordination/feature, larger.

## Notes and lessons learned
