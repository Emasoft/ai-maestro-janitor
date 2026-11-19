---
trdd-id: CAZIKQVH
title: The redaction bridge hides nothing on 16 lines where the shield scanner reports an assignment finding
column: complete
status: archived
created: 2026-11-18T18:12:33+0100
updated: 2026-11-19T00:02:38+0100
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
approval-datetime: 2026-11-18T18:12:33+0100
implementation-commits: [aac5be3c, d481db79]
---

# The redaction bridge hides nothing on 16 lines where the shield scanner reports an assignment finding

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-19

- Fixed in commit aac5be3c (fix(secret-shield): read each JSON line of a text as JSON, after the old passes). redactDeep and redactBlocks run the two old walks unchanged, then read each line of a text that parses as a JSON object or array as JSON, then hide found values where copied, also behind escapes; bridge op "both" and the dry run use the new redactText. Tests: 20 in hooks/secret-shield/tests/json-text.test.ts.
- Cause: only the plain rules read a text, and they missed a value behind an escape inside a JSON line.
- d481db79 corrected the stale comments in scripts/lib/transcript_redact.py and added the follow-up TRDD-8O9A2QRS (union pass for the 1,732 of 200,000 texts this order leaves partly visible, hook timing risk, load-sensitive ratio test).
- Evidence: secret-shield mod tests 1365 pass 0 fail (reports_dev/main-agent/post1/a87-verify/mod-tests.txt, run by the orchestrator on this tree); 16 of 16 bench lines carry markers through the bridge, 0 of 200,000 generated texts show more of a planted secret than bd6bca6f through redactDeep and through redactBlocks, index output equals no-index on 60,000 texts (reports_dev/mods-expert-developer-agent/probe/p10/final-run-v8.txt); 20 tests in hooks/secret-shield/tests/json-text.test.ts.
- Not covered: lines with a prefix (a numbered Read line), multi-line pretty-printed JSON. The mod is not loaded live yet (hooks/hooks.json has no modules key; wiring is TRDD-2V7OAUPE).

## Approval log

- 2026-11-18T18:12:33+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-19 — Moved from backburner straight to complete by main-agent@ai-maestro-janitor: no separate testing or human review column was passed.
- 2026-11-19T00:02:38+0100 — COMPLETE by main-agent@ai-maestro-janitor. Done means met: reproduced in json-text.test.ts, cause found, the bridge marks all 16 lines the scanner reports; fixed in aac5be3c, comments in d481db79.

## Symptom

By main-agent 2026-11-18: redact_texts (scripts/lib/transcript_redact.py) returned unchanged 16 lines that scan.ts reports as kind assignment: tests/agent_context_bench/corpus-vawikrk2-20260821.jsonl lines 3, 12, 13, 14, 25, 50, 59, 60, 93, 111, 113 and 140; corpus.jsonl lines 1, 4 and 238; benign-ordinary.jsonl line 27. The realtime and transcript redaction paths use the bridge, so a value the scanner sees can reach the agent or a transcript.
Not reproduced by the cheap-worker that wrote this card. The main agent equality-tested the 16 lines on 2026-11-18 with scripts_dev/triage/bridge_equal.py: redact_texts returned all 16 unchanged, with no marker of either kind. The mods expert found the same gap on the live mod path (P10 of its design report, 2026-11-18): redactDeep finds none of the 16 inside a text, redactJsonLine finds them. Increment 3a of TRDD-DSXC9MP9 is to fix it in the core.

## Suspected cause

Not known. A lead: the key and value context inside a JSON string line (design/specs/TRDD-BAQB9SYO-increment-3-redact.md, line 5, item b).

## Done means

The gap is reproduced with a fragment-built test line, its cause is found, and the bridge and the scanner agree, or the difference is documented as intended. Related: TRDD-DSXC9MP9, TRDD-Q6LPJTPO.

## Acceptance

- [x] The gap is reproduced with a fragment-built test line (hooks/secret-shield/tests/json-text.test.ts, 20 tests; mod tests 1365 pass 0 fail in reports_dev/main-agent/post1/a87-verify/mod-tests.txt).
- [x] The cause is found: only the plain rules read a text, so a value behind an escape inside a JSON line was missed (reports_dev/mods-expert-developer-agent/20261118_191313+0100-p10-json-lines.md).
- [x] The bridge and the scanner agree: 16 of 16 lines carry markers through the bridge (reports_dev/mods-expert-developer-agent/probe/p10/final-run-v8.txt, line bridge_equal exit=0 changed=16 unchanged=0 marker=16).
