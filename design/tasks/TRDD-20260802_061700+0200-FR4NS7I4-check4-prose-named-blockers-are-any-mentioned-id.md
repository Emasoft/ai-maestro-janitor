---
trdd-id: FR4NS7I4
title: check4 reads every TRDD id mentioned on a held card as one of its blockers
column: testing
created: 2026-08-02T06:17:00+0200
updated: 2026-08-02T06:52:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
severity: LOW
scope: project
release-via: publish
relevant-rules: []
implementation-commits: []
---

# check4 reads every TRDD id mentioned on a held card as one of its blockers

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

### 2026-08-02 — FIXED the same session it was filed (`todo → testing`)

**The open boundary question is answered by evidence, not taste: PARAGRAPH, not line.** The card
below warned that a card writing its blocker on one line and the id on the next is the shape most
likely to regress. It is not hypothetical — it is the corpus's ONLY true positive:
TRDD-3XS3PDCF's *"HARVEST precheck stays BLOCKED (not merely deferred) … see TRDD-ab232dbd"*
wraps across two lines. A same-line rule would have dropped the one case the widening exists for,
so the scope is the blank-line-separated paragraph.

**Measured on the live corpus before writing any code**, both ways over every card:

| | prose-named candidates |
|---|---|
| whole-body (before) | **52** |
| paragraph-scoped (after) | **23** |

and on the two open cards that motivated it, TRDD-2C8XFOW9 goes **4 → 0** and TRDD-AM8JD9SG
**8 → 0**, while TRDD-3XS3PDCF still yields `ab232dbd`. Board-wide the reconciler now reports
**zero** stale-blockers, and every one it stopped reporting was a reuse citation.

**Implementation.** `_paragraph_spans(text)` returns offsets, not substrings, so the match runs on
the MASKED body and the ids are read from the ORIGINAL one — legitimate only because
`_mask_inline_code` is length-preserving, which is now stated at its definition so a future
"optimisation" to deletion cannot silently break the slicing.

**The frontmatter path is untouched** — a declared `blocked-by:` is authoritative whatever the body
says, pinned by its own test so a later narrowing of the prose path cannot bleed into it.

Tests: 3 added (true positive spanning lines; citation in another paragraph; frontmatter-only), the
second confirmed failing first with `['3b9b2040', 'aebedbff'] == []`. 57 in `test_trdd_common.py`,
187 across the TRDD suite, **14062 full-suite**, ruff clean.

Remaining: rides the next publish. `release-via: publish` ⇒ terminal column will be `published`.

**Precision noise, not a wrong close** — this is the sibling finding of TRDD-N7NZOYAK (which
was a correctness bug and is fixed). Filed separately per rule 13: different mechanism,
different check, different severity. Nothing is mis-closed by it; a real card just carries a
permanent phantom finding, which is the way a rarely-firing signal becomes background noise
nobody reads.

## The defect

`scripts/lib/trdd_common.py::check4_stale_blockers` widens its candidate set beyond
`blocked-by:`:

```python
if _BLOCKED_PROSE_RE.search(_mask_inline_code(record.body)):
    for uid in extract_trdd_refs(record.body):
        if uid not in candidates and uid != record.uid:
            candidates.append(uid)
```

The two conditions are evaluated over the **whole body**, independently: *does this card's
prose carry block-language ANYWHERE* and *does it mention a TRDD id ANYWHERE*. Nothing requires the
two to be near each other, so on a card that is legitimately held, **every** id it cites —
a sibling, a superseded card, a thing to reuse — is treated as one of its blockers, and each
one that has since gone terminal is reported as a cleared blocker to act on.

**Live instance (2026-08-02):** TRDD-2C8XFOW9 is correctly `column: blocked` with
`blocked-by: [ai-maestro#75]`, and reports EQ792YPX and T7N67AQP as stale blockers. Both are
citations to REUSE — 2C8XFOW9 is the EHT of EQ792YPX, and it takes the per-pane presence gate
from T7N67AQP. Their being `published` is exactly what makes them reusable. There is nothing
to unblock and the report cannot be made to go away by fixing the card, because the card is
already right.

## Why it is only LOW

It over-fires, never under-fires: it cannot hide a real cleared blocker, only add ones that
were never blockers. And `check4`'s output is advisory — "blocker cleared; re-evaluate" — with
the reconciler explicitly SURFACE-ONLY (it mutates no TRDD). The cost is a human or agent
re-deriving "no, those were reuse citations" on every sweep, on a card where that has now been
written down once.

## Sketch of a fix (do not treat as decided)

Require **proximity**: promote a prose-named id only when it appears on the same line as, or
within a sentence of, the block-language match — the same discrimination `check3` already
applies by masking inline code. That keeps the case the widening was for (`BLOCKED-on
TRDD-XXXX` written in prose but never encoded in `blocked-by:`) and drops the case it was
never for (a citation elsewhere in a long body).

Watch the boundary before changing it: a card that writes its blocker on one line and the id
on the next is the shape most likely to regress, so the regression tests must include both
`blocked-on <id>` on ONE line and the same words split across TWO lines, and state which one
the new rule intends to keep.

## Verification

- A card with block-prose and an unrelated terminal TRDD citation far from it ⇒ NOT reported
  (fails today, using 2C8XFOW9's real shape).
- A card whose prose says `blocked-on TRDD-XXXX` with XXXX terminal ⇒ still reported.
- A card with a terminal id in `blocked-by:` ⇒ still reported, regardless of prose.
- Re-run over the live board: the stale-blocker count should drop to the cards that name a
  blocker deliberately, and no card that named one should stop being reported.

## Notes and lessons learned
