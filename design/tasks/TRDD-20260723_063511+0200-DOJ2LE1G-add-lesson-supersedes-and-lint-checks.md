---
trdd-id: DOJ2LE1G
title: memgrep add-lesson gains --supersedes with SUPERSEDED BODY, and lint gains four checks
column: dev
created: 2026-07-23T06:35:11+0200
updated: 2026-07-23T07:05:00+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
severity: high
relevant-rules: [1]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-23

**MEMGREP CORE SHIPPED (Phase 1a/1b/1c). Plan approved; implementing across the 4 TRDDs.**
All changes in `scripts/memgrep/src/memory.rs`; 110 cargo tests green (8 new).

**DONE:**
- `add-lesson --supersedes` — captures the `--atom`'s CURRENT verbatim body (via
  `atom_verbatim_body`, `[^N]` anchors stripped), appends ` SUPERSEDED BODY: <old>` to the
  lesson text, and records a `supersedes:<atom>` metadata field. Run BEFORE cleaning the atom.
- `add-lesson --retire-atom` (requires `--supersedes`) — injects `status: superseded,
  superseded-by:<lesson-id>` into the atom marker (idempotent). DEFAULT is correct-in-place
  (same atom id, stays valid) — never a `-v2` duplicate.
- FOUR new `lint` checks (deterministic, FP-free): `unquoted-desc` (unquoted prose desc — a
  clean legacy snake_case slug is grandfathered), `empty-lesson-body`, `oversized-atom`,
  `superseded-without-body` (a `supersedes:` lesson lacking `SUPERSEDED BODY:`). Plus the
  inline-code `[^N]` FP fix (`mask_inline_code`).
- **oversized-atom default = 1500 chars** (`MEMGREP_ATOM_MAX_CHARS`, 0=off). Chosen from the
  LIVE corpus distribution (558 atoms: median 559, p90 1241, p95 1624, max 3271). 600 flagged
  half the corpus incl. well-authored pages; 1500 flags only the ~6% bloated tail (36
  corpus-wide) — the real decomposition candidates. My own contract page now lints clean.

**NEXT ACTION:** rebuild+install the memgrep binary (`cargo install --path scripts/memgrep`)
at the END of all phases so the checks go live for the skills/detector; then Phase 2 (migrate).

**DEFERRED (moved to the phase that owns them):**
- 1d — the py mirror in `wikimem_syntax_lint.py`: fold into **WN7M829Y** (the detector surface).
  Prefer the detector SHELL OUT to `memgrep lint` over re-implementing the 1500 threshold in
  Python (avoid a second drifting copy — the 3-pillars anti-pattern).
- 1e — atom↔lesson travel in `memory_edit_verify.py`: fold into **VJCMZ2OP** (migrate), where
  the travel semantics are concretely defined and self-verified by the migrate transaction.

**GATE CAVEAT for Phase 3 (found while linting the real corpus):** the corpus ALREADY carries
many pre-existing footnote/link violations (USER: 74 `never-referenced` + 33 one-sided; PROJ:
47+14; LOCAL: 8+30). So the txn-commit gate MUST be a DELTA gate (block only on violations the
edit INTRODUCES), NOT "block on any lint violation" — else every edit to a page with a
pre-existing violation is rejected for an unrelated reason.

## Part 1 — the lesson contract (the supersession protocol, enforced)

Today `add-lesson --page --atom --keywords [--desc]` takes a free DO-NOT/BECAUSE/DO body and
anchors a `[^N]` from the atom. It does NOT know about supersession, so correcting a wrong
atom is done by hand and the never-delete rule is violated (the old body is lost).

Add `memgrep add-lesson --supersedes <atom-id>`:
- reads the target atom's **verbatim** current body,
- flips that atom's block to `status: superseded`,
- writes the lesson with the MANDATORY body shape the user pinned:

  ```
  LESSON LEARNED: don't do X, because <WHY>. Do Y instead, because <WHY>. SUPERSEDED BODY: <old atom body>
  ```

The embedded `SUPERSEDED BODY:` is what makes correction non-destructive: the atom's full
history is reconstructable from its dated superseded lessons — the atom's changelog. An atom
carries MANY such lessons and (per VJCMZ2OP) TRAVELS with them on refactor.

## Part 2 — four new `lint` checks (deterministic, FP-free)

`lint` is the integrity gate every write ends with. Add:

| check | fires when |
|---|---|
| `unquoted-desc` | a `desc:` value is not wrapped in quotes (breaks grep / in-body filter) |
| `empty-lesson-body` | a `[^N]:` header has metadata but no prose body → `--only-notes` returns nothing |
| `oversized-atom` | an atom body exceeds the readable-size budget → must be decomposed |
| `superseded-without-body` | a lesson demotes an atom (`status: superseded`) but omits `SUPERSEDED BODY:` → never-delete violated |

The write verbs already prevent `unquoted-desc` at creation; the lint check catches
hand-edited or legacy pages. `empty-lesson-body` is the same class the current `[^N]` bare
token already trips — formalise it as a named rule, and (separately noted) teach lint to skip
`[^N]` INSIDE inline code so example prose does not false-positive.

## Part 3 — atom↔lesson travel in the editorial verifiers

`scripts/lib/memory_edit_verify.py` (`verify_split`/`verify_merge`/`verify_atomize`) must
assert that when an atom moves pages, its notes + lessons + non-shared refs move WITH it, and
that a shared ref stays on the source. This is the invariant the VJCMZ2OP `migrate` verb
automates; the verifiers are what prove a hand-move or a migrate did not drop a lesson.

## Verification

- `add-lesson --supersedes <atom>` demotes the atom, embeds its verbatim old body, and the
  page lints clean.
- Each of the four lint checks fires on a crafted-bad page and passes a crafted-good page.
- `verify_*` in `memory_edit_verify.py` fails a transaction that drops a moved atom's lesson.
- Full `cargo test` (memgrep) + `uv run pytest` + `ruff check` green.

## Notes and lessons learned
