# Split planning — detailed mechanics

Reference for step 3 of the SPLIT algorithm. See the main skill for the full
algorithm context and invariants.

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
  sub-page (or the overview) — nothing dropped, nothing reworded; copy lesson
  bodies and their `[ocd:… lmd:…]` prefixes byte-for-byte. `verify_split` FAILS on
  any dropped or silently-reworded lesson.
- **Hub globs partition (hubs only):** if the source is `tier: hub` with a
  `globs:` list, distribute those patterns across the sub-pages so their union
  equals the parent set with NO overlap (each pattern has exactly one owning
  sub-page). A non-hub source has no globs to partition.
- **Size:** every output page (overview + each sub-page) should end up at or under
  the cap. If a natural sub-topic is itself still over the cap, that sub-page is
  fine for THIS run — the next heartbeat splits it further. Convergence only
  requires real progress this level.

## Why never guess the scope

Two documented incidents: janitor#242 — a `consolidate` overwrote an in-flight
`repair`'s authority 367 s later on the same root, which is why the dispatch claim
renames the record out of the pool atomically. And #150 — on 2026-07-30 a
dispatched `conflict` pass could not read its assignment file, re-derived cadence
on its own, ran USER instead, and left the stamped LOCAL scope marked
run-without-running for a full cadence: 378k tokens, zero mutations. An abstain
that says *"dispatched but could not read my assignment"* is cheap and
actionable; a confident run on the wrong scope is neither.

## Backlink-redirect mechanics

**A split transaction has exactly ONE source — the page being split.** Backlink
holders are NOT listed as sources to `begin` (the split verifier requires
`len(sources) == 1` and aborts otherwise). Instead you redirect a holder by
writing its rewritten content as a STAGED FILE at the holder's own rel-path
(step 5): the commit reconstructs that as a write overwriting the live holder.
So `begin` takes only `$REL`; the holder edits ride along as extra staged writes.
The verify gate `no_dangling_refs` only fails on links to a RETIRED slug, and
keeping the source slug as the overview retires nothing — but redirecting
moved-detail backlinks is still the correct editorial act, so do it.

## Hard invariants (every SPLIT pass enforces)

- **Transactional** — stage → verify → atomic-swap; crash-resumable; idempotent.
  Never edit a live page directly; always via `memory_txn_cli.py`.
- **No information lost** — union(overview, sub-pages) ⊇ every fact + every `[^N]`
  lesson of the source, copied verbatim (lessons byte-identical).
- **Type & tier preserved** — sub-pages keep the source's `metadata.type`; a
  component is never fragmented; one element = one page.
- **Connected** — overview links DOWN to every sub-page, each sub-page links UP;
  moved-detail backlinks redirected in the SAME txn; zero dangling/one-sided links.
- **Bounded & disable-able** — one page, one level per run; recursion across
  heartbeats; honors the kill-switch and `split_per_day: 0`.

Each is mechanically checked by `memory_edit_verify.verify_split` before the
transaction commits, so a pass that would violate one aborts rather than landing a
half-split page — the invariants are enforced, not merely documented.

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
shorten the prose to fit the budget, and never edit the page directly: write the new atoms
through `memgrep add-atom` so the parser synthesises each element and a malformed atom is
impossible by construction.

**Give each new atom its own `keywords:`, drawn from the SYMPTOM phrases a future session
will search with** — not from the words the prose happens to use. Recall ranks on
`description + title + keywords`, never the body, so an atom nobody can recall is worse than
an oversized one: splitting a findable atom into three unfindable ones is a net loss.

**Retire the original with `add-lesson --supersedes` (same atom id)** when it stated
something now spread across the new atoms. Never overwrite it — supersession is what keeps
the old statement readable as dated history instead of deleting knowledge.

**No transaction, deliberately.** The memgrep write verbs are already scope-locked and
CAS-guarded, so they carry the same crash-safety `memory_txn_cli` provides for hand-staged
page edits. Opening one here would nest two locking schemes for no benefit.

**Verify before you finish.** Re-run the lint line; an unverified decomposition that left the
atom over budget re-dispatches this chore forever, which is the failure the write-side gate
was originally built to prevent.

**The `## Superseded` carve-out applies exactly as it does to the write gate**: a body below
that delimiter is protocol-frozen history. Leave it alone even when it is over budget —
rewriting retired facts destroys the record they exist to be.
