---
trdd-id: DSN035UN
title: Deterministic auto-fixers in memgrep and the scripts replace LLM repair instructions, shrinking the memory skills
column: design
status: tasked
created: 2026-10-01T17:23:43+0200
updated: 2026-10-01T19:47:05+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T17:23:43+0200
eht: [LKOUJC76, 622ROA5F, 2UAEQQ4A, OWGEOJ0D, 7SMPCPNT, I23YCEW7, 4G427D8M, 9SUZ48E8, QBU0HSM9, KSCAFSLD, RLD015QB, RUJQ7WSX, U2VUXGBP, B9YPSF02, UDE86OSZ, V12ZHM1B, BHIS99XE, 3HLI7DMK, JD2QR5SQ, VHFGPCOJ, 8524H5V1, QXG8SRVD, I4MOD020, OLNPXGBC, 1HXEAHY7, QX59MA4H, EMZUVIBK, ZYX8B2RA, RQMJFJGR, MIU9H3ZC, VA35WWWS, RVWJQR8E, PC2ZZR31, 7IPJA0ED]
---

# Deterministic auto-fixers in memgrep and the scripts replace LLM repair instructions, shrinking the memory skills

## Owner directive (verbatim, 2026-10-01)

"in general you should automate more repairing using heuristic code in the scripts and in memgrep. linters like ruff are able to auto fix hundreds of issues. take example. this will also help reducing the size of the skills."

## Measured starting point (2026-10-01)

memgrep lint autofixes only publish-globally/symlink drift today (--no-fix to suppress). PROJECT-scope lint finding counts by rule: atom-no-ocd 43, atom-no-lmd 37, atom-oversized 17, lesson-uncited 16, link-one-sided 7. The repair skill sits at 4999/5000 tokens (TRDD-IKZROIE5) because its body spells out mechanical fixes an agent performs by hand.

## Shape (proposal, awaiting owner approval)

ruff model: every lint rule is classified SAFE-FIX (deterministic, provably lossless, applied by memgrep lint --fix) or JUDGMENT (left to the agent). The skills then say: run the fixer, then handle only what it reports as unfixable. Next action: a per-rule classification table with the evidence for each SAFE-FIX verdict, then one rule at a time, each with its own test.

## Approval log

- 2026-10-01T17:23:43+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

2026-10-01 plan v4 approved by owner; derived cards minted: C01=TRDD-LKOUJC76, C02=TRDD-622ROA5F, C10=TRDD-2UAEQQ4A, C11=TRDD-OWGEOJ0D, C12=TRDD-7SMPCPNT, C13=TRDD-I23YCEW7, C14=TRDD-4G427D8M, C15=TRDD-9SUZ48E8, C16=TRDD-QBU0HSM9, C17=TRDD-KSCAFSLD, C18=TRDD-RLD015QB, C19=TRDD-RUJQ7WSX, C1A=TRDD-U2VUXGBP, C1B=TRDD-B9YPSF02, C1C=TRDD-UDE86OSZ, C1D=TRDD-V12ZHM1B, C20=TRDD-BHIS99XE, C21=TRDD-3HLI7DMK, C22=TRDD-JD2QR5SQ, C23=TRDD-VHFGPCOJ, C24=TRDD-8524H5V1, C25=TRDD-QXG8SRVD, C30=TRDD-I4MOD020, C31=TRDD-OLNPXGBC, C32=TRDD-1HXEAHY7, C33=TRDD-QX59MA4H, C34=TRDD-EMZUVIBK, C40=TRDD-ZYX8B2RA, C41=TRDD-RQMJFJGR, C42=TRDD-MIU9H3ZC, C43=TRDD-VA35WWWS, C44=TRDD-RVWJQR8E, C45=TRDD-PC2ZZR31, C46=TRDD-5ITPD1UD, C47=TRDD-7IPJA0ED (C46 is LOCAL scope); execution starts with C01/C02 after C00 unknowns report
