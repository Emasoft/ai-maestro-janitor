---
trdd-id: OD5Z90YL
title: ReDoS harness for every secret-shield regex
column: backburner
status: tasked
created: 2026-11-04T21:05:18+0100
updated: 2026-11-04T21:49:26+0100
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

Split from TRDD-KADV0ZO6 Done-when item 3 after its review on 2026-11-04: build the ReDoS harness that the publish gate of TRDD-KADV0ZO6 runs over every regex in hooks/secret-shield. Requirements: (1) a registry of every regex: the rules/ exports (which TOKENS lists), the module-private regexes in patterns.ts (URL_PASSWORD, the assignment and setting rules, MARK, MARKS, MARK_SPLIT) and any regex in register.ts or rows.ts; (2) completeness checked against the source, never against the registry's own length: scan every .ts file under hooks/secret-shield except tests/ for new RegExp( and regex literals, with an allow-list for non-regex matches, and fail when a source regex is missing from the registry; a regex built by a factory counts once per rule it builds, not once per call site; (3) a per-regex adversarial failing tail in a table under tests/, never a generic tail, because the two quadratics found on 2026-11-04 needed specific shapes (a run of scheme characters such as A1- repeated; 'b://u:1?' repeated with the URL count growing with the size), and a generic run of x is linear even on those regexes; each tail states its design basis in the table, and for each regex one run shows its tail turning a known-quadratic variant of that regex red; (4) each regex timed with only TRDD-Q6LPJTPO's ratio rule (under 12 across an 8x size step, or under 2 ms at the larger size), with the larger size at 256 KB as that card's ReDoS check uses, a warm-up run and the median of at least 5 runs per size, no absolute limit and no load precondition; (5) at the larger size, each regex also runs on the long failing prefix alone, asserting zero hits, and on that prefix followed by a separator and a short, self-contained real match, asserting exactly one hit and the exact marked ending: a redact() hit for a rule, a raw exec match for a helper regex such as MARK, MARKS or MARK_SPLIT; the positive samples live in tests/ as split strings, never as literal tokens in rules/; (6) red-on-old-code proof: URL_PASSWORD as it was before 133a766a, and as it was before 6decd71d, fails the new test; (7) the existing timing tests of 133a766a and 6decd71d in tests/patterns.test.ts are brought under rule (4) or replaced by the harness. Known before starting: under claude plugin test URL_PASSWORD slows by a step of tens to about 200 times between 96 KB and 128 KB on the grown() shape of tests/patterns.test.ts (redact() medians on its shape b about 3 ms at 96 KB, 75 ms at 128 KB, 188 ms at 256 KB and 615 ms at 512 KB, load about 67), and the regex before 6decd71d shows a step of similar size on 'b://u:' repeated then x; on grown() the password stays hidden at every measured size up to 1 MB. So with the larger size at 256 KB, URL_PASSWORD fails rule (4) today, and the harness stays red until the step is diagnosed and removed. Diagnose it by varying one thing at a time: (a) fix the URL count at 4096 and grow the padding, then fix the padding at 32 KB and grow the URL count, and separate a long query scan from a long password, since grown() shape a has both; (b) the same regex and text under Node (V8); (c) system Bun against claude plugin test; (d) drop one regex construct at a time and re-time; (e) a shape that never triggers the port-skip lookahead, on the regex before 6decd71d and on the current one. Related: TRDD-AGOEWF2E (a very long URL password is not hidden), possibly the same engine limit. Done when: requirements 1 to 7 hold, each shown by a run, and the harness fails when one new private regex is added to patterns.ts, when one new rules/ export is left out of both the registry and TOKENS, and when one new regex is added to register.ts or rows.ts, each without a registry entry.

## Approval log

- 2026-11-04T21:05:18+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
