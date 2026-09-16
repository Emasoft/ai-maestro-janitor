---
trdd-id: 3e1e9b12-e3bc-484c-b337-b208593cfe1d
title: Janitor actively enforces the TRDD process across compactions and resumes
column: complete
current-owner: amama
task-type: infra
release-via: none
created: 2026-05-30T22:32:23+0200
updated: 2026-06-13T15:46:17+0200
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

### ⏵ TRIAGE 2026-06-09 (stale-task #151 — verified current state)
Core feature DONE + committed (SessionStart hook f4b1c7e + report-to-trdd-drift detector
d3dc991, 14 tests). Derived-bug #1 below is **already fixed** (verified, was stale).
Genuine remainder = #2 (report-conversion — undirected/unrelated, defer to a directed
session) + #3 (rides the USER-gated publish). Nothing for the janitor to implement solo.

### NEXT ACTION / derived tasks
1. ✅ **DONE — verified 2026-06-09 (the 2026-05-30 "not yet fixed" note was stale).**
   `scripts/detectors/trdd-reminder.py` parses YAML frontmatter `status:` (v1) AND
   `column:` (v2) FIRST (`_FM_STATUS_RE`/`_FM_COLUMN_RE`, `_parse_trdd_state`), keeping the
   `**Status:**` bold line ONLY as a pre-frontmatter fallback. Confirmed by LIVE behavior —
   `[trdd-reminder]` correctly lists the v2 `column:`-based TRDDs with day-ages every
   heartbeat this session. No code change needed.
2. ✅ **DONE — triaged 2026-06-11 (user-directed "complete the pending tasks"). Both reports
   are FULLY-EXECUTED historical plans — no TRDD conversion needed; this citation closes the
   detector loop (the paths are now TRDD-referenced):**
   - `reports/audit/20260424_041237+0200-consolidated-fix-plan.md` — the v0.3.4-era fix plan
     for the SHELL implementation (`dispatch.sh`, `lib/dedupe.sh`, `*.sh` detectors). Its
     substrate no longer exists: the entire plugin was ported to Python (every detector/hook/
     lib in today's tree is the "Python port of X.sh"), and the named fixes (int coercion,
     dedupe locking, `CLAUDE_PLUGIN_ROOT` guards) are present in the Python successors.
     Disposition: EXECUTED/OBSOLETE — historical evidence only.
   - `reports/study-github-monitoring/CONSOLIDATED_PLAN.md` — the 10-agent study's Wave map
     (W1-W7). Implemented end-to-end by the Wave 2-37 task series; the named detectors all
     exist today (mcp-rugpull, ai-context-poisoning, typosquat-watcher, repo-trust-score,
     posture grade, pre-bash-safety compositional-exfil blocker, post-edit-safety
     sensitive-write watch, historical-cache-scan, …). Disposition: EXECUTED — historical
     evidence only.
3. Ship in the next janitor release so the hook + detector go live (rides the same
   USER-gated publish as the rest of the unpushed work).
4. ✅ **DECIDED 2026-06-11 — keep as-is (list on `resume`, full-inject only on `compact`).**
   Rationale: a resume keeps the full prior transcript — injecting every STATE block there
   would duplicate content the session already has and bloat context for zero information
   gain; the compact is the lossy event where injection is load-bearing. Revisit only if a
   real resume-after-long-gap incident shows the listing alone was insufficient.

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
