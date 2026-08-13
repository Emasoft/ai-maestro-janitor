---
trdd-id: 3QIQ2E6J
title: Split siblings are perpetual conflict candidates — the refusal ledger cannot fix this because the pages are genuinely new
column: testing
created: 2026-08-12T21:00:24+0200
updated: 2026-08-13T10:18:09+0200
current-owner: unassigned
task-type: refactor
approval-tier: 0
scope: project
severity: high
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-WP7TCRME, TRDD-RG4IUZ6I, janitor#241]
---

# Split siblings re-litigate forever

## ⏵ 2026-08-13 — IMPLEMENTED (producer + consumer). Retro-stamp REFUSED, with reasons.

Shipped exactly the settled design below — Python only, no Rust change, no memgrep release.

| piece | where |
|---|---|
| the marker + all four pure predicates | `scripts/lib/memory_split_lineage.py` (new) |
| producer — stamps the pages a split PRODUCES | `memory_txn.MemoryTxn.stage_write`, gated on `op == "split"` |
| consumer — diverts sibling pairs out of the candidate list | `detectors/memory-librarian.py::_conflict_pairs` |
| the visible trace | `ScopeReport.split_suppressed` → proposal section + an UNCONDITIONAL log line |

**Field:** `split-lineage: <32-hex>`, the split transaction's own `txn_id` — already minted,
already unique, and traceable back to that transaction's journal, so the audit trail costs nothing
extra. A re-split OVERWRITES it (grandchildren are siblings of the *newer* event).

**The producer is the transaction, NOT the skill.** A skill instruction is a request to an agent,
and a lineage field that is merely *usually* present is worse than none: the pairs it silently
fails to cover are exactly the ones that keep costing ~221k tokens, with nothing to show they were
missed. `stage_write` is the one choke point every writer passes (including `apply_atomic`), and
`memory_txn_cli.py::cmd_commit` reconstructs the split's write set through it (`:506`), so the
real agent-driven path is covered — verified, not assumed.

**Not every write is stamped.** `is_split_child` stamps a NEW path or the SOURCE path (the
overview), and refuses a pre-existing non-source page — those are BACKLINK REDIRECTS
(`canonicalize_retired_links`). Stamping them would mark unrelated pages as siblings: box 2's
failure, arriving through the back door of "stamp everything this transaction wrote".

### ✔ The `publish-globally` fight cannot happen — VERIFIED in the Rust, not reasoned about

The card required the field be added THROUGH that normalizer, "not beside it, or the two will
fight". Read the code: `atomic_write_page`'s only content mutation is
`insert_frontmatter_field(text, "publish-globally", …)`, which splices ONE line in before the
closing `---` and copies every other line through verbatim (`memory.rs:4260`). Unknown keys are
preserved, so there is nothing to fight over — and the split path is Python and never invokes the
Rust writer at all. `stamp` inserts at the same position so a page touched by both has no
ordering tell. Confirmed end-to-end: `memgrep lint` on a stamped page → **0 findings**; the
frontmatter schema is open, there is no allowed-key list to add to.

### ✔ Falsified per guard, both directions

- drop the `bool(a)` guard in `same_split` (⇒ "no lineage" == "no lineage" ⇒ suppress everything):
  2 unit tests red, **and** the end-to-end control red.
- `is_split_child` → always True (the tempting simplification): 2 red, including the
  backlink-redirect case.

### ⚠ FOUND WHILE FALSIFYING — a pre-existing control test that gated nothing

`test_wiki_conflict_pair_reads_real_bodies` stayed GREEN with the conflict scan fully silenced.
Both its assertions were satisfiable at zero conflicts: the heartbeat line reads
`"N aggregation + M conflict"` so `assertIn("conflict", out)` passes at M=0, and the two notes
also cluster on `retry`, so their names appear in the AGGREGATION section regardless. Then my
own first fix was ALSO weak — asserting on the conflict SECTION still passed, because the new
suppression trace is rendered in that same section and names the same two pages. It now asserts
on column-0 candidate ROWS, and only that version goes red under the falsification.

### ✗ RETRO-STAMP REFUSED — no provenance survives, and the only available inference is the one this card killed

The pages named in the resume directive (`memory-librarian-flags-benign` / `-candidates-cli` /
`-verdict-log`) **do not exist on this host** — janitor#241 was filed from a different agent's
corpus. What *is* here is the live defect, in USER scope right now:

```
verify-cross-repo-cited-sha-before-building-{deployment-and-enforcement-claims,
                                             governance-and-release-state} vs …-sha-verification-check
debugging-methodology-verify-before-concluding-causal-claims vs debugging-methodology
```

No `.maint-staging/*.json` journal survives for any of them, so the ONLY way to assert lineage is
the shared filename PREFIX — prefix-derived ancestry, killed on acceptance box 2 and explicitly
off-limits. Two of those pairs are hub-vs-component, which is precisely the relation box 2
protects. A stamp is a claim that *the janitor separated these two*; fabricating it would make the
marker mean "an agent guessed", which is the same defect this card rejects for the refusal ledger
— a record that asserts a verdict nobody reached.

Cost of NOT retro-stamping is bounded and self-healing: those pairs are re-litigated until their
next split re-stamps them properly, or a human merges them. Cost of a wrong stamp is permanent,
silent, undetectable suppression. **If retro-stamping is wanted, it needs a `--retro-stamp` verb
taking an EXPLICIT page list plus a human's per-pair confirmation, recorded as human-asserted
lineage — a USER call, not an inference.**

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**Filed as a TICKET, not fixed, and that is the correct call under TRDD-WP7TCRME Rule 1:** a
structural problem needing a schema change is never a warning and never a quick patch. Reported
as janitor#256's sibling issue **janitor#241** by the Claude on ai-maestro-autonomous-agent,
with a measured cost: **221,612 subagent tokens for ZERO mutations** on a 62 KB corpus.

**VERIFIED first-hand (2026-08-12), not taken on report:**
  - `memory_refusals.candidate_key` builds the refusal key from **root-relative PATHS**
    (`scripts/lib/memory_refusals.py:61`). A split creates new page names, so the key changes
    and the recorded refusal stops matching.
  - `content_hash` cannot rescue it either: it hashes the pages' BYTES, which a split also
    changes by construction.
  - **No lineage field exists** on a wikimem page — `grep` for `split-from` / `parent-page` /
    `derived-from` across `scripts/lib/` and the split skill returns nothing. So today there is
    no way to ask "did the janitor itself separate these two pages?"

## Why patching the refusal ledger is the WRONG fix

The tempting repair is to carry the parent's refusals over to the children. It does not hold
up: after a split the pair genuinely IS different — different names, different bytes,
different subjects — so a refusal that claimed to have judged "these two" would be asserting a
verdict nobody reached. That is worse than the re-litigation, because it makes the ledger lie.

**The real defect is upstream of refusals: split siblings should never be conflict CANDIDATES
at all.** They share vocabulary by construction — the split is what gave them a common subject
— so the conflict scan surfaces them, an agent judges them, declines, and the next split-shaped
edit re-arms the whole cycle. The janitor is proposing to undo a decision the janitor just
made, and paying ~221k tokens per round to be told no.

## ⏵ 2026-08-13 — DESIGN SETTLED (two decisions), scope cut to PYTHON-ONLY. Not yet implemented.

Re-verified the card's three claims first-hand (all hold: no lineage field anywhere in
`scripts/`+`skills/`; `candidate_key` is path-keyed; `content_hash` hashes bytes). Then two
findings that change the work:

**1. NO RUST CHANGE, NO memgrep RELEASE — the consumer can read frontmatter itself.** The
conflict candidates are surfaced by `detectors/memory-librarian.py`, whose `NoteMeta`
(`:286`) carries only `tags` + `tokens` because it parses `memgrep index --markdown`. Routing a
new field through that output means editing the Rust crate AND shipping a memgrep release. But
the librarian already holds each note's memdir-relative PATH, so it can read the lineage field
straight from the page's own frontmatter. That keeps the whole change in Python + the split
skill, and — the real prize — it means the field never has to become part of memgrep's index
schema at all.

**2. A CHEAPER ALTERNATIVE WAS CONSIDERED AND KILLED ON THE ACCEPTANCE CRITERIA — do not
revive it.** `verify_split` already requires a split to emit an OVERVIEW page that links every
sub-page (`:1181`, "a map of summaries … the leaves it points to"), so "siblings = both linked
from one overview" looked like it needed no schema change whatsoever. **It fails acceptance box
2.** A hub links ALL its components, not only pages one split produced, so that predicate
silences genuine conflicts BETWEEN two components of the same hub — exactly the case box 2
protects. Link-derived sibling-hood is strictly wider than split-sibling-hood.

**Therefore the card's original sketch stands and is the right shape:** an explicit marker
meaning *"the janitor itself separated these two"*, which is the exact predicate and nothing
wider. Its narrowness is the feature, not an accident of implementation.

**Still genuinely open when picked up** (per the card's own warning, do not treat as settled):
the field's NAME and whether it names the parent page or a per-split id. Prefer a per-split ID:
naming the parent breaks when the parent is later renamed or itself split again, whereas an id
survives both and answers "same split event?" directly. Whatever is chosen must be emitted and
normalized through the `publish-globally` normalizer (`9ddb3cf7`, `25013e64`), never beside it.

**SIBLING CARD FOUND — TRDD-RG4IUZ6I, and this card did not know it existed.** Filed 4 days
EARLIER for the same janitor#241 defect with the same 221,612-token measurement; neither card
cites the other. It agrees with this one on the real fix (sibling suppression) and CONTRADICTS
it on carrying refusals forward, where this card's argument wins: a refusal carried onto pages
with different names, bytes and subjects asserts a verdict nobody reached. It also proposed
deriving lineage from overview links — the approach killed above.

**One thing on it is UNIQUE and must survive any supersession: headroom-aware split sizing** —
do not emit a sibling within ~10% of the split cap. RG4IUZ6I measured a sibling sitting **279 B**
under the cap, so the next split re-voids the refusals in question. That is an independent
reason the refusal-carrying fix was treating a symptom, and it belongs in the split skill
whichever card ships. Resolution (supersede RG4IUZ6I by this card, item 3 carried across) is a
USER call — force-supersede is non-exempt.

## Sketch (decide when picked up — do NOT treat as settled)

Record split lineage on the pages, and skip pairs that share it:

  1. the split transaction stamps each child with the parent it came from (a frontmatter
     field — name it when the schema is being touched anyway, see below);
  2. the conflict candidate scan skips any pair whose lineage marks them as siblings of one
     split;
  3. an explicit human merge stays possible — this suppresses the AUTOMATED proposal, not the
     operation.

**Coordinate with the `publish-globally` work (`9ddb3cf7`, `25013e64`).** That just made
frontmatter normalization a pre/post-condition of every page write, iterating to zero findings.
A second new field must be added THROUGH that normalizer, not beside it, or the two will fight:
one inserting a field the other does not know about, each rewriting the page the other just
"fixed", every write, forever.

## Acceptance

- [x] Split siblings are not offered as conflict candidates — `test_split_siblings_are_not_offered_as_conflict_candidates`,
      run end-to-end through the detector on the SAME fixture the control proves IS a conflict
- [x] A genuine conflict between UNRELATED pages still fires — two ways: pages from DIFFERENT
      splits still conflict (`test_pages_from_DIFFERENT_splits_still_conflict`), and lineage-free
      pages are never siblings (falsified: removing that guard reddens the control)
- [x] The lineage field coexists with `publish-globally` — verified in `memory.rs:4260`
      (single-line splice, unknown keys preserved) and confirmed by `memgrep lint` → 0 findings.
      NOTE the card's phrasing assumed one writer; there are two, and the Rust one never runs on
      the split path. Coexistence is the real requirement and it is proven, not assumed.
- [ ] Measured: a post-split conflict pass costs ~0 tokens instead of ~221k — **not yet
      measurable here.** It needs a real split to occur on this host so its children carry the
      stamp; the existing sibling-shaped pairs predate the marker and were NOT retro-stamped (see
      the refusal above). The mechanism is proven end-to-end in the suite; the token figure is a
      production measurement that has to wait for the next split.

## Approval log

- 2026-08-12T21:00:24+0200 — FILED at `todo` by janitor-main-session (tier 0, own scope).
  Deliberately not started: it needs a page-schema addition, and the session that found it is
  running at ~398k weighted tokens per heartbeat fire (TRDD-WP7TCRME's measurement), which is
  the most expensive possible context in which to design a schema change.
