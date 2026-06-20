---
trdd-id: a5780c23-8481-4c8f-802c-99ce2365f0ea
title: Memgrep-managed index + editor anti-corruption — retire the context-loaded MEMORY.md
column: dispatch
created: 2026-06-20T05:21:52+0200
updated: 2026-06-20T09:17:39+0200
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
- **DECISION (USER, 2026-06-20):** retire MEMORY.md via the **deprecation stub** —
  a tiny self-documenting notice the harness loads (negligible bloat) telling any
  reader the index is memgrep-managed and to never add/trim it. Self-enforcing even
  for a harness-only Claude.
- **PART A + OVERVIEW + memgrep-#49 DONE (committed, ride next publish):** Part A — the
  recall rule and the write/update/split/consolidate/bootstrap skills retire MEMORY.md →
  memgrep-only; bootstrap seeds the stub. The `<project>-overview.md` ENTRY-POINT page,
  and the new `memgrep
  overview` command (which the stub advertises). memgrep #49 fixed (`[[name]]` wikilinks
  resolve by frontmatter `name:`, not just file-stem — killed the 59/94 false
  broken-link reports). All tested (106 cargo tests), markdownlint clean.
- **THE HARVEST CHORE (USER spec, 2026-06-20) — the existing-MEMORY.md reduction done
  NON-DESTRUCTIVELY.** A permanent DAILY janitor pass: when a MEMORY.md carries added
  memories (beyond the stub), do NOT delete them — HARVEST each into proper wikimem
  pages under the FULL editorial model (same-theme-per-page, complete metadata, tier
  expand/reduce, bidirectional links, `## See also`, atomic memories each with their own
  Notes/lessons, correct LOCAL/PROJECT/USER scope routing, greppable + indexed), THEN
  reduce MEMORY.md to the stub. Agent-intelligence editorial pass (like split/merge),
  through the txn core with a verify that proves no memory is lost BEFORE the stub write.
- **NEXT ACTION — remaining build:** (1) **the harvest pass** — new skill
  `/janitor-memory-harvest` + `harvest_per_day=1` + a `[janitor-memory-harvest]` marker
  (scheduler + dispatch + heartbeat prompt) + a verify + tests (Part C below); (2) **Part
  B** — `verify_split`/`verify_merge` body-fact-fidelity (catch #48) without
  false-failing dedup, + tests; (3) **re-enable** the editor frequencies ONLY after B +
  the harvest verify pass their tests. Ship via publish.

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

## Part C — the harvest chore (incorporate stray memory artifacts into the wiki, NON-destructive)

A permanent DAILY janitor pass that NEVER deletes a memory. `/janitor-memory-harvest`
(fired by a bare `[janitor-memory-harvest]` marker; `harvest_per_day=1`):

1. **Detect (any non-wiki memory artifact).** In each scope, TWO sources: (a) a
   `MEMORY.md` that is NOT already the stub (it carries pointers or added memory content
   beyond the deprecation notice); AND (b) any OTHER stray memory `.md` file the agent
   already has that is NOT yet a proper wikimem page (loose notes sitting outside the
   model). Both are harvested into the wiki the same way, once a day.
2. **Harvest, don't delete.** For each memory it holds: if it is a pointer to an EXISTING
   note, that note already IS the memory (the repair pass fixes its shape); if it is
   content NOT yet in a proper page, CREATE a wikimem page for it under the FULL editorial
   model — same-theme memories share ONE page; complete frontmatter (name, description,
   ocd, lmd, node_type, type, tier); tier expand(aspect)/reduce(component); bidirectional
   `## Applies to`/`## Governed by` + `## See also`; each memory atomic with its own
   `## Notes and lessons learned`; routed to the right scope (machine-private → LOCAL,
   project-shared → PROJECT, cross-project → USER); greppable + indexed (`memgrep reindex`).
3. **Verify then stub.** Only after a verify PROVES every memory in MEMORY.md now exists
   in a proper wikimem page (greppable via memgrep) does the pass reduce MEMORY.md to the
   stub. Through the txn core; a backup of the original MEMORY.md is kept (RULE 0). If the
   verify cannot prove preservation it ABSTAINS (leaves MEMORY.md intact, surfaces a
   finding) — never a lossy stub.
4. **Permanent + bounded.** Once/day per scope; idempotent (a stub MEMORY.md is a no-op);
   honors the kill-switch + `harvest_per_day=0`. It exists because agents WILL keep
   mis-adding to MEMORY.md (the harness directive still nudges them); the chore quietly
   re-files those into the wiki forever.

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
