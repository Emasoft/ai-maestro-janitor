---
trdd-id: a5780c23-8481-4c8f-802c-99ce2365f0ea
title: Memgrep-managed index + editor anti-corruption — retire the context-loaded MEMORY.md
column: design
created: 2026-06-20T05:21:52+0200
updated: 2026-06-20T05:21:52+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 0
severity: HIGH
effort: L
labels: [memory, memgrep, index, corruption, architecture, fleet]
task-type: refactor
parent-trdd: TRDD-87935f21
relevant-rules: []
release-via: publish
test-requirements: [unit]
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/48", "github.com/Emasoft/ai-maestro-janitor/issues/50"]
---

# TRDD-a5780c23 — Memgrep-managed index + editor anti-corruption

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-20

- **USER directive (2026-06-20, verbatim intent):** the memory repair/editor skills
  are flawed — "most claudes found themselves with corrupt memories, and with the
  index too big and they attempted to manually trim it. but the index should be
  completely managed by the rust memgrep, it should have absolutely no limits in
  terms of size, since the search is made only via memgrep, and memgrep does not
  expose the index to the agents."
- **SAFETY DONE (2026-06-20):** all 4 autonomous editor passes DISABLED
  (`consolidation/split/repair/conflict_per_day = 0` in the shared memory_settings
  store) — stops fleet-wide corruption until this lands. Reversible.
- **KEY FINDING (verified):** the memgrep SQLite index (`.memgrep/index.db`,
  unlimited, agent-invisible) ALREADY EXISTS and `memgrep recall` ALREADY uses it
  (`--use-index`, auto-fresh otherwise). So the target search backend is DONE. The
  harm is the REDUNDANT `MEMORY.md` (10 KB, loaded into every session's context,
  maintained by 7 skills/rules) — that is the thing that grows + gets trimmed.
- **TWO PARTS:**
  - **A — retire the context-loaded MEMORY.md** (the user's explicit fix).
  - **B — editor anti-corruption** (the "corrupt memories" + issue #48): editor
    passes must move content VERBATIM, never paraphrase; verifiers must guard
    body-fact fidelity.
- **OPEN DESIGN DECISION (needs USER):** how to retire MEMORY.md given the HARNESS
  `# Memory` directive (un-changeable; it loads `<slug>/memory/MEMORY.md` into
  context AND instructs maintaining it). Options below; recommend **(1) the
  deprecation stub**.
- **NEXT ACTION:** get the USER's call on the open decision, THEN implement A+B
  (NOT to be rushed under rate-limits at the hour this was authored).

## Part A — retire the context-loaded MEMORY.md (recall = memgrep only)

Recall already runs on the memgrep SQLite index. The work is REMOVAL:

1. **Skills stop maintaining MEMORY.md.** Remove the "add a one-line pointer to
   MEMORY.md" / "update the MEMORY.md index" steps from janitor-memory-write,
   -update, -split, -consolidate, -repair, -bootstrap (7 surfaces). They instead
   ensure the memgrep index is fresh (`memgrep reindex`, incremental + auto — or
   rely on recall's auto-fresh index).
2. **The recall rule (`markdown-memory-recall.md`) is rewritten:** the index is
   memgrep's SQLite DB — unlimited, agent-invisible; recall is ONLY
   `memgrep recall`/`find`; NEVER load, maintain, hand-edit, or TRIM a human
   MEMORY.md (trimming loses pointers = the corruption the user saw).
3. **Resolve the harness conflict** (the OPEN DECISION):
   - **(1) Deprecation stub (RECOMMENDED).** Replace MEMORY.md content with a tiny
     self-documenting notice: "⚠ DEPRECATED — index is memgrep-managed (unlimited,
     agent-invisible). Do NOT add lines or trim; recall via `memgrep recall`/`find`."
     The harness loads only the tiny stub (negligible bloat) and any Claude opening
     it is told to stop — self-enforcing at the point of contact, even for a Claude
     following only the harness directive.
   - **(2) Delete MEMORY.md.** Harness loads nothing (zero bloat) but relies wholly
     on the rule to stop re-creation; a harness-only Claude would re-make it.
   - **(3) Rule-override only, keep MEMORY.md.** Smallest change, but the file keeps
     growing if any agent ignores the override.

## Part B — editor anti-corruption (issue #48 + the "corrupt memories" report)

The editor passes (split/consolidate/repair/conflict) corrupt by REWRITING prose:

- **#48:** a SPLIT pass paraphrased a body table and emitted factually-WRONG scope
  roots (`$HOME/.claude/memory/` — nonexistent); `verify_split` passed (it does not
  diff body-fact fidelity — the same gap this TRDD's P5 sibling documented for
  merge).
- **repair:** its lone rewrite — "rewrite the answer-shaped description" — is not
  fact-guarded by `verify_repair`.

Fix:

1. **Editor passes move content VERBATIM.** Split moves whole `##` sections
   byte-for-byte into sub-pages; merge concatenates + dedups identical lines;
   repair adds metadata/Notes ONLY. No pass paraphrases body prose. The repair's
   description-rewrite is removed or constrained to a non-lossy reshaping that the
   verifier checks.
2. **Verifiers guard body-fact fidelity** (not just lessons): a parser-independent
   check that every substantive source body line survives (verbatim or as a
   superset) into the result — catching a paraphrase/drop. Tune to avoid
   false-fails on legitimate dedup (the reason the original punted — solve it, do
   not skip it).
3. Re-enable the passes only AFTER B's verifier guards are in place + tested.

## Acceptance

- A: recall works with NO MEMORY.md maintenance; the 7 skills no longer touch it;
  the rule documents the memgrep-only index; the harness-conflict resolution is
  applied; no context bloat grows with corpus size.
- B: a split/merge that paraphrases or drops a body fact FAILS its verifier on a
  fixture; a clean structural move PASSES; #48's exact case is caught.
- Editor re-enabled (frequencies restored) only after B passes its tests.
- Unit tests on real fixtures; CPV `--strict` green; shipped.

## Notes

- Related open issues this subsumes/touches: #48 (split body-fidelity), #50
  (markers fire on clean scopes — once recall is memgrep-only + verifiers guard
  fidelity, the no-op-marker waste is a separate fix, see #50/#43), #49 (memgrep
  `[[name]]` resolves by file-stem not frontmatter `name:` — a memgrep bug feeding
  false broken-link noise; mandate #1).
- The migration helper (TRDD-47df698b) and this share the memory_scopes SSOT
  increment (TRDD-87935f21 next step).
