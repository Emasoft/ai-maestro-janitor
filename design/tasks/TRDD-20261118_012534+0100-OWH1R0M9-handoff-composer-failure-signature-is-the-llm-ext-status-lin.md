---
trdd-id: OWH1R0M9
title: Handoff composer failure signature is the llm-ext status line, and handoff size has no bound
column: todo
status: tasked
created: 2026-11-18T01:25:34+0100
updated: 2026-11-18T16:45:27+0100
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
approval-datetime: 2026-11-18T01:25:34+0100
implementation-commits: [0c55d740]
---

# Handoff composer failure signature is the llm-ext status line, and handoff size has no bound

Source: GitHub issue #364 (https://github.com/Emasoft/ai-maestro-janitor/issues/364), filed by another agent; its claims are unverified.

Owner order 2026-11-17 (verbatim): "convert those issues into TRDDs to solve all those issues and improve the whole janitor system migrating to mods most of its functionalities. but those TRDDs must be written now and handled later." Written now, handled later; TRDD-BAQB9SYO has priority.

## Symptom

By the issue: the handoff write command printed SUMMARY_FAILED three times on 2026-11-17 and 2026-11-18 in one session. The compose log gives as the reason a llm-ext status line (Auth: token resolved) that is not an error, with outcome classes transient (deadline) then permanent (repeated). By the issue the real error is further down stderr and the log never shows it; a later comment says that sentence is an inference, the stderr of the failing runs was not captured, and what the three failures actually were is unknown. Separately by the issue, successful handoffs grew with the transcript (118,225, 196,084 and 253,536 chars) and the composer checks no size before writing.

## Suspected cause

By the issue: failure_signature in the summary library is the exit code plus the first stderr line, but the first stderr line of llm-ext is the same startup status line on every run, so the logged reason is that line and every exit-1 failure gets the same signature; the retry loop counts unknown-outcome attempts by detail string and gives up as permanent repeated once one detail reaches the give-up threshold, so two different failures end the retries as if one cause repeated. The llm-ext side writes the line at import time on every command and may stop printing it, but by the issue the signature must not depend on any status line. Expected by the issue: the signature skips status lines or uses the last error line, the log carries the line that names the failure, and the summary has a size bound or a pointer-only handoff above it.
- Follow-up, 2026-11-18T01:38:37+0100, by fast-worker for main-agent: a second comment on issue 364 (by the commenter, not verified here) reports a hand rerun of the composer's llm-ext session-summary command with stderr saved: exit 1 after 88 s, 23 stderr lines, the first the Auth status line, the last a FAILED: session-summary line naming an API error 403 (model not available in the region) on a free model. By the comment the llm-externalizer side did not rotate to another model on that 403; its fix is on the llm-externalizer development branch, not pushed yet. The commenter infers that the failures logged at 22:55 on 2026-11-17 and 00:02 on 2026-11-18 share this cause; the one at 16:13 (transient deadline) is unknown. The comment proposes keying failure_signature on the FAILED: line or the last non-empty stderr line.

## Files named by the issue

scripts/lib/llm_ext_summary.py (failure_signature lines 306-323; retry loop around lines 500-507, _UNKNOWN_REPEAT_GIVEUP); scripts/compose_agent_handoff.py (lines 133-134, HANDOFF_READY); the write-handoff skill; per-project .janitor/logs/agent-handoff-compose.log; the llm-externalizer side scripts/llm-ext/src/index.ts (lines 643-647, another repository).

## Done means

The defect is reproduced or shown absent, fixed with a test where one fits, and the issue is answered and closed.
Related card TRDD-WUIN2IGF (migrate most janitor functionality to Claude Code mods, owner order 2026-11-17) may move the component this fix touches; check it before fixing. Link only, no design rule.

## Approval log

- 2026-11-18T01:25:34+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-18T16:38:09+0100 — progress, by cheap-worker for main-agent: implementation-commits set to [0c55d740]. Per main-agent evidence: failure_signature keys on the last FAILED: line with times, hex ids and long numbers masked; part (b) is not shown resolved. Part (b) is the handoff size bound. The 0c55d740 commit message calls it held because _handoff_body caps the injected handoff at about 7.8 KB (not checked by cheap-worker). That cap is on the injection, not on the composer write, which the card says checks no size (issue claim, not checked here). Files of 0c55d740 (git show --stat): scripts/lib/llm_ext_summary.py, tests/test_llm_ext_summary.py. Card not moved: a GitHub issue answer (issue 364) comes first.
