---
trdd-id: A2JLFIQ5
title: the rotator's automatic tick does not say why the primary credential was not read
column: testing
status: tasked
created: 2026-10-05T15:21:19+0200
updated: 2026-10-10T14:14:07+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T15:21:19+0200
parent-trdd: QQ7QCS3T
---

# the rotator's automatic tick does not say why the primary credential was not read

The headless daemon skips the read of the primary live credential on purpose and works from the mirror copy (default-off behaviour shipped in 2b18348f; the owner question on that default is TRDD-QQ7QCS3T). The line the automatic tick logs when it uses the mirror carries no reason, so that line reads the same whether the read was skipped by policy, failed, or the mirror itself was hard to read. The capture path does name its reason.

Consequence seen on 2026-10-05: a reader of the log took the designed skip for a defect, opened TRDD-HVGU9OBL, and withdrew it after reading the code.

Wanted: the automatic tick's line names the reason the primary was not read, in the same words the capture path uses, so a skip by policy, a failed read and a degraded mirror read can be told apart from the log alone. A log-text change only; no change to what is read or to any keychain call.

## Approval log

- 2026-10-05T15:21:19+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T13:53:35+0200 — column → testing by main-agent@ai-maestro-janitor. built; waits on the full gate and then on the named field check after a release

## Acceptance

- [x] A test shows the automatic tick's line contains the policy-skip reason when the headless setting is on.
- [ ] A test shows a different, distinguishable reason when the primary read is attempted and fails. NARROWED 2026-10-10: the test reaches that reason (the helper's third, 'unreadable (no primary item / keychain absent)') with the headless variable unset and no latch file; NO read attempt is made in the test, because it must not touch a real keychain. A real attempted-and-failed read is unobserved.

## STATE

2026-10-05 — Column todo. Nothing built. The change touches the rotator's logging only; because the rotator is credential code, a review must confirm no read, write or prompt is added.
2026-10-05 — OPEN OBSERVATION, unexplained and on no other card: on 2026-10-05 the heartbeat printed slot reads from the credential store timing out at their five-second limit while the machine's load was very high. Whether those timeouts were load alone was not determined, and it was not checked that the mirror read itself succeeded on the ticks that used it. Working from the mirror is by design a reduced-trust state (the identity is treated as untrusted).
2026-10-10 13:53 BUILT in one commit with these lines (TRDD-S6GX1DHN wave 7 card 4). SEEN IN THE FIELD first: today's rotator log prints, once a minute, 'auto: primary live credential UNREADABLE from this context, using the -livebak MIRROR' with no reason, next to a capture line that does name it. CHANGE: in scripts/oauth_rotator/rotator.py _resolve_untrusted_live, that line now carries the reason from the existing _primary_read_unreadable_reason(), the helper the capture line uses. Read by the main session before the brief: the helper reads only the JANITOR_ROTATOR_HEADLESS variable and the primary-read latch file (JSON under the rotator folder); it makes no keychain call and starts no process. The diff is three lines of code and one comment; no read, write or prompt is added. TEST: tests/test_oauth_rotator.py::test_untrusted_live_auto_line_names_its_reason covers all three reasons (policy skip; unreadable with no latch; refused by the latch) and that they differ; re-run by the main session, passed. The test file's autouse fixture points the rotator folder at a temporary directory, so the latch the test writes cannot land in the real one (checked: the real folder has no latch file). Box 2's 'attempted and fails' is the helper's third reason, reached in the test with the variable unset and no latch; no real keychain read is made in the test. Worker checks: 188 passed in the file; ruff, mypy, pyright clean; the worker saved no separate red-run output (it reported the first version failing before the edit). KNOWN LIMITS: the repair line ('primary live item present but unreadable from this context') still gives no reason; it is a different line and not on this card. The line is emitted through _decide; whether _decide dedupes on text was not read by the main session, so the reason may change how often the line prints. FIELD CHECK after a release: the tick's line in rotator.log contains 'skipped by policy'. DETECT: grep -a 'auto: .*UNREADABLE (' on rotator.log under the plugin data oauth-rotator folder. The OPEN OBSERVATION of 2026-10-05 above (slot reads timing out under load) is untouched and still on no other card. Cost: 1 coding worker in two rounds (about 0.12 million tokens).
2026-10-10 14:12 GATE GREEN on 0449b637: 18306 passed, 2 skipped; ruff, mypy, pyright exit 0; strict validator exit 0 (reports/board/gate-0449b637.txt, strict-validate-0449b637.txt). Review of 0449b637 (0.50 million tokens): no code defect, nothing new read, written or prompted; ACCEPTED its one point, box 2 was ticked without its narrowing in the box, now written there. Noted, no action: the line grows by about 45 characters a minute; if _decide dedupes on text its key changes once at upgrade (still not read). STAYS IN TESTING, dated reason: the card names a field check that needs a release (wave 3 closing rule). DETECT as above.
2026-10-10 14:25 Box 2 UNTICKED after the review of 0bf0c976: a box whose own text says the case is unobserved is not met. The reason string is tested; an attempted read that fails is not, and cannot be without a real keychain.
