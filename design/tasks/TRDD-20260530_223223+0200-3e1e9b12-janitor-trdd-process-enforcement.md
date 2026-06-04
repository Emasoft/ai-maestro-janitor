---
trdd-id: 3e1e9b12-e3bc-484c-b337-b208593cfe1d
title: Janitor actively enforces the TRDD process across compactions and resumes
status: in-progress
created: 2026-05-30T22:32:23+0200
updated: 2026-05-30T22:32:23+0200
---

# TRDD-3e1e9b12-e3bc-484c-b337-b208593cfe1d — Janitor actively enforces the TRDD process across compactions and resumes

**Filename:** `design/tasks/TRDD-20260530_223223+0200-3e1e9b12-janitor-trdd-process-enforcement.md`
**Tracked in:** this repo (design/tasks/ is git-tracked)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-05-30

> Born from a concrete failure (recorded in TRDD-32acd15f POST-MORTEM): a compacted
> session re-derived a plan that the TRDD AND a consolidated report already held,
> because nothing ACTIVELY forced a read. A rule is passive; this feature makes the
> janitor ENFORCE the discipline.

### Current state (all committed to this repo; ship on next publish)
- ✅ **Global rule** `~/.claude/rules/trdd-design-tasks.md` — added the mandatory
  `## STATE` head-section convention, a Compaction-safety clause (a summary is not
  a substitute; STATE block wins), and the **report→TRDD conversion** rule
  (decisions in gitignored reports must be written into a TRDD). *(Lives in
  `~/.claude`, not this repo.)*
- ✅ **SessionStart hook** `scripts/hooks/on-session-start-trdd-state.py`
  (commit `f4b1c7e`) — on `source=compact` injects each in-progress TRDD's full
  `## STATE` block as AUTHORITATIVE/SUPERSEDING the summary; lists them on other
  sources; silent when none. Registered as a 2nd SessionStart hook in
  `hooks/hooks.json`. 7 tests.
- ✅ **Detector** `scripts/detectors/report-to-trdd-drift.py` (commit `d3dc991`) —
  6h-cadence heartbeat detector; reminds (once/interval until converted) when a
  decision/synthesis-named report under `reports/` is referenced by NO TRDD. Roster
  entry in `dispatch.py`. 7 tests. Verified live: skips the now-cited
  CONSOLIDATED.md, surfaces 2 genuinely-unconverted reports.

### Why a hook + a detector (not just a rule, not a Write/Stop hook)
- Rule = passive baseline (ignorable — and was). Hook + detector = active.
- SessionStart `compact` is the exact moment context was lost → inject the truth there.
- Reports are often written by SUBAGENTS → a folder-scanning DETECTOR catches them;
  a main-session Write/Stop hook would miss them. And it must be a REMINDER, not a
  hard block (data-only reports are not decisions → a block would false-positive).

### Gotcha
The running janitor is the INSTALLED cache version (0.5.0); these repo changes
activate only after a publish + install (or `/reload-plugins` for plugin-scoped
`hooks/hooks.json`). Until then they are repo-only.

### NEXT ACTION / derived tasks
1. **`trdd-reminder.py` parses the OLD `**Status:**` bold line, not frontmatter
   `status:`** — so it likely no-ops on every current (frontmatter) TRDD. Migrate it
   to frontmatter parsing (the new hook/detector already do). Derived bug found
   2026-05-30; not yet fixed.
2. Review the 2 reports the detector flagged
   (`reports/audit/…-consolidated-fix-plan.md`, `reports/study-github-monitoring/CONSOLIDATED_PLAN.md`)
   — convert each decision into a TRDD, or mark obsolete.
3. Ship in the next janitor release so the hook + detector go live.
4. Consider whether the hook should inject (not just list) on `source=resume` too.

## Problem

TRDDs and consolidated reports are the durable planning artifacts, but across a
context compaction they were being ignored: the lossy summary replaced them as the
de-facto memory and even promoted wrong conclusions. A passive rule cannot prevent
this. The janitor — already the home for global, all-project hooks/detectors — is
the right place to ACTIVELY enforce: surface the authoritative TRDD STATE on every
resume/compact, and nag when a decision report never became a TRDD.

## Design

Layered enforcement:

1. **Convention (passive baseline)** — the global TRDD rule mandates a `## STATE`
   head block (single source of truth, supersedes the chronological body, lists a
   SUPERSEDED set + the durable reports to read) and the report→TRDD conversion.
2. **SessionStart hook (active, on resume/compact)** — injects in-progress TRDD
   STATE blocks; strongest on `compact`.
3. **Heartbeat detector (active, mid-session)** — surfaces decision reports that no
   TRDD references, so a floating decision is caught within a cadence.

All project-scoped; silent for projects that don't use TRDDs; never touch
user/global scope.

## Out of scope
- A hard BLOCK on Stop/Write (too aggressive — most reports are evidence, not decisions).
- Auto-generating TRDD content from a report (judgment call — the agent converts).
- Migrating `trdd-reminder.py` to frontmatter (recorded as derived task #1).
