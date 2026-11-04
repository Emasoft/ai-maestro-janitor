---
trdd-id: 5VZTPXBJ
title: Secret-shield token rules miss a token right after an escaped newline, a percent-encoded quote or a tab
column: todo
status: tasked
created: 2026-11-04T22:38:06+0100
updated: 2026-11-05T00:46:34+0100
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
approval-datetime: 2026-11-04T22:38:06+0100
---

# Secret-shield token rules miss a token right after an escaped newline, a percent-encoded quote or a tab

## Problem

Each of the five `\b`-led token rules measured misses a token that follows an escape whose last character is a word character. Measured on 2026-11-04 with redact() from hooks/secret-shield/patterns.ts (Bun 1.3.14). Four of the tokens below (all but AIza, whose standalone case was not re-run here) were hidden when they stood alone, and all five were visible in all three of these contexts; the other `\b`-led rules, including the new Google rules `\bGOCSPX-` and `\bya29.`, are expected to miss the same way (not measured):

- after the two characters backslash and n inside a JSON string, as serialized JSON writes a newline (measured as `{"m":"line\\nAIza..."}` in JS source);
- after `%22` (a URL-encoded quote);
- after a literal backslash-t.

Tokens measured: `AIza` (google-api-key), `ghp_` (github-token), `sk-ant-api03-` (anthropic-key), `AKIA` (aws-access-key), `xoxb-` (slack-token).

Cause, inferred from the regex semantics and not traced in code: `\b` needs a non-word character before the prefix, and `n`, `2` and `t` are word characters. The refresh-token rule's lookbehind `(?<![\w/+])` is expected to fail for the same reason (not measured). Measured contexts for AIza: `{"m":"line\\nAIza..."}`, `q=%22AIza...%22` and `a\\tAIza...` (JS source strings).

Not covered by the escaped-JSON change (c0e1abcc), which fixed the key-name rule only.

## Done when

1. A known-defect test pins today's miss (the TRDD-AGOEWF2E pattern): for each measured rule, a token after a literal backslash-n, after `%22` and after a literal backslash-t stays visible. The test fails when the defect is fixed, and is then turned into a positive test.
2. A fix hides each token in each of the three contexts. Candidate approaches, none chosen:
   - a boundary that also accepts a preceding `\\[nrt]` or `%[0-9A-Fa-f]{2}`;
   - a second pass over an unescaped copy, with positions mapped back.
   The fix must not hide text the current false-positive corpus keeps.
3. Each changed rule stays linear (64, 256 and 512 KB, below the core count; a timing taken above the core count is inconclusive, not failed).

Found during TRDD-Q6LPJTPO (Google family, d711e5f8).

## Approval log

- 2026-11-04T22:38:06+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Notes

- 2026-11-05 — Done-when item 1 is not ticked. The KNOWN DEFECT escape-boundary test in hooks/secret-shield/tests/known-misses.test.ts (317d6a9e) covers all three escapes (a literal backslash-n, %22 and a literal backslash-t) for each of 21 rules, and asserts that count. But this card measures five rules (AIza, ghp_, sk-ant-api03-, AKIA, xoxb-), not 21, and its Done-when items are numbered, not checkboxes, so there is no box to tick. To close item 1, the Problem section must state the 21-rule coverage, and the items must become checkboxes. (Withdrawn: see the correction of 2026-11-05 below.)
- 2026-11-05 — The refresh-token rule's refusal of a start right after a plus sign is measured and admitted as KNOWN-MISSES entry google-refresh-after-plus. The URL-encoded form of a refresh token is on the TRDD-Q6LPJTPO backlog.
- 2026-11-05 — The test is one loop over all rules. A partial fix turns it red and must split it per rule.
- 2026-11-05 — Correction to the first note above: Done-when item 1 is met. That note wrongly treated the test's 21-rule coverage as a mismatch: item 1 needs the 5 measured rules, and the 21 include them (per the tokens record of the KNOWN DEFECT test in hooks/secret-shield/tests/known-misses.test.ts: AIza is googleApiKey, ghp_ is githubTokenClassic, sk-ant-api03- is anthropicKey, AKIA is awsAccessKey, xoxb- is slackToken). Its call to turn the items into checkboxes is withdrawn.
