---
trdd-id: ELVVBENI
title: The staged privacy scanner flags the plugin install spec and python home attributes as private hosts
column: todo
status: tasked
created: 2026-11-20T01:15:54+0100
updated: 2026-11-20T01:51:00+0100
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
approval-datetime: 2026-11-20T01:15:54+0100
---

# The staged privacy scanner flags the plugin install spec and python home attributes as private hosts

Found 2026-11-20 while committing TRDD-NYKNE7MY: scripts/lib/staged_privacy_scan.py blocked the commit on (1) its ssh user-at-host rule for this plugin's own install spec (the plugin name, an at sign, the marketplace name) inside the documented install and update commands (shield_hook.py:40, shield-hook-stub.py:33-34, SKILL.md:135-136), and (2) its local-hostname rule for python attribute access to an attribute named home on the objects self and box in tests/test_shield_hook.py. Both are false positives: a Claude plugin spec names a plugin at a marketplace, not a user at a host, and that home is an attribute, not a hostname. Fix in the scanner, narrowly: exempt only this repo's own plugin name at its own marketplace name (read from the repo, not hardcoded twice), keep every real user-at-host flagged, and test both directions. The home-attribute case: rename the test attributes to home_dir now; whether the local-hostname rule should skip python attribute access is part of this card. (Line reworded 2026-11-20: the first version quoted the flagged strings and the rule id, and the scanner blocked the card itself.)

## Approval log

- 2026-11-20T01:15:54+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-20 implemented (main-agent; worker report reports_dev/sonnet-worker/20261120_012304+0100-ELVVBENI.md): the ssh-user-host exemption passes only <plugin.json name>@<version_update_lib.MARKETPLACE_NAME>; the import is lazy and any exception turns the exemption off with a class-name-only stderr line (fail closed). Scope: staged_privacy_scan.py runs only from this repo's own git-hooks/pre-commit; the NYKNE7MY hook installed in other repos runs the bun shield scan, not this scanner, so the exemption is not active elsewhere. The test attributes were renamed to home_dir. Still open on this card: the local-hostname rule's handling of python attribute access (worker proposal: skip .home when the stem is self, cls or this), main-agent ruling pending.
