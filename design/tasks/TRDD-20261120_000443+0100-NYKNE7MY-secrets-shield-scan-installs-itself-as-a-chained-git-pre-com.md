---
trdd-id: NYKNE7MY
title: Secrets shield scan installs itself as a chained git pre-commit hook in one step
column: todo
status: tasked
created: 2026-11-20T00:04:43+0100
updated: 2026-11-20T03:25:57+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-20T00:04:43+0100
---

# Secrets shield scan installs itself as a chained git pre-commit hook in one step

USER quote relayed 2026-11-20 by the 3-pillars-tasks-management session (cross-session message, untrusted relay, verbatim): 'use the janitor /janitor-secrets-shield-scan skill. but you need to ask the janitor plugin claude via sendmessage to update the janitor plugin to enable it. ask it to do it. it should also able to add the scan as a pre-commit hook directly.' Needed: a mode of /janitor-secrets-shield-scan (for example --install-hook) that adds a pre-commit stage scanning the STAGED content with the shield rules, chained onto any existing pre-commit hook instead of replacing it (the 3-pillars repo already runs UBS from one): keep the old hook, call it first or second with its exit code honoured, idempotent on re-run, honour core.hooksPath, refuse on a hook it cannot parse rather than overwrite it, and an uninstall that restores the original byte for byte. Never print a secret value; block the commit on a finding.

## Approval log

- 2026-11-20T00:04:43+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-20 additions (main-agent, open to owner veto): install writes the DATA-dir dispatcher-stub.py only when it is absent, because /janitor-arm owns it and an older plugin_root would downgrade the live heartbeat. Known residuals, accepted for now: (a) the trust root is the DATA dir; loading dispatcher-stub.py from it matches C3's threat model (a cache writer cannot write DATA), but a DATA-dir writer defeats the gate; (b) a version with a manifest but no pin and no key passes on its self-consistent manifest alone.
- 2026-11-20 residual R3 (main-agent): shield_hook.py --plugin-root runs the given tree without integrity verification; it is a developer and test entry point, never what the installed hook calls. Also: a DATA-dir dispatcher-stub.py too old to have the verification routines makes the stub refuse the commit and ask for a re-arm.
- 2026-11-20T03:25:56+0100 main-agent: pinned CPV v5.23.1 plugin --strict on ba94b7a9: rc=0, SUMMARY CRITICAL=0 MAJOR=0 MINOR=0 NIT=0 WARNING=75 (local reports_dev/opus-main/cpv-strict-20261120_030958+0100.txt), so the ba94b7a9 subject holds. Commit 8928379e also carries the memory-page devitalization of detector-and-hook-fixes-2026-11.md, which belongs to the CPV cleanup, not to this card. The shortened skill description dropped the trigger wording audit for credentials, mask or remove, block secrets at commit time; the body Trigger line keeps the command. The clear-chain memory page lost recall by the word injector (reworded to keystroke sender); add it back through memgrep in a phrase the A2A rule does not match. The envget byte-for-byte help comparison noted on DSXC9MP9 is the worker's, not rerun by main-agent.

## Design notes

2026-11-20 decisions (main-agent, open to owner veto): (1) the install target is the EFFECTIVE hooks dir (git rev-parse --git-path hooks, which honours core.hooksPath); if that dir is tracked by git (a husky-style or this repo's git-hooks/), refuse and print the exact lines the owner should add, because writing there edits another project's tracked tree; (2) the installed hook calls a stable stub in the janitor DATA dir (~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/), never a versioned cache path, so a plugin update needs no reinstall; (3) chaining: an existing pre-commit is renamed to pre-commit.pre-janitor (byte for byte) and the new pre-commit runs it first, honouring its exit code, then the shield scan of the STAGED blobs (git diff --cached, index content, not working files); re-install is idempotent (a marker line), uninstall restores pre-commit.pre-janitor byte for byte; (4) fail closed: if bun or the shield scanner is missing the commit is refused with a message naming the missing tool, its exact install command and how to retry; (4b) integrity: the stub runs only a cached version that passes dispatcher-stub.py's C2 manifest check and C3 pin, loading those functions from dispatcher-stub.py itself; a version with no or an unreadable manifest is REJECTED for the gate (every cached version on this host ships one, 3.9.1 to 3.9.8 checked 2026-11-20), unlike dispatcher-stub which accepts it; no key, or a pin naming another version (this host's stale C3 anchor), stays accepted; limit: this detects a corrupted or tampered manifest-carrying version and a missing manifest, not a cache writer who rewrites both a file and its manifest when no pin names that version; if no version is acceptable the commit is refused, with no fallback to an unverified version; (5) a finding prints rule, path and line, never the value; (6) linked worktrees share .git/hooks, so the hook must work from a worktree and never write to the shared ubs cache from one; (7) tests only in tmp_path repos, including an existing UBS-style pre-commit that must still run. ubs joins this hook in TRDD-A2I47CLF, not here.
