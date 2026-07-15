---
trdd-id: 87RKBYJ8
title: Subconscious agent — full per-changed-page wikimem maintenance duties spec
column: backburner
created: 2026-07-15T19:55:48+0200
updated: 2026-07-15T20:19:00+0200
current-owner: janitor-session
task-type: feature
scope: project
severity: major
labels: [wikimem, memgrep, memory-maintenance, subconscious-agent, desc-field]
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

## NEXT ACTION
1. Reconcile this list against the current `janitor-memory-*` skills + `memory_edit_verify` oracles;
   produce a gap list (existing vs missing).
2. Prioritize the NET-NEW duties that need infra: (8) the up-to-date/superseded delimiter + memgrep
   default-exclude; (21) the published-globally symlink at user-scope; (9) superseded→lesson rewrite
   as a verified transaction; (2) desc enforcement (depends on TRDD-AP2X9A0H).
3. Implement per chore, each as a verified transaction; add tests to `memory_edit_verify`.
4. Publish (skills + memgrep live in the plugin → release + cache update to deploy).

## Verification
- Run the agent on a deliberately-broken page (bad frontmatter, mixed-topic atoms, a superseded atom
  not yet a lesson, a dangling link, missing `desc`, superseded atoms above up-to-date ones) and
  confirm every duty above is applied, `verify_*` proves no knowledge lost, and memgrep by default
  lists only up-to-date atoms (by `desc`) with superseded excluded unless requested.

## Notes and lessons learned
