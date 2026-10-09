---
trdd-id: WD07P0T8
title: replace-mem-topic gate accepts a content file missing its opening frontmatter fence
column: backburner
status: tasked
created: 2026-10-09T03:39:58+0200
updated: 2026-10-09T03:44:15+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-09T03:39:58+0200
---

# replace-mem-topic gate accepts a content file missing its opening frontmatter fence

## Approval log

- 2026-10-09T03:39:58+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-09: card minted from the C31 memory-write review (eighth round on TRDD-OLNPXGBC). Defect: memgrep's replace-mem-topic write gate ACCEPTED a content file whose opening '---' frontmatter fence was missing — a frontmatter-stripping intermediate (the 'tldr body | tail -n +2' idiom strips the file's real first line along with the header) passed the gate and failed only post-hoc lint, inverting the gate's promise (its help says refusals name every violation). The gate must refuse any replacement body that does not open with a '---' fence where the target page has frontmatter. Origin: review of commits 4408f93a + 02a793ce, finding Q3(b). Related: TRDD-OLNPXGBC (the review that found it), LOCAL page fastedit-capped-file-whitespace-surgery.md (the page the stripped intermediate briefly damaged).
2026-10-09 review finding M2 applied: the mechanism claim 'tldr body | tail -n +2 idiom strips the file's real first line' is INFERRED, not verified — the eighth review reported the symptom (a fence-less intermediate passed the gate) and the transcript says only 'a truncating intermediate'. When this card is pulled, verify the actual mechanism first, then build the regression test against the verified input shape. Duplicate check done at mint time: no existing card tracks the write-gate fence-refusal promise (note: WD07P0T8 sits in backburner with no unblock-when; only drain-by-default pulls it).
