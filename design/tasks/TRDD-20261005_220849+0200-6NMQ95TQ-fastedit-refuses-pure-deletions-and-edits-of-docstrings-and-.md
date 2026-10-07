---
trdd-id: 6NMQ95TQ
title: fastedit refuses pure deletions and edits of docstrings and module constants and workers then edit by script
column: blocked
status: tasked
created: 2026-10-05T22:08:49+0200
updated: 2026-10-07T04:57:54+0200
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
blocked-by: [fastedit#14, fastedit#15]
pre-block-column: todo
blocker-probe: gh issue view 14 --repo Emasoft/fastedit --json state
blocker-holds-if: match:OPEN
blocker-probe-canary: match:state
---

# fastedit refuses pure deletions and edits of docstrings and module constants and workers then edit by script

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed three times in one day in this repository: fastedit refused a pure deletion of a block inside a function, an addition to a module docstring, and a new module-level constant. In the first case the worker edited a scratch copy by script and applied it as a full-function replacement, which the standing rule forbids; in the second the item was skipped and a stale docstring remains; in the third the text was written inline instead. To do: reproduce each refusal on a scratch file, find the supported way to make each edit, report upstream what has none, and state in worker prompts what to do on a refusal.

## Approval log

- 2026-10-05T22:08:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-06 FOURTH REFUSAL CLASS: a one-line insertion inside a function body (cmd_recall_cli and the find function of scripts/memgrep/src/memory.rs, card ZYX8B2RA) was refused six times across two workers. The owner refused the plain-edit fallback on 2026-10-06. ZYX8B2RA now waits on this card.
2026-10-06: further fastedit defects, a different subject from this card, recorded here as pointers. (a) Reported as Emasoft/fastedit#15: after two edits to one file, fastedit diff shows both edits, not only the last (measured on a scratch file, fastedit 0.5.0), and its help does not state the baseline; which backup it compares against is INFERRED, not read in the code. (b) Seen once, not reproduced, mentioned in a comment on #15: on that scratch file a later fastedit diff in a new process printed nothing and fastedit undo said there was no undo history; the same sequence on a second file kept its history. If real, undo history can vanish between processes.
- 2026-10-07T04:29:46+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on Emasoft/fastedit#14 and #15 (refused edits, diff baseline), both open on 2026-10-07; re-test the six recorded edits on each new fastedit release


## STATE

2026-10-06 NEXT ACTION: the refused edits are reported upstream as Emasoft/fastedit#14 (and the diff baseline as #15; file modes on #11, recurrence commented 2026-10-06). Wait for fixes there; this card's blocked dependents (TRDD-ZYX8B2RA, TRDD-YELTOX2S) resume when a fastedit release accepts the six recorded edits. Re-test those edits against each new fastedit release.
2026-10-06: hooks/hooks.json was found at mode 0600 after two fastedit writes today (an anchored fastedit edit for bace60f4, then create --force for dd779c12; mode not checked in between); a scratch test with fastedit 0.5.0 kept 0644 for create --force and edit, so the trigger is unknown. 41 tracked files in this repo were at 0600 (unknown writers and times); all restored to 0644 on 2026-10-06. Reported as a correction on Emasoft/fastedit#11. The dd779c12 commit message overstates (says both files).
2026-10-06: worker-reported, not reproduced: fastedit could not delete two stray blank lines in scripts/memgrep/src/fixers/mod.rs (C22 step S1); the worker then rewrote the whole file with fastedit create --force instead of stopping as its brief asked. The committed diff removed no original line. Same class as this card if reproduced: deletions with no replacement text are refused.
2026-10-06 (C22 S3+S4, commit 1f2a2896): three more refusals, all worker-reported and not reproduced by the main agent except that, for (b), the main agent checked that the committed diff near lint_label adds only the three stray lines, (a) and (b) on scripts/memgrep/src/memory.rs, (c) on design/specs/wikimem-memgrep-spec.md: (a) fastedit edit --replace lint_label with lint_label's own doc and body as the snippet printed a content-faithfulness failure, then 'Applied edit' while the file stayed unchanged; (b) fastedit delete lint_label removed the function but left its attached doc comments; (c) a keep-marker section replace in design/specs/wikimem-memgrep-spec.md was rejected after 9 attempts with a marker leaking into the merge. Earlier in the same step fastedit deletions left orphan #[test] and doc lines that a worker then removed with Python string replaces.
