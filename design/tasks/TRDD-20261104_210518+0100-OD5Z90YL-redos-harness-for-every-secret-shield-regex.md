---
trdd-id: OD5Z90YL
title: ReDoS harness for every secret-shield regex
column: backburner
status: tasked
created: 2026-11-04T21:05:18+0100
updated: 2026-11-04T21:05:18+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-04T21:05:18+0100
---

# ReDoS harness for every secret-shield regex

Split from TRDD-KADV0ZO6 Done-when item 3 after its review on 2026-11-04: build the ReDoS harness that the publish gate of TRDD-KADV0ZO6 runs over every regex in hooks/secret-shield. Requirements: (1) a registry of every regex: the rules/ exports, the module-private regexes in patterns.ts (URL_PASSWORD, the assignment and setting rules, MARK, MARKS, MARK_SPLIT) and any regex in register.ts or rows.ts; (2) completeness checked against the source, never against the registry's own length: scan every .ts file under hooks/secret-shield except tests/ for new RegExp( and regex literals, with an allow-list for non-regex matches, and fail when a source regex is missing from the registry; (3) a per-regex adversarial failing tail in a table under tests/, never a generic tail, because the two quadratics found on 2026-11-04 needed specific shapes (a run of scheme characters such as A1- repeated; 'b://u:1?' repeated with the URL count growing with the size), and a generic run of x is linear even on those regexes; (4) each regex timed with only TRDD-Q6LPJTPO's ratio rule (under 12 across an 8x size step, or under 2 ms at the larger size), with a warm-up run and the median of at least 5 runs per size, no absolute limit and no load precondition; (5) at the larger size, each regex also runs on the long failing prefix followed by a separator and a short, self-contained real match and asserts at least one hit: a redact() hit for a rule, a raw exec match for a helper regex such as MARK, MARKS or MARK_SPLIT; the positive samples live in tests/ as split strings, never as literal tokens in rules/; (6) red-on-old-code proof: URL_PASSWORD as it was before 133a766a, and before the port-skip query-scan fix, fails the new test. Known before starting: under claude plugin test the fixed URL_PASSWORD shows an undiagnosed fixed step of about 60 ms between 64 KB and 128 KB that stays flat to 256 KB; diagnose it before choosing sizes of 128 KB or more. Done when: requirements 1 to 6 hold, each shown by a run, and the harness fails when one new private regex is added to patterns.ts without a registry entry.

## Approval log

- 2026-11-04T21:05:18+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
