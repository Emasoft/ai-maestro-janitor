---
trdd-id: IJFY1VJ0
title: Three false-positive classes in the agent-context rules narrowed on measured evidence
column: complete
created: 2026-08-28T03:08:49+0200
updated: 2026-08-28T03:17:37+0200
current-owner: janitor-session
task-type: bugfix
project-id: ai-maestro-janitor
min-approval-requirement: none
---

# Three FP classes, each narrowed by the narrowest change its evidence supports

The ai-maestro hub enumerated all 16 findings on its corpus (2026-08-28) and classified them.
**Zero true positives in the 16.** Their method is worth recording: they imported the SHIPPED
detector module and called its own `_scan` / `_downgrade_described_attacks` /
`_is_verified_local_only`, replacing only the print loop — totals reproduced exactly
(candidates=96 scanned=96 findings=16 files=7 verified_local=7). That also sidesteps the
last-hash stamp, which lives in `main()`.

## B — an optional suffix turned a noun phrase into a directive (6 of 16, the largest class)

`(?:needed|required|necessary)?` was OPTIONAL, so bare `no approval` matched.
`aimaestro-trdd-approval.md` — a document whose entire subject IS approval tiers — reported
itself five times: `(no approval authority)` in an ASCII ladder, `No approval request was
sent.`, `Pre-approved means "no approval request was needed"`. `\s+` also spans newlines, so
"Claude has no" / "permission prompts pending" matched ACROSS the line break.

**Fix:** suffix mandatory, `[ \t]` instead of `\s`. A directive needs the suffix — "no
permission NEEDED" tells the agent to proceed; "no approval authority" describes a role.

## C — the 200-char window crossed table cells and clauses (4 of 16)

`[^.\n]{0,200}` stopped at neither a markdown PIPE nor an EM DASH. Two hits were one
DIAGNOSTIC TABLE whose symptom column read "Never invoked a skill it should have" and whose
CAUSE column happened to contain ```description```.

**Fix:** the window, never the verb. Three of the four began at `never`, and dropping `never`
from `_MANDATE_VERB` would blind the rule to "never invoke skill X" — a real shadowing attack.
This is the same argument that keeps `without` out of the concealment negation list: a term
that heads real attacks cannot be spent on FP reduction. The discriminator is whether the
backticked name is the mandate's OBJECT, and across a cell boundary it never is.

## D — an overloaded noun (1 of 16)

`(?:system\s+)?prompts?` made `system` optional, so any invalidation verb within 60 chars of
an interactive prompt matched — ```invalidate-password`, TTY prompt`` fired.

**Fix:** `system` mandatory before `prompt`. "prompt" is an everyday noun (TTY, permission,
shell); only the SYSTEM prompt is a standing instruction. `instructions`/`directives` stay
unqualified — they carry the meaning alone.

## A — DECLINED, with reasons (3 of 16)

Quotation-in-order-to-forbid: "you are no longer testing the system — you have BECOME the
system". No negation adjacent to the needle, so the concealment polarity guard does not apply.

The reporter asked why `_downgrade_described_attacks` did not fire, since all 7 files are
`verified_local`. Checked: it requires a CONJUNCTION — `verified_local` **and** a declared
genre marker — and these files carry no marker. **That gate is working as designed and must not
be widened here.** Admitting "governance rules document" as a genre marker would downgrade
findings in exactly the file type the detector exists to protect: agent-context files ARE rules
files, and an injected line inside a locally-authored CLAUDE.md is the detector's core threat
model. Trading that for 3 FPs is the wrong direction. Left as a known FP class.

## Acceptance

- [x] B/C/D: every cited FP goes clean; constructed true positives for each still fire.
- [x] Blind-corpus recall floors unchanged — the narrowings cost zero detection.
- [x] 3 new tests; 9803 detector tests pass; ruff + mypy clean.
- [x] A: declined explicitly with the reasoning recorded, not silently skipped.

## Notes and lessons learned

- Every one of these was an OPTIONAL group or an over-wide window — `(?:…)?` and `{0,200}`
  are where a security regex quietly becomes a noun-phrase matcher. Worth auditing the rest of
  the rule table for the same two shapes rather than waiting for the next corpus report.
- The reporter's cross-project discipline is what made the evidence trustworthy: they ran MY
  shipped code rather than reimplementing my regexes, so the totals were comparable to what my
  detector actually prints.
- **Measured after shipping: 16 → 5** (ai-maestro re-ran the shipped code against this working
  tree). The 5 survivors are the 3 declined class-A lines, the one class-B directive-shaped line
  kept deliberately, and one re-filed line — see below.
- **CORRECTION to this card's C claim, and it was mine.** I asserted the "hand-kept name list"
  line went clean. It does not. My test input carried an EM DASH the real line lacks, so the
  test passed while covering a sentence nobody had reported. Measured on the real text: 87 chars
  between verb and backtick with no `.`, no `|`, no em dash and no newline — one genuinely
  unbroken clause held together by a parenthetical and a colon. So C cleared 3 of its 4, and the
  4th is class A wearing a C costume: the prohibition is about METHODOLOGY, and the `agent` noun
  and the backtick are incidental to it. It now sits behind the same A decision.
- **A test whose input is a PARAPHRASE of the bug report proves the paraphrase.** The test now
  pins the REAL line asserting it STILL FIRES, with the reason, so no future reader mistakes it
  for coverage. Not fixed by adding `:` or `)` to `_CLAUSE_STOP` — "must never invoke the skill:
  `deploy-prod`" is a real attack shape carrying a colon in exactly that position, so the
  widening would cost recall to clear one FP already judged acceptable.
- **The audit shape gains a third member.** Alongside `(?:…)?` and `{0,N}`: a bare `\s` where
  `[ \t]` was meant. `\s` silently crosses a line boundary no directive would — that is how
  "Claude has no" / "permission prompts pending" matched across a paragraph break.
- **The audit was RUN, not just recommended, and it paid for itself once.** Sweeping this module
  for the three shapes found exactly ONE more instance of the class-B defect:
  `(?:disable|bypass|…)\s+(?:the\s+)?audit(?:ing|log|trail)?` fired on **"a bypass audit was
  scheduled"** — an audit OF bypasses, read as an instruction to bypass an audit. The branch's
  own comment already named that part-of-speech flip and guarded the HYPHENATED twin
  ("direct-API-bypass audit"); the unhyphenated form was not covered. A DETERMINER before the
  verb is the tell, so `(?<!a )(?<!an )(?<!the )` now joins the hyphen guard. "bypass the audit
  trail" still fires.
- The other 8 trailing-optional groups are verb inflections (`(?:s|ed|ing)?`), not noun stems —
  no noun-phrase risk. The 74 `\s+` sites are multi-word idioms where crossing a line break is
  harmless or wanted; only class B's had a NOUN as its final token, which is what made the break
  change the meaning. **Deliberately not churned** — a speculative rewrite of 74 sites would
  risk recall to fix nothing measured.
- Known and left, recorded in the test: "an audit bypass review" still fires via the separate
  `audit[-_\s]?bypass` alternation. No measured FP supports narrowing it and `audit-bypass` is
  the attacker's own idiom, so it stays until evidence says otherwise.

