---
trdd-id: 3GP0D06D
title: secret-shield tests run in the release gate and CI
column: backburner
status: tasked
created: 2026-11-04T01:26:43+0100
updated: 2026-11-04T01:26:43+0100
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
The secret-shield mod's tests (hooks/secret-shield/tests, run through the mods test kit) are run today only by a scratch runner script outside the repo. No committed runner exists, and neither scripts/publish.py nor CI runs them. So a release can ship a shield that fails its own tests, and every 'no behaviour change' step of TRDD-Q6LPJTPO rests on a worker happening to run the scratch script.
## Do
Commit a runner for the mod tests (assembling the mod the way the scratch script does), add it to the publish gate next to pytest, ruff, mypy and pyright, and run it in CI. It fails closed when the runtime it needs is missing.
## Done when
A failing shield test makes publish.py and CI fail, shown by one deliberate failure in a scratch branch.
Found during TRDD-Q6LPJTPO (review of commit baeecd80).

## Approval log

- 2026-11-04T01:26:43+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
