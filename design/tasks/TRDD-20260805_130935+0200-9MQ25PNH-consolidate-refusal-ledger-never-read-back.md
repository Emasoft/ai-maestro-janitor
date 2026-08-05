---
trdd-id: 9MQ25PNH
title: memory-consolidate re-dispatches already-refused candidates because its refusal ledger is written but never read back
column: todo
created: 2026-08-05T13:09:35+0200
updated: 2026-08-05T13:09:35+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
relevant-rules: []
blocked-by: []
implementation-commits: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**Not started.** The defect is MEASURED and the mechanism is VERIFIED in code; what is open is
which of the three fixes to take. This card exists because two agent reports carried a decision
and reports are gitignored/ephemeral — the decision had to survive them.

**NEXT ACTION:** implement the **refusal-aware fingerprint** (option 3, made precise in the
2026-08-05 section below — option 1 alone was investigated and is UNSOUND). Concretely:
`corpus_fingerprint(root)` gains a way to exclude pages covered by a live refusal, and
`consolidate_has_work` compares that narrowed fingerprint. Then the two acceptance tests.

The design is settled and grounded in the live ledger + proposal file; what remains is the edit
and its tests. Do NOT re-derive the candidate model — it is written down below with the evidence.

## The finding

`memory-consolidate` pays a full agent dispatch — **~279k weighted tokens** — to re-judge
candidates a previous dispatch already judged and declined, because its gate does not consult the
refusal ledger it writes.

Measured on this host, two consecutive dispatches, both **ABSTAINED**:

| when | scope | weighted tokens | outcome | evidence |
|---|---|---:|---|---|
| 2026-08-04 | LOCAL | (this run's report) | abstained — no new merge candidate | `reports/memory-subconscious-agent/20260804_121403+0200-consolidate-local.md` |
| 2026-08-05 | USER | 279,646 | abstained — corpus already well-split | `reports/janitor-memory-subconscious-agent/20260805_095753+0200-consolidate-USER.md` |

The LOCAL report is explicit that its survey re-derived a verdict already on file: it lists four
pages *"already surveyed in full and recorded as 4 DISTINCT subjects"* in the refusal ledger, and
then surveyed them again anyway.

For the cost comparison that makes this worth fixing rather than tolerating: the `conflict` chore
dispatched the same day cost **278,860** and DID do work. **An abstention costs within 0.3% of a
working dispatch** — so "the agent correctly decided there was nothing to do" is not a saving, and
tuning the agent's judgement cannot help. The only lever is not dispatching.

## Verified mechanism — the two chores are gated differently

- **`conflict` IS refusal-gated.** `conflict_has_work` consults the surfaced pairs, and 3 of 4
  candidate pairs were skipped as already-refused on the 2026-08-05 run.
- **`consolidate` is gated on a CORPUS FINGERPRINT.** `memory_content_precheck.consolidate_has_work`
  takes `last_fingerprint` from `corpus_fingerprint(root)` — a stat-only hash over the candidate
  corpus. `memory_refusals.record()` is called, but **nothing reads it back for this chore.**

**Verified in code, not inferred** (2026-08-05): `memory_refusals.is_refused(...)` appears at
`memory_content_precheck.py:372` for `"repair"` and `:570` for `"conflict"` — and **nowhere for
`"consolidate"`**. `consolidate_has_work`'s signature is `(root, *, last_fingerprint, stamp_age_s,
recheck_after_s)`: it has no parameter through which a refusal could even be passed.

**Pre-empting the objection this card will meet.** `consolidate_has_work`'s own docstring states the
fingerprint is *"the only sound way to gate consolidate"*, and argues correctly that a
subject-overlap/keyword proxy is unsound in both directions (the skill's contract needs the *same
subject*, "not merely sharing keywords"). **Option 1 below is not a keyword proxy** and that
argument does not reach it: replaying a stored *agent verdict* about an unchanged candidate is the
same kind of evidence the fingerprint gate already trusts — a prior read of identical bytes — just
scoped to the candidate instead of the whole corpus. It is strictly stronger for the same reason:
a refusal carries a `content_hash` over the candidates' own bytes, so it survives unrelated edits
elsewhere that needlessly flip a corpus-wide fingerprint.

The same docstring already concedes the failure this card is about — *"the gate passes, an agent
spawns (~260k tokens), and then ABSTAINS on subject, which the structural gate never examined."*
That was written as a known limitation; the measurements below are what it costs in practice.

So any byte changing anywhere in the candidate corpus flips the fingerprint and re-opens the whole
dispatch, even when every candidate inside it was individually adjudicated minutes earlier. The two
gates answer different questions — *"has the corpus changed?"* vs *"is this candidate still
refused?"* — and only the first is being asked.

This is also self-aggravating: the memory chores WRITE to the corpus, so a productive `conflict`
or `atomize` run changes the fingerprint and thereby re-opens `consolidate`.

## 2026-08-05, later — OPTION 1 AS WRITTEN IS UNSOUND. Take option 3, in the specific form below.

Grounded in the real ledger and the real proposal file, not in the card's original guess.

**What the candidates actually are.** Consolidate refusals are NOT keyed on this gate's
`(tier, type)` structural pairs. They are keyed on the **librarian's aggregation candidates** —
whole groups. Verified from the live ledger:

```
USER   a-regression-test-must-be-verified-to-fail.md|debugging-methodology-verify-before-concluding.md|…  (6 pages)
USER   macos-keychain-access-inheritance.md|macos-keychain-locking.md                                     (2 pages)
LOCAL  feedback_oauth_rotator_design_directives.md|reference_oauth_renew_browser_transport_solution.md|…  (4 pages)
```

Those keys are byte-for-byte the page lists in the `### Aggregation candidates` bullets
(`- topic \`oauth+renew+rotator\` (4 notes): a.md, b.md, …`) under each `## <SCOPE> scope` heading.
So a `conflict_has_work`-style filter is directly implementable: the parser constants
(`_SCOPE_HEADING_RE`, `_NO_CANDIDATES_SENTINEL`) already exist; it needs an
`### Aggregation candidates` heading constant, a bullet regex, and an
`aggregation_candidates(root, scope)` mirroring `conflict_pairs`.

**But the conflict pattern must NOT be copied wholesale, and this is the trap.** `conflict_has_work`
treats an ABSENT/empty proposal as *idle* — legitimate, because the conflict skill's own
precondition says "Empty/absent → stop". **Consolidate does not stop there.** Its report shows a
second discovery path: *"Also manually surveyed the most-recently-touched pages in the scope"*. So
for consolidate, "every librarian candidate is refused" does **not** imply idle — a corpus change
elsewhere could have created a candidate the librarian has not yet surfaced.

**Therefore the sound gate is a REFUSAL-AWARE FINGERPRINT** (option 3, made precise):

> Compute the corpus fingerprint over only those pages **not covered by a live refusal**. Suppress
> when that narrowed fingerprint is unchanged since the last dispatch.

Why this is sound where option 1 alone is not:
- A page under a live refusal has already been judged, so excluding it from the fingerprint stops an
  unrelated edit elsewhere from re-opening a settled group.
- If a refused page's own bytes change, `memory_refusals` invalidates that refusal on its
  `content_hash`, the page re-enters the fingerprint, and the chore re-arms — automatically.
- Any genuinely new or edited page is outside every refusal, so it still moves the fingerprint and
  still re-arms — which preserves the manual-survey path the report documents.

N: do NOT implement plain option 1 (suppress when all surfaced candidates are refused). It would
silently disable the agent's self-survey, which is a real discovery path, and the failure would be
invisible — a missed merge looks exactly like no merge.

## Options (pick one)

1. **Read the ledger back.** Make `consolidate_has_work` return false when every *live* candidate
   is covered by an unexpired refusal whose `content_hash` still matches — the fingerprint then
   only decides whether to RECHECK, not whether to DISPATCH. Most faithful; the ledger already
   stores exactly what is needed (`memory_refusals.refusal()` takes paths + a content hash).
2. **Fingerprint the CANDIDATES, not the corpus.** Narrow `corpus_fingerprint` to the bytes of the
   pages that are actually candidates, so unrelated edits do not re-open the chore. Cheaper, but
   still re-dispatches whenever a candidate is touched for an unrelated reason.
3. **Both** — (2) reduces the trigger rate, (1) makes the remaining triggers cheap. Likely correct.

N: do NOT "fix" this by lowering the consolidate cadence. That trades a wrong dispatch for a missed
one and leaves the mechanism intact.

## Derived / related

- **janitor#140** carries the measurements and the mechanism distinction (posted 2026-08-05).
- **janitor#108** is the same cost class from the other side (per-agent cache-write floor).
- **janitor#200** — a neighbouring scheduler gap: `atom-oversized` has NO owning gate at all, so it
  can never dispatch. Together the two show the gate layer is under-tested in both directions: one
  chore that fires when it should not, one finding that can never fire at all.
- `TRDD-b4b9e27c` (wikimem scheduler) is `column: complete` and therefore FROZEN — this card exists
  instead of extending it. Do not reopen that one.

## Acceptance

- [ ] An unchanged, already-refused candidate set does NOT re-dispatch `consolidate` after an
      unrelated byte changes elsewhere in the corpus. (Test asserts the gate, not the agent.)
- [ ] A candidate whose CONTENT changed since its refusal DOES re-dispatch (the refusal is
      conditioned on content, so it must expire when the content moves).
- [ ] The chosen option is recorded here with its reasoning, not just implemented.
- [ ] Measured before/after dispatch counts over a fixed window, both taken the same way.
