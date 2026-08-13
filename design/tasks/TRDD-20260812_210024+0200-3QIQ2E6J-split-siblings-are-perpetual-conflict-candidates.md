---
trdd-id: 3QIQ2E6J
title: Split siblings are perpetual conflict candidates — the refusal ledger cannot fix this because the pages are genuinely new
column: todo
created: 2026-08-12T21:00:24+0200
updated: 2026-08-13T04:16:35+0200
current-owner: unassigned
task-type: refactor
approval-tier: 0
scope: project
severity: high
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-WP7TCRME]
---

# Split siblings re-litigate forever

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

- [ ] Split siblings are not offered as conflict candidates, proven on a real post-split corpus
- [ ] A genuine conflict between UNRELATED pages still fires (the fix must not silence the chore)
- [ ] The lineage field is emitted and normalized by the same path that owns `publish-globally`
- [ ] Measured: a post-split conflict pass costs ~0 tokens instead of ~221k

## Approval log

- 2026-08-12T21:00:24+0200 — FILED at `todo` by janitor-main-session (tier 0, own scope).
  Deliberately not started: it needs a page-schema addition, and the session that found it is
  running at ~398k weighted tokens per heartbeat fire (TRDD-WP7TCRME's measurement), which is
  the most expensive possible context in which to design a schema change.
