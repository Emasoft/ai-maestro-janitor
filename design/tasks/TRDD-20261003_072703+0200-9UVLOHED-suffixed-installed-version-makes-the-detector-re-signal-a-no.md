---
trdd-id: 9UVLOHED
title: Suffixed installed version makes the detector re-signal a no-op plugin update forever
column: dev
status: tasked
created: 2026-10-03T07:27:03+0200
updated: 2026-10-03T07:29:00+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T07:27:03+0200
---

# Suffixed installed version makes the detector re-signal a no-op plugin update forever

Bug: scripts/detectors/plugin-updates.py _semver_tuple returned (-1,) for an installed version with a commit suffix such as 0.2.2-4ad88f7c087a (int of 2-4ad88f7c087a raises), so _is_newer(0.2.2, 0.2.2-4ad88f7c087a) was True and the detector re-signalled a no-op user-scope update for that plugin on every fire. The daemon log showed 97 'no change (rc=0)' runs since 05:39, each a claude plugin marketplace update plus claude plugin update subprocess pair. Fix: build the tuple from the _SEMVER_PREFIX_RE match so a -suffix is ignored; non-semver stays (-1,). Equal numeric prefixes count as not newer, so a pre-release to release step (1.0.0-rc1 to 1.0.0) is not signalled. Test: tests/test_plugin_updates.py.

## Approval log

- 2026-10-03T07:27:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
