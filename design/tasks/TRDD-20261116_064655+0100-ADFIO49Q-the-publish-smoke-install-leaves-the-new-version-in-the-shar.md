---
trdd-id: ADFIO49Q
title: The publish smoke install leaves the new version in the shared plugin cache, so the janitor update check counts it as installed
column: todo
status: tasked
created: 2026-11-16T06:46:55+0100
updated: 2026-11-16T07:07:52+0100
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
approval-datetime: 2026-11-16T06:46:55+0100
---

# The publish smoke install leaves the new version in the shared plugin cache, so the janitor update check counts it as installed

On the host that runs scripts/publish.py, stage_install_smoke (scripts/publish.py:3496, install at :3537) runs claude plugin install with --scope local from a temp dir; the new version dir lands in the shared plugin cache and stays there (3.9.5: cache dir created 06:21:20, smoke stage reported installs cleanly). The session detector (scripts/detectors/version-update.py:72-75) and the daemon (scripts/lib/version_update_lib.py:508-523, do_auto_update_if_needed) take latest_installed as the highest version dir in the cache, so the session detector requests no update (observed: 06:27:39 it logged latest_installed=3.9.5) and, read from the code, the daemon would not run claude plugin update either (not observed: the daemon made no version-update run between 02:54:27 and the manual update at 06:29:28; it runs about every 6 hours). The user-scope install stays on the old version until a manual update. The cron stub already ran from the newest cache dir (06:27:39), so stub and hooks can run different versions. installed_plugins.json also holds 97 local-scope entries for this plugin, 95 of them for project paths that no longer exist: 88 under assistant-containment temp dirs (source unknown; nothing in this repo names that prefix), 1 from a publish-install-smoke dir, and 6 others not examined. They are not cleanup leftovers of the current smoke stage, which uninstalls its local entry (read from the code; the registry held no local-scope 3.9.5 entry on 2026-11-16). Fix options to weigh: (a) compare latest_published with the version registered for the janitor's own install scope in installed_plugins.json, in the detector, in do_auto_update_if_needed and in its after-update check; (b) run the smoke install against an isolated config dir so it never writes the shared cache or registry. Touches the C3 certify path too. Consult the Fable advisor before implementing. Evidence: TRDD-A70YJLXN Notes, 2026-11-16.

## Approval log

- 2026-11-16T06:46:55+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Design

2026-11-16 (main agent) chosen fix, option (a) only: the reference for "behind" becomes the version registered for the user scope in installed_plugins.json (new helper registered_user_version; non-semver or no user record gives an empty value and the cache version is used, as today). After an update, success means the user record advanced; the cache re-list decides only when there was no user record, because on a publishing host the cache dir already exists and never advances. The detector uses the same reference in Branch A, only for a cache install. Option (b) and the dead registry entries are out of scope. The implementation commit carries the full design.
2026-11-16 (main agent) consequence for the owner: once the daemon updates the user scope on this host after a publish, it sets the reload flag, so every armed session is asked to reload plugins after each publish, the publishing session included. Today every logged daemon run here says updated=False, so this has not been firing. The project CLAUDE.md prefers avoiding /reload-plugins, because it re-bills the prompt cache; the cron stub already rolls to the newest cache dir without a reload.
2026-11-16 (main agent) implementation steps: (1) version_update_lib.registered_user_version(records) returns the user-scope record's version, or "" when there is no user record or the value is not semver; (2) update_reference(cache_latest, registered_user) returns registered_user or cache_latest; (3) update_succeeded(user_before, user_after, cache_before, cache_after): with a user record before the attempt, only the user record advancing counts, otherwise the cache advancing; (4) do_auto_update_if_needed compares GitHub against that reference and checks update_succeeded after attempt_auto_update, still returning the highest cache version for the C3 pin; (5) the detector computes the reference only for a cache install and uses it in Branch A (condition, request label, logs, manual nudge, floor-line text; the floor dedupe key keeps the cache version, because the staged privacy scan reads any edited line with two words joined by an at-sign as an ssh login, and the key still changes with each release), and logs registered_user=; Branch B is unchanged; (6) tests/test_version_update_registry_ref.py covers the helpers on a real registry file in a temporary HOME, and do_auto_update_if_needed with cache 3.9.5 and user 3.9.4 (updated), user not advancing (failure) and user current (silent).
2026-11-16 (main agent) retry bound: while the user record is behind, each armed session's detector fire (about every 5 minutes) may raise the request flag, and the daemon clears it before each run (scripts/daemon.py:4513-4519), so there is at most one update attempt per detector fire across all armed sessions. Task.run has no minimum interval, and an attempt that does not advance is logged as a failure but does not raise, so the failcount backoff does not engage; that was already true for a cache that did not advance. The case "the user record never advances although the cache already holds the release" did not happen when tested: a manual claude plugin update --scope user at 06:29:28, with cache/3.9.5 already present, moved the user record from 3.9.4 to 3.9.5.
2026-11-16 (main agent) decision on the reload consequence: proceed. A daemon self-update setting the reload flag is the existing behaviour on every host that did not publish; the project CLAUDE.md requires every armed session on this machine to end up on the new version, and the cron stub already rolls to the newest cache dir. The owner can still turn the trade around; this card records it.
2026-11-16 (main agent) detector coverage: three tests run the detector's main() against a real registry file in a temporary HOME, with the GitHub release lookup, the cache listing and the ai-maestro server probe stubbed, and with the semver pattern widened so the repo checkout counts as a cache install; a run from a real cache-install layout is not covered.
