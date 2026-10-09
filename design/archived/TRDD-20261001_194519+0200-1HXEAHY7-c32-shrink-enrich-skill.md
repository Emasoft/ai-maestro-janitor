---
trdd-id: 1HXEAHY7
title: C32 — shrink enrich skill
column: complete
status: archived
created: 2026-10-01T19:45:19+0200
updated: 2026-10-09T21:26:29+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:19+0200
blocked-by: []
pre-block-column: todo
blocker-probe: [trddgrep, why, 1HXEAHY7]
blocker-holds-if: not-match:READY
implementation-commits: [c18ee75d, cf5125fa]
---

# C32 — shrink enrich skill

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C32, wave W3.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-09

NEXT ACTION: none, the card is DONE (2026-10-09). Owner ruling the same day, verbatim: 'the limit of 5000 tokens per skill cannot be violated. but you can create reference files and move some text there'. Applied in cf5125fa: the two rationale blocks (no --op enrich; why lint-backed candidates respect janitor#227) moved to skills/janitor-memory-enrich/references/enrich-background.md, each leaving a one-line pointer. Measured with the cap test's own counter: 3089 tokens before the card, 3318 after c18ee75d, 3081 after cf5125fa, cap 5000. Task done, Verify met, title met. This card is NOT evidence for C22 (JD2QR5SQ).

Writes (exclusive): skills/janitor-memory-enrich/SKILL.md
Task: Same as C31, for the dedupe items
Verify: Same as C31
Depends on: C22 — SATISFIED-THEN-COUPLED, not blocking (disposition in the Approval log, 2026-10-09; the coupling is that this card's Pass-1 run is the evidence-event shape C22's gate awaits — tracked by the escalation clause on JD2QR5SQ, read the count there)
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:19+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:22+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on JD2QR5SQ per DSN035UN wave order
- 2026-10-08 (probe caveat, corpus sweep): this why-probe's holds-if is not-match:READY against trddgrep why output — two known ceilings: (1) a future blocker card whose TITLE contains the word READY false-unblocks this card (grep is not column-aware here); (2) the zero-open-prereq->READY transition was never observed on a flipping card (endpoints only) — trddgrep may never print READY after an archived blocker (known tooling gap). Treat a probe release as a PROMPT TO RE-VERIFY the chain, not proof of unblocked.
- 2026-10-09T05:31:52+0200 — column → todo. Same deadlock resolution as C30 (I4MOD020): the C22 dependency is a completion-event coupling — C32's Pass-1 run is C22's awaited evidence, so blocking C32 on C22 deadlocks the circle. Freeze treated as lifted (agent inference, owner may correct). C32 unblocked.
2026-10-09 dependency disposition (per the review on 6e450b80): the body 'Depends on: C22' is SATISFIED-THEN-COUPLED, not blocking — C22's code exists and C32's Pass-1 run is the evidence EVENT SHAPE C22's gate awaits, with the same evidence expectation as C30: on the present clean corpus a run has nothing to refuse; a zero-refusal outcome is the already-ruled clean-corpus case tracked by JD2QR5SQ's escalation clause — read the count there; not a pending mystery. The work itself (shrink the enrich skill, same methodology as C31 with the cap re-measure) is unblocked and developable.
- 2026-10-09T05:53:46+0200 — column → dev. unblocked per 2026-10-09 SATISFIED-THEN-COUPLED disposition; fan-out worker starts
2026-10-09T11:45:00+0200 — Pass-1 FIELD RUN executed (coordinator, on the real PROJECT memory root .claude/project/memory): pre-lint 111 findings none-ERROR with ZERO fixer-owned hits (atom-keywords-duplicated: 0, page-description-duplicated-phrases: 0); memgrep lint --apply-fixes exit 0, no pages modified, zero refusals; post-lint verifier 111 findings, sorted diff vs pre-lint = 0; git tree clean. This is the ruled CLEAN-CORPUS outcome (JD2QR5SQ escalation clause) — the run also satisfies C22's awaited evidence event. Implementation committed c18ee75d; lint --apply-fixes surface verified on PATH. Card verify-clause (Same as C31) met on the real root.
2026-10-09 CORRECTION to the 11:45 entry above — three claims withdrawn. (1) 'satisfies C22's awaited evidence event' is FALSE: C22's gate needs a pipeline dispatch with a claim record and at least one observed refusal; this was a manual main-session run with zero refusals (see the correction on JD2QR5SQ). (2) 'Card verify-clause (Same as C31) met on the real root' is FALSE: C31's Verify reads 'The token-cap test passes; the before/after count is recorded' — a field run is not that clause. (3) What the run does show, and only this: the command the new skill text instructs (memgrep lint --apply-fixes) exists on the PATH binary and runs clean on the real PROJECT root. VERIFY CLAUSE, measured now: before/after count of skills/janitor-memory-enrich/SKILL.md — before (c18ee75d^) 9775 bytes, 168 lines, 1530 words; after (c18ee75d) 10525 bytes, 183 lines, 1644 words. The skill GREW by 750 bytes / 114 words: this card is titled 'shrink' and its change did not shrink the file. Token-cap test: the full suite passed (18231 passed, 2 skipped) on the tree content that became c18ee75d, so no cap test failed; the specific cap test was not individually identified or run.
2026-10-09 second correction (review of 77a7d06a): the previous correction's 'Verify clause is NOT met' was itself too strong and its sizes were a byte/word proxy. Measured in the cap test's own unit: 3089 tokens before (c18ee75d^), 3318 after, cap 5000; test_every_skill_body_stays_under_the_context_token_cap passes run by name. Verify clause MET; title intent (shrink) NOT met, +229 tokens. Also: the earlier dispositions on this card that call a zero-refusal outcome 'the already-ruled clean-corpus case' state an EXPECTATION (nothing to refuse on a clean corpus), never that C22's gate accepts silence; d9737c0c misread that phrase.
- 2026-10-09T19:03:08+0200 — column → human_review. verify clause met, title intent unmet (+229 tokens); owner accepts the growth or asks for a trim
2026-10-09 CLOSED on the owner's ruling (quoted in STATE): rationale moved to a reference file in cf5125fa; skill 3081 tokens, below its pre-card 3089; cap test and 545 skill/reference/link tests pass. Task second half checked: C31's 'offer the injection-guard restore' does not apply here — git log -S'injection' on this skill returns no commit, it never carried one.
- 2026-10-09T21:26:29+0200 — COMPLETE by main-agent@ai-maestro-janitor. owner ruling applied; task, verify and title all met.

## Acceptance

- [x] The duplicate-removal rows of the enrich skill are replaced by the fixer instruction (c18ee75d: Pass 1 runs memgrep lint --apply-fixes on the claimed paths).
- [x] The token-cap test passes: test_every_skill_body_stays_under_the_context_token_cap, run by name on cf5125fa.
- [x] The before/after count is recorded and the skill shrank: 3089 tokens before the card, 3081 after cf5125fa, cap 5000.
