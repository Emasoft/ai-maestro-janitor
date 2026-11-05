---
trdd-id: 2V7OAUPE
title: Wire secret-shield into hooks.json and disable jr-redact
column: blocked
status: tasked
created: 2026-11-03T22:46:01+0100
updated: 2026-11-05T02:41:31+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-03T22:46:01+0100
blocked-by: [0Y3UW1NF, TEP6F3A3, 3GP0D06D, KADV0ZO6, AGOEWF2E, HF7GNHNF, J0TBHZ15]
unblock-when: [trdd:0Y3UW1NF terminal, trdd:TEP6F3A3 terminal, trdd:3GP0D06D terminal, trdd:KADV0ZO6 terminal, decision:owner-answers-TEP6F3A3-wiring-gate]
pre-block-column: design
blocker-probe: for i in 0Y3UW1NF TEP6F3A3 3GP0D06D; do trddgrep --porcelain show $i | cut -f3; done | grep -cE '^(complete|published|live)$'
blocker-holds-if: not-match:^3$
---

# Wire secret-shield into hooks.json and disable jr-redact

## Task
Add "modules": ["./secret-shield/register.ts"] to hooks/hooks.json (path to be confirmed against how hooks.json resolves module paths), disable the jr-redact plugin in the same step, remove "Not active yet." from the three secret_shield_* option descriptions, then run a live probe: a fake token built with printf in Bash output and in an MCP tool result must reach the transcript as a janitor marker, with byte counts of the session .jsonl.
Acceptance gate (must pass before complete): live probe, for both a normal and an error tool result containing a fake token, the model-facing transcript shows the marker and not the token (TRDD-337UVA3J).
Blocked by TRDD-3GP0D06D: the shield is not turned on while its tests run outside the release gate.

## Blocked by
TRDD-0Y3UW1NF (write-back guard) and TRDD-TEP6F3A3 (checks before wiring). TRDD-337UVA3J does not block it: upstream ships without error-result redaction.

Split out of TRDD-M1218EMH.
- Why the trdd:<id> terminal predicates cannot release this card on a failed, cancelled, superseded or refused blocker: trdd-drift _try_unblock (scripts/detectors/trdd-drift.py) restores a blocked card only when the predicate holds (TERMINAL_COLUMNS) and every blocked-by id is in DONE_COLUMNS, so only complete, published or live releases it, and blocker-probe counts those three. A blocker that ends at completed keeps this card blocked (see TRDD-OEEH2W28). Covered by test_try_unblock_holds_when_blocked_by_is_terminal_but_not_done in tests/test_trdd_drift_unblock_when.py. Since 2026-11-04 the predicate decision:owner-answers-TEP6F3A3-wiring-gate never clears on its own, so the predicates alone cannot release this card until it is removed once the owner has answered TRDD-TEP6F3A3's wiring questions; the wiring gate test (tests/test_secret_shield_wiring_gate.py) reads only blocked-by and does not check that predicate.

## Approval log

- 2026-11-03T22:46:01+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-03T22:46:10+0100 — column → blocked. waits for the write-back guard and the pre-wiring checks

## Notes

2026-11-04 — when jr-redact (from the claude-code-mods marketplace) is enabled alongside the janitor shield, both rewrite the same tool results; jr-redact marks them [REDACTED:<kind>] but passes error results unredacted (register.ts:11, found by a corpus miner), and its password rule can also replace the username (redact.ts:32). If jr-redact stays enabled, decide the two redactors' order and whether a value already marked by one is left alone by the other before this card turns the shield on; if this card disables it as planned, the ordering question is moot.
 - 2026-11-05 — No automated gate runs the secret-shield TS suite: scripts/publish.py stage_tests runs pytest only, no .github workflow calls claude plugin test, and nothing type-checks hooks/. This covers every shield family so far (d711e5f8, dbd5aaf9, 28b42512). The tests run only when someone runs them by hand in a scratch plugin shell; the real hooks/hooks.json names no module yet.
 - 2026-11-05 — The TS-suite publish gate is tracked in TRDD-T36Z4ACR.
- 2026-11-05 — Owner decision ("you must stop any work on the rotator code too. also never write or present anything in repos not belonging to Emasoft (me) unless i explicitly ask you to. measure and fix everything you said. you can file any bug you want in my Emasoft repos. but the trddgrep is now handled by the 3-pillars-task-system plugin. you can sendmessage to it, a claude instance updating the plugin it is running right now."). Read as: no upstream report of the URL-password slowdown; it is measured and fixed here (TRDD-OD5Z90YL diagnosis, TRDD-AGOEWF2E long-password miss), and jr-redact is measured before it is disabled. This card stays blocked until those land.
- 2026-11-05 — blocked-by now also names AGOEWF2E, HF7GNHNF and J0TBHZ15, the three items the owner-decision note above waits for. The 'Read as' reading in that note was put to the owner, whose next message ('decide yourself on anything else, but decide on verified facts') did not contest it. Correction to commit f0453a7d: its message says 'until both land'; the blockers are three.
