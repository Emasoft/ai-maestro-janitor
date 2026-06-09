---
trdd-id: c77dae09-fccb-4e91-b3cf-1534492f0896
title: Memory librarian — background auto-aggregation of per-topic memory pages with linked tangents
column: dev
created: 2026-06-09T17:53:01+0200
updated: 2026-06-09T21:01:24+0200
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

**Status (2026-06-09):** PARTIALLY built (column: dev). The SAFE, surface-only
first version LANDED — commit **6575e04**: `scripts/detectors/memory-librarian.py`,
a project-scoped 6h-cadence detector that uses memgrep to find same-topic
AGGREGATION + CONFLICT candidates and SURFACES them (writes
`<memdir>/memory-reorg-proposed.md` + a `[memory-librarian]` heartbeat nudge).
**ZERO corpus mutation — verified live** (notes byte-identical before/after a run;
17 tests; the no-mutation test is the load-bearing safety guarantee). This is the
"detect + surface" half of the librarian's mandate (the janitor surfaces; agents
resolve).

**DEFERRED (the open-question, memory-MUTATING half):** the agent-reasoned
**auto-merge/aggregation** (cluster → canonical page, move notes with their `[^N]`
lessons, rewrite tangents as `[[links]]`) is NOT built — it needs the conscious
agent-reasoning pass (Opus/LLM-Externalizer on a cadence) + the careful design of
the open questions below (cadence, conscious boundary, RULE-0 git-backed merges).
Left for deliberate design, not a background dispatch.

This is the "librarian" half of the memory system — the background organizer that
keeps the note corpus rational over time, complementing the existing authoring
(the `# Memory` harness directive + `janitor-memory-write` skill) and recall
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

---

## ADDENDUM — 2026-06-09 (USER): separation of powers + non-destructive correction + read-the-notes rule

A second USER directive refined the maintenance model. Two roles, strictly
separated, plus a correction protocol and a reading rule.

### Separation of powers (janitor vs single agent)

| | **Janitor** (background librarian) | **Single agent** (a session) |
|---|---|---|
| **CAN** | reorganize / aggregate notes into one per-topic wiki page; **detect contradictions & conflicting memories and SURFACE them** to agents | **create** new memories (authoring); **correct** false memories / memories with wrong facts |
| **CANNOT** | **create** new memories; **correct** memories (fix a fact) | **reorganize** the memories |

The load-bearing rule: **the janitor never edits memory CONTENT.** It only
(a) reorganizes structure (aggregation, linking) and (b) *finds and surfaces*
contradictions — it raises a flag, an agent resolves it. The agent never
reorganizes; it only creates and corrects content. Conflict detection (janitor)
and conflict resolution (agent) are split so a background pass never silently
rewrites a fact, and a single session never fights the librarian's structure.

> Implementation note: the janitor's conflict-surfacing is a new detector /
> librarian-pass output — e.g. a `memory-conflicts-surfaced.md` (or a heartbeat
> `[memory-conflict]` nudge) listing pairs of notes that assert contradictory
> facts about the same topic, for the next agent session to reconcile. memgrep
> can PROPOSE the candidate conflicting pairs (same topic/tag, opposing
> assertions); the janitor surfaces, never resolves.

### The 2-step non-destructive correction protocol (AGENT mandate)

When a new discovery **contradicts** an existing memory, the agent MUST change
the memory — but non-disruptively, in exactly two steps:

1. **Clean the fact in place.** Replace the wrong statement in the memory body
   with the correct one, so the page's record of the FACTS is always clean and
   true (the body is the current truth — no "we used to think X" clutter inline).
2. **Preserve the error as a lesson — the WHY is the point.** The error that
   caused the false memory / false conclusion / wrong solution-plan is recorded
   as a **numbered entry** in a **`## Notes and lessons learned`** section at the
   **bottom** of the page, and the corrected fact is **connected to it via a
   standard-markdown footnote reference** (`[^N]`). **The load-bearing content of
   a lesson is the WHY** — *why* the previous statement was wrong, *why* the plan
   failed: the root cause, not merely "this was wrong". A lesson without a WHY is
   useless — it cannot stop the next repeat. Lessons thereby accrue in their
   **category page** (the topic's wiki page), so all lessons-learned for a topic
   are collected in one findable place.

This mirrors the existing CLAUDE.md **Bug Autopsy** directive (every fixed bug
becomes a guardrail) and RULE 0 (never lose information): the *fact* is corrected,
the *error* is never deleted — it is demoted to a linked footnote so future
readers don't repeat it.

### Page shape (target)

```markdown
---
name: <topic-slug>
description: "<symptom surface for recall>"
---
<clean, current FACTS about this topic — corrected in place>.
The widget retries 3× then fails.[^3]
... links to tangential topics: see [[other-topic]] ...

## Notes and lessons learned
[^3]: 2026-06-09 — earlier this said "retries 5×"; wrong, the cap is 3 (the
  config key was misread as `max_attempts` when it is `max_retries`). Lesson:
  verify the constant against the source, not the variable name. (was: TRDD-xyz)
```

### NEW RULE (USER-mandated) — read-the-notes-too

> When an agent reads ANY memory, it MUST also read **all the notes / footnotes
> attached to it** (every `[N]` / `[^N]` reference and the `## Notes and lessons
> learned` entries they point to). Reading a memory's facts without its lessons
> is incomplete — the lessons are *why* the facts are the way they are and *what
> errors not to repeat*.

This rule must be added, on implementation, to **both** halves of the recall
surface:
- `rules/markdown-memory-recall.md` (the recall protocol rule), and
- the `janitor-memory-recall` skill,
- and reflected back to the harness `# Memory` directive's recall guidance.

It pairs with the existing "recall before acting" discipline: recall the page,
then read it WHOLE (facts + its linked lessons), then act.

### memgrep auto-resolves footnotes (makes the read-notes rule FREE) — cross-ref TRDD-d151fe52

So the agent never burns tokens chasing references, `memgrep` MUST — when it
returns a memory (`recall`, `fact`, `get` of a note) — **automatically resolve
and inline the full text of every footnote that memory references**, returning
the memory body **AND** all its `[^N]` lessons-learned **in one result**. One
`memgrep recall` yields the complete picture (facts + every linked WHY); the
agent issues **no** second search for the references.

- **Syntax = standard markdown footnotes.** Reference `[^N]` in the body;
  definition `[^N]: <the WHY>` under `## Notes and lessons learned`. This is the
  convention agents already know (nothing new to memorize) AND memgrep's existing
  markdown parser already understands it — so resolution is a parse, not a new
  format.
- **Scope:** resolve footnotes defined **within the same note** by default. A
  footnote may also point at another page's lesson (cross-page `[[topic]]#^N`)
  — for those, return the link, optionally `--expand-cross-page` to inline.
- **Implementation:** a new memgrep behavior on the memory subcommands (likely a
  default-on `--with-notes` that the `recall`/`fact`/`get` paths honor); the
  footnote block is appended to each returned note, clearly delimited, so the
  caller sees body-then-lessons. Belongs in memgrep's memory layer (TRDD-d151fe52).

#### Output format — token-economical by default (USER, 2026-06-09)

memgrep RENDERS the resolved notes minimally — storage format ≠ render format:

- **On disk** the note uses standard markdown footnotes (`[^N]` ref, `[^N]: …`
  def under `## Notes and lessons learned`) — what the agent writes, what
  memgrep parses.
- **In the returned output** memgrep normalizes to the **strict-necessary**
  shape: inline references render as a **bare number `[9]`**, and after the
  memory body it appends the list:

  ```
  [9] - <lesson WHY text>.
  [10] - <lesson WHY text>.
  ```

  No on-disk hashes, no reference tags, no footnote-definition machinery — only
  the number + the content.
- **Metadata STRIPPED by default.** A note's own metadata (frontmatter, keys,
  class, type, origin ids, etc.) is NOT emitted. An **opt-in flag**
  (e.g. `--full-notes`) restores the full form:

  ```
  [9] - [metadata, keys, class, …] <lesson text>.
  ```
- **URLs / references / image links are ALWAYS kept** — even in the default
  minimal form. Any URL, cross-reference, or image link (`![..](..)`,
  `[..](http..)`, bare URLs) present in a note's text is load-bearing and MUST be
  reported; only the note's *metadata* is strippable, never its links/resources.

Rationale: the agent gets every lesson's WHY + every resource it points to, at
minimum token cost — the metadata (which the agent rarely needs at read time) is
the only thing dropped, and only until `--full-notes` asks for it.

### Per-element datetimes (OCD + LMD) + notes are first-class searchable elements (USER, 2026-06-09)

**The background reorg breaks "page mtime = memory age."** Because the librarian
MOVES memories between wiki pages in the background, a page's filesystem
last-modified time reflects only the librarian's last reorg — NOT when any
specific memory in it was created or changed. So dating must move DOWN to the
element:

- **Every memory element carries its own two datetimes in metadata:**
  - **OCD — Original Creation Date** (when the memory/lesson was first written),
  - **LMD — Last Modified Date** (when its content last changed).
  These are intrinsic to the element and survive moves between pages.
- **Uniform metadata across ALL memory elements.** A fact-memory and each
  **note/lesson-learned share the SAME metadata schema** — OCD, LMD, type, class,
  keys, origin, etc. A note/lesson is a **first-class memory element**, not a
  second-class footnote: it carries full metadata (stored in the `[…]` prefix
  that the render strips by default — see the output-format section). The
  page-level `created:`/`updated:` frontmatter stays, but it is now a derived/
  coarse marker, not the source of truth for any individual memory's age.

**memgrep searches/filters/sorts notes-and-lessons too** (not just fact bodies):

- **Search within lessons** — query among the notes/lessons-learned, including a
  **lessons-ONLY** mode (e.g. `memgrep recall --only-notes "<symptom>"` /
  `memgrep notes <query>`) to find a specific lesson without the fact bodies.
- **Datetime-range filter** — "all lessons learned between datetime A and B"
  (e.g. `--since`/`--until` over OCD or LMD), enabled precisely because each
  element now has its own OCD/LMD.
- **Configurable sort** — sort/order results by OCD, LMD, relevance, topic, etc.
  The sort key is an option, not hard-coded (e.g. `--sort lmd|ocd|score`,
  `--order asc|desc`).

This makes the lessons corpus a queryable ledger: "what did I learn last week",
"every lesson about <topic> newest-first", "the lesson I wrote on <date>" all
become single memgrep calls. Belongs in memgrep's memory + where-DSL layers
(TRDD-d151fe52) — it already has `--where` boolean filtering and a markdown date
sense to build on.

### Notes follow their memory on a move + the indexer + git (USER, 2026-06-09)

**Atomic co-movement — a memory and its notes are inseparable.** Because each
memory is LINKED to its notes/lessons, when the librarian relocates a memory to
another wiki page, **all of its referenced notes move WITH it**, appended to the
destination page's `## Notes & Lessons Learned` section. The memory never gets
divorced from the lessons that explain it. (A merge is therefore: move the
fact-memory into the canonical page's body AND append its `[^N]` lessons into
that page's lessons section, renumbering as needed.)

**Mandatory section — every memory `.md` has `## Notes & Lessons Learned`** at
its bottom, even if currently empty: it is the standing landing zone so an
incoming memory's notes always have a home, and so the corpus shape is uniform
(every page = body + lessons section).

**The indexer must be FAST + intelligently structured (not a per-query scan).**
The corpus is thousands of `.md` files that the janitor **continuously
aggregates and re-aggregates** — elements move pages constantly. Answering
"every lesson between datetime A and B" or "newest lessons about <topic>" by
walking + regexing thousands of files each time is too slow. memgrep needs a
**persistent, incrementally-maintained index** keyed for these queries — at
minimum by `(element-type {fact|note}, OCD, LMD, topic/tags, page)` — so a
time-range or topic query is an index lookup, not a tree scan. This is the
single biggest engineering requirement of the whole memory system and is
memgrep's job (TRDD-d151fe52): its current `index` subcommand must grow from a
doc-generator into a real query index (a sidecar SQLite or equivalent), kept in
sync as the librarian moves elements.

**Git is the lever (the "…under git, so…").** The whole memory dir is
git-tracked, which the design must exploit, not fight:
- **Every move/merge is an auditable commit.** `git log --follow` reconstructs a
  memory's full lineage — which pages it lived on, when it moved — so the
  librarian's reorgs are completely traceable and **RULE 0 is satisfied for
  free**: nothing is ever lost, every move is reversible. (Intrinsic OCD/LMD
  metadata remains the authoritative age source — git-follow across moves +
  renames is fragile — but git is the recovery/audit backstop.)
- **Incremental indexing rides git.** The index re-processes ONLY what
  `git diff <last-indexed-commit>..HEAD` reports as changed, never the whole
  corpus — so constant background churn costs near-nothing to re-index. memgrep
  is already gitignore-aware; making it git-commit-aware for incremental index
  updates is the natural extension.
- **Move-churn discipline.** Continuous background moves generate many commits;
  the librarian should BATCH a reorg pass into a few well-described commits
  (not one commit per moved line) so history stays readable and the index's
  incremental delta stays coherent.

### Implementation note (do NOT build piecemeal)

The correction protocol, the `## Notes and lessons learned` page structure, the
footnote-reference convention, the janitor conflict-surfacing detector, and the
read-the-notes rule are ONE coherent feature. They must be designed and shipped
together (the read-the-notes rule is meaningless until the lessons section
exists). Capture-first, integrate-once — do not add the reading rule in
isolation. Implement as a unit when this TRDD leaves `backburner`.
