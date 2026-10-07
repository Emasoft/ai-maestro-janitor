---
trdd-id: 2MU62A5F
title: the resume shows the tool and event items Jev kept even on a thin session
column: testing
status: tasked
created: 2026-10-05T10:57:06+0200
updated: 2026-10-07T09:35:57+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T10:57:06+0200
parent-trdd: D7RLXAN1
implementation-commits: [09b769b2, 52c87cbb]
---

# the resume shows the tool and event items Jev kept even on a thin session

Acceptance (c) of TRDD-D7RLXAN1 failed: on thin sessions 0 of 2 tool and event items Jev kept were shown after the resume.
Nothing is built for it yet; it changes the item rule of TRDD-U6C3YXEL, which is superseded, and TRDD-350W5II2 does not cover it.
Wanted: the resume injects the tool and event items Jev kept, not only the token stage's set, so a thin session still shows 3.

## Approval log

- 2026-10-05T10:57:06+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T09:35:57+0200 — column → testing by main-agent@ai-maestro-janitor. built; the real-session re-render is still outstanding

## Acceptance

- [x] The resume injects the tool and event items Jev kept, not only the token stage's set (met by 09b769b2 and 52c87cbb; four tests in tests/test_jev_compaction.py).
- [ ] The two real thin sessions named in the card are re-rendered and show 3 items (NOT done).
