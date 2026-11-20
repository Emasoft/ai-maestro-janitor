---
trdd-id: A2I47CLF
title: An armed janitor installs a blocking pre-commit gate running the shield scan and ubs in every git repo it runs in
column: todo
status: tasked
created: 2026-11-20T00:07:31+0100
updated: 2026-11-20T00:40:01+0100
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
approval-datetime: 2026-11-20T00:07:31+0100
npt: [NYKNE7MY]
---

# An armed janitor installs a blocking pre-commit gate running the shield scan and ubs in every git repo it runs in

USER, 2026-11-20 (verbatim): 'have you ensured that when the janitor is armed, the /janitor-secrets-shield-scan skill is executed by the pre-commit hook? the janitor must actively add the pre-commit hook with both jss scan and ubi scan to all git repos, blocking if not passing clean.' (ubi = ubs, the Ultimate Bug Scanner; jss = the secrets shield scan.) State 2026-11-20: NOT done. Only this repo's own git-hooks run staged_secret_scan.py at prepare-commit-msg and commit-msg, and ubs there is advisory except exit 2 partial (ubs_partial_gate.py). No armed janitor installs anything into other repos. Interpretation (main-agent, open to owner veto): 'all git repos' = every git repo a janitor-armed session runs in (the project root and its linked worktrees), installed on arm and re-checked on every SessionStart and heartbeat; NOT a disk-wide sweep of every clone on the machine. Needed: (1) the shield scan of the STAGED content and ubs on the staged files, both blocking: any shield finding or ubs exit 1 or 2 refuses the commit, with the finding list printed without secret values; (2) chain onto an existing pre-commit hook (UBS-only hooks, husky, pre-commit framework) and honour core.hooksPath, never replace or lose the original, idempotent, uninstall restores it byte for byte (NYKNE7MY carries the install mode); (3) the heartbeat reports a repo whose gate is missing or was removed and reinstalls it; (4) a documented false-positive path: ubs:ignore with a reason on the line, a shield allow entry with a reason, never a blanket skip. Consequence to plan for: ubs becomes blocking in this repo too, so staged files that already carry ubs findings (see TRDD-SWQXCIOS dispositions) will block until each is fixed or carries a reasoned ubs:ignore.

## Approval log

- 2026-11-20T00:07:31+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-20 OPEN QUESTION, pending the owner's ruling (main-agent): NYKNE7MY's installer refuses to write into a git-tracked hooks folder (core.hooksPath pointing at a tracked dir, such as this repo's git-hooks/ or a husky .husky/). Under that rule such repos never get the gate, which conflicts with 'all git repos' above. Options put to the owner: (a) chain through the tracked hook file, so every contributor sees and runs the gate; (b) keep refusing and print the line to add by hand. Until the owner rules, the installer refuses. Also decided: a missing tool refuses the commit with the tool's name and its install command.
