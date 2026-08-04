---
trdd-id: 3PWQK8NM
title: memgrep can supersede an atom without inventing a lesson
column: todo
created: 2026-08-04T18:29:04+0200
updated: 2026-08-04T18:29:04+0200
current-owner: ai-maestro-janitor
task-type: feature
relevant-rules: []
npt: []
eht: []
---

# memgrep can supersede an atom without inventing a lesson

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-04

**NOT STARTED.** Spec landed (`WM-LES-09`, `WM-LES-10`); the verb does not exist.

- **The gap**: `add-lesson --supersedes` is the ONLY supersession path and it REQUIRES a
  lesson body. `WM-LES-09` forbids a lesson when nothing went wrong, so a clean update —
  an implementation landing as designed, a fact being refined — currently has **no
  conformant way to be recorded**. The author must either fabricate a lesson (polluting the
  guardrail surface) or edit in place (destroying the history `WM-LES-10` requires).
- **NEXT ACTION**: add lesson-free supersession to the memgrep verb surface (see §2), then
  a `WM-LINT` check for `WM-LES-10` violations.

## 1. Why (owner rule, 2026-08-04)

An atom carries an UNBOUNDED chain of superseded versions, and **not all of them carry a
lesson**. A lesson records that something WENT WRONG. When an implementation simply lands as
designed, nothing went wrong: the atom body is updated to the new truth and the previous body
is demoted to a dated superseded version beneath it — a CHANGELOG entry, not a guardrail.

Forcing a lesson in that case manufactures a fake mistake. That is not cosmetic: the lesson
surface is read as "things to not repeat", so diluting it with non-mistakes is the same class
of harm as an uncited lesson — it degrades the signal the surface exists to carry.

## 2. Shape

Preferred: a `--supersedes <ATOM-ID>` flag on **`add-atom`** — the new atom IS the new truth,
and the old body is demoted beneath it in the same transaction. That reads correctly
(`add-atom --supersedes` = "this replaces that") and reuses the existing CAS + scope-lock
write path.

MUST hold, inherited from the lesson-bearing path:

- the old body is embedded VERBATIM as a dated superseded version — never dropped
  (`WM-LES-06`, `WM-LES-07`);
- the atom KEEPS ITS ID (a `-v2` duplicate is the anti-pattern);
- the chain is unbounded — N supersessions, newest truth on top, each prior body dated
  beneath it;
- `--base-sha256` CAS + the scope write lock apply exactly as for every other write verb;
- `validate` + `lint` clean afterwards.

## 3. Lint follow-up (`WM-LES-10`)

A check that flags an atom whose body changed between commits with no new superseded version
and no typo-only diff. Without it the rule is unenforced, which is the failure shape of the
memorize-nudge: a rule that depends on the author remembering.

Deliberately NOT a hard gate at first — a false positive that blocks a write is worse than a
warning, and "is this diff substantive?" is a judgement a linter approximates rather than
decides.

## 4. Acceptance

- [ ] An atom can be superseded with NO lesson, in one transaction.
- [ ] The old body survives verbatim, dated, beneath the new one.
- [ ] The atom id is unchanged; no `-v2` page or atom appears.
- [ ] A second supersession of the same atom appends rather than replacing the first (chain,
      not a slot).
- [ ] `validate` + `lint` clean; existing lesson-bearing supersession is unaffected.
- [ ] Spec drift suite recognises the new verb (`tests/test_wikimem_spec_drift.py`).
- [ ] The `WM-LES-10` lint check warns on a substantive in-place edit.

## 5. Risks

- **Silent history loss** — an implementation that overwrites instead of demoting. Mitigated
  by the same `verify_*` oracle discipline as every other editorial path: the old body must
  be provably present after the write.
- **Chain bloat** — an atom with 30 superseded versions becomes unreadable. Do NOT cap it
  (the chain is the record); if it bites, address it by rendering — recall already returns
  the current body and only the second hop shows history.
