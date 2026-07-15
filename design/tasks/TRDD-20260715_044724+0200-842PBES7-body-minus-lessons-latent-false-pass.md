---
trdd-id: 842PBES7
title: Harden _body_minus_lessons against silent multi-heading truncation (latent false-PASS, unreachable today)
column: backburner
created: 2026-07-15T04:47:24+0200
updated: 2026-07-15T04:47:24+0200
current-owner: janitor-session
task-type: refactor
scope: project
severity: low
labels: [memory, wikimem, verify, defensive-hardening]
relevant-rules: []
---

# Harden _body_minus_lessons against silent multi-heading truncation

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-15

**NEXT ACTION:** make `_body_minus_lessons` (`scripts/lib/memory_edit_verify.py:212`) FAIL LOUD
(raise) when handed text containing MORE THAN ONE full-line `## Notes and lessons learned`
heading — instead of silently truncating at the first. This closes a latent false-PASS class
permanently. LOW priority: no current caller triggers it.

**Source of truth:** GitHub issue #88's *residual*. The bug #88 reported (multi-page haystack
loses pages 2..N) is ALREADY FIXED (v0.42.0, commit 7d1fe1f, `_norm_page_blob`) — verified this
session; the reported reproducer even calls `_norm_body_blob`, a function name that no longer
exists. This TRDD captures ONLY the residual latent footgun, not the reported (fixed) bug.

## What is fixed vs what remains

**FIXED (do not re-fix):** the fact-preservation haystack. `body_facts_preserved` (line 274) and
`mirror_preservation_ok` (line 352) both use `_norm_page_blob`, which strips frontmatter and
collapses whitespace but does NOT truncate at any lessons heading. Verified 2026-07-15:
`body_facts_preserved([page1, page2], page1+page2)` → `(True, [])`; both facts present in the
whole-page blob. The multi-page concatenation (`verify_split:781`) only ever flows into that
non-truncating haystack.

**RESIDUAL (this TRDD):** `_body_minus_lessons` (line 221, `body[: m.start()]`) still truncates at
the FIRST full-line lessons heading, and `_substantive_body_lines` (line 253) inherits it.
Verified: `_substantive_body_lines(page1+page2)` returns only page 1's fact — page 2 silently
dropped. This is a SOURCE-side extractor: fewer source facts extracted → those facts never checked
→ a merge/atomize that dropped them would be certified. That is a **false PASS** (the dangerous
direction), whereas the fixed haystack bug was only a false-FAIL.

## Why it is unreachable today (and why to fix it anyway)

Every caller of `_substantive_body_lines` passes a SINGLE page, never a concatenation:
`body_facts_preserved` iterates `for src in sources` (each a page); `mirror_preservation_ok`
iterates `for name, text in buffer_notes` (each a note). So the false PASS cannot occur through
the current call graph. But a verifier that silently narrows its own input is a trap primed for
the next caller — the whole point of a fail-safe verifier is that misuse must fail LOUD, not
certify silently. Per the bug-autopsy directive: close the class, don't just note it's dormant.

## The fix (issue #88 option 2)

Make `_body_minus_lessons` RAISE (a clear `ValueError`) when it sees a SECOND full-line
`## Notes and lessons learned` heading, rather than truncating. The docstring says "The note's
BODY" (singular) — a multi-page corpus is caller misuse, and misuse should be loud. Callers that
legitimately handle concatenations already route through `_norm_page_blob`, so none needs to
change.

## DERIVED tasks

1. **Confirm no legitimate single page carries two lessons headings.** The curated-page shape
   mandates exactly one `## Notes and lessons learned`; a second full-line occurrence is by
   definition either a concatenation or a malformed page — both of which SHOULD raise. Verify the
   L-3 case (a meta-page mentioning the heading INLINE) does not false-trigger: the raise must key
   on a FULL-LINE match (same anchoring as line 221), never a substring.
2. **Audit callers once more before shipping** — grep every `_body_minus_lessons` /
   `_substantive_body_lines` caller and confirm each passes a single page. If any legitimately
   needs multi-page extraction, that caller is the real bug and must move to a per-page loop first.
3. **Test both:** a single page with one heading → unchanged; a concatenation with two headings →
   raises; an inline mention of the heading text → does NOT raise.

## Verification

1. `_body_minus_lessons(page1+page2)` (two full-line headings) RAISES.
2. `_body_minus_lessons(single_page)` unchanged (body up to its one heading).
3. A meta-page containing "`## Notes and lessons learned`" inline (not full-line) does NOT raise.
4. Full `pytest` + `ruff check` green (no existing caller starts raising).

## Notes and lessons learned

[^1]: [ocd:2026-07-15 lmd:2026-07-15] Issue #88 reported a real bug that was ALREADY FIXED 21h
  before it was filed — its reproducer referenced `_norm_body_blob`, a pre-fix name. Verifying
  against the LIVE code (running the repro, not reading the prose) is what caught it; a prose-only
  read would have opened a TRDD to re-fix a solved bug. But the verification ALSO surfaced a
  genuine residual the issue's option-2 correctly names. Lesson: verify the reported bug against
  current code before fixing (it may be solved), AND read the fix critically (a solved report can
  still name a real adjacent gap). Both halves matter.
