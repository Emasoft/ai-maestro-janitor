---
trdd-id: Y6WFN5L9
title: The CLAUDE.md writer and the rules installer left their files at mode 0600
column: testing
status: tasked
created: 2026-10-06T19:23:42+0200
updated: 2026-10-07T04:31:08+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T19:23:42+0200
implementation-commits: [1edf766d, 113121d2]
---

# The CLAUDE.md writer and the rules installer left their files at mode 0600

scripts/repomap_generate.py _atomic_replace (every project's CLAUDE.md wikimem index block) and scripts/lib/rules_installer.py _publish_monotonic (rule files under the user's .claude/rules) wrote through tempfile.mkstemp (0600) then os.replace, which keeps that mode. Fixed in 1edf766d and 113121d2: the temp file gets the target's existing mode, or 0644 when the target is absent or exactly 0600 (a deliberately-0600 file cannot be told apart and is widened; stated trade-off). Measured 2026-10-06: 15 of 24 installed rule files were at 0600; they heal only when a rule's version stamp next advances. OPEN: 41 tracked files in this repo were at 0600 (restored to 0644; list in reports/file-modes/, gitignored); the janitor explains CLAUDE.md only; the writer of the other ~40 source and test files is unknown (fastedit simple paths tested clean; its merge, retry and undo paths untested).

## Approval log

- 2026-10-06T19:23:42+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-06 NEXT ACTION: none on code. NAMED LIVE CHECK after the release carrying 113121d2 (v3.7.5): the next CLAUDE.md index refresh leaves the file at its previous mode (not 0600), and a rule file reinstalled at a new version is 0644. Open question above stays with TRDD-6NMQ95TQ.
2026-10-07 live check (a worker's read of the logs, not re-read by the main agent): verdict: behavioural check NOT YET OBSERVABLE, code PROVEN installed; card stays in testing. Requirement 1 (0644 for a new or 0600 target, else keep the mode) PROVEN present: installed 3.8.2 scripts/lib/rules_installer.py lines 205-208 'old = os.stat(dst).st_mode & 0o777' ... 'os.chmod(tmp, 0o644 if old in (None, 0o600) else old)' and scripts/repomap_generate.py lines 422-425 with the same two statements; repo and installed rules_installer.py lines 195-210 identical; tests/test_repomap_generate.py:482 parametrises (None,0o644),(0o644,0o644),(0o600,0o644),(0o640,0o640),(0o444,0o444), tests not run; tag v3.7.5 (2026-10-06 19:33:05) contains 113121d2 and 1edf766d. Requirement 2 (next CLAUDE.md index refresh keeps the previous mode) NOT YET OBSERVABLE: of 40 CLAUDE.md files carrying the index marker, the non-worktree mtimes are janitor 2026-10-05 10:16:47 (mode 644), AgentlensPro 2026-10-03 (mode 600), emasoft-complete-ios-app-authoring 2026-10-01 (mode 600), autonomous-agent 2026-09-29 (644), all before the fix release; worktree copies (mode 644, mtimes to 2026-10-07 03:43) are git checkout output and do not count. Requirement 3 (a rule file reinstalled at a new version is 0644) NOT YET OBSERVABLE: all 9 janitor-stamped rules in the user rules dir are still mode 600 with mtimes 2026-09-12 to 2026-10-04; 15 of 24 rule files at 600, 9 at 644, the same count as the card's measurement, so no healing occurred; the bundled rules carry no stamp so versions could not be compared that way; 6 of the 600 files carry no janitor stamp (another writer owns them, no claim made). The open item of 41 tracked repo files at 0600 with an unknown writer was not checked and stays with TRDD-6NMQ95TQ. No log line records rule installs. Still waits on: (a) one repomap_generate run on a project whose CLAUDE.md is mode 600 (for example AgentlensPro), expecting 0644 afterwards; (b) one stamped rule version bump, expecting 0644.
