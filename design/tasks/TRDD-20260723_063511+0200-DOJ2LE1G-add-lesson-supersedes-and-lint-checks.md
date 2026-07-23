---
trdd-id: DOJ2LE1G
title: memgrep add-lesson gains --supersedes with SUPERSEDED BODY, and lint gains four checks
column: backburner
created: 2026-07-23T06:35:11+0200
updated: 2026-07-23T06:35:11+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
severity: high
relevant-rules: [1]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-23

**NOT STARTED.** Design captured; awaiting plan-mode sign-off. This is the NPT that
WN7M829Y (retroactive repair) depends on — the repair chore cannot supersede-correctly until
`add-lesson --supersedes` exists and `lint` can flag the four defects.

**NEXT ACTION:** implement `--supersedes <atom-id>` in `memory::cmd_add_lesson_cli`
(`scripts/memgrep/src/memory.rs`): read the target atom's verbatim body, demote it to
`status: superseded`, and emit the lesson with the mandatory body shape. Then add the four
lint rules in `memory::cmd_lint_cli`.

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
