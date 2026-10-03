---
trdd-id: 9UVLOHED
title: Suffixed installed version makes the detector re-signal a no-op plugin update forever
column: testing
status: tasked
created: 2026-10-03T07:27:03+0200
updated: 2026-10-03T07:32:28+0200
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
implementation-commits: [1931918c]
---

# Suffixed installed version makes the detector re-signal a no-op plugin update forever

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

- Code landed as 1931918c. Callers checked: this _semver_tuple is used only inside plugin-updates.py (_is_newer at line 146, used at 164 for user scope and 329 for project/local scope); the _semver_tuple in version_update_lib.py and env_detect.py are separate functions and are unchanged.
- Behaviour given up: commit-only changes (same marketplace version, new commits) and pre-release to release steps are no longer signaled by this detector; both were caught before only by the every-fire loop. Whether another path (a daemon user-scope sweep) catches commit-only updates is not verified.
- Until a release with this fix is installed, the cached detector keeps signaling every fire. Host-only stop, owner's call: add the claude-menu-system plugin id (plugin name, at-sign, marketplace emasoft-plugins) to CLAUDE_PLUGIN_OPTION_PLUGIN_AUTO_UPDATE_EXCLUDE (comma-separated plugin ids, read by _plugin_excluded).
- Remaining before complete: after release, daemon.log shows no further 'plugin-update claude-menu-system ... no change' lines.

Bug: scripts/detectors/plugin-updates.py _semver_tuple returned (-1,) for an installed version with a commit suffix such as 0.2.2-4ad88f7c087a (int of 2-4ad88f7c087a raises), so _is_newer(0.2.2, 0.2.2-4ad88f7c087a) was True and the detector re-signalled a no-op user-scope update for that plugin on every fire. The daemon log showed 97 'no change (rc=0)' runs since 05:39, each a claude plugin marketplace update plus claude plugin update subprocess pair. Fix: build the tuple from the _SEMVER_PREFIX_RE match so a -suffix is ignored; non-semver stays (-1,). Equal numeric prefixes count as not newer, so a pre-release to release step (1.0.0-rc1 to 1.0.0) is not signalled. Test: tests/test_plugin_updates.py.

## Approval log

- 2026-10-03T07:27:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-03T07:32:28+0200 — column → testing. code committed; only field acceptance after release remains
