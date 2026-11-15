---
trdd-id: BDRXOZ6N
title: Generated CHANGELOG entries fail the next release's cspell preflight
column: backburner
status: tasked
created: 2026-11-15T11:50:58+0100
updated: 2026-11-15T11:53:01+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-15T11:50:58+0100
---

# Generated CHANGELOG entries fail the next release's cspell preflight

## Approval log

- 2026-11-15T11:50:58+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-15T11:53:01+0100 — RATIFIED by the main agent: this card was created by a sonnet-worker on the main agent's explicit instruction; after trddgrep refused the first new for a missing --author, the worker reused main-agent@ai-maestro-janitor without being given it. The main agent confirms that identity as the card's author and owner (it directed the creation) and confirms the tool's mandate line as the record of that instruction. approved: true covers the card's existence on the backburner only; the fix choice stays with the owner (line 33).

## Finding

- publish.py regenerates CHANGELOG.md with git-cliff at step 9, after its own CI-parity preflight at step 4b. So each release commits a changelog that cspell never checked, and the NEXT release's preflight fails on it.
- Two occurrences: 948c3dd0 (3.8.12) and 200aed7f (3.9.0, five words: all-letter TRDD ids FADYLSQB, KSUIEPTQ, RJJGXPIK, SQBTMGYW written without the TRDD- prefix, plus EPERM).
- The two proposed fixes, owner to choose: (a) an override in .cspell.json scoped to CHANGELOG.md only that ignores standalone 8-letter uppercase ids, since that file is generated from commit subjects; (b) publish.py runs cspell on the regenerated CHANGELOG.md before step 10 commits it.
- The card itself is a main-agent backburner chore (see Approval log); only the CHOICE between fix (a) and fix (b) is the owner's, proposed to the owner in the session chat on 2026-11-15 and not yet answered.
