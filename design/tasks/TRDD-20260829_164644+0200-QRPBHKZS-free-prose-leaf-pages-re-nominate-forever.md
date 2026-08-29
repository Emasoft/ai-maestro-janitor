---
trdd-id: QRPBHKZS
title: free-prose leaf pages re-nominate every 7 days and cost ~200k tokens to decline each time
column: backburner
blocked-by: []
created: 2026-08-29T16:46:44+0200
updated: 2026-08-29T16:46:44+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 3
severity: MEDIUM
effort: M
min-approval-requirement: none
task-type: bugfix
labels: [memory, chore, candidate-gating, cost]
release-via: publish
test-requirements: [unit]
external-refs: [TRDD-JPL0JU86, janitor#249]
---

# TRDD-QRPBHKZS — a structural "no" is re-asked every 7 days at ~200k tokens a time

Split out of **TRDD-JPL0JU86** on 2026-08-29, which measured this while deciding a different
question and correctly refused to fold it in.

## The measurement

A `[janitor-memory-atomize]` marker fired 2026-08-26. The agent claimed USER scope, was handed
**5 candidates — all `debugging-methodology-*` navigation/map stubs** produced by earlier splits,
read each in full, and declined all 5 as `free-prose-leaf-no-distinct-facts`: pure map pages whose
facts and lessons all live on the sub-pages they link to.

**The verdict was CORRECT. The correct null result cost 208,696 subagent tokens and 13 tool
calls.** The refusal then self-expires after 7 days, so the same 5 pages re-nominate and the same
~200k is spent reaching the same answer — indefinitely.

## Why the expiry is the defect

A refusal expires because the usual reason a page is not a candidate is *contingent*: nothing to
do **today**, but tomorrow's edit could change that. Re-asking is right for those.

These are not those. A split-generated map page holds no durable facts **by construction** — that
is what makes it a map — and it is precisely the kind of page that does not change. So a
7-day expiry re-asks a question whose answer is STRUCTURAL, and pays full price each time.

The general shape, worth stating because it will recur: **an expiring cache in front of an answer
that cannot change is not a cache, it is a scheduled re-computation.**

## Scope

1. **Let a refusal declare itself structural.** The agent already distinguishes
   `free-prose-leaf-no-distinct-facts` from a contingent "nothing due". A refusal carrying a
   structural reason should not expire on a timer — only on the page's CONTENT changing, which
   the corpus already tracks (`lmd`, and the content precheck's own hash).
2. **Prefer cheap over durable where both work.** A predicate that recognises a facts-free map
   page from the page itself is better than any marker, because it costs nothing to maintain and
   cannot go stale. Reach for the marker only for what a predicate genuinely cannot see.
3. **Do not extend JPL0JU86's mechanism to cover this.** That card ratified option A for a
   different population (symlinked pages a guard refuses), and warned that conflating the two
   could silence a page that merely has nothing to do today. Same warning applies here: the
   silencing predicate must key on "holds no durable facts", never on "was declined before".

## What NOT to do

- **Do not simply lengthen the 7-day expiry.** That trades the cost rate for the staleness
  window without fixing either — the same defect shape as pricing a bound in the wrong unit.
- **Do not have the agent decline earlier to save tokens.** janitor#260 forbids an agent
  substituting its own measurement for the scheduler's precheck, and it is right to: that is how
  real work gets skipped. The fix belongs in the EMITTER, which is the party that can be tested.

## Acceptance

- [ ] A structural refusal survives until the page's content changes, rather than 7 days.
- [ ] The 5 `debugging-methodology-*` map pages stop re-nominating for `atomize`.
- [ ] A page that was declined for a CONTINGENT reason still re-nominates on the old cadence.
- [ ] Regression test: two refusals, one structural and one contingent, expire differently.

## Notes and lessons learned

- 2026-08-29 — **A correct answer that costs 200k tokens and is thrown away is a defect, even
  though nothing malfunctioned.** Every component behaved as designed: the emitter nominated, the
  agent read carefully, the verdict was right, the refusal was recorded. The loss is entirely in
  the RETENTION policy, which is the one place nobody was looking because nothing there errored.
  **Ask of any expiring negative result: can the answer actually change? If not, the expiry is
  a scheduled re-computation wearing a cache's clothes.**
