---
trdd-id: 1RSHQNJK
title: package-manager-policy flags plugin repos whose npm deps install into CLAUDE_PLUGIN_DATA
column: backburner
status: tasked
created: 2026-11-04T20:43:38+0100
updated: 2026-11-04T20:56:13+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-04T20:43:38+0100
---

# package-manager-policy flags plugin repos whose npm deps install into CLAUDE_PLUGIN_DATA

Reported 2026-11-04 by the 3-pillars-tasks-management Claude session (peer-reported, not verified here): in its repo, a Claude Code plugin, this detector filed proposal TRDD-V77D8U7G (a card in the 3-pillars-tasks-management repo; PKGPOL-001, no .npmrc), which that session moved to refused with the owner's reason, relayed verbatim: "why do you need .npmrc? this is a plugin. there is no npm package in it. everything is just already included either as a script or as a compiled binary. [...] the dependencies, like better-sqlite or other libraries, should be installed in the $CLAUDE_PLUGIN_DATA folder, to be preeserved across updates." Per the peer, that repo ships esbuild bundles in dist/, and scripts/ensure-deps.sh copies package.json and package-lock.json into $CLAUDE_PLUGIN_DATA and runs npm ci --omit=dev there, so a repo-root .npmrc is not read at runtime. Verified here 2026-11-04 by reading scripts/detectors/package-manager-policy.py: _is_node_project (line 310) returns True whenever a JS lockfile exists, and _audit_npmrc (line 350) then raises PKGPOL-001 when the repo root has no .npmrc; nothing asks whether the root is a Claude Code plugin (.claude-plugin/plugin.json) whose dependencies install elsewhere. The npm knob-name defect found with this report is its own card, TRDD-3CCCDMA6. To decide: for a plugin repo, skip the repo-root .npmrc audit, or audit the real install site instead (the script that runs npm ci into CLAUDE_PLUGIN_DATA, for --ignore-scripts or an equivalent policy); dev-time installs at the repo root do read a repo-root .npmrc, so decide whether that case keeps a lower-severity finding. Done when: a plugin repo shaped like the reporter's raises no PKGPOL-001, tested on a real fixture tree, no mocks.

## Approval log

- 2026-11-04T20:43:38+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
