---
trdd-id: E8LNOXLQ
title: merge-protocol.md tells the agent to do what memory_txn_cli.py unconditionally rejects
column: complete
created: 2026-07-22T13:48:23+0200
updated: 2026-08-12T14:26:05+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
severity: medium
relevant-rules: [1]
---

## The defect

`skills/janitor-memory-consolidate/references/merge-protocol.md` contradicts itself, and
its operative instruction is the one the CLI refuses. Both halves landed in the SAME
commit (`62e1043`, 2026-06-19) — this is not a partial patch that drifted, it shipped
inconsistent.

| where | says |
|---|---|
| `merge-protocol.md:52-57` | *"Two writes for a merge is an error"* — then, same paragraph: *"Backlink-holder pages you also copied into staging and edited count as **additional** writes — that is fine and expected"* |
| `merge-protocol.md:113-115` | *"copy each holder page into the staging dir, replace `[[B]]` with the survivor's slug, **let it ride as an extra write**"* |
| `merge-protocol.md:150-156` | a worked example doing exactly that (`cp "$LOCAL_MEM/oauth-rotator-hub.md" "$STAGING/…"`) |
| `scripts/memory_txn_cli.py:169-171` | `if len(writes) != 1: raise MemoryTxnError("merge expects exactly ONE surviving page, found N write(s)")` |

The CLI counts **all** staged writes. It cannot distinguish a merge source from a
backlink holder, so a holder edited in the merge txn is unconditionally rejected.

## Why it matters

The LINK LAW makes this path common, not exotic: retiring slug `B` dangles every page
that linked `[[B]]`, and `no_dangling_refs` blocks the commit until they are repointed.
So every merge with at least one backlink holder — which is most of them, since
same-subject pages are usually cross-linked — hits this. The agent follows the reference
doc, stages the holder, and burns a rejected commit before discovering the contract.

Observed twice, by two independent passes:

- 2026-07-21 (`reports/memory-subconscious-agent/20260721_102701+0200-consolidate-feedback-osascript-merge.md`)
  hit it and worked around it with a **separate, prior `--op repair` txn** for the holder,
  then the merge txn with exactly one write. That workaround is correct and satisfies
  `no_dangling_refs` at merge-commit time — it just is not what the doc says.
- 2026-07-17 (`…-consolidate-local-scope-user-claude-accounts.md`) avoided it only because
  its single backlink was self-referential post-merge.

## Two candidate fixes — decide, do not do both

1. **Correct the doc** to prescribe the prior-`--op repair` sequence the 07-21 pass proved
   works, and delete the "extra write" language + the worked example. Cheapest, no code
   risk, keeps the CLI's shape check strict.
2. **Relax the CLI** to require exactly one write *among the declared merge sources* while
   allowing non-source holder writes. Matches what the doc already promises and lets a
   merge + its redirects be one atomic transaction — which is the stronger invariant,
   since the prior-repair workaround leaves a window where the holder points at a slug
   that still exists but is about to be retired.

Option 2 is better on the merits and needs care: `_verify_merge` would have to learn which
staged paths are sources, and `verify_merge`'s dangling-ref check must still see the
holder's new content.

## Verification

- A merge with one backlink holder completes in ONE transaction (option 2) or the doc's
  sequence runs clean as written (option 1).
- `no_dangling_refs` still fails a merge that leaves a holder unrepointed.
- Full `uv run pytest` + `ruff check` green.

## Notes and lessons learned

[^1]: [id:ATOM-E8LN-0001, status:valid, keywords:"reference_doc_contradicts_the_tool documented_pattern_rejected_by_cli burned_commit_retry same_commit_shipped_both", ocd:2026-07-22, lmd:2026-07-22]
  DO NOT trust a skill's own reference doc as the contract when a script enforces the
  real one, BECAUSE `merge-protocol.md` both states "two writes is an error" AND
  instructs the agent to add an extra holder write — both from commit `62e1043` — so an
  agent following it burns a rejected commit on the most common merge shape. DO read the
  enforcing code's check (`_verify_merge`) before following prose that describes a
  tool's accepted input.

## Approval log

- 2026-08-12T14:26:05+0200 — COMPLETE by janitor-main-session. Surfaced by `trdd-drift`
  (backburner, 21d untouched) and closed on evidence, NOT implemented: **the defect no longer
  exists.** Option 1 was taken by some later change to the reference doc, so the contradiction
  this card describes is gone. Verified at HEAD, both halves:
  - `merge-protocol.md` now states "**a backlink holder canNOT ride along in the merge
    transaction**", prescribes TWO transactions holder-FIRST, and explicitly retracts the old
    claim ("an earlier revision of this paragraph claimed holder rewrites were 'fine and
    expected'; that was never true of the code");
  - the CLI check it contradicted is unchanged and still there
    (`memory_txn_cli.py`: "merge expects exactly ONE surviving page").
  Doc and code now agree, in the CLI's favour.

  **Option 2 (relax the CLI so a merge + its redirects are ONE atomic txn) is deliberately NOT
  carded.** It was the better invariant on the merits, but with option 1 applied it is an
  enhancement, not a defect: the only cost left is a transient window between the holder-repair
  commit and the merge commit, inside a single chore run. Buying that back means loosening the
  shape check on the memory-transaction safety substrate — a poor trade for a window nothing has
  been observed to lose data in. Revisit only if a real failure is seen.

  **The finding worth carrying:** this card had sat 21 days describing a defect that had already
  been fixed elsewhere, and its own line numbers had drifted (`memory_txn_cli.py:169-171` is now
  a different function). Nothing re-checks whether a parked card's PREMISE still holds — the
  drift detector measures AGE, which says "old", not "wrong". Checking the premise cost two greps
  and replaced an afternoon of implementing a fix for a problem that no longer existed.
