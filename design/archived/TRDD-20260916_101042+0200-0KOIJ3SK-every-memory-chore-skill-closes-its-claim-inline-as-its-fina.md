---
trdd-id: 0KOIJ3SK
title: Every memory chore skill closes its claim inline as its final numbered step
column: complete
created: 2026-09-16T10:10:42+0200
updated: 2026-09-16T10:31:38+0200
current-owner: session
created-by: session
task-type: bugfix
min-approval-requirement: none
assignee: session
mandate: true
mandated-by: none
approved: true
approval-judge: session
approval-datetime: 2026-09-16T10:10:42+0200
parent-trdd: V3BQT7QE
derived: true
---

# Every memory chore skill closes its claim inline as its final numbered step

Live run 2026-09-16: the consolidate curator claimed dispatch 1789491146-5957aca4, wrote its report and returned without running complete; the claim stayed CLAIMED until the orchestrator closed it by hand. Four skills (conflict, consolidate, harvest, split) only link references/close-claim.md and need the inline block added. Four skills (atomize, enrich, repair, retro-lesson) already carry an inline complete invocation, split across lines, that must be reformatted onto one line and confirmed to be the final numbered step, preceded by set-report in the same block. Acceptance: (1) each of the 8 SKILL.md files ends its procedure with a numbered step describing both the set-report and complete invocations of memory_dispatch_claim.py, each passing the state directory and, for set-report, the report file, with the state directory spelled as the literal path from the spawn prompt; (2) every SKILL.md contains exactly one complete --state-dir invocation of memory_dispatch_claim.py on a single line; (3) each body stays under CPV's five thousand token cap, roughly 13,600 characters, or less; (4) cpv-remote-validate in strict mode reports zero critical, major, minor and nit findings.

## Approval log

- 2026-09-16T10:10:42+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-16T10:31:37+0200 — COMPLETED by the session acting as approver; the char-count proxy in criterion 3 is superseded by CPV's measured token cap, which passes. Not a guard: the structural fix (spawner or orphan sweep closing a claim whose report exists) is still open and lives with TRDD-V3BQT7QE.
- 2026-09-16T10:31:38+0200 — COMPLETE by session-as-approver. 8/8 skills close inline; CPV strict clean.

## Acceptance

- [x] All 8 memory-chore SKILL.md files end their procedure with a numbered step that runs set-report then complete inline (commit 42404659).
- [x] Each of the 8 files contains exactly one complete --state-dir invocation (grep count 1 per file).
- [x] Body under CPV's 5000-token cap: cpv-remote-validate --strict reports MAJOR 0 for every skill (reports/cpv/20260916_102637+0200-close-claim-verify2.txt). The body's 13,600-char proxy is NOT met for atomize/harvest/split as whole files (14.9-15.3k chars incl. frontmatter and TOC embeds); the tool's own token measure is the criterion that counts.
- [x] cpv-remote-validate --strict: CRITICAL 0 / MAJOR 0 / MINOR 0 / NIT 0.
