---
trdd-id: WN7M829Y
title: The janitor background chore retroactively repairs malformed atoms via supersession
column: todo
created: 2026-07-23T06:35:11+0200
updated: 2026-08-13T12:58:00+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
severity: medium
relevant-rules: [1]
npt: [DOJ2LE1G]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-08-13

**RE-MEASURED 2026-08-13 12:5x, first-hand (`memgrep lint` per scope). The 2026-08-02 numbers
below are 11 days stale in BOTH directions:**

| scope | 2026-08-02 | now | |
|---|---|---|---|
| LOCAL | 0 | **0** | held |
| PROJECT | 0 ("fully clean, 8/8 decomposed") | **2** | **REGRESSED** |
| USER | 22 remaining | **10** | drained, uncredited |

USER quietly drained 22 → 10 and nobody updated the card. PROJECT went 0 → 2, so this is **not a
backlog that empties** — it REFILLS.

### Why it refills, verified in the code rather than assumed

`atom_max_chars()` (memory.rs:3788, default 1500) is referenced from exactly ONE place —
memory.rs:4553, inside the LINT path. There is no write-time check anywhere: `add-atom` will
create a 3000-char atom without complaint. And the finding is deliberately **INFO**, pinned by a
test whose own message says why: *"atom-oversized must be INFO, not WARN — no chore gate can ever
act on it (janitor#200)"*.

Put together, the three facts are a closed loop: **nothing prevents creation, the detection tier is
chosen so no automation may act, and the only thing that clears the backlog is a hand-dispatched
agent batch.** So every measurement of "how many oversized atoms remain" is a snapshot of how long
it has been since someone ran a batch — which is exactly what the table above shows, and why this
card has been re-measured three times and never closed.

**That reframes the card.** "Retroactively repair" is treating a symptom on a schedule nobody
keeps. The candidate fixes are different in kind and should be chosen deliberately, not drifted
into:

  1. **Refuse at write time** — `add-atom`/`add-lesson` reject an over-budget body and tell the
     author to split. Stops the refill at the source; costs an author friction they cannot defer.
  2. **Raise the tier so a chore CAN act** — directly contradicts janitor#200's ratified reasoning
     (INFO because an oversized atom is a style debt, not an actionable defect). Needs that
     decision revisited on its merits, not quietly reversed.
  3. **Accept it as permanent style debt** and close this card — legitimate, and cheaper than
     either of the above, provided it is a DECISION rather than the current default of
     re-measuring forever.

All three are USER/design calls, so none is taken here. What IS settled is that the current shape
cannot converge, and the card should stop being scheduled as if it will.

## ⏵ STATE (superseded) — 2026-08-02

**2026-08-02 20:15 — USER BATCH 1 VERIFIED: 33→22 (11 done, 0 flagged).** Count re-checked
first-hand via `memgrep lint`; no pending transactions; touched pages gained no new findings.
Remaining: **22 USER atoms in 2 more batches — HELD by the burn throttle** (5h window at 1.5×
pace; resume after the ~22:40 reset per `.janitor/state/resume-directive.txt`). Report:
`reports/janitor-memory-subconscious-agent/20260802_195003+0200-wn7m829y-oversized-pass3-user-b1.md`.

**2026-08-02 19:45 — PASS 2a VERIFIED: LOCAL 1→0.** The page the verifier defect blocked
(`reference_publish_cargo_clippy_bindgen_flaky.md`) decomposed clean on the first try after
`c05ab942` — the fix is proven end-to-end, not just in the unit test. PROJECT and LOCAL are
now **fully clean (8/8 decomposed, 0 flagged remaining)**. Remaining: USER scope's 33, in
~3 bounded batches (batch 1 dispatched this turn). Report:
`reports/janitor-memory-subconscious-agent/20260802_193740+0200-wn7m829y-oversized-pass2a.md`.

**2026-08-02 20:25 — PASS 1 VERIFIED; VERIFIER DEFECT IT FOUND IS FIXED; PASS 2a DISPATCHED.**
Pass 1 result, re-verified first-hand (`memgrep lint` counts + `git show 834f9e2` — memory
files only): **PROJECT 2→0** (committed `834f9e2`), **LOCAL 6→1** (7/8 decomposed, all
oracle-gated, no fact/lesson lost). The 1 flagged page exposed a REAL pre-existing verifier
defect, minimally reproduced and FIXED in `c05ab942`: `load_bearing_tokens` extracted a
line-wrapped numeric-unit token with a literal `\n` while `_token_haystack` collapses
whitespace — so a byte-identical NO-OP failed `fact_tokens_preserved`, permanently blocking
atomize/repair on any page with a wrapped "N unit" phrase. Tokens are now normalized with the
haystack's own collapse (regression test proves real mutations are still caught); the flagged
page's no-op now passes (verified live). Pass 2a (that 1 LOCAL page) dispatched. **USER's 33
remain — deliberately NOT one giant pass** (pass 1 cost ~347k agent tokens for 8 atoms; 33 in
one run would blow the agent's window): queue ~3 bounded batches on subsequent turns.
Report: `reports/janitor-memory-subconscious-agent/20260802_192922+0200-wn7m829y-oversized-pass1.md`.

**2026-08-02 19:35 — RE-MEASURED + FIRST BOUNDED PASS DISPATCHED (`column: dev`).**
Fresh `memgrep lint` across all three scopes: the mechanical classes are CLEAN —
0 unquoted-desc (the 4 from 2026-07-23 already fixed), 0 empty-lesson-body,
0 superseded-without-body (the DOJ2LE1G gate holds). What remains is exactly the
judgment class: **41 `atom-oversized`** — 6 LOCAL + 2 PROJECT + 33 USER. Dispatched the
`janitor-memory-subconscious-agent` (background, user-visible in the session reply — the
card's "user aware" condition) on the SMALL, recoverable scopes first: PROJECT (2,
git-tracked) + LOCAL (6). Policy per this card: decompose via txn-gated atomize/`migrate`
(the VJCMZ2OP verb, hardened today with malformed-props + already-on-dest pre-flights),
lessons travel with their atom, verify lossless, NEVER delete; a page it cannot prove
lossless is FLAGGED, not forced. USER's 33 wait for the next batch, judged on this one's
report. Older context below.

## ⏵ prior STATE — 2026-07-23

**NPT DOJ2LE1G is DONE + LIVE** (add-lesson --supersedes + the 4 lint checks + binary
installed), so the retroactive repair is now UNBLOCKED and TOOLING-READY. This is the only
remaining piece of the wikimem-authoring plan; Phases 1/2/3 shipped.

**Scope corrected while implementing (do NOT hack the scheduler):** the four defect classes do
NOT map cleanly onto the existing repair/atomize passes, so `repair_has_work` must NOT be
extended to flag them — that would dispatch repair passes that cannot fix them (churn):
- `unquoted-desc` — mechanically fixable (quote the value). REPAIR-class.
- `oversized-atom` (36 corpus-wide) — DECOMPOSITION, judgment-heavy; not a repair fix. Needs the
  atomize pass OR `memgrep migrate` to split one atom into several — a NEW editorial capability.
- `empty-lesson-body` / `superseded-without-body` — may be UNRECOVERABLE (the old body/why can be
  gone). Where recoverable, supersede; where not, the honest fix is to flag for a human, not invent.

**So the retroactive sweep is genuine EDITORIAL-AGENT work with real shared-corpus blast radius,
not more scheduler code.** The corpus currently carries **36 oversized + 4 unquoted-desc** (0
empty-lesson-body, 0 superseded-without-body — the new gate keeps it that way going forward).

**NEXT ACTION (run deliberately, ideally with the user aware — shared memory):** dispatch the
`janitor-memory-subconscious-agent` on a bounded scope with a per-class policy —
unquoted-desc → in-place repair (quote); oversized → decompose via atomize/`migrate` (judgment);
empty/superseded-without-body → supersede if the old fact is recoverable, else flag. Surface
progress; never delete an atom. This is the piece to do with the USER in the loop, not a silent
autonomous batch. Detection is already available (`memgrep lint <scope>` flags all four).

## The ask

The malformed atoms already in the corpus (unquoted `desc`, body-less lesson, oversized atom,
superseded-without-body) must be FIXED retroactively by the background janitor memory chore —
never by deleting them. A wrong atom gets `status: superseded` + a lesson reference that
embeds its verbatim old body; only pure typos / formatting errors may be edited in place.

## The fix (this TRDD's scope)

1. **Detect.** `scripts/detectors/wikimem-syntax.py` + `scripts/wikimem_syntax_lint.py` gain
   the four defect classes from DOJ2LE1G, so a malformed atom SURFACES as drift (never
   mutating anything — the detector only reports).
2. **Repair.** The `janitor-memory-subconscious-agent` REPAIR/ATOMIZE passes (the
   `janitor-memory-{repair,atomize}` skills) act on the due scope:
   - a pure typo / formatting error (e.g. a missing quote the write verbs would have added) →
     an in-place REPAIR transaction (`--op repair`), which `verify_repair` proves lossless;
   - a WRONG fact → the supersession protocol: `add-lesson --supersedes <atom>` demotes the
     atom and records the correction as a dated lesson. NEVER a delete.
   - an OVERSIZED atom → decompose into smaller atoms via an ATOMIZE/split transaction, with
     the lessons travelling to the correct child atom (VJCMZ2OP / the `migrate` verb).
3. **Prove it.** Every repair is a `memory_txn` transaction gated by the `verify_*` oracle in
   `memory_edit_verify.py`; the pass ends with `memgrep validate && memgrep lint` on each
   touched page. A pass that cannot prove no-knowledge-lost ABORTS and flags for a human.

## Boundary

The chore FIXES what the deterministic oracle can prove safe and FLAGS the rest — it never
deletes an atom, never invents a `WHY` for a supersession it cannot source, and never
reorganises structure beyond the flagged defect (that is the separation-of-powers rule: the
janitor reorganises + surfaces, the agent corrects content).

## Verification

- A seeded corpus with one of each defect class: the detector surfaces all four; the repair
  pass fixes the typo in place and supersedes the wrong-fact atom (old body preserved).
- No atom is ever deleted by the pass (grep the transaction journal for deletes → only
  merge/split-legitimate ones).
- `verify_repair` / `verify_atomize` green on every applied transaction; `pytest` + `ruff`
  green.

## Notes and lessons learned

## Approval log

- 2026-08-12T15:39:16+0200 — RE-COLUMNED dev → todo by janitor-main-session. A WORK column
  asserts active work; nobody was working this (idle 10d). Its "blocker" is a stale in-session
  note ("HELD by the burn throttle… resume after the ~22:40 reset") from 2026-08-02 — that
  window closed 10 days ago. No scope or acceptance changed.
