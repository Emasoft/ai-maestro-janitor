# Split planning — detailed mechanics

Reference for step 3 of the SPLIT algorithm. See the main skill for the full
algorithm context and invariants.

## Finding the single page to split — the exclusion list

The `find` in SKILL.md step 1 walks every real NOTE in the scope strictly larger than the
cap, biggest first, EXCLUDING the non-note set (mirrors the librarian's
`_NON_NOTE_NAMES`): the staging dir; the PRIVATE `user-mem/` store (never scan it —
privacy); and the generated/index files `MEMORY.md` / `memory-index.md` /
`memory-reorg-proposed.md`. `-printf` is GNU-only and breaks on BSD/macOS find, so
size+sort portably via `wc -c` instead.

## 3. Plan the split (decide the seams; preserve type and every fact)

Group the page's `##` content sections into **2–4 coherent sub-topics**, one per
sub-page. Then design the outputs:

> **3a. Synthesize seams first (seamless oversized page — the fail-safe path).**
> When the page has fewer than 2 natural `##` seams, MANUFACTURE them before
> grouping — never abstain:
> 1. Split the body into blank-line-separated paragraphs. Group consecutive
>    paragraphs into **2–4 chunks**, each comfortably under the cap, cut at a
>    coherent topic boundary. Head each chunk with a synthetic
>    `## Part N — <2–4 word topic>` derived from its content.
> 2. If the body has NO blank-line breaks (one unbroken blob), hard-chunk at
>    **line boundaries** (never mid-line) into N under-cap pieces, each headed
>    `## Part N (continued)`.
>
> Copy every body line **VERBATIM** into exactly one chunk — only the `## Part N`
> headings are new. (`body_facts_preserved` FAILS on any reworded or dropped
> line, so synthesis is partition-and-label, never paraphrase.) Then treat the
> synthesized `## Part N` sections exactly like natural seams below. This is what
> makes split **fail-safe**: an over-cap hub/aspect ALWAYS converges.

- **Overview page** — REUSE the source's path/slug (keeps the page's identity,
  frontmatter `name`, `ocd`, `tier`) and make it a concise map: OPEN with a
  one-sentence **lead** naming the subject (wikimem-model → Page anatomy → "The
  lead"), then one tight summary line per sub-page, each with a `[[sub-page-slug]]`
  link (the link law — the overview links DOWN to every sub-page). Move the bulk
  detail OUT to the sub-pages; the overview is a navigation surface, not a dumping
  ground. A stray `[^N]` lesson may stay (verify folds it in), but the natural home
  for lessons is the sub-page that owns the topic.
- **Sub-pages** — one new `.md` per sub-topic, slug = `<source-slug>-<subtopic>`
  (kebab-case). **Preserve type:** each carries the SAME `metadata.type` as the
  source and a `tier` consistent with it (`hub`→sub-pages stay `hub` or the
  appropriate child tier per the model; an `aspect`→sub-aspects stay `aspect`).
  Each sub-page links UP to the overview (`## Governed by` /
  `See also: [[overview-slug]]`) and the overview links DOWN to it — wire BOTH
  ends in the same edit. Each MUST include the mandatory
  `## Notes and lessons learned` section.
- **Carry every fact and every `[^N]` lesson** from the source into exactly one
  sub-page (or the overview) — nothing dropped, nothing reworded; the split verb
  moves lesson bodies and their `[ocd:… lmd:…]` prefixes byte-for-byte. The write
  gate REFUSES any dropped or silently-reworded lesson (nothing lands).
- **Hub globs partition (hubs only):** if the source is `tier: hub` with a
  `globs:` list, distribute those patterns across the sub-pages so their union
  equals the parent set with NO overlap (each pattern has exactly one owning
  sub-page). A non-hub source has no globs to partition.
- **Size:** every output page (overview + each sub-page) should end up at or under
  the cap. If a natural sub-topic is itself still over the cap, that sub-page is
  fine for THIS run — the next heartbeat splits it further. Convergence only
  requires real progress this level.

## Claim exit codes

`memory_dispatch_claim.py --chore split --state-dir "$STATE_DIR"` reports its
outcome via exit status: **2** = nothing claimable right now; **3** = no
memory-maintenance state at all (`$STATE_DIR` is wrong); **4** = `$STATE_DIR` was
empty; **5** = the dispatch was recorded for a different state dir, so the claim
was refused. Any of these, an unreadable result, or a printed chore name other than
`split` means STOP and report — never pick a scope yourself, never re-derive what
is due (the stamp already advanced when the marker was emitted), and never read the
legacy `memory-maint-pending.json` slot.

## Why never guess the scope

Two documented incidents: janitor#242 — a `consolidate` overwrote an in-flight
`repair`'s authority 367 s later on the same root, which is why the dispatch claim
renames the record out of the pool atomically. And #150 — on 2026-07-30 a
dispatched `conflict` pass could not read its assignment file, re-derived cadence
on its own, ran USER instead, and left the stamped LOCAL scope marked
run-without-running for a full cadence: 378k tokens, zero mutations. An abstain
that says *"dispatched but could not read my assignment"* is cheap and
actionable; a confident run on the wrong scope is neither.

## Why `memgrep links --from` takes the slug, not the rel-path

`memgrep` matches the note NEEDLE against the BASENAME/stem only, never a path
substring, so a rel-path containing `/` can NEVER match and backlinks come back
silently empty — always pass `$(basename "$REL" .md)`, never `$REL`.

## Backlink-redirect mechanics

**The split verb touches exactly its own pages.** `split-mem-topic --page S --into N`
rewires the S⇄N pair only (See-also both ways). A backlink HOLDER whose `[[S]]` pointed
at moved detail is repointed with its OWN `reference-mem-topic --page <holder> --to
<sub-page>` call (step 5) — one gated write, both ends wired, no staged copy, no hand
edit. Keeping the source slug as the overview retires nothing, but redirecting
moved-detail backlinks is still the correct editorial act, so do it.

## Hard invariants (every SPLIT pass enforces)

- **Verb-gated** — every write goes through the memgrep write verbs' shared gate;
  a refusal writes nothing. Never edit a live page by hand.
- **No information lost** — union(overview, sub-pages) ⊇ every fact + every `[^N]`
  lesson of the source, copied verbatim (lessons byte-identical).
- **Type & tier preserved** — sub-pages keep the source's `metadata.type`; a
  component is never fragmented; one element = one page.
- **Connected** — overview links DOWN to every sub-page, each sub-page links UP
  (the split verb wires each pair both ways); moved-detail backlinks redirected
  via `reference-mem-topic`; zero dangling/one-sided links.
- **Bounded & disable-able** — one page, one level per run; recursion across
  heartbeats; honors the kill-switch and `split_per_day: 0`.

Each is mechanically checked by the memgrep write gate before the batch lands,
so a pass that would violate one is refused rather than landing a half-split
page — the invariants are enforced, not merely documented.

## Size rule (e) — headroom, and why it is a rule rather than a preference

**Never emit a sub-page within ~10% of `split_max_bytes`** (≈32,400 B at the 36,000 default).
Prefer one more seam over one nearly-full sibling.

A sibling that lands just under the cap is re-split by the very next atom added to it — and
**every split MINTS NEW PAGE NAMES.** Conflict refusals are keyed by root-relative PATH
(`scripts/lib/memory_refusals.py::candidate_key`), so new names void every refusal recorded for
that family, and the `conflict` chore re-judges it from scratch.

Measured (janitor#241 / TRDD-RG4IUZ6I): one such null pass cost **221,612 subagent tokens for
zero mutations**, and the sibling that caused it sat **279 bytes** under the cap. Re-measured
2026-08-13: that page is **35,724 B against 36,000 — 276 bytes of headroom**, so the next edit
to it repeats the whole cycle.

Splitting right up to the cap is not efficient use of space; it schedules the next expensive
re-litigation. (The durable fix — explicit split lineage so siblings are never conflict
candidates at all — is TRDD-3QIQ2E6J; this rule stands whichever card ships.)

## Decomposing an over-budget atom

The atom half of this chore (TRDD-VOWAUVE5, USER ruling 2026-08-22). Step 1 of the skill
runs it when no page is over cap; these are the rules that make it safe.

**Ask memgrep, never measure it yourself.** `memgrep lint "$SCOPE_ROOT" | grep -F
'[atom-oversized]'` prints `INFO <abs-path>:<line> [atom-oversized] — atom body is N chars
(> BUDGET) …`. Both the budget (`MEMGREP_ATOM_MAX_CHARS`) and the atom SEGMENTATION that
decides where one body ends live inside the crate, so any second opinion is a second source
of truth. That is the janitor#227 shape — a gate dispatching work its arbiter cannot confirm
re-dispatches an agent forever — and it has already been paid for once in this codebase.

**Decomposition preserves every fact; it only changes how many atoms carry them.** Never
shorten the prose to fit the budget, and never edit the page directly. For a plain two-way
split, `memgrep split-mem-atom` does it in one call — it divides the atom's `[^N]` refs by
which half's prose cites them and leaves the first atom's marker untouched, so there is
nothing to retire. For a split into 3+ pieces, write the new atoms through `memgrep
new-mem-atom` (was: `add-atom`) so the parser synthesises each element and a malformed atom
is impossible by construction.

**Give each new atom its own `keywords:`, drawn from the SYMPTOM phrases a future session
will search with** — not from the words the prose happens to use. Recall ranks on
`description + title + keywords`, never the body, so an atom nobody can recall is worse than
an oversized one: splitting a findable atom into three unfindable ones is a net loss.

**On the `new-mem-atom` path, retire the original with `memgrep update-mem-atom --lesson --atom
<id> --supersedes` (same atom id)** when it stated something now spread across the new atoms.
Never overwrite it — supersession is what keeps the old statement readable as dated history
instead of deleting knowledge. (Not needed on the `split-mem-atom` path — see above.)

**No transaction, deliberately.** The memgrep write verbs are already scope-locked and
CAS-guarded, so they carry the full crash-safety themselves.

**Verify before you finish.** Re-run the lint line; an unverified decomposition that left the
atom over budget re-dispatches this chore forever, which is the failure the write-side gate
was originally built to prevent.

**An atom that CANNOT be brought under budget without losing fidelity is judged ONCE.** A
verbatim owner quote or a quoted multi-step procedure (the page's own lesson often says "do not
decompose") is a legitimate over-budget atom. Skip it, and when EVERY over-budget atom left on
the page is of that kind, record it so the gate stops re-dispatching (janitor#326):

```bash
uv run --script "$PLUGIN/scripts/memory_refusal_cli.py" record \
  --intervention split-atom --scope "$SCOPE" --root "$SCOPE_ROOT" \
  --page "$PAGE" --reason "<one line: which atom(s), why they cannot be shortened>"
```

This refusal is page-granular and never expires on a clock: it re-arms only when the page's
bytes change. Before picking an atom, skip pages that `memory_refusal_cli.py check
--intervention split-atom …` reports as refused. Record only when no decomposable over-budget
atom remains on the page, or the next over-budget atom would never be judged.

**The `## Superseded` carve-out applies exactly as it does to the write gate**: a body below
that delimiter is protocol-frozen history. Leave it alone even when it is over budget —
rewriting retired facts destroys the record they exist to be.

## Splitting an atom that holds two topics

The size decomposition above fires on `MEMGREP_ATOM_MAX_CHARS`. This one fires on an atom
holding TWO SUBJECTS **at any size**, and the two are independent properties: do NOT implement
this by lowering the size threshold — that would make the size rule fire on well-formed long
atoms while still missing every short two-topic one (TRDD-3AKSYZRV).

**The candidate list is a TRIAGE surface, never an assertion.** Its predicate is purely
structural — an atom whose body has ≥2 non-blank lines AND an internal paragraph break — which
says only that the author already treated the atom as more than one unit of thought. Deciding
that those units are two SUBJECTS is a judgement, which is exactly why this is an agent duty and
not a `memgrep lint` rule: a rule whose majority honest outcome is KEEP fires forever and never
converges. Measured on this repo's PROJECT corpus: 159 atoms, 127 pass the ≥2-line floor alone,
78 also have a paragraph break.

Read the named atom in full, then answer one question: **does it state two distinct facts a
future `recall` would want to find separately?**

### YES — split it by topic

```bash
memgrep split-mem-atom --page "$PAGE" --atom "$ATOM" \
  --at "<literal substring where the second topic starts>" \
  --desc "<the second topic's own triage sentence>" \
  --keywords "<the second topic's own phrases>" \
  --orig-keywords "<the first topic's own phrases>" \
  --orig-desc "<the first topic's own triage sentence>" \
  [--lessons-to-new <comma-separated footnote labels>]
```

`--orig-keywords` / `--orig-desc` are **mandatory here and absent from a size split**, and the
asymmetry is the whole point. The original atom's `keywords:` were written to serve BOTH
subjects, so leaving them alone hands the first half a recall surface half of which describes
the fact that just moved out — and `recall` ranks on keywords alone, so the first atom keeps
answering queries about the topic that left. Both halves are held to the same keyword floor: a
topic split that leaves one side with two keyphrases has traded one unfindable atom for two.

`--lessons-to-new` names ONLY the footnote labels whose lesson belongs to the new topic. By
default every trailing `[^N]` anchor follows the ORIGINAL atom, because `add-lesson` parks its
anchor on whatever the atom's last body line happens to be — which is the second half's last
line after a split, and which says nothing about which topic the lesson corrects. A lesson
written with `--supersedes` also names the ORIGINAL id in its own props, so the default keeps
the two consistent. A ref sitting mid-prose is never moved: an author placed it beside the claim
it annotates.

### NO — record the judgement, and treat that as a successful pass

```bash
uv run --script "$PLUGIN/scripts/memory_refusal_cli.py" record \
  --intervention split-topic --scope "$SCOPE" --root "$SCOPE_ROOT" \
  --page "$PAGE" --reason "<one line: why this atom is one topic, not two>"
```

Recording it is what makes the chore TERMINATE — without it the same atom is re-judged every
pass forever, which is the failure mode a permissive candidate list would otherwise create. The
refusal is keyed on the PAGE (page-granular, matching the ledger every other chore here uses)
and re-validated against the page's CONTENT, so editing the page revives its candidates
automatically and no expiry bookkeeping is needed.

## Exit / retry / rollback contract (step 6)

- **SUCCESS** = the verbs exited 0. Surface one line:
  `[memory-split] split <source-slug> → overview + N sub-page(s) in <scope>.` PROJECT scope (if
  explicitly enabled) writes into the in-repo root, NOT pushed — note "PROJECT staged; rides the
  next publish.py".
- **Gate refusal or a precondition error** (stale `--base-sha256`, lock contention): the verbs
  wrote NOTHING (live tree untouched). Read the printed reasons, FIX the plan,
  and retry. **Bounded to ≤3 attempts.** After 3 failures: MUTATE NOTHING, and
  surface: `[memory-split] FAILED <source-slug> after 3 attempts: <reason> — page left intact;
  review manually.`
- **Lock contention / stale-hash loser** (a concurrent `janitor-memory-write` touched a source
  since you read it): a normal abstain, not a failure — re-read, recompute, and let the next
  heartbeat retry on fresh content.
- **Idempotency:** a re-run finds the page now under the cap and does nothing.
