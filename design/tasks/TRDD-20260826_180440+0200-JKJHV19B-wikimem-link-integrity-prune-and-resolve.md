---
trdd-id: JKJHV19B
title: Wikimem link integrity — prune stale and duplicate links, resolve dangling ones
column: backburner
created: 2026-08-26T18:04:40+0200
updated: 2026-08-28T06:49:44+0200
current-owner: janitor-main-session
task-type: feature
project-id: ai-maestro-janitor
scope: project
severity: major
min-approval-requirement: none
labels: [wikimem, memgrep, memory-maintenance, links]
parent-trdd: 87RKBYJ8
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# Duties 16-17 — link integrity in the wikimem editor

## ⏵ 2026-08-26 22:15 — THE CHORE IS NOT THE DELIVERABLE. The corpus has ZERO defects for it.

Advisor consulted (Fable 5) on where the candidate query belongs. Its verdict corrected my
proposal — enumeration in Rust, but as a QUERY VERB, never a `lint` rule, because a rule whose
majority honest outcome is KEEP fires forever and destroys the "gate and arbiter identical ⇒ the
chore terminates" property that makes `enrich` work. It also split box 1's unsolved filter
correctly: code-span masking is mechanical and **already shipped** (`mask_inline_code`,
`memory.rs:4061`), while "a sentence ABOUT linking" is agent judgment that belongs in the refusal
ledger, not in the tool.

**Then the measurement made most of that moot, and this is the finding.** The verb it told me to
build **already exists** — `memgrep links --broken` — and nobody had run it across all three
scope roots at once:

| run | result |
|---|---|
| box 1's hand-built Python query, one root at a time | **98** non-resolving |
| `memgrep links --broken` over all THREE roots | **8** |

And of those 8: **4 are `[[ATOM-…]]` links whose atoms all EXIST** (verified: every one is a
defined marker), 1 is the prose placeholder `TRDD-id`, and 3 are forward refs this card already
decided KEEP. **Actionable defects: ZERO.** Duty 17's CREATE fired zero times out of 98 in box 2
and zero out of 8 here.

**⚠ The two counts of `8` are NOT the same set** — `diff` says so. Scanning PROJECT alone gives 8
(cross-scope targets like `debugging-methodology`, which lives in USER); scanning all three gives a
DIFFERENT 8. I nearly read the equal totals as "the roots make no difference", which is precisely
tonight's peer-exchange lesson arriving a third time: two equal numbers are not one set.

### So the shipped work is a 20-line fix, not a chore

`links --broken` answers *"does a target FILE exist"*. An atom is addressable but is not a file,
so every atom link returns `[BROKEN]` — correct for the question asked, wrong for the question the
finding then claims to answer. `memory-librarian._index_corpus` indexed only page slugs (stem +
`name:`), so those 4 fell through `_classify_broken_link`'s unresolved branch and were reported as
*"a forward reference … or a rename casualty"* — advice whose literal reading is **write a page
named `ATOM-9E4P-KYW5`**. Four live false findings on every librarian run, each proposing to
create a page for an atom that already exists.

Fixed by widening what RESOLVES (`_note_slugs` now also indexes body-atom anchors and lesson
`id:`s, fence-aware) rather than by teaching the reader to ignore a finding. Verified on the real
corpus: all 4 index, a phantom control does not.

**This is the same defect class as everything else measured today** — an instrument answering a
different question than the sentence asks — and it is the third instance in one evening.

### What is left of the chore

Nothing to fix means the chore's value is preventing FUTURE rot, not clearing present rot, which
is a much weaker case than the card was written on. Boxes 3-4 stay open deliberately: the honest
next increment is the refusal-ledger design the advisor described (gate = memgrep's dangling list
MINUS ledger), and it should be started only when the corpus actually accumulates candidates.
Building a transaction-core pass now would be machinery with no input.

Split out of **TRDD-87RKBYJ8** (the spec + reconciliation ledger) per its own rule: the remaining
gap rows become their own cards when their turn comes, and are never implemented under the parent
id. **This is the next increment** — the parent's audit put 16-17 immediately after the four
already-terminal children (57WJL5L2, AZ6QRK0D, J3ZH3RSI, 3SOO1RWE).

## The two duties, verbatim from the parent

16. EDIT / POLISH the references + links to other wikimem pages and atoms; PRUNE the ones that are
    duplicated or point to outdated pages that no longer exist.
17. If a link/hyperlink is DANGLING (no corresponding page or atom), CREATE the missing page or
    atom.

## Why these two are ONE card and not two

They are the two halves of one decision made per link. Reaching a dangling `[[link]]`, the pass
must choose between PRUNE (16) and CREATE (17), and the choice needs the same evidence in both
cases — what the link was reaching for, whether any other page already covers it, whether the
target was renamed or genuinely never existed. Splitting them would put the two outcomes of a
single judgment in different cards and guarantee that one of them is implemented without the
other, leaving a pass that can only ever delete or only ever create.

## ⚠ The hazard that makes this NOT a mechanical sweep

**A dangling link is not automatically a defect.** The memory protocol says so explicitly: a
`[[name]]` that does not match an existing memory *"is fine — it marks something worth writing
later, not an error"*. So a pass that resolves every dangling link by deletion destroys exactly
the forward-references the protocol asks authors to leave, and a pass that resolves them all by
creation manufactures empty pages nobody wrote.

That is the whole design problem of this card, and it is why the parent deferred it rather than
scripting it. The distinguishing evidence is not in the link — it is in whether the SUBJECT the
link names is one the corpus should hold.

## What already exists (verify before building — the parent's own lesson)

- `memgrep lint` already reports `link-one-sided` (measured today: it flagged a real one-sided
  link within minutes of a peer's write, and the LINK LAW fix was a one-line back-link).
- `memgrep links --to / --from` exists; note `reference_memgrep_links_to_from_semantics` records
  that its direction reads inverted to newcomers.
- The transaction core (`memory_txn` / `memory_edit_verify`) already proves no knowledge is lost,
  and `verify_repair` is the right verifier shape — an edit here is one write at the page's own
  path, exactly like a repair.

So the missing piece is the DECISION procedure and its candidate query, not the machinery.

## ⏵ 2026-08-26 19:00 — CANDIDATE QUERY BUILT AND RUN; 10 defects FIXED; the rest is judgment

Acceptance box 1 is done, and it produced a taxonomy rather than a list — which is the point,
because a flat "98 dangling links" would have been 73% noise.

**Raw query over all three scope roots: 262 pages, 884 resolving page links, 98 non-resolving.**
Classified:

| class | n | verdict |
|---|---|---|
| 1 · PROSE *about* links — `[[wikilink]]`, `[[link]]`, `[[links]]` | **72** | NOT defects. Pages discussing the wiki syntax, e.g. "wire both ends of a `[[wikilink]]`" |
| 2 · `.md` extension, target exists (`[[foo.md]]` vs page `foo`) | **9** | mechanical — **FIXED** |
| 3 · separator mismatch (`-` vs `_`), target exists | **1** | mechanical — **FIXED** |
| 4 · genuinely missing subject | **19** refs / 12 names | the judgment call this card is for |

**Class 1 is the finding that matters for the eventual implementation.** Three quarters of a
naive dangling-link report is prose that merely spells a wikilink. A pass that "resolves dangling
links" without this filter would have rewritten or deleted 72 pieces of correct writing — and it
would have looked like it was doing its job. The candidate query MUST exclude prose-mention
targets, and the exclusion list is short and stable (`wikilink(s)`, `wikilinked`, `link(s)`,
`wikimem`, `name`, `page`).

**Classes 2 and 3 are fixed** — 10 links, each provably safe because the target page exists under
a trivially different spelling. Done through `memgrep edit --replace-all` per page; LOCAL scope
now lints 0, USER 2 (pre-existing `atom-oversized`, unrelated).

**Class 4 — as box 1 reported it, 12 distinct missing subjects:**
`who-verifies-and-closes-work` · `project-ai-maestro-janitor-oauth-rotator` ·
`reference_memory_system_integration` · `universal-plugins-ignore-aimaestro-instruction-set` ·
`what-ai-maestro-is` · `security-act-dont-ask` · `removal-blast-radius` ·
`agent-claims-the-api-was-never-delivered` · `claim-verification` ·
`governance-ssot-is-the-governance-rules-branch` · `B` · `Note`.

**⚠ SUPERSEDED — see the 19:40 section below. Half of that list is wrong, and the two entries it
was most confident about ("junk … the only two that should simply be PRUNED") are both correct
prose that pruning would have damaged.**

### A duplicate page found while fixing, worth its own attention

`feedback_memory_dual_test_evaluation.md` exists in **BOTH** LOCAL and USER scope with different
content — a genuine cross-scope duplicate, i.e. duty 10/11 territory (TRDD-E7D4QPH1). Found only
because the fix failed on the USER copy and succeeded on the LOCAL one. Not touched here beyond
the link fix; recorded so E7D4QPH1 starts with a real instance instead of a hypothetical.

## ⏵ 2026-08-26 18:36 — THE DECISION MADE PER LINK; box 1's list was 50% false, all one direction

Every one of the 12 was checked against the corpus rather than trusted. **Six were not defects at
all**, and the reason each was false is a distinct blind spot in the box-1 query — so the finding
is not "the list had errors", it is **three separate ways a link-resolution query lies**:

| # | name | verdict | why box 1 was wrong |
|---|---|---|---|
| 1 | `who-verifies-and-closes-work` | **EXISTS** | the query was **non-recursive** — the page is in a `wikimem/` SUBDIR |
| 2 | `removal-blast-radius` | **EXISTS** | same subdir blind spot |
| 3 | `security-act-dont-ask` | **EXISTS** | the query resolved by **FILENAME**; a page's identity is its frontmatter `name:` (file `feedback_security_act_dont_ask`, name `security-act-dont-ask`) |
| 4 | `governance-ssot-is-the-governance-rules-branch` | **PHANTOM** | zero occurrences anywhere in the corpus — the list itself carried a name nothing references |
| 5 | `B` | **KEEP (prose)** | placeholder in *"when a merge folds page A into page B, every `[[B]]` link read as dangling"* — the janitor#183 write-up |
| 6 | `Note` | **KEEP (prose)** | already inside a code span: *"values may be `[[Note]]` links or `^block-ref` references"* |

**The two blind spots that matter for the eventual pass**, because both are silent:

- **Recursion.** 4 real pages live in `wikimem/` subdirs (1 LOCAL, 3 USER) — invisible to a
  top-level scan, fully visible to `memgrep`. A pass that "resolved" #1 and #2 by CREATE would have
  manufactured duplicates of pages that already exist — the exact cross-scope duplicate mess duty
  10/11 exists to clean up. **The most destructive outcome available, reached by trying to help.**
- **Identity.** `name:` ≠ filename stem on **4 pages** (measured corpus-wide; all LOCAL `feedback_*`).
  Small, but it only takes one to turn a live link into a phantom hole.
- And the prose filter's shape is unsound: box 1 excluded an **allowlist** of placeholder words
  (`wikilink`, `link`, `page`, `name`…). `B` and `Note` slipped through because a writer may reach
  for any word. The test must be **structural** — is the `[[…]]` inside a code span or in a sentence
  *about* linking — never a name list.

### The six real ones, decided, with the reason recorded

| name | outcome | reason |
|---|---|---|
| `project-ai-maestro-janitor-oauth-rotator` | **RETARGET** → `feedback_oauth_rotator_resume_protocol` | a stale name for a page the SAME file already links two lines below; back-link present, so the LINK LAW held on the fix |
| `claim-verification` | **PRUNE** → `` `~/.claude/rules/claim-verification.md` `` | **cross-namespace**: the subject is a global RULE file, not a memory page, so the wikilink can never resolve |
| `reference_memory_system_integration` | **KEEP** | forward ref to a rollout tracker — board/TRDD territory, not a memory subject |
| `universal-plugins-ignore-aimaestro-instruction-set` | **KEEP** | sanctioned forward ref |
| `what-ai-maestro-is` | **KEEP** | sanctioned forward ref |
| `agent-claims-the-api-was-never-delivered` | **KEEP** | forward ref to a case page worth writing |

Both edits applied through `memgrep edit`; `validate` NONE and `lint` 0 findings on both pages.

### What this settles about the duty pair itself

**CREATE fired ZERO times out of 98 candidates.** Duty 17 — *"if a link is dangling, CREATE the
missing page"* — has no instance in the real corpus. Meanwhile the outcomes that DID fire are
`KEEP` (4), `RETARGET` (1), `PRUNE-as-wrong-namespace` (1), `DE-LINK` (2 prose), and — six times,
more than any real outcome — **"your query is wrong"**.

So the pass this card was scoped to build would have spent its whole duty-17 half on a case that
never occurs, while the dominant outcome is one the duty pair does not name at all. That is the
finding, and it should change the shape of the implementation rather than be filed as trivia: the
expensive, careful part is **the candidate query**, not the decision. Get the query right and the
decision is six easy judgments; get it wrong and a confident pass damages correct writing in three
different ways while reporting success.

## Acceptance

- [x] A candidate query that lists, per page: duplicated links, links to non-existent pages, and
      links whose target exists but no longer covers the subject. **Built and run** — see the
      taxonomy above; the load-bearing part is excluding prose-mention targets (72 of 98)
- [x] The PRUNE/CREATE decision is made per link with a recorded reason, and a deliberate
      forward-reference is a THIRD outcome (KEEP) — a pass that cannot express KEEP is wrong by
      construction. **Done for all 12, in the 19:40 table — and KEEP was the majority verdict
      (4 of 6 real), which is the box's own premise confirmed against the corpus rather than
      assumed.** The outcome set is SIX, not three: `KEEP · RETARGET · PRUNE · DE-LINK · CREATE ·
      not-a-defect`. `CREATE` fired zero times; `not-a-defect` fired six.
- [ ] Every edit goes through the transaction core; `verify_repair` proves no lesson or atom is
      lost
- [ ] A test drives a page carrying one duplicate link, one dangling forward-reference, and one
      link to a deleted page, and asserts exactly one prune, one keep, one create/repair — the
      three outcomes must be distinguishable or the pass has no decision in it.

      **AMENDED 2026-08-26 by the box-2 measurement — that fixture would pass while the pass stays
      broken.** It exercises only the three outcomes the duty pair names, and box 2 measured that
      `CREATE` never fires on the real corpus while the dominant outcome is `not-a-defect`, which
      the fixture cannot even express. The test that actually pins this pass must ALSO carry:
      a page in a **subdirectory** (catches the non-recursive walk), a page whose frontmatter
      `name:` differs from its filename (catches resolution by filename), and a `[[Placeholder]]`
      in prose using a word no allowlist contains (catches the lexical filter). Each of those
      three produced a false defect in the real run; none of them is visible in a fixture built
      from the duty text.
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`

## Notes and lessons learned

The LINK LAW ("every link is bidirectional — wire both ends in the same edit") is the standing
rule this duty enforces retroactively. Measured 2026-08-26: a peer agent that had that rule in its
own loaded context still wired one end, and `memgrep lint` caught it — evidence that the automated
half is the reliable half here, and the reason this card should lean on lint's finding set rather
than on a fresh scanner.

## ⏵ 2026-08-28 — `todo` → `backburner`, with the precondition stated

Re-verified the shipped half FIRST-HAND rather than trusting this card's own claim:
`_note_slugs` (`scripts/detectors/memory-librarian.py:1364`) does index body-atom anchors AND
lesson `id:`s, fence-aware, exactly as recorded — and 86 librarian tests pass. So the four live
false findings this card was really about are gone.

**Why backburner and not todo:** `todo` asserts ready-to-start work. The remaining boxes 3-4 are
the refusal-ledger pass, and this card's own measurement says the corpus has **zero** candidates
for it — building a transaction-core pass now would be machinery with no input. That is a
deliberate park, not a stall.

**PRECONDITION to un-park (the stated one `trdd-drift` honours):** `memgrep links --broken` over
all three scope roots reports a dangling link that is NOT (a) an `[[ATOM-…]]` whose atom exists,
(b) the `TRDD-id` prose placeholder, or (c) a forward reference this card already decided to KEEP.
The first genuine candidate is the signal to start; until then there is nothing to arbitrate.

