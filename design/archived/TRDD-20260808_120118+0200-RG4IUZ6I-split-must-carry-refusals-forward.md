---
trdd-id: RG4IUZ6I
title: A split must carry conflict refusals forward — page-name keys die with the page
column: human_review
created: 2026-08-08T12:01:18+0200
updated: 2026-08-16T02:39:50+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#241, janitor#227, TRDD-3QIQ2E6J]
---

# A split must carry conflict refusals forward

## ⏵ STATE — 2026-08-16 02:39: ITEM 3 JUDGED NOT WORTH BUILDING. Card → `human_review`; nothing buildable is left.

**Advisor consultation FAILED and is recorded as such rather than skipped.** A
`fable-advisor:advisor` agent was dispatched at 01:35 with the full design question (hard gate vs
advisory, which legitimate splits it would break, feedback-loop risk, where the threshold should
live). It ran **one hour** without returning and the janitor's own agent-liveness window expired
it. The verdict below is therefore MINE, taken under the rule's explicit-note clause — not an
advisor-backed one, and it should be re-examined if anyone ever gets that verdict.

### The verdict: do NOT add a headroom gate to `verify_split`

1. **A hard gate is disproportionate to what it buys.** `split_converged` today fails only pages
   OVER the cap. Requiring ≤90% makes a currently-legal 91% page abort an otherwise-correct
   transaction. The repo's own lesson from TRDD-3QIQ2E6J ("the producer is the transaction, NOT
   the skill") argues for enforcement — but that lesson was about a STAMP, which only ever adds
   information and cannot fail a legitimate split. A gate rejects work, and the two cases do not
   carry the same burden of proof.
2. **The `unsplittable` escape hatch cannot be reused honestly.** It means "over the cap and
   atomic". Pressing it into service for "under the cap but tight" would make an agent flag pages
   that are not over the cap at all, and conflating two conditions in one flag is how the next
   reader mis-implements both.
3. **The justification measurably shrank tonight, and this is the decisive part.** Item 3's stated
   value was preventing the guaranteed re-split that "re-voids today's refusals" — but measured
   2026-08-16 on this host, split siblings never reach the conflict path at all: `_conflict_pairs`
   requires an OPPOSING-CLAIM signal on top of shared vocabulary and siblings are complementary by
   construction, so nothing has ever been suppressed and no refusal is being re-voided. What
   remains of the cost is "a near-cap sibling gets re-split sooner", which churns `split-lineage`
   and wastes a pass. Real, small, and self-limiting.
4. **The middle option needs an API change it does not earn.** An advisory (report-don't-fail)
   result is the shape this codebase uses elsewhere — `split_converged` returns `(ok, oversized)`,
   `_conflict_pairs` returns `(conflicts, split_suppressed)`. But `verify_split` returns
   `(ok, reasons)` and a non-empty `reasons` ABORTS, so an advisory needs a third channel plumbed
   through `memory_txn_cli._verify_split` and its caller. That is a real change to a ratified
   verification path in exchange for a cost item 3 can no longer show is being paid.

**So there is no buildable work left on this card.** Item 1 is forbidden, item 2 shipped under
TRDD-3QIQ2E6J (now `complete`), and item 3 is judged not worth its cost on current evidence. The
only thing outstanding is the supersede-this-card decision, which is a USER call (force-supersede
is Tier 2, non-exempt) — so `human_review` is the honest column, alongside AZ6QRK0D and WN7M829Y.

**If the decision is to keep the card alive, the cheapest correct form of item 3 is a line in the
split skill after all** — not because prose is sufficient in general, but because the cost it
guards against is now small enough that skill-level guidance is proportionate to it.

## ⏵ STATE — 2026-08-16: TRDD-3QIQ2E6J is now `complete`. Only item 3 remains, and item 2's premise shrank.

Fact update, no decision taken. Since the block below was written:

- **Item 2 SHIPPED** under TRDD-3QIQ2E6J (sibling suppression via an explicit `split-lineage:`
  marker), and that card has closed. Nothing here to build.
- **Item 1 remains forbidden** on 3QIQ2E6J's argument, which this card already conceded.
- **Item 3 (headroom-aware split sizing) is still the only unshipped piece**, and still exists
  nowhere else. It is ordinary in-scope work; it does not need the supersession decision.
- **The supersede-this-card resolution is STILL a USER call** — force-supersede is non-exempt
  (Tier 2). It has not been taken and must not be taken here.

**One thing changed that weakens this card's own framing, and it should be known before anyone
picks item 3 up as urgent.** Measured 2026-08-16 on this host, where real splits now exist (7
pages, 2 lineage ids): the librarian reports zero USER-scope conflict candidates and has never
logged a suppression. `_conflict_pairs` requires an OPPOSING-CLAIM signal on top of shared
vocabulary (the shared-tag trigger was removed for #35/#38/#43), and split siblings are
complementary by construction — so the "flagged forever, O(n²) sibling pairs" mechanism this card
describes is **not** what is happening today. The 221,612-token measurement predates that gate.

Item 3 is therefore still worth doing for its own reason — a sibling 279 B under the cap
guarantees its own re-split, which churns lineage and wastes a pass — but not for the
re-litigation cost this card was filed on. See TRDD-3QIQ2E6J's closing block for the full reading.

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
