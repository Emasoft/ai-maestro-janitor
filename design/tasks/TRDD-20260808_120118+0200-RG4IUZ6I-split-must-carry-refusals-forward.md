---
trdd-id: RG4IUZ6I
title: A split must carry conflict refusals forward — page-name keys die with the page
column: todo
created: 2026-08-08T12:01:18+0200
updated: 2026-08-13T04:19:51+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#241, janitor#227, TRDD-3QIQ2E6J]
---

# A split must carry conflict refusals forward

## ⏵ STATE — 2026-08-13: THIS CARD CONFLICTS WITH TRDD-3QIQ2E6J. Do not build item 1.

**Same root cause, same measurement (221,612 tokens / zero mutations), same issue janitor#241 —
and NEITHER card cites the other.** 3QIQ2E6J was filed 4 days later by a session that evidently
did not know this card existed. Comparing them item by item:

| this card | 3QIQ2E6J | verdict |
|---|---|---|
| **1. split txn rewrites the refusal ledger** (carry refusals to the children) | *"Why patching the refusal ledger is the WRONG fix"* — a refusal carried onto pages with different names, bytes and subjects asserts a verdict **nobody reached**, so the ledger LIES | **3QIQ2E6J wins on argument.** Do NOT build item 1 |
| **2. sibling-pair suppression in the librarian** | same fix | **AGREED — this is the real fix** |
| 2's lineage source: *"the overview/`Governed by` links"* | an explicit split marker | **this card's source is WRONG** — see below |
| **3. headroom-aware split sizing** (no sibling within ~10% of the cap) | absent | **UNIQUE TO THIS CARD — must not be lost** |

**Why item 2's stated lineage source fails, verified 2026-08-13:** deriving sibling-hood from
overview / `Governed by` links is strictly WIDER than split-sibling-hood — a hub links ALL its
components, not only the pages one split produced. So it would suppress genuine conflicts
BETWEEN two components of the same hub, which is exactly what 3QIQ2E6J's acceptance box 2
forbids ("a genuine conflict between UNRELATED pages still fires"). The suppression predicate
must be an explicit "the janitor separated these two" marker; its narrowness is the point.

**RECOMMENDED RESOLUTION (a USER call — force-supersede is non-exempt, so not taken here):**
supersede this card by **TRDD-3QIQ2E6J**, first carrying **item 3** across, since it is real,
cheap, and exists nowhere else. Item 3 also prevents the guaranteed-recurrence case this card
alone measured: one sibling sat 279 B under the split cap, so the next split re-voids the very
refusals item 1 wanted to preserve — which is an independent argument that item 1 was treating a
symptom.

**Until that call is made, nobody should implement EITHER card's item 1.** Building it would make
the refusal ledger assert judgements no agent ever made, and a lying ledger is harder to detect
than the re-litigation it was meant to stop.

## Why (janitor#241, autonomous peer — measured)

Conflict refusals are keyed by page-name PAIRS (`memory_refusals.candidate_key` over
root-relative paths). A split retires the parent name and mints sibling names, so every
recorded refusal touching the family stops matching; the next conflict pass re-litigates from
scratch. Measured: one such null pass cost 221,612 subagent tokens, zero mutations. It
compounds: one parent refusal becomes O(n²) sibling pairs; split siblings are partitions of
ONE page so they share the vocabulary the librarian keys on (worst-possible candidates,
flagged forever); and one sibling sat 279 B under the split cap, guaranteeing the next split
re-voids today's refusals. One chore manufactures null work for another.

## What (two complementary halves)

1. **The split transaction rewrites the refusal ledger** (the split KNOWS old + new names):
   for each refusal keyed on the retired parent, write derived entries for every
   (surviving-counterpart, sibling) pair, carrying the original reason + a `derived-from`
   note; drop the dead key. Same txn discipline as the wikilink canonicalization the split
   already does (`canonicalize_retired_links` precedent).
2. **Sibling-pair suppression in the librarian**: pages minted by the same split (lineage is
   recorded in the overview/`Governed by` links) are partitions of one subject — a
   sibling-vs-sibling pair needs a positive contradiction signal, not shared vocabulary, to
   become a conflict candidate. Suppress vocabulary-only sibling pairs.
3. Note: headroom-aware split sizing (don't emit a sibling within ~10% of the cap) is worth a
   line in the split skill — prevents the guaranteed-recurrence case.

## Acceptance

- [ ] Split txn test: parent-keyed refusal → derived sibling-pair entries, reason preserved
- [ ] Librarian test: same-split sibling pair with only shared-vocabulary signal is NOT a
      candidate; a genuine contradiction still is
- [ ] The 221k-token null-pass scenario replayed → no dispatch (refusals match)
- [ ] #241 answered when it ships
