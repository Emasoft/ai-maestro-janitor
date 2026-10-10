---
trdd-id: BAK8B3C0
title: Does the relocate re-survey miss a racing page whose name matches but whose description does not
column: testing
status: tasked
created: 2026-10-10T09:12:51+0200
updated: 2026-10-10T09:18:56+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T09:12:51+0200
parent-trdd: VIFQ1LKI
implementation-commits: [ee149708]
---

# Does the relocate re-survey miss a racing page whose name matches but whose description does not

Split from TRDD-VIFQ1LKI on 2026-10-10 so the open hole keeps an owner when that card closes.

WHAT IS KNOWN (read from code, commits be4e8fc4 and 6ab9618e): relocate_survey_then_create in scripts/lib/memory_content_precheck.py mints a page with memgrep new-mem-topic after an empty survey. The verb refuses by page NAME when the page already exists. The helper then re-surveys once with memgrep recall, which matches by TOPIC words against description, title and tags. If another agent created a same-name page whose description the topic query does not match, the re-survey is empty and the helper returns (False, None); the caller records a refusal and the atom is not moved in that pass.

WHAT IS NOT KNOWN: whether this has ever happened (FIELD CASE UNOBSERVED); what new-mem-topic prints on a refusal and whether that output names the existing page path, which nobody has read; whether any code calls the helper at all (on 2026-10-10 a grep of scripts, skills, agents and commands found no caller outside the tests, so agents follow the relocate skill text by hand and the same hole exists there as prose).

TO VERIFY BEFORE ANY BUILD: run new-mem-topic against an existing page in a scratch root and record its exact refusal output and exit code; decide whether the helper and the skill should take the destination from that output or from the page path composed from scope root plus name.

ALSO OWED HERE: the Returns sentence of the helper's docstring was left with nested parentheses and a badly wrapped line by 6ab9618e; rewrap it in the same change.

## Acceptance

- [x] The refusal output and exit code of new-mem-topic on an existing page are recorded on this card from a real run
- [x] A decision is recorded: close the hole (and how) or leave it with the reason
- [x] The docstring Returns sentence is rewrapped without nested parentheses

## Approval log

- 2026-10-10T09:12:51+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T09:18:56+0200 — column → testing. built in ee149708; waits for the full gate on it

## Corrections

2026-10-10 09:16, from the review of 957985a3: (1) the sentence saying recall 'matches by TOPIC words against description, title and tags' was taken from the memory rule text, NOT read from memgrep's code or from the helper's query; treat it as unverified and read it as part of this card. (2) 'the caller records a refusal' should read 'the relocate skill tells the agent to record a refusal'; no caller of the helper was found. (3) This card is NOT in TRDD-VIFQ1LKI's eht on purpose: the hole is unobserved and must not block that card's closure. (4) CARRIER: this card's change also carries the one skill sentence TRDD-VIFQ1LKI needs for its box 1 (step 3 of the relocate skill's CREATE section: record the empty survey in the report); it is worked next after TRDD-K0PMVRN6, in wave 4.
2026-10-10 09:19 BUILT in ee149708 (1 lean-worker, 0.11 million tokens; the main session read the whole diff and the probe lines of its report, docs_dev/20261010_091757+0200-bak8b3c0-probe-and-edits.md, gitignored). PROBE, worker-run on a scratch root: the first new-mem-topic exits 0; the second exits 1 with empty stdout and stderr 'Error: <root>/probe-topic.md already exists — new-page never overwrites an existing page'. So the refusal NAMES the existing page path. DECISION: the hole is closed in the skill prose (if the second survey is still empty, open the page the refusal named and use it if it owns the topic, else record a refusal); the helper's code is left as documented because no caller was found, and parsing stderr in a function nobody calls is code without a user. Not verified: how recall matches (still unread); that an agent follows the new sentence (FIELD CASE UNOBSERVED; only a live relocate pass after a release shows it). This card was a spike in verify_assumptions and became a build once the probe was specified; it was taken ahead of TRDD-ADIGRD0T in the trddgrep next order because it carries the sentence TRDD-VIFQ1LKI needs to close. The worker reported ruff, mypy, pyright and three test files at exit 0; the full gate on ee149708 writes reports/board/gate-ee149708.txt and had not reported when this was written; if it fails this card goes to dev.
