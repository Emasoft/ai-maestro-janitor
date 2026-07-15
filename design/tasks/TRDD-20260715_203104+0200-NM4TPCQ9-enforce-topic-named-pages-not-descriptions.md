---
trdd-id: NM4TPCQ9
title: Enforce topic-named wikimem pages — agents create description-named pages, the spec is ignored
column: backburner
created: 2026-07-15T20:31:04+0200
updated: 2026-07-15T21:55:25+0200
current-owner: janitor-session
task-type: feature
scope: project
severity: major
labels: [wikimem, memory-write, subconscious-agent, agent-compliance, naming]
parent-trdd: 87RKBYJ8
relevant-rules: []
---

# Enforce topic-named wikimem pages (not memory-description names)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-15

**The problem (USER, 2026-07-15) — it is COMPLIANCE, not the spec.** The specs already state the rule
(one page = one topic; a page's name is its topic — see `wikimem-atom-block-properties.md` `^9K3ZP7QW`
+ `^TPCNM5RK`). But the **AGENTS do not follow it.** Observed repeatedly: an agent creates a wikimem
page whose title is a MEMORY'S DESCRIPTION — a long, specific, useless filename like
`implementation-of-duckdb-ingestion-of-otel-logs.md` — instead of putting that atom into a broad TOPIC
page like `agents-tracing.md` or `claude-telemetry-and-logging.md`. One memory becomes one orphan page;
the corpus fills with description-named singletons that no future atom ever joins, defeating the whole
point of topic pages (collecting many atoms about one subject).

**Why the spec alone doesn't fix it:** the rule lives in reference pages agents don't reliably read at
CREATION time. Enforcement must be at the two points where a page is actually born:

### Prong 1 — WRITE-TIME PREVENTION (main Claude + subagents, via `janitor-memory-write`)
The memory-CREATION skill must make the topic-naming rule LOUD and example-driven, at the exact step an
agent names a new page:
- Before creating ANY new page: **`memgrep recall` for an existing TOPIC page** and add the atom
  THERE. (This rule already exists as `wikimem-atom-block-properties-harvest-and-status.md [^1]` "atoms
  go into EXISTING topic pages; new file only if none exists" — it is not being enforced.)
- Create a new page ONLY when no topic page exists, and **name it by the broad TOPIC**, never by the
  one memory. Give the USER's concrete good/bad examples verbatim in the skill:
  - BAD: `implementation-of-duckdb-ingestion-of-otel-logs.md` (a sentence describing one fact)
  - GOOD: `agents-tracing.md`, `claude-telemetry-and-logging.md` (a broad topic many atoms share)
- The tell to reject: **a filename that reads like a description of a single memory** (long, hyphen-
  joined verb-phrase naming a specific implementation/event) rather than a short topic noun.

### Prong 2 — CORRECTIVE (subconscious agent, a new duty in TRDD-87RKBYJ8)
Even with prevention, existing/legacy description-named pages must be repaired. Add a duty: **detect a
page whose title is a memory-DESCRIPTION not a TOPIC**, then either (a) if a correct topic page exists,
MERGE the atom into it and retire the singleton (redirect `[[link]]`s + ref-count footnotes per the
move rule), or (b) if the topic legitimately has no page, RENAME the page to its broad topic. This
extends existing duties 10/14/15 (merge-same-topic / relocate-off-topic / create-topic-page) with the
NAMING axis.

## NEXT ACTION
1. **DONE 2026-07-15 (Prong 1):** `janitor-memory-write/SKILL.md` (naming rule at step 3 + checklist
   line) + `references/atom-authoring.md` (naming rule at the schema's `name:` field), both with the
   USER's BAD/GOOD examples verbatim. Same commit also synced the `desc` ≤200-prose spec
   (AP2X9A0H item a) into `atom-authoring.md` + `wikimem-model.md`. Deploys with the next publish.
2. TRDD-87RKBYJ8: add the corrective duty (detect description-named page → merge/rename to topic) to
   group E/G and to the duty verification.
3. Consider a cheap heuristic the subconscious agent (or a detector) can flag: a page filename with
   ≥4 hyphen-joined tokens AND a leading verb/gerund (`implementation-of-`, `how-to-`, `fix-for-`) is a
   likely description-name — SURFACE it for review (never auto-rename without the verify_* gate).
4. Publish (skill + memgrep + any detector live in the plugin → release + cache update to deploy, per
   `macos-keychain.md [^2]` / TRDD-EQJPPZ2L: repo ≠ deployed).

## Verification
- A fresh agent asked to save a specific memory (e.g. "duckdb ingestion of otel logs") recalls the
  existing topic page and adds an atom there — or, if none exists, creates `agents-tracing.md`-style
  TOPIC page, NOT a `implementation-of-…`-style description page.
- The subconscious agent, run on a deliberately description-named page, merges/renames it to its topic
  with `verify_*` proving no knowledge lost.
- Skill + plugin tests + publish gates green.

## Notes and lessons learned
