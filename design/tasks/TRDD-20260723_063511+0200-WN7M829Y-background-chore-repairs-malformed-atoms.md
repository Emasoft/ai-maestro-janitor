---
trdd-id: WN7M829Y
title: The janitor background chore retroactively repairs malformed atoms via supersession
column: human_review
created: 2026-07-23T06:35:11+0200
updated: 2026-08-16T02:19:48+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
severity: medium
relevant-rules: [1]
npt: [DOJ2LE1G]
---

## ⏵ STATE — 2026-08-16: FOURTH MEASUREMENT, and most of the apparent explosion is NOT decay

**Re-columned `todo` → `human_review`.** The 2026-08-13 block below already concluded that all
three candidate fixes are USER/design calls and that "the card should stop being scheduled as if it
will converge". Leaving it in `todo` kept scheduling it exactly that way. It is a decision card now;
`human_review` is the ratified column for that.

**The heartbeat reports `memgrep lint: 240 finding(s)` against this card's 50 three days ago. Do
NOT read that as 5× decay — I upgraded the linter tonight.** The binary the 2026-08-13 measurement
used was `a685cca` (2026-08-07); tonight's is `a698f16`, 13 crate commits later (TRDD-9XMPS8OZ).
Checked which codes that binary could even emit, with `git merge-base --is-ancestor`:

| code | PROJECT | USER | comparable to 08-13? |
|---|---|---|---|
| `publish-globally-missing` | 44 | 0 | **NO** — introduced by `9ddb3cf7`, not in the old binary |
| `atom-after-footer` | 40 | 51 | **NO** — moved to the Rust linter in `5c09ffdc`, not in the old binary |
| `link-one-sided` | 0 | 67 | **NO** — the rule existed, but `88390fc2` ("per-page lint can finally see the cross-page rules") is not in the old binary |
| `lesson-uncited` | 8 | 15 | yes — **23 → 23, flat** |
| `atom-oversized` | 4 | 11 | yes — **12 → 15, refilled** |

So **135 of the 240 findings were structurally invisible three days ago**. They are newly VISIBLE
debt, not newly created debt, and any "the corpus is rotting fast" conclusion drawn from the
headline number is an artifact of measuring with a better instrument.

**What survives the correction, and it is the card's own thesis:** `atom-oversized` went 12 → 15
with nothing draining it, and `lesson-uncited` sat exactly flat at 23. Neither converges on its
own. That is the third independent confirmation, and it is now made on a like-for-like basis rather
than on a total that changed meaning underneath it.

**Related, filed tonight: TRDD-3K8SVX2H.** Part of the `atom-oversized` count is unfixable by
construction — `lint` reports it against bodies under `## Superseded`, which the protocol forbids
editing. Any option chosen below should net that class out first, or the backlog it is measured
against can never reach zero.

**Method note worth keeping.** Two of the three wrong turns in taking this measurement were the
harness, not the data: `memgrep lint` writes findings to **stderr** (a `2>/dev/null` silently
produced an empty, clean-looking result), and in zsh a shell variable named `path` is tied to
`$PATH`, so `dir=${s#*:}` works while `path=${s#*:}` destroys the environment mid-loop. A
measurement that comes back suspiciously clean deserves the harness checked before the conclusion.

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

### 2026-08-13 13:5x — the pattern is BROADER than this card's four classes

A heartbeat surfaced `memgrep lint: 50 findings, none at or above ERROR`. Broken down first-hand:

| code | PROJECT | USER | tracked by |
|---|---|---|---|
| `lesson-uncited` | 8 | 15 | `janitor-memory-update` skill |
| `link-one-sided` | 0 | 15 | same — and it violates the stated **LINK LAW** (every link bidirectional) |
| `atom-oversized` | 2 | 10 | **this card** |

**`atom-oversized` is 2 + 10 — byte-identical to the re-measurement above.** Nothing drained it
in the intervening hour, which is one more confirmation that it does not drain by itself.

**⚠ CORRECTION, same session, 14:0x — "the INFO tier" is the wrong cause for PROJECT.** I traced
the scheduler rather than leaving that as inference, and the two scopes fail for DIFFERENT
reasons:

- **PROJECT — deliberately gated OFF, not tier-limited.** `memory-maintenance.py::_scopes_in_play`
  drops PROJECT unless the `edit_project_scope` setting is opted into; it is currently `False`.
  Its stated reason: PROJECT memory is in-repo and unpushable outside `publish.py`. Verified
  end-to-end: `_first_due_intervention("PROJECT", …)` returns **`split`** (due AND has work), the
  scheduler ran 30 min ago, and the dispatch log shows **12 dispatches 08-06 → 08-11, every one
  LOCAL or USER, zero PROJECT — ever**. So PROJECT's 10 findings are not evidence of a broken
  drain; they are the visible cost of a switch nobody turned on.
- **USER — the tier explanation stands.** Chores DID run there 3–16 h ago and its 40 findings
  survived, so there the chore genuinely does not act on these codes.

**This adds a FOURTH option, and it is the USER's, not mine:** flipping `edit_project_scope` to
true would let the chores drain PROJECT. It is deliberately not flipped here — it authorises an
automated agent to edit git-tracked, PUSHED memory, which is exactly the kind of consent the
gate exists to obtain. No defect was found; the investigation's result is that the system behaves
as designed and the design has an off switch in the way.

**The other 30 findings — the part the tier argument DOES cover.** `lesson-uncited` and `link-one-sided` are NOT
among this card's four defect classes, yet they exhibit the identical structure: nothing refuses
them at write time, they are emitted at INFO so no chore gate may act, and only a hand-dispatched
agent batch clears them. So the closed loop this card documents is not a property of *oversized
atoms* — it is a property of **the INFO tier itself**. That materially strengthens option 1
(refuse at write time), because a write-time gate generalises to all three codes while a
per-class agent batch has to be re-run forever, per class.

Not filed as a separate card: both codes are already defined in
`design/specs/wikimem-memgrep-spec.md` and acted on by `skills/janitor-memory-update`, so a new
card would duplicate existing coverage rather than add any.

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
