---
trdd-id: RG4IUZ6I
title: A split must carry conflict refusals forward — page-name keys die with the page
column: todo
created: 2026-08-08T12:01:18+0200
updated: 2026-08-08T12:01:18+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#241, janitor#227]
---

# A split must carry conflict refusals forward

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
