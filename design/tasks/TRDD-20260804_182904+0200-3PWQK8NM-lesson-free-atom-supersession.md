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

**MECHANISM — verified in the source 2026-08-04, correcting this card's first draft.** The page
already has the container this needs and it is NOT a footnote: a canonical `## Superseded`
delimiter heading (TRDD-57WJL5L2). Every `status: superseded` atom MUST sit BELOW it — `lint`
enforces both directions (an atom marked superseded above the heading, and a page with
superseded atoms but no heading) — and `recall` skips them unless `--include-superseded`. That
is exactly the owner's "moved down to the notes as a superseded version", already implemented.

So the operation is a MOVE plus an INSERT, not a footnote append:

1. mark the target atom `status: superseded` + `superseded-by:<new atom id>`;
2. MOVE it verbatim below the `## Superseded` heading (creating the heading if absent);
3. insert the NEW atom, carrying the current truth, in the live section above.

**ID CORRECTION**: this card first said "the atom KEEPS ITS ID", copied by analogy from the
correct-in-place lesson path. That is WRONG here and would have been built wrong: both versions
coexist on the page, so they cannot share an id. The SUPERSEDED atom keeps its original id and
gains `superseded-by:`; the NEW atom gets a fresh id. The chain is by id-linkage, which is what
makes it unbounded — v1 → v2 → v3, each pointing at its successor. The `-v2` anti-pattern being
avoided is a duplicate LIVE atom, not a dated superseded one.

MUST hold, inherited from the lesson-bearing path:

- the old body survives VERBATIM — never dropped, never summarised (`WM-LES-06`, `WM-LES-07`);
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
- [ ] The old atom is moved BELOW `## Superseded`, verbatim, marked `status: superseded` +
      `superseded-by:<new id>`; the heading is created when the page lacks one.
- [ ] `recall` returns the NEW atom and skips the old one unless `--include-superseded`.
- [ ] A second supersession chains (v1 → v2 → v3) rather than overwriting the first record.
- [ ] No duplicate LIVE atom is left behind.
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
