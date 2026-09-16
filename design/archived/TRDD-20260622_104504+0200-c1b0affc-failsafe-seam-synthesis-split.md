---
trdd-id: c1b0affc-ea1c-4230-9e5c-36bbf66a4744
title: Fail-safe wikimem split — synthesize seams so a seamless oversized page ALWAYS converges
column: published
created: 2026-06-22T10:45:04+0200
updated: 2026-06-25T10:22:22+0200
current-owner: claude-janitor-dev
assignee: claude-janitor-dev
parent-trdd: TRDD-aebedbff
task-type: feature
release-via: publish
relevant-rules: []
test-requirements: [unit]
impacts: []
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/57", "github.com/Emasoft/ai-maestro-janitor/issues/58", "github.com/Emasoft/ai-maestro-janitor/issues/60"]
---

# Fail-safe seam-synthesis split (#57/#58) + leave-it-to-the-janitor directive

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-22

USER (2026-06-22): other Claudes can't split wikimem files; "make the splitting a
fail-safe recipe that works async, outside the main claude agent", "give instructions to
leave all operations to the janitor memory agent", and chose **build now / finish the
job** (don't worry about budget resets).

### ROOT CAUSE (verified)
A splittable page that is OVER `split_max_bytes` but has <2 `##` content sections
abstains EVERY cycle → never converges (#57). The abstain is **skill-level**, NOT a code
gate: `verify_split` (the commit-time gate in memory_txn_cli `_verify_split`) does NOT
call `is_legal_split` — it only checks output invariants (lessons/body-facts preserved,
convergence under cap, no dangling refs). So a synthesized-seam split ALREADY passes
`verify_split` today; the only thing stopping it is the split SKILL instructing the agent
to "leave it intact". `is_legal_split` is referenced by the skill's reasoning + unit tests
only.

### THE FIX (fail-safe seam synthesis)
1. **Split skill** (`skills/janitor-memory-split/SKILL.md`) — replace the "<2 sections →
   un-splittable, leave intact" abstain with a **seam-synthesis recipe**: for a hub/aspect
   page over the cap with <2 `##` seams, SYNTHESIZE seams — (a) group blank-line-separated
   paragraphs into 2-4 coherent chunks each under the cap, copying every line VERBATIM
   (so `body_facts_preserved` passes), inserting a synthetic `## Part N — <topic>` heading;
   (b) if the body is one seam-less blob, hard-chunk at LINE boundaries into N under-cap
   pieces labeled `## Part N (continued)`. Each chunk → a type-preserving sub-page; overview
   maps them; lessons distributed verbatim; links wired. `verify_split` proves no loss.
   A `component` is still NOT fragmented (one element = one page) but is SURFACED loudly as
   "re-tier — too big to be one component", never silently abstained.
2. **`is_legal_split`** (`memory_edit_verify.py`) — add `oversized: bool=False`; a seamless
   hub/aspect that is `oversized` is splittable (synthesis), so it returns ok with a
   "synthesize seams" reason instead of refusing. A non-oversized seamless page still
   isn't fragmented (nothing to gain). Component refusal unchanged. Update its unit tests +
   add seam-synthesis tests.
3. **Subconscious agent** already injects the split skill → inherits the fail-safe.
4. **Leave-it-to-the-janitor**: strengthen the simple skills (write/update/recall) + add a
   crisp top-of-skill directive: a MAIN agent must NOT run any wikimem EDITORIAL op
   (split/merge/consolidate/conflict/repair/harvest) itself — note the need and let the
   janitor's async `janitor-memory-subconscious-agent` do it. Other Claudes that hit a
   `[janitor-memory-*]` marker dispatch the agent (post-0.16.0) — they never run it inline.

### THEN (finish the job)
5. `uv run scripts/publish.py` → v0.16.0 (bundles: this fix + subconscious agent 619cedd +
   #54/#55/#59/#53 FP fixes + control commands). Then /reload-plugins + /janitor-arm.
6. Close #54, #55, #59, #53, #57, #58, #60 with the published version.

### DONE LOG
- (building now …)
