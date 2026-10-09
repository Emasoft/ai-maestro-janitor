---
trdd-id: POWY0X9G
title: Strict publish gate fails on a list-marker NIT in an archived card that no tool may edit
column: todo
status: tasked
created: 2026-10-09T21:38:45+0200
updated: 2026-10-09T21:38:45+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-09T21:38:45+0200
---

# Strict publish gate fails on a list-marker NIT in an archived card that no tool may edit

Measured 2026-10-09 on main at 7a418cd6 with the publish gate's own command (PLUGIN_SKIP_GITHUB_INTEGRITY=1 uvx --from git+https://github.com/Emasoft/claude-plugins-validation@v5.16.2 --with pyyaml cpv-remote-validate plugin . --strict): exit 4, SUMMARY CRITICAL=0 MAJOR=0 MINOR=0 NIT=1 WARNING=42. The one NIT is markdownlint MD004/ul-style on design/archived/TRDD-20260815_231053+0200-XM3FPJC0-nothing-notices-a-file-that-grows-without-bound.md: its body uses asterisk list items (16) and trddgrep's own COMPLETE line in the Approval log (line 152) starts with a dash. publish.py blocks on any exit below 5, so this NIT blocks every release. The file was archived on 2026-10-08 (c0b24f87), one day after the v3.8.11 tag, so no release has been attempted with it in place.

The direct fix is refused: trddgrep edit XM3FPJC0 answers that archived cards are immutable (TRDD-MQE5D28T D8). Not bypassed.

Options, owner or next puller decides: (a) trddgrep writes its log lines with the marker the card body already uses; (b) markdownlint is configured to skip design/archived/ (a config scope change, not a rule suppression on live content); (c) a sanctioned mechanical-repair path for archived cards. Any card with asterisk lists will hit this when it is archived, so fixing only this one file would not hold.

## Acceptance

- [ ] The strict validator command above exits 0 or 5+ on main.
- [ ] A card with asterisk list items, moved to complete by trddgrep, does not produce an MD004 finding.

## Approval log

- 2026-10-09T21:38:45+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
