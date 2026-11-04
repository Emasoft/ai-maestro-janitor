---
trdd-id: 3GP0D06D
title: secret-shield tests run in the release gate and CI
column: todo
status: tasked
created: 2026-11-04T01:26:43+0100
updated: 2026-11-04T02:27:20+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-04T01:26:43+0100
---

# secret-shield tests run in the release gate and CI

## Problem
The secret-shield mod's tests (hooks/secret-shield/tests, run through the mods test kit) are run today only by a scratch runner script outside the repo. No committed runner exists. A grep found no reference to secret-shield in scripts/, tests/ or .github/ apart from the wiring-gate test, so publish.py and CI most likely do not run them; confirm this by reading publish.py's gate step first. If so, a release can ship a shield that fails its own tests, and every 'no behaviour change' step of TRDD-Q6LPJTPO rests on a worker happening to run the scratch script.
## Do
Commit a runner for the mod tests (assembling the mod the way the scratch script does), add it to the publish gate next to pytest, ruff, mypy and pyright, and run it in CI. It fails closed when the runtime it needs is missing.
Open question: can a CI runner get the mods test kit (claude-code/testing) and its runtime without interaction? If it cannot, the gate runs locally in publish.py only, and CI reports the missing step as a coverage gap rather than going permanently red.
## Done when
A deliberate failing shield test makes the gate step fail when that step is run on its own, without publishing, and makes CI fail on a feature branch.
Found during TRDD-Q6LPJTPO (review of commit baeecd80).
- The runner names hooks/secret-shield/tests explicitly and never runs a root-level bun test: _corpus_dev/ holds about 130 cloned untrusted repos with their own *.test.ts and *.spec.* files, which a root discovery would run (review finding, 2026-11-04).

## Approval log

- 2026-11-04T01:26:43+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
