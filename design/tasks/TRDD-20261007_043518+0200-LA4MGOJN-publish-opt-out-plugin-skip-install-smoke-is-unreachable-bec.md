---
trdd-id: LA4MGOJN
title: publish opt-out PLUGIN_SKIP_INSTALL_SMOKE is unreachable because the bypass guard refuses it
column: testing
status: tasked
created: 2026-10-07T04:35:18+0200
updated: 2026-10-07T04:57:08+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T04:35:18+0200
---

# publish opt-out PLUGIN_SKIP_INSTALL_SMOKE is unreachable because the bypass guard refuses it

Finding, copied from reports/board/20261007_050000+0200-fix-publish-exemption.md (gitignored): scripts/publish.py around line 3229, in stage_install_smoke, reads PLUGIN_SKIP_INSTALL_SMOKE=1 as an opt-out. main() calls stage_bypass_guard() (around line 3476) first, in the same process, and the guard refuses (exit 1) every PLUGIN_SKIP_ variable that is not in its exemption set, at launch. PLUGIN_SKIP_INSTALL_SMOKE is not in the set, so setting it makes the publish refuse before stage_install_smoke can read it: the opt-out is unreachable through the environment in a real run (dead code as an opt-out). Found while fixing the exemption rename (TRDD-CWKM5218, commit 52eb054e); not changed there.

Two options, not chosen here: (A) add PLUGIN_SKIP_INSTALL_SMOKE to the guard's exemption set so the opt-out works; (B) delete the dead opt-out from stage_install_smoke.

Acceptance: one test showing the chosen behaviour.

## Approval log

- 2026-10-07T04:35:18+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T04:35:22+0200 — column → todo by main-agent@ai-maestro-janitor. triaged: developable bugfix
- 2026-10-07T04:57:08+0200 — column → testing by main-agent@ai-maestro-janitor. merged on main; waits for a release

## STATE

2026-10-07: found while fixing the exemption rename (TRDD-CWKM5218, commit 52eb054e). NEXT ACTION: decide exempt or delete; the owner rule against bypasses favours delete.
2026-10-07 correction: the publish.py line references above are off; the audit read them at line 3236 (the PLUGIN_SKIP_INSTALL_SMOKE read in stage_install_smoke) and line 3483 (the stage_bypass_guard call in main), not 3229 and 3476.
2026-10-07: decided delete (the owner's rule forbids bypasses) and merged on main (295b48c1, merge f0c15f0b): the read of the variable is gone and a test asserts it does not come back. Not yet in a release.
