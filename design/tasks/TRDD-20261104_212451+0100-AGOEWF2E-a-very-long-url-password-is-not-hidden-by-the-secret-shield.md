---
trdd-id: AGOEWF2E
title: A very long URL password is not hidden by the secret shield
column: todo
status: tasked
created: 2026-11-04T21:24:51+0100
updated: 2026-11-05T04:04:49+0100
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
approval-datetime: 2026-11-04T21:24:51+0100
implementation-commits: [28eed2a3, df430e1a]
---

# A very long URL password is not hidden by the secret shield

Measured on 2026-11-04 under claude plugin test: one URL whose password alone is 1,048,576 mixed characters ('https://u:' + 'aB3dE5fG7hJ9kL1m' repeated + '@h'; the alphabet has no colon, at sign, slash, whitespace, quote or backtick) is not hidden: redact() reports no url-password hit and returns the text unchanged, and URL_PASSWORD alone gives 0 matches, with the regex of 133a766a and with that of 6decd71d alike. The same URL at 256 KB and at 512 KB is hidden. Above 512 KB only this one shape, alone in its text, was measured, and only at 1 MB; a larger size, or a long password inside other text, was not run. An earlier measurement in system Bun saw a miss from about 385 KB (133a766a) and about 360 KB (the regex of 6decd71d) on a shape not recorded here. The direct 0 matches rule out looksSecret and every other redact() filter, the hits at 256 KB and 512 KB rule out the alphabet, and the known-defect test in tests/patterns.test.ts would fail if the regex threw, so the regex returns no match. Inferred, not shown: the regex engine gives up on a match this long. The shield is not wired yet (TRDD-2V7OAUPE); once it is, a URL password past that size would reach the model unhidden. Related: TRDD-OD5Z90YL (a step in URL_PASSWORD's time between 96 KB and 128 KB, cause not found), possibly the same engine limit. Done when: (1) a stated cause predicts by how much the size where hiding stops moves when one named variable changes (the text before the URL, or the runtime), and one run confirms that amount; the runs vary one thing at a time: the password length alone, the same text and regex under Node (V8), and system Bun against claude plugin test; (2) either the miss is fixed, shown by a test that hides the password at every power of two from 256 KB to 4 MB, or the size limit is measured in the runtime the mod runs in, written down in hooks/secret-shield, and the shield fails closed past it: a length or work bound checked before or around the regex, never the regex's own empty result, withholds a value it cannot finish scanning, shown by a test; (3) every rule in hooks/secret-shield (the rules/ exports and the module-private regexes of patterns.ts) that can match a value longer than 64 KB is checked the same way, with the result per rule recorded on this card.

## Approval log

- 2026-11-04T21:24:51+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Notes

- 2026-11-05 — Owner decision ("you must stop any work on the rotator code too. also never write or present anything in repos not belonging to Emasoft (me) unless i explicitly ask you to. measure and fix everything you said. you can file any bug you want in my Emasoft repos. but the trddgrep is now handled by the 3-pillars-task-system plugin. you can sendmessage to it, a claude instance updating the plugin it is running right now."). Read as: no upstream report of the URL-password slowdown; it is measured and fixed here (TRDD-OD5Z90YL diagnosis, TRDD-AGOEWF2E long-password miss), and jr-redact is measured before it is disabled. Now in scope: measure and fix here.
- 2026-11-05 — Measured (same raw data as TRDD-HF7GNHNF): the miss is the second ceiling of the same group-loop family. Under claude plugin test a password in a mixed 16-character alphabet is hidden up to 552,896 characters and missed from 552,960 (bisect step 64), silently: 0 matches and no error, in 47 to 60 ms. Text before the URL (2.7 MB of prose, or 800 KB of short URL starts) moves the limit by 0, and so does the case flag; dropping the lookbehind moves it to 589,760 and dropping the port-skip lookahead to 749,504; a long user part instead of a long password is missed from 995,328. System Bun 1.3.14 misses from 360,448; Node v26 throws a RangeError at 2^23 iterations instead of missing. These shifts were measured first and explained afterwards, so they do not tick Done when 1 (a prediction, then one confirming run). A password that is a run of x is never hidden at any size, because redact() treats it as a placeholder, so tests need a mixed alphabet. With the three loops unrolled (TRDD-HF7GNHNF), the regex alone matches a mixed password at 4,194,304 characters (redact() not measured at that size), but a password made mostly of colons is still missed somewhere between 589,824 and 1,048,576 characters, so the fix needs an explicit bound that fails closed. Not yet checked (Done when 3): every rules/ export and module-private regex that can match a value longer than 64 KB.
