---
trdd-id: MQBV844P
title: CONSOLIDATE can never merge two cross-linked pages — no_dangling_refs and body_facts_preserved are mutually unsatisfiable, and the LINK LAW guarantees every merge candidate is cross-linked
column: todo
created: 2026-07-14T14:11:05+0200
updated: 2026-08-02T07:34:00+0200
current-owner: janitor-session
task-type: bugfix
scope: project
severity: high
labels: [wikimem, memory-maintenance, verify-oracle]
relevant-rules: [1]
---

# The two merge gates contradict each other, so CONSOLIDATE can never merge

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-02

### 2026-08-02 — the DECISION is still yours; the one decision-INDEPENDENT item is done

Pulled during a board drain and deliberately **not implemented**. The NEXT ACTION below is a
choice between (a)/(b)/(c) on the memory system's ANTI-CORRUPTION gate, and this card's own
argument for why an agent must not make it unsupervised is correct and stands: from outside,
*"I relaxed `body_facts_preserved` and now the merge passes"* is exactly what a wrong fix looks
like. It stays in `todo`, awaiting the user.

**What WAS done — the stale doc, fixed, because it is false under all three options.** The card
noted `merge-page-rules.md` still claims the verifier does not guard body facts. Verified against
the code rather than taken on the card's word: `body_facts_preserved` is real
(`memory_edit_verify.py:304`) and IS wired into `verify_merge` (:899). A SECOND site said the same
thing and the card had not spotted it — `merge-protocol.md`, under *"What the catalog does NOT
cover"*, even reproduced the reasoning issue #48 overturned (*"a strict body-superset check would
false-fail on every legitimate dedup"*). Both told an editing agent it is the sole guard of body
facts, which is the opposite of true, on the very pages an agent reads before merging.

Corrected to what the check actually does, limits included rather than simply inverted: substring
(not line-equality) matching, which is precisely what answers the old dedup objection — a deduped
fact still appears once, so it still matches, while a dropped or paraphrased one does not; and a
fact demoted into a `[^N]` lesson counts as preserved, because the haystack is the whole page.
**The agent's own duty is narrowed, not removed:** the net is COARSE and has two blind spots BY
DESIGN — lines under 24 chars and every `#` heading — which is the documented issue-#91 shape,
where a split condensed prose into shorter, WRONG path bullets and nothing caught it. Short-form
facts and the lead remain the editor's.

This changes no gate and prejudges none of (a)/(b)/(c).

## ⏵ STATE — 2026-07-14 (the analysis; unchanged)

**The defect (PROVEN, not inferred).** For a merge of pages A+B (survivor B, retiring A), where B
carries a `[[A]]` wikilink in body prose:

| merge strategy | `body_facts_preserved` | `no_dangling_refs` |
|---|---|---|
| keep the `[[A]]` pointer verbatim | PASS | **FAIL** (`B -> [[A]]`) |
| delete the pointer line | **FAIL** (dropped body fact) | PASS |
| redirect the pointer to `[[B]]` | **FAIL** (paraphrased body fact) | PASS |

There is **no** output that satisfies both. The gates disagree about what a merge MEANS:
`no_dangling_refs` says a link to a retired slug MUST become a link to its survivor;
`body_facts_preserved` (issue #48 hardening) says that line may not change by a single byte. Verified
by running the real functions from `scripts/lib/memory_edit_verify.py` against all three candidates.

**Why this is HIGH and not an edge case.** The wikimem **LINK LAW** ("every link is bidirectional —
if A links to B, B links to A") GUARANTEES that any two pages related enough to be merge candidates
are cross-linked. Two pages that own the SAME subject — the only pages CONSOLIDATE ever merges — are
the most cross-linked pages in the corpus. So the deadlock is not reachable-in-principle: it is the
**common case**. **CONSOLIDATE can never merge the very pages it exists to merge.**

And it fails SILENTLY: the pass ABSTAINS, correctly and quietly, on every run. Nothing is corrupted,
nothing is logged as broken — the duplicate subject simply persists forever and the scheduler burns a
pass rediscovering the same blockage. (This is the SECOND instance of the "an abstain is a finding"
lesson in two days — see LOCAL TRDD-FJ1TAI3Y `[^1]`, whose type-gate abstain was the FIRST. The first
abstain hid a real defect in the DATA; this one hides a real defect in the CODE.)

**How it surfaced:** TRDD-FJ1TAI3Y steps 1+2 fixed the account-roster pages' type mismatch and their
stale content, so `is_legal_merge` finally returned `(True, "ok")` — and the merge promptly hit this
SECOND, deeper gate. Step 1 and 2 were necessary and correct; they just revealed the next layer. The
memory agent opened the transaction, built the best-case candidate, got exactly one `verify_merge`
failure, and cleanly `abort`-ed — **zero mutation, live tree byte-identical**. The crash-safe core did
its job perfectly; the oracle it was protecting is the thing that is wrong.

**PROPOSED FIX (NOT implemented — needs the USER's call, see below): verify MODULO the mandated
redirect.** Before substring-matching, canonicalize wikilinks that point at a slug retired BY THIS
MERGE to point at the survivor — in BOTH the source needles AND the result haystack. Then the
"redirect" strategy passes both gates, and the two oracles finally agree on what a merge is. Every
other character of every body line must still survive VERBATIM, so the anti-corruption guarantee that
issue #48 bought is untouched: this permits exactly the one edit `no_dangling_refs` already mandates,
and nothing else.

**Why this needs the USER and is not mine to ship.** It edits the memory system's ANTI-CORRUPTION
gate. The standing instruction on these oracles is *"do NOT 'fix' this by loosening the verifier"* —
and from the outside, "I relaxed body_facts_preserved and now the merge passes" is EXACTLY what a
wrong fix looks like. The distinction I am claiming (reconciling two contradictory gates vs. weakening
one) is real, but it is precisely the kind of claim an agent should not get to make about a safety
gate unsupervised. **The alternative reading is legitimate and must be considered: perhaps the merge
SHOULD be impossible here, and the right move is to keep both pages and simply drop the duplicate
subject law for cross-linked pairs.**

**NEXT ACTION:** USER decides between:
  (a) **Reconcile the gates** (canonicalize retired→survivor links before comparison) — restores
      CONSOLIDATE, keeps byte-for-byte strictness on all other content. My recommendation.
  (b) **Exempt pointer-only lines** from `body_facts_preserved` in a merge — narrower, but needs a
      "is this line ONLY structural glue" predicate, which is fuzzy and could drop a real fact riding
      on the same line ("The token lives in the keychain; see also [[X]]."). I do NOT recommend it.
  (c) **Accept it** — CONSOLIDATE never merges cross-linked pages; the corpus tolerates duplicate
      subjects. Then say so explicitly and make the pass REPORT the deadlock instead of abstaining
      silently, so the scheduler stops rediscovering it.
Then implement with a falsification test (the 3-candidate table above IS the test).

**Load-bearing facts / gotchas:**
- The `[^N]` LESSON case is strictly worse than the body case: `lessons_preserved` requires the WHOLE
  lesson body as one continuous byte-identical substring, so a lesson containing a `[[retired]]` link
  is FLATLY unfixable by any edit. Whatever fix lands must cover lessons, not just body lines.
- Do NOT "fix" this by making the executor delete the cross-link on each page in a separate REPAIR
  pass first (the workaround the consolidate agent suggested). It destroys a REAL bidirectional link
  that the LINK LAW mandates, it must be repeated before EVERY future merge, and `verify_repair`
  likely imposes the same byte-for-byte tension on the lesson-embedded link anyway. It trades a code
  bug for permanent corpus damage.
- The `merge-page-rules.md` skill doc still claims "verify guards lessons, NOT body facts". That is
  STALE — issue #48 added `body_facts_preserved`. Fix the doc alongside whatever lands here.

## Verification

1. The 3-candidate table above, as a unit test over the real oracles: after the fix, the "redirect"
   row must pass BOTH gates; the "keep verbatim" row must still fail `no_dangling_refs`; the "delete"
   row must still fail `body_facts_preserved` (dropping a fact is still a drop).
2. A lesson carrying a `[[retired]]` link must merge cleanly (the strictly-worse case above).
3. **Falsify:** a merge that ACTUALLY drops or paraphrases a real body fact (one with no retired-slug
   link in it) MUST still fail. If it doesn't, the fix weakened the gate and is wrong.
4. Re-run the real TRDD-FJ1TAI3Y pair end-to-end; it must merge with zero knowledge lost.

## Notes and lessons learned

[^1]: [ocd:2026-07-14 lmd:2026-07-14] Two guards, each individually correct, can compose into a system
  that cannot act. Neither `no_dangling_refs` nor `body_facts_preserved` is wrong on its own terms —
  they are wrong TOGETHER, because they encode incompatible beliefs about whether a merge may rewrite
  a link. Nobody tested them as a pair, so the contradiction shipped and then hid behind an abstain.
  Lesson: when two independent invariants constrain the same edit, the thing to test is not each
  invariant but their INTERSECTION — prove that at least one legal output still exists. A verifier
  suite with an empty solution space is indistinguishable, from the outside, from work that is simply
  never needed.
