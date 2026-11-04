---
trdd-id: TEP6F3A3
title: Secret-shield checks before wiring the mod
column: design
status: tasked
created: 2026-11-03T22:42:41+0100
updated: 2026-11-04T21:49:32+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-03T22:42:41+0100
---

# Secret-shield checks before wiring the mod

## Questions to answer before hooks/hooks.json gains a modules key
- Does a Claude Code older than 2.1.287 reject the whole hooks/hooks.json when it carries a modules key, so the janitor's classic hooks stop too?
- In which order do the mod's tool.call rewrite and the janitor's Python PostToolUse updatedToolOutput run, and does one undo the other?
- Does a CLAUDE_PLUGIN_OPTION_SECRET_SHIELD_* value in the settings env block reach the mod's options? Probe with a project settings file in the probe repo. If it does not, add a Python warning when the env block sets one, since it would have no effect.
- What does the user type: /janitor-secret-shield, or a plugin-prefixed name? Check the command list in a live session.
How to test a Claude Code older than 2.1.287 when none is installed; if it cannot be tested, declare a minimum Claude Code version instead.
Does CPV --strict accept a modules key in hooks/hooks.json?
Disabling jr-redact belongs to the wiring card, not here.
- Do the shield's TypeScript tests run in a gate that blocks the publish, and does every shield regex pass the ReDoS check? Answered under Done when (2026-11-04).
## Done when
Each question has a measured answer recorded here, and the option descriptions and the usage text match it.
Found during TRDD-M1218EMH.
If any check finds a blocker for wiring (for example an older Claude Code rejects a hooks.json with a modules key, or tool.call runs after the Python PostToolUse rewrite in a way that breaks redaction), end this card at failed or cancelled, never complete, so TRDD-2V7OAUPE stays blocked and the wiring gate test keeps refusing; record the finding and decide with the owner.
- 2026-11-04 finding (answers the gate question above): no gate in this repo runs the shield's TypeScript tests. publish.py stage_tests runs pytest only (_PYTEST_CMD, scripts/publish.py:228); a grep found no caller of bun test, bun run test, npm test, vitest or plugin test in scripts/, tests/, .github/ or hooks/, nor in git-hooks/pre-commit and git-hooks/pre-push; .github uses no reusable workflow; whether CPV --strict runs plugin tests was not checked. The shield commits of 2026-11-04 were tested by workers running claude plugin test by hand (worker reports, not re-run by the main agent). This is a prerequisite of wiring, not a blocker that ends this card at failed: the gate is tracked in TRDD-KADV0ZO6, which blocks TRDD-2V7OAUPE.
- 2026-11-04 finding (answers the ReDoS question above): URL_PASSWORD had two quadratic shapes, its scheme prefix (fixed in 133a766a) and its port-skip query scan (fixed in 6decd71d); both are recorded on TRDD-Q6LPJTPO. Not every shield regex has passed the ReDoS check of TRDD-Q6LPJTPO's Acceptance criterion yet: URL_PASSWORD slows by a step between 96 KB and 128 KB, measured only under load (TRDD-OD5Z90YL), and one URL whose password alone is 1 MB is not hidden under claude plugin test, with the size where hiding stops measured on one shape only and possibly lower in other runtimes (TRDD-AGOEWF2E). This is a prerequisite of wiring, not a blocker that ends this card at failed: before TRDD-2V7OAUPE wires the mod, every shield regex passes that ReDoS check, including its 100 ms limit at 256 KB. The board enforces only part of this: TRDD-2V7OAUPE waits for TRDD-KADV0ZO6, whose Done-when needs the TRDD-OD5Z90YL harness, which checks growth but not the 100 ms limit. Open for the owner (asked 2026-11-04): whether wiring also waits for TRDD-AGOEWF2E; what exit applies if the step proves to be the engine's own and cannot be removed; and whether jr-redact, which wiring disables, hides what this shield misses, which was not measured.

## Approval log

- 2026-11-03T22:42:41+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
