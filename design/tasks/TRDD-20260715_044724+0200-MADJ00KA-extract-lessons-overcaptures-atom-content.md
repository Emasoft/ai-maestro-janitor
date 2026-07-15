---
trdd-id: MADJ00KA
title: extract_lessons swallows atomized fact content after the last footnote, false-failing verify_split
column: backburner
created: 2026-07-15T04:47:24+0200
updated: 2026-07-15T04:47:24+0200
current-owner: janitor-session
task-type: bugfix
scope: project
severity: medium
labels: [memory, wikimem, verify-split, atomize]
relevant-rules: []
---

# extract_lessons over-captures atomized fact content after the last footnote

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-15

**NEXT ACTION:** add the atom-marker line (`^id [keywords: …]`, `_ATOM_MARKER_RE`) to the
footnote-capture STOP-set in `extract_lessons` (`scripts/lib/memory_edit_verify.py:170`), so a
`[^N]:` footnote def followed by atomized fact content stops at the first atom marker instead of
swallowing the whole tail to EOF.

**Source of truth:** GitHub issue #97 (janitor-memory-subconscious-agent, SPLIT pass, 2026-07-14).
VERIFIED by running the issue's own reproducer against current code this session — see Evidence.
UNTRACKED before this TRDD.

## The bug (reproduced 2026-07-15)

`extract_lessons` captures each `[^id]:` footnote body until the NEXT stop token. The current
stop-set (line 170) is:

```python
re.finditer(r"(?ms)^\[\^[^\]]+\]:.*?(?=^\[\^[^\]]+\]:|^#{1,6} [A-Z(\[]|\Z)", scan)
#                                        next footnote def ─┘  next heading ─┘   EOF ─┘
```

It stops at: the next footnote def, a heading `^#{1,6} [A-Z(\[]`, or EOF. It does **not** stop at
an atom block-property marker line `^id [keywords: …]` — the very shape `verify_atomize` matches
elsewhere in this file with `_ATOM_MARKER_RE = re.compile(r"^\s*\^[A-Za-z0-9_-]+\s*\[.*\]\s*$")`.

So a page whose atomized facts sit AFTER the last footnote def with NO closing `##` heading has
its entire tail misclassified as one giant "lesson". `verify_split`'s `lessons_preserved` then
false-fails every legal split of that page — no sub-page can reproduce the giant blob as one
contiguous substring without keeping it unsplit (defeating the split).

**Reproduced against current code** (issue #97's self-contained repro, a hub page with a real
`[^1]:` lesson of ~55 chars followed by `^atom-1`/`^atom-2` fact blocks):

```
len(extract_lessons(source))    -> 1     # one "lesson"
len(lessons[0])                 -> 289   # the WHOLE tail, both atoms swallowed (should be ~55)
```

## Why it is live-relevant

The `janitor-memory-atomize` pass PRODUCES exactly these pages — `^id [keywords: …]` markers with
fact content, appended after the notes section. Observed live this session: an
`[janitor-memory-atomize]` fire atomized a USER-scope page (+6 atoms). The moment such a page
grows oversized and needs a `tier: hub` split, this false-fail blocks it. Atomize and split are
both in the same subconscious agent's rotation, so the two passes collide on their own output.

## The fix

Extend the `extract_lessons` stop-set to also stop at an atom-marker line. Reuse the existing
`_ATOM_MARKER_RE` shape rather than a fresh literal (single source of truth for "what an atom
marker looks like"). The footnote capture then ends at whichever comes first: next footnote def,
next heading, next atom marker, or EOF.

## DERIVED tasks

1. **Confirm the mask/`scan` interaction.** Line 170 iterates over `scan` (a fence-masked copy)
   but slices the ORIGINAL `text` (per the comment at line 171). The added stop pattern must
   match on `scan` consistently with the other alternatives, and the slice bounds must stay
   correct — verify an atom marker inside a code fence does NOT prematurely stop a real lesson.
2. **Do not over-stop.** A `[^N]:` lesson body can legitimately span multiple lines and paragraphs
   (dated reasoning). Only a line that is a WHOLE atom marker (`_ATOM_MARKER_RE`, full-line
   anchored) may stop it — never a `^` mid-sentence.
3. **Re-verify the OTHER direction:** after the fix, a page with NO atoms (a plain footnote to
   EOF) must still capture the full lesson — the EOF alternative must remain.
4. **Add the #97 repro as a regression test** in the existing `extract_lessons` test module; watch
   it fail before the fix, pass after.

## Verification

1. The #97 repro yields `len(lessons)==1` and `len(lessons[0])≈55` (the genuine lesson only), with
   `^atom-1`/`^atom-2` content EXCLUDED.
2. `verify_split` passes a legal split of an atomized oversized hub page (the atoms distributed
   across sub-pages, the lesson preserved).
3. Existing `extract_lessons` / `lessons_preserved` / `verify_atomize` tests still pass.
4. Full `pytest` + `ruff check` green.

## Notes and lessons learned

[^1]: [ocd:2026-07-15 lmd:2026-07-15] Two editorial passes in the same agent (atomize, split) each
  parse the corpus with their OWN regex vocabulary, and they disagreed: atomize KNOWS the
  `^id [keywords:…]` marker (`_ATOM_MARKER_RE`), split's `extract_lessons` did not, so split
  mis-parsed atomize's output. Lesson: when two passes operate on the same artifact, the STRUCTURE
  markers one pass writes must be in the OTHER pass's stop/parse vocabulary — a shared marker
  constant, not two independent notions of "where a section ends."
