---
trdd-id: 87RKBYJ8
title: Subconscious agent — full per-changed-page wikimem maintenance duties spec
column: todo
blocked-by: []
created: 2026-07-15T19:55:48+0200
updated: 2026-08-26T18:05:00+0200
current-owner: janitor-session
task-type: feature
scope: project
severity: major
labels: [wikimem, memgrep, memory-maintenance, subconscious-agent, desc-field]
implementation-commits: [3179af38]
relevant-rules: []
---

# Subconscious agent — full per-changed-page wikimem maintenance duties spec

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-15

**The ask (USER, 2026-07-15, verbatim intent):** the `janitor-memory-subconscious-agent` that
processes wikimem pages must, **for each wikimem page that changed lately**, perform the full set of
editorial duties below. Some already exist as chores (consolidate / split / conflict / repair /
atomize / harvest); this TRDD is the COMPLETE, authoritative duty list to reconcile the agent's
skills against — implement the missing ones, and make the existing ones enforce these rules. Depends
on the `desc` field (TRDD-AP2X9A0H).

**ROOT PRINCIPLE (USER, 2026-07-15) — the WHY behind duties 10/14/15:** *a wikimem page exists ONLY
to collect the atoms about the SAME topic, so every page must be a single, distinct topic (or
subtopic).* Topic (not the title string) decides a page's identity. Every same-topic-merge (10),
off-topic-relocate (14), and create-page-for-orphan-topic (15) duty is a direct consequence: they
exist to keep each page topic-pure. Captured as an atom on the wikimem overview page
(`wikimem-atom-block-properties.md ^9K3ZP7QW`).

**Implementation note:** the wikimem editor is transaction-gated (`memory_txn` /
`memory_edit_verify`), and every edit must pass the deterministic `verify_*` oracle (no knowledge
lost). Every duty below must be expressible as a verified transaction. Scheduling is via
`detectors/memory-maintenance.py`; the per-chore procedures are the `janitor-memory-*` skills the
agent loads. These duties EXTEND / TIGHTEN those.

## The duties (each is a per-changed-page pass; group ⇒ likely owning chore)

### A. Frontmatter + metadata correctness
1. FIX the page frontmatter if broken / incomplete / outdated.
2. ADD what is missing from the metadata — **including the `desc` field** (TRDD-AP2X9A0H): ensure it
   is present, **max 200 chars, AND correct** (a true summary of the atom, not a slug).
3. Ensure each ATOM's metadata is COHERENT with its content (keywords, id, datetime, status).

### B. Body formatting + greppability
4. FIX the markdown formatting of the body so the page is **greppable** by memgrep.
5. Ensure references to bottom-of-page notes use the **standard markdown `[^x]` footnote format**;
   IMPORTANT links stay **inline** as markdown links/paths (e.g. hyperlinks to other wikimem pages).
6. Ensure the page is composed **ONLY of atoms of memory** — no unreachable prose parts that just
   waste tokens (every durable line belongs to an atom).

### C. Page body STRUCTURE + up-to-date/superseded ordering
7. Enforce the body structure: **up-to-date atoms FIRST**, then **superseded / lessons-learned
   atoms**, then **notes / references / links / see-also at the BOTTOM**.
8. Up-to-date atoms in the UPPER part, superseded atoms in the LOWER part, separated by a **clear
   delimiter memgrep can use** to show only up-to-date atoms by default and EXCLUDE superseded ones
   unless the filter params explicitly request them. (⇒ needs a memgrep convention + a memgrep change.)

### D. Superseded-atom → lesson-learned conversion
9. Every SUPERSEDED atom must be rewritten into a **lesson-learned** form:
   **"X MUST NOT BE DONE BECAUSE [WHY], WHAT TO DO INSTEAD."** The body preserves the OLD content but
   reframed as the lesson; the **old TRDD(s) stay linked**.

### E. Cross-page merge / dedup (⇒ consolidate chore)
10. MERGE a page with existing wikimem pages of the **same TOPIC — even if the title differs
    slightly**; it is the actual topic that counts, not the title string.
11. Search + merge atoms with the **same content**, avoiding duplicates. If two topic pages both need
    the same atom, only **ONE page carries it**; the other CITES it with a **titled hyperlink** (an
    informative title, not too long).

### F. Split oversized pages (⇒ split chore)
12. SPLIT pages that got too big: aggregate the atoms into subtopics, CREATE new topic pages linked
    from the original, and REPLACE the original page content with a **summary atom**.

### G. Atom atomicity + topical placement (⇒ atomize chore)
13. SPLIT atoms that mix multiple arguments (especially different topics) — keep atoms ATOMIC and
    easy to grep by keywords: **one paragraph / one table / one list per atom**.
14. Detect an OFF-TOPIC atom and MOVE it to the wikimem page right for its topic (e.g. methodological
    considerations → the best-practices page).
15. If an off-topic atom's topic has **no page yet**, CREATE that page.
15b. Detect a page whose TITLE is a memory-DESCRIPTION, not a TOPIC (e.g.
    `implementation-of-duckdb-ingestion-of-otel-logs.md` vs the correct `agents-tracing.md`) → MERGE
    its atom(s) into the right topic page (redirect `[[links]]` + ref-count footnotes) or, if the
    topic has no page, RENAME it to the broad topic. This is the NAMING axis of duties 10/14/15 —
    owned by **TRDD-NM4TPCQ9** (which also adds the write-time prevention in `janitor-memory-write`).

### H. Links / references integrity
16. EDIT / POLISH the references + links to other wikimem pages and atoms; PRUNE the ones that are
    duplicated or point to outdated pages that no longer exist.
17. If a link/hyperlink is DANGLING (no corresponding page or atom), CREATE the missing page or atom.
18. ADD links to the **TRDDs actually relevant** to each atom's content.

### I. Reachability + wiki-layer + scope validation
19. Verify each atom is REACHABLE: **unique keywords + id + datetime**, formatted correctly to be
    grepped by memgrep.
20. VALIDATE the expander (hub/aspect, radiating) vs reducer (component, receiving) division; correct
    a mis-typed page; EXPAND or REDUCE where needed.
21. Ensure each page is at the CORRECT scope level (LOCAL / PROJECT / USER); a page whose frontmatter
    carries the **published-globally** value must be **SYMLINKED at user-scope**.

## Gap list — 2026-07-16 reconciliation (duty → owning chore → status)

| # | Duty | Chore | Status |
|---|---|---|---|
| 1 | fix broken frontmatter | repair | ✅ EXISTS (`verify_repair`; live — backfilled `tier` 2026-07-15) |
| 2 | desc present ≤200 + correct | write/atomize/harvest + repair | 🟡 authoring REQUIRED everywhere (2026-07-15/16); repair does NOT yet backfill/validate desc |
| 3 | atom metadata coherent w/ content | repair | 🟡 shape validated; keyword/content COHERENCE unchecked |
| 4 | greppable markdown formatting | repair + librarian | 🟡 librarian SURFACES page-shape; repair fixes structure only |
| 5 | `[^x]` footnotes + inline links | model + repair | 🟡 spec'd; no enforcement pass |
| 6 | body = only atoms (no stray prose) | atomize | ✅ EXISTS (live — 2 pages atomized 2026-07-15) |
| 7-8 | up-to-date first / superseded below a memgrep-excluded delimiter | — | ❌ NET-NEW: delimiter convention + memgrep default-exclude + reorder pass |
| 9 | superseded→lesson rewrite (DO NOT/BECAUSE/INSTEAD + old TRDD links) | update (correction protocol) | 🟡 per-correction demotion EXISTS; bulk retro-pass chore MISSING |
| 10 | merge same-TOPIC pages (title differs) | consolidate | ✅ EXISTS; topic-not-title made explicit 2026-07-16 |
| 11 | cross-page atom dedup (one carrier, others cite) | consolidate | 🟡 lesson-dedup inside a merge only; cross-page atom dedup MISSING |
| 12 | split oversized → subtopics + summary atom | split | ✅ EXISTS (`verify_split`; oracle bugs #97/#88 verified FIXED on disk 2026-07-16 — reproducers don't reproduce, full suite green; issues just need closing) |
| 13 | split multi-topic atoms | atomize | ❌ atomize adds markers, never splits an atom |
| 14 | relocate off-topic atom | — | ❌ NET-NEW relocate chore (move rule spec'd, no executor) |
| 15 | create page for orphan topic | write (authoring) | 🟡 at creation only; corrective chore MISSING |
| 15b | description-named page → merge/rename | consolidate | 🟡 merge half LANDED 2026-07-16 (survivor rule + rename-candidate finding); rename executor MISSING |
| 16-17 | prune/repair links; dangling → create | librarian (surface) | 🟡 librarian SURFACES (132 link findings); fixing executor MISSING |
| 18 | TRDD backlinks per atom | — | ❌ NET-NEW |
| 19 | atom reachability (unique id/keywords/dates) | repair + memgrep | ✅ EXISTS — corpus-wide `atom-dup-id` landed (`memory.rs:3979`, Check 8, Severity::Error, every location reported; verified first-hand 2026-08-02) |
| 20 | expander/reducer (hub/aspect/component) revalidation | write (at creation) + librarian | 🟡 flagged, not corrected |
| 21 | scope validation + published-globally USER symlink | scope-leak detector | 🟡 privacy direction policed; symlink publishing infra MISSING (= issue **#52**) |

### ✅ 2026-08-22 — ALL FOUR CHILDREN ARE TERMINAL. The block is discharged; the card is workable.

Measured today: `57WJL5L2` complete · `AZ6QRK0D` published · `J3ZH3RSI` complete ·
`3SOO1RWE` complete. So NEXT ACTION step 2 — "implement the NET-NEW infra in priority order" —
is done for all four pieces that were split out, and step 3 was already closed.

**Two errors that happened to cancel, worth naming so neither is repeated.** The note below says
the parent is `blocked` on the children, but the frontmatter has read `column: todo` with
`blocked-by: []` the entire time — the split was performed in prose and never in the fields. So
for three weeks the board claimed this card was ready to pick up while it was genuinely blocked,
and it now claims the same thing while that is finally TRUE. A card whose column is right by
accident is not a card you can trust; `blocked-by:` is the field the drain rule keys on, and
prose is invisible to it.

**WHAT ACTUALLY REMAINS, because "the children are done" must not be read as "the card is done".**
Only the four listed pieces were split out. Three ❌ NET-NEW duties in the table above were NOT,
and no child owns them:

- **13** — split a multi-topic ATOM (atomize adds markers, it never splits an atom). Note this is
  adjacent to but DISTINCT from the over-budget-atom decomposition shipped under TRDD-VOWAUVE5:
  that one triggers on SIZE, this one on an atom carrying two topics at any size.
- **14** — relocate an off-topic atom (the move rule is spec'd, no executor exists).
- **18** — TRDD backlinks per atom.

Plus the 🟡 partials (3, 4, 5, 11, 15, 15b, 16-17, 20), each of which is a real half-built duty
rather than a missing one. Step 4 (publish) is gated on the repo's publish blocker, not on work.

Next time this card is pulled: split those three ❌ duties the same way, one card each — the
card's own resume note is right that pulling it means SPLITTING it, not implementing several
features under one id.

### ⏵ 2026-08-26 — ALL FOUR CHILDREN ARE TERMINAL. Nothing here is blocked, and step 2 is DONE.

Checked each one today:

| child | duty | column |
|---|---|---|
| TRDD-57WJL5L2 | 7-8 superseded delimiter + memgrep default-exclude | `complete` |
| TRDD-AZ6QRK0D | 21 `published-globally` symlink | `published` |
| TRDD-J3ZH3RSI | 9 superseded→lesson retro-pass | `complete` |
| TRDD-3SOO1RWE | 2 atom `desc` backfill | `complete` |

So the 2026-08-02 note below — *"this card sits `blocked` on the four"* — is stale, and the
frontmatter was already right (`column: todo`, `blocked-by: []`); the prose was the thing lying.
**NEXT ACTION step 2 is complete in full**, and step 4 (publish) rode out with the children.

**What `todo` means on this card now, precisely:** it is a SPEC + reconciliation ledger whose own
instruction is *"do not implement [the remaining rows] under this id either — split them out the
same way when their turn comes."* So pulling this card can only ever produce ANOTHER split, never
an implementation. The remaining un-split gap rows are 11, 13, 14, 15, 15b-rename, 16-17, 18.

### ⏵ 2026-08-26 18:05 — SECOND SPLIT DONE. The remaining rows are now CARDS, not prose.

The rows this card had been carrying as a gap list are split out, in the parent's own priority
order, exactly as its rule requires (never implemented under this id):

| duty | card | column |
|---|---|---|
| 16-17 link integrity — prune / resolve / KEEP | **TRDD-JKJHV19B** | `todo` — the next increment |
| 14 move an off-topic atom to its right page | TRDD-QDYQLM5V | `backburner` |
| 13 split atoms that mix multiple arguments | TRDD-LASH4SLW | `backburner` |
| 18 link atoms to their governing TRDDs | TRDD-7GCALSTP | `backburner` |
| 11 one page carries a shared atom, others cite | TRDD-E7D4QPH1 | `backburner` |
| 15 create the page an orphan topic needs | TRDD-VIFQ1LKI | `backburner`, `blocked-by: QDYQLM5V` |

Row **15b** is NOT split here — it is already owned by TRDD-NM4TPCQ9. Rows 19, 20, 21 are covered
or terminal per the 2026-08-02 re-audit.

**Why now, and stated plainly:** this card was read at 12:05 today, its instruction ("pulling it
produces another SPLIT") was recorded, and then nothing was split for six hours while the session
reported itself blocked. It was not blocked — the split needs no decision from anyone. The
kanban rule's exact failure: filing a card *about* work is not the work, and a card that records
its own next action and does not take it is stalled rather than parked.

**This card is now a pure ledger.** Every row is either terminal, split, or owned elsewhere. It
should be pulled only to reconcile the duty list against the tree, never to build.

Left in `todo` rather than moved to `backburner` because the next increment is genuinely
available work — but anyone pulling it should expect to author a child TRDD, not to write code.

### 2026-08-02 19:38 — SPLIT into 4 child TRDDs; parent `blocked` on them (rule 13)

The card's own resume note says pulling it means SPLITTING it, not implementing four
features under one id. Done — the four NET-NEW pieces are now their own cards, in the
parent's priority order, each carrying the audit's verified facts + smallest step:

1. **TRDD-57WJL5L2** — duties 7-8: superseded-below-delimiter convention + memgrep
   default-exclude + reorder pass (highest value — recall currently mixes obsolete facts in).
2. **TRDD-AZ6QRK0D** — duty 21: `published-globally` → real USER-scope symlink mechanism
   (coordinate with issue #52).
3. **TRDD-J3ZH3RSI** — duty 9: bulk superseded→lesson retro-pass (7th maintenance marker).
4. **TRDD-3SOO1RWE** — duty 2: atom `desc` backfill/validation in repair (cheapest).

This card is now the SPEC + reconciliation ledger and sits `blocked` on the four (its step 4,
publish, follows them). The remaining PARTIAL/MISSING rows NOT split out (11, 13, 14, 15,
15b-rename, 16-17, 18) stay recorded in the gap table for future increments — split them out
the same way when their turn comes; do not implement them under this id either.

### 2026-08-02 19:12 — independent duty-coverage RE-AUDIT folded in (verified)

A lean-worker re-audited all 20 duty rows against the CURRENT tree with file:line citations:
**6 COVERED / 10 PARTIAL / 4 MISSING** (report:
`reports/lean-worker/20260802_190200+0200-87rkbyj8-duty-coverage.md`). Deltas vs the
2026-07-16 table, each spot-verified FIRST-HAND before recording (decide-on-facts):

- **Row 19 → ✅ COVERED** — `atom-dup-id` corpus-wide id-uniqueness is ON DISK
  (`scripts/memgrep/src/memory.rs:3979`, Check 8, `Severity::Error`, reported at every
  location). The old "lands with TRDD-0NGYP3IG" note is stale — it landed. Table row updated.
- **Row 2 confirmed PARTIAL** — `verify_repair`'s `_REQUIRED_FM_KEYS`
  (`memory_edit_verify.py:1106`) is PAGE-frontmatter only (`name, description, ocd, lmd,
  node_type, type`); no atom-level `desc:` presence/length check anywhere in repair.
- **Rows 7-8 confirmed MISSING** — zero hits for any superseded include/exclude or delimiter
  machinery across `scripts/memgrep/src/*.rs` (grepped alternates: `include-superseded`,
  `exclude…superseded`, `## Superseded`).
- **Row 21 confirmed** — no `publish` subcommand in `main.rs`; the symlink appears only as a
  test fixture (`memory.rs:7027-7051`). Still issue #52 territory.

The audit's priority ordering matches this card's own NEXT ACTION step 2 order (7-8 first,
then 2 / 9 / 16-17, then 14 / 13 / 18 / 21) — no re-prioritisation needed.

**Step 3 CLOSED OUT:** issues #97 and #88 are both `CLOSED` on the tracker (checked
2026-08-02) — the "close the two issues" leftover is done; nothing remains of step 3.

### 2026-08-02 — `dev → todo`. Real work, genuinely queued, and nobody is building it.

Step 1 is done and step 3 is verified-fixed; step 2 is four NET-NEW pieces that have not been
started, and step 4 depends on step 2. Nothing has moved since 2026-07-16, so `dev` was asserting
an activity that is not happening — and the pipeline rule is explicit that an untrue column is
worse than an unstarted card, because it hides the stall from the only view anyone checks.
`todo` says what is true: ready to be pulled.

Two things a resumer should not re-derive: **step 2's own note says each of the four is likely its
own child TRDD** (rule 13 — one atomic task per card), so pulling this card means splitting it,
not implementing four features under one id. And **step 3's issues #97/#88 are fixed on disk with
regression tests** by a session that never closed them — the remaining act there is closing the
issues, not fixing anything.

## NEXT ACTION
1. ~~Reconcile → gap list~~ **DONE 2026-07-16 (table above).**
2. Implement the NET-NEW infra, in priority order: (7-8) delimiter + memgrep default-exclude;
   (21) published-globally symlink at user-scope (coordinate with issue #52's cross-project design);
   (9) the bulk superseded→lesson retro-pass as a verified transaction; (2) desc backfill in repair.
   Each is its own bounded implementation (likely its own child TRDD — one atomic task each).
3. ~~Fix the split-oracle bugs (#97, #88)~~ **VERIFIED FIXED 2026-07-16** — already fixed on disk
   with regression tests (a prior session fixed them without closing the issues); each issue's own
   reproducer no longer reproduces, full pytest suite 13051 passed / 0 failed. Report:
   `reports/memory-edit-verify/20260716_002102+0200-fix-issues-97-88.md`. ~~Close the two
   issues~~ **both CLOSED on the tracker (verified 2026-08-02) — step 3 fully done.**
4. Publish (skills + memgrep live in the plugin → release + cache update to deploy).

## Verification
- Run the agent on a deliberately-broken page (bad frontmatter, mixed-topic atoms, a superseded atom
  not yet a lesson, a dangling link, missing `desc`, superseded atoms above up-to-date ones) and
  confirm every duty above is applied, `verify_*` proves no knowledge lost, and memgrep by default
  lists only up-to-date atoms (by `desc`) with superseded excluded unless requested.

## Notes and lessons learned
