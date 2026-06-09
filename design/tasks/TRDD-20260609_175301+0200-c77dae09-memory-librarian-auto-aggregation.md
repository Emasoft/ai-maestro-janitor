---
trdd-id: c77dae09-fccb-4e91-b3cf-1534492f0896
title: Memory librarian — background auto-aggregation of per-topic memory pages with linked tangents
column: backburner
created: 2026-06-09T17:53:01+0200
updated: 2026-06-09T17:53:01+0200
current-owner: janitor-dev-session
assignee: janitor-dev-session
priority: 4
severity: MEDIUM
effort: L
labels: [memory-system, janitor, librarian, aggregation, background, memgrep]
task-type: feature
parent-trdd: TRDD-ce195129
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, integration]
runtime-targets: [macos, linux]
external-refs: []
---

# TRDD-c77dae09 — Memory librarian: background auto-aggregation

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-09

**Status:** captured from a USER directive 2026-06-09; NOT started. This is the
"librarian" half of the memory system — the background organizer that keeps the
note corpus rational over time, complementing the existing authoring (the
`# Memory` harness directive + `janitor-memory-write` skill) and recall
(`markdown-memory-recall.md` rule + `janitor-memory-recall` skill + `memgrep`).

**NEXT ACTION when picked up:** design the background librarian pass (cadence,
the conscious-decision boundary, the aggregation/link algorithm) as a concrete
spec, then implement. Read TRDD-ce195129 (memory-system-design) first for the
existing corpus shape + memgrep capabilities.

## USER directive (verbatim intent, 2026-06-09)

> The memory system requires some auto-aggregation running in background. It is
> like a wiki, so each page should contain everything about one argument
> [topic]. But how to move the memories from one page to another is a process
> that requires conscious decision by the agent. And in background it can
> aggregate multiple `.md` files into single `.md` files about a specific
> argument [topic]. Other pages touching the same argument tangentially do not
> need to duplicate the info, but to link the main page of the argument. This
> process of re-allocation and aggregation must be automated and run in
> background. This is why memory is the job of the janitor, that as a librarian
> classifies and organizes the library of memory in a rational way.

## The model — a wiki, curated by a background librarian

1. **One topic per page.** Each memory page is the canonical, complete page for
   ONE topic (argument) — everything known about that topic lives there. This is
   the wiki invariant.
2. **Tangential mentions LINK, never duplicate.** A page about topic B that
   touches topic A tangentially must `[[link]]` to A's canonical page rather than
   copy A's facts. Single source of truth per topic; links carry the rest.
3. **Aggregation is automated + background.** The janitor periodically scans the
   corpus, clusters notes by topic, and **merges multiple `.md` files about the
   same topic into one canonical page** — collapsing scattered fragments into the
   wiki page for that topic.
4. **Re-allocation (moving a memory between pages) is a CONSCIOUS decision.** The
   background job does NOT blindly move facts. Deciding that a fact belongs on
   page X rather than page Y — or that two notes are "the same topic" — requires
   agent reasoning (LLM judgment), not a mechanical rule. So the background pass
   is an *automated cadence that invokes conscious per-decision reasoning*, not a
   dumb text-merger.
5. **Janitor-as-librarian.** This is why memory organization is the janitor's
   job: like a librarian, it classifies and shelves the library rationally, on a
   schedule, in the background — without the user or the main session having to
   stop and curate.

## The load-bearing tension to resolve in design

"Aggregation must be automated and background" **vs** "moving memories requires
conscious agent decision." Resolution sketch (to validate during design): the
background cadence (janitor heartbeat / daemon tick) is the *trigger*; the actual
classify/merge/relocate decisions are made by an **agent reasoning pass** (Opus,
or the LLM-Externalizer for cheap bounded clustering), which:
- proposes a topic-clustering of the current notes (which files are "the same
  topic"),
- for each cluster, proposes a canonical page + a merge (dedupe facts, keep the
  richest phrasing, preserve symptom-indexed `description`s for recall),
- rewrites tangential duplications in OTHER pages as `[[links]]` to the canonical
  page,
- updates `MEMORY.md` (the loaded index) + any `memory-index.md`,
- NEVER silently drops a fact — a merge is a union, like the corpus-distillation
  "default to MERGE/union" rule.

The "conscious decision" requirement means the merge step is agent-authored, not
a regex; the "background/automated" requirement means it is *scheduled* and
*unattended*, not user-initiated.

## Open design questions (decide during the design column)

- **Cadence + trigger:** janitor heartbeat (per-session, project-scoped) vs the
  global daemon (machine-wide)? Memory dirs are per-project
  (`~/.claude/projects/<slug>/memory/`), so likely a per-project detector that
  runs at a low cadence (e.g. every N hours, or when note count grows past a
  threshold) and is debounced like the slow detectors.
- **Who reasons:** spawn an Opus agent for the merge decisions, or use
  LLM-Externalizer (`cluster_synonyms` / `scan_folder`) for the cheap clustering
  pre-pass + Opus only for the actual merges? Tiered: cheap clustering →
  expensive merge only on real clusters.
- **memgrep's role:** `memgrep` already has `recall` / `index` / `links` /
  `fact` subcommands and link-semijoin. The librarian likely drives off
  `memgrep index` (topic/tag extraction) + `memgrep links` (backlink graph) to
  PROPOSE clusters cheaply, then hands candidates to the reasoning pass. Possibly
  add a `memgrep cluster` or `memgrep aggregate --dry-run` that emits a proposed
  merge plan for an agent to approve/execute.
- **Safety:** RULE 0 — never lose a memory. Every merge is git-committed (or
  `.trashcan/`-backed) BEFORE the source files are removed; a merge is a union,
  reversible. The background pass must be idempotent (re-running produces no
  churn once the corpus is already rational) and must not fight the authoring
  directive (don't undo a note the user just wrote).
- **Conscious boundary:** which moves are safe to auto-apply vs which need to be
  PROPOSED to the next session for confirmation (a `memory-reorg-proposed.md`
  the heartbeat surfaces, like the other janitor nudges)? Likely: auto-apply
  obvious same-topic merges; PROPOSE cross-topic reallocations.

## Relationship to the rest of the memory system

- **Authoring** — `# Memory` harness directive + `janitor-memory-write` skill
  (writes one fact per note, symptom-indexed `description`).
- **Recall** — `rules/markdown-memory-recall.md` + `janitor-memory-recall` skill
  + `memgrep recall` (symptom-ranked, precision-first).
- **Organization (THIS TRDD)** — the background librarian that keeps the corpus a
  rational wiki over time.
- **Tool** — `memgrep` (TRDD-d151fe52) is the engine all three lean on.

This TRDD is the missing third leg (organization) of the memory system.
