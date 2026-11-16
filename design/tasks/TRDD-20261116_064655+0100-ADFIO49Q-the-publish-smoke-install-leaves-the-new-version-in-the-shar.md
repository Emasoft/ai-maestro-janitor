---
trdd-id: ADFIO49Q
title: The publish smoke install leaves the new version in the shared plugin cache, so the janitor update check counts it as installed
column: todo
status: tasked
created: 2026-11-16T06:46:55+0100
updated: 2026-11-16T06:46:55+0100
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
