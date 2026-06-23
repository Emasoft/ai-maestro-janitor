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
