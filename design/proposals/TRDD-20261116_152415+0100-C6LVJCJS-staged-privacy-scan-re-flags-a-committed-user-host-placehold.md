---
trdd-id: C6LVJCJS
title: Staged privacy scan re-flags a committed user-at-host placeholder whenever its line changes
column: proposal
status: proposed
created: 2026-11-16T15:24:15+0100
updated: 2026-11-16T15:24:15+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: user
scope: project
project-id: ai-maestro-janitor
approved: false
---

# Staged privacy scan re-flags a committed user-at-host placeholder whenever its line changes

Main-verified by code read.
- scripts/lib/staged_privacy_scan.py prints "A value the file already holds at HEAD is not re-flagged" (around lines 407-408), but its module docstring (lines 7-15) scopes that HEAD exemption to e-mails and host-identity tokens, and the shape-rule pass (step 3, around lines 355-361) has no HEAD check.
- scripts/lib/private_path_patterns.py: _allow_ssh_host allows a dotted non-LAN host as an email domain, while _GENERIC_HOST_TOKENS holds only localhost and localhost.localdomain, so a bare "db" is flagged.
- Observed 2026-11-16 (commit attempts, not a code read): adding a trufflehog marker to line 95 of tests/agent_context_bench/corpus-vawikrk2-20260821.jsonl (placeholder host "db", value already at HEAD) was blocked; lines 23 and 35 (a dotted host under the internal TLD) passed.
Options for the owner (no option is approved):
(a) make the message match the behaviour;
(b) skip shape matches already in the file's HEAD blob;
(c) add "db" to the generic host tokens;
(d) change the line 95 placeholder host to a dotted name (blind-corpus content change).
This is a security-gate decision for the owner. Line 95 stays one inert, unverified trufflehog Postgres hit until then.

## Approval log
