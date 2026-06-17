---
trdd-id: 54b25d7e-ba33-49e5-b7e5-add0a54f0c8c
title: Wikimem editor — librarian that aggregates, splits to overview+in-depth, and harmonizes like a Wikipedia editor
column: design
created: 2026-06-17T02:35:58+0200
updated: 2026-06-17T02:35:58+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 3
severity: MEDIUM
effort: XL
labels: [memory, wikimem, librarian, editorial, automation, configurable]
task-type: feature
parent-trdd: TRDD-c77dae09
npt: [TRDD-b3eae1cd]
relevant-rules: []
release-via: publish
test-requirements: [unit]
external-refs: []
---

# TRDD-54b25d7e — Wikimem editor librarian (aggregate / split / harmonize)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-17

**USER directive (2026-06-17), verbatim intent:** the memory-reorg scope is
BIGGER than a broken-link/page-shape cleanup. The janitor must act like a
**Wikipedia editor** over the memory corpus:

1. **AGGREGATE** — merge memories about similar concepts / related elements
   into a single page.
2. **SPLIT** — break an oversized page into many smaller **in-depth** pages,
   **linked by the original page which REMAINS as an OVERVIEW** (the Wikipedia
   model: an overview/hub article + specific in-depth sub-articles).
3. **HARMONIZE + VERIFY** — when multiple agents wrote different, sometimes
   conflicting memories, reconcile them: act like Wikipedia editors who
   harmonize and fact-check.
4. **ANY editorial improvement** is in scope — general copy-editing, dedup,
   re-tiering (hub/aspect/component), link hygiene.

Three hard constraints from the USER:
- **Maximally SCRIPT-automated** — it is complex, so push everything mechanical
  into scripts; reserve the AGENT only for the genuinely-editorial *judgment*.
- **Low-frequency cadence** — run NOT every heartbeat but on a **configurable**
  interval that won't burn tokens (the heavy editorial pass is rare).
- **Everything configurable** — cadence, thresholds, scopes, on/off, dry-run.

**NEXT ACTION:** design the script/agent split (below), land the NPT
(TRDD-b3eae1cd heuristic fix) FIRST, then build the scriptable mechanical
transforms, then the low-frequency agent-editorial pass. This is XL — phase it.

**Load-bearing context:** today's `memory-librarian` detector only SURFACES
candidates to `memory-reorg-proposed.md` (separation of powers: janitor
surfaces, an agent applies — see [[reference]] in the memory-system rule). A
2026-06-16 run produced **56 "conflict" candidates that were ~all FALSE
POSITIVES** (keyword-overlap, not real contradictions) — that is exactly why
the NPT (b3eae1cd: gate conflict/aggregation on subject-entity + cohesion, not
keyword overlap) MUST land before any auto-apply, or the editor will merge/
flag unrelated notes. Do NOT auto-apply on the current heuristic.

## Why (the problem)

Multiple agents (orchestrator, sub-agents, fleet plugins) write memories into
the shared corpus independently. Over time this produces: duplicate notes on
one subject, oversized pages that should be an overview + sub-pages, conflicting
facts (one agent's note supersedes another's but both survive), and link rot.
The wikimem model (hub/aspect/component tiers, bidirectional link law —
TRDD-bc16d602) DEFINES the target shape; nothing yet MAINTAINS the corpus toward
it. This TRDD builds the maintainer: the "editor".

## Design — the script/agent split (the load-bearing decision)

The USER wants max automation. The split principle: **scripts do every
MECHANICAL transform; the agent makes only the EDITORIAL judgment calls.**

### A. SCRIPTABLE (zero-agent, runs in the detector / a CLI tool)
- Page-shape conformance: add the mandatory `## Notes and lessons learned`
  section; backfill `ocd`/`lmd`; fix footnote ref/def mismatches.
- Link hygiene: add the reciprocal for a one-sided `[[link]]` (the link law);
  repair broken-link **slug typos** (hyphen↔underscore, `.md` suffix) by
  fuzzy-matching to an existing note; leave genuine forward-refs alone.
- Dedup-identical: collapse byte-identical / near-identical duplicate notes.
- Oversize DETECTION: flag pages over a configurable size for split.
- MEMORY.md index sync; `memgrep reindex`.
- SPLIT EXECUTION (once an agent supplies the decomposition boundaries):
  mechanically carve the in-depth sub-pages, leave the overview/hub with the
  summary + down-links, wire the bidirectional links.
- MERGE EXECUTION (once an agent confirms an aggregation set): concatenate +
  de-dup into the target page, demote superseded statements to `[^N]` lessons
  (never delete — the correction protocol), update back-links.

### B. AGENT-REQUIRED (the editorial judgment — rare, low-frequency)
- **Aggregation boundary:** do these N notes truly cover ONE subject-entity?
  (Gated by the b3eae1cd cohesion heuristic — the NPT.)
- **Split decomposition:** how to break an oversized page into an overview +
  which in-depth sub-pages (the conceptual cut).
- **Conflict harmonization:** which of two conflicting facts is CURRENT vs
  SUPERSEDED; author the clean current fact + the dated `[^N]` correction
  lesson (the WHY).
- General copy-editorial improvement.

The agent pass runs on the **low-frequency cadence**, reads the script-prepared
candidate bundle (so it spends tokens only on judgment, not on
discovery/mechanics), emits decisions, and the scripts execute them.

## Configuration (everything configurable — `CLAUDE_PLUGIN_OPTION_*`)
- `WIKIMEM_EDITOR_ENABLED` (on/off).
- `WIKIMEM_EDITOR_CADENCE_S` — low-frequency interval for the heavy editorial
  pass (default: daily-ish, NOT per-heartbeat).
- `WIKIMEM_EDITOR_MAX_PAGE_BYTES` — oversize→split threshold.
- `WIKIMEM_EDITOR_COHESION_MIN` — aggregation cohesion floor (b3eae1cd).
- `WIKIMEM_EDITOR_SCOPES` — which of LOCAL/PROJECT/USER to maintain.
- `WIKIMEM_EDITOR_APPLY` — dry-run (propose only, today's behavior) vs apply.

## Phasing (XL — do NOT do in one pass)
1. **NPT first:** land TRDD-b3eae1cd (subject-entity + cohesion gating) so
   aggregation/conflict detection stops false-positiving (56:0 today).
2. **Scriptable mechanical transforms** (set A) behind `APPLY=dry-run` first,
   with tests; flip to apply for the SAFE ones (link reciprocals, page-shape,
   slug-typo links) — these need no judgment.
3. **Low-frequency agent-editorial pass** (set B): the cadence scheduler +
   the candidate-bundle preprocessor + the apply-decisions executor.
4. **Split/merge execution** wired to agent decisions.

## Constraints / gotchas
- PROJECT scope is git-tracked + PUSHED + shared — apply there cautiously;
  LOCAL is machine-private. Never auto-apply across scopes (a LOCAL and a
  PROJECT note are different layers — the librarian never merges across scopes).
- Corrections NEVER delete a superseded fact — demote to a dated `[^N]` lesson
  with the WHY (the memory correction protocol).
- This must stay token-frugal (Phase-1 token-meter mindset): the heavy pass is
  RARE and the agent only sees the pre-digested candidate bundle.

## Approval log
- 2026-06-17T02:35:58+0200 — Authored from the USER's 2026-06-17 directive
  expanding the memory-reorg scope to a full Wikipedia-editor model. Tier-0
  in-scope janitor design task (docs/design, own scope). NPT on TRDD-b3eae1cd.
