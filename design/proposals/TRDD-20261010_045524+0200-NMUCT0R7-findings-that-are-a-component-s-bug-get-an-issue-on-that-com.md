---
trdd-id: NMUCT0R7
title: Findings that are a component's bug get an issue on that component's repo
column: proposal
status: proposed
created: 2026-10-10T04:55:24+0200
updated: 2026-10-10T04:55:24+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: user
assignee: main-agent@ai-maestro-janitor
approved: false
parent-trdd: 6ESS2MGE
---

# Findings that are a component's bug get an issue on that component's repo

Route 3 of the owner's routing rule of 2026-09-27 (quoted on TRDD-6ESS2MGE): a finding that is a bug in memgrep, the janitor daemon, cpv or another component goes to an issue on that component's own repo, never to an unrelated project or Claude instance. What exists (read by the main session 2026-10-10): scripts/lib/cross_project_issue.py file_finding refuses a repo the gh user does not own (lines 202-204), refuses when the duplicate search fails, and is called only from scripts/daemon.py:1440 for github-config gaps, capped at 5 per beat. What is missing: no detector classifies a finding as component-owned, so no table of finding to owning repo exists. Posting to GitHub unattended is outward-facing and stays with the owner (drain card stop list), hence min-approval user, and the card waits in proposals. To do when the owner approves: list which ledger codes are component bugs, with the owning repo for each; route them through file_finding; nothing posts without the owner's word.

## Approval log
