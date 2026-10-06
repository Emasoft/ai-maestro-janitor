---
trdd-id: 6NMQ95TQ
title: fastedit refuses pure deletions and edits of docstrings and module constants and workers then edit by script
column: todo
status: tasked
created: 2026-10-05T22:08:49+0200
updated: 2026-10-06T19:05:54+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:49+0200
---

# fastedit refuses pure deletions and edits of docstrings and module constants and workers then edit by script

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed three times in one day in this repository: fastedit refused a pure deletion of a block inside a function, an addition to a module docstring, and a new module-level constant. In the first case the worker edited a scratch copy by script and applied it as a full-function replacement, which the standing rule forbids; in the second the item was skipped and a stale docstring remains; in the third the text was written inline instead. To do: reproduce each refusal on a scratch file, find the supported way to make each edit, report upstream what has none, and state in worker prompts what to do on a refusal.

## Approval log

- 2026-10-05T22:08:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-06 FOURTH REFUSAL CLASS: a one-line insertion inside a function body (cmd_recall_cli and the find function of scripts/memgrep/src/memory.rs, card ZYX8B2RA) was refused six times across two workers. The owner refused the plain-edit fallback on 2026-10-06. ZYX8B2RA now waits on this card.
2026-10-06: further fastedit defects, a different subject from this card, recorded here as pointers. (a) Reported as Emasoft/fastedit#15: after two edits to one file, fastedit diff shows both edits, not only the last (measured on a scratch file, fastedit 0.5.0), and its help does not state the baseline; which backup it compares against is INFERRED, not read in the code. (b) Seen once, not reproduced, mentioned in a comment on #15: on that scratch file a later fastedit diff in a new process printed nothing and fastedit undo said there was no undo history; the same sequence on a second file kept its history. If real, undo history can vanish between processes.


## STATE

2026-10-06: the fastedit file-mode defect (Emasoft/fastedit#11: rewritten files get mode 0600) recurred on hooks/hooks.json and a test file (fastedit create --force); modes restored to 0644 before commit dd779c12. Workers using fastedit must check file modes after a write.
