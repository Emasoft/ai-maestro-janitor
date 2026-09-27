---
trdd-id: BVTYT2BN
title: settings-ensurer stderr message prints hardcoded tilde path even when HOME is redirected
column: complete
status: archived
created: 2026-09-27T00:44:28+0200
updated: 2026-09-27T12:10:40+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-09-27T00:44:28+0200
---

# settings-ensurer stderr message prints hardcoded tilde path even when HOME is redirected

Verified 2026-09-27 during the V12 matrix run: scripts/hooks/on-session-start.py:1093 prints '[ai-maestro-janitor] Updated N recommended setting(s) in ~/.claude/settings.json' with the tilde path HARDCODED in the message string, while the actual write target resolves at call time via settings_ensurer._settings_path (settings_ensurer.py:79, Path(home) if home else Path.home()) honoring a redirected HOME. Measured: in a V12 isolated run (fake HOME), stderr printed the '~/' message but the write landed in the fake home's .claude/settings.json (9 keys verified inside the scratch box) and the REAL ~/.claude/settings.json was untouched (mtime unchanged, zero key delta). Impact: wording-only - an operator or test reading stderr in any HOME-redirected context (tests, sandboxes, CI with HOME override) is told the wrong file was modified and may trust a false claim about their real config. The ensurer's safety design (verify-before-swap atomic write, lock-serialized, invariant-checked) is correct and untouched. FIX: one line - resolve the display path from the same source the writer uses (pass the resolved path into the message, or print the resolved absolute path) in on-session-start.py plus a one-test assertion that a redirected HOME produces a stderr naming the redirected path. Worker task: implement via fastedit, run the settings-ensurer test file plus ruff/mypy/pyright on scripts/, report path back. Related: TRDD-EQ792YPX (the ensurer's origin card).

## Approval log

- 2026-09-27T00:44:28+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-27T00:44:53+0200 — column → todo. one-line fix scoped on the card, ready for lean-worker dispatch
2026-09-27T00:55+0200 — review round 1: stands as carded, ready for dispatch. Two one-line clarifications recorded: (a) the worker report's claim that the ABORTED batch V12 box also had a fake settings.json was NOT reproducible by find (only the retry-v12 box has one) — the card's claims rest on the retry run, which was verified; (b) '9 keys' means 9 recommended settings across 2 top-level entries (env block with 8 + askUserQuestionTimeout), not 9 file keys. Also noted for the release-gate reader: reports_dev evidence files are machine-local (gitignored), not verifiable from a fresh clone.
2026-09-27T01:05+0200 — review round 2 CORRECTION of the round-1 note (a): the batch-box fake settings.json DOES exist — at the doubly-nested path scratch-v3v12-1790459630/v12/project/scripts_dev/jev_verify/scratch-v3v12-1790459630/v12/home/.claude/settings.json (nesting artifact of the batch run's relative-path bug); the round-1 'not reproducible by find' line was the orchestrator's misread of its own find output, and the worker report's batch-box claim was CORRECT. Read the worker report as accurate on this point.
2026-09-27T01:20+0200 — review round 3: stands; one cross-link clause added by that round: the batch box's doubly-nested settings.json path is corroborating evidence for TRDD-SWSNQAZF's path-form defect (the batch's relative scratch arg nested its box inside the repo tree) — the two cards corroborate each other.
2026-09-27T04:35+0200 — IMPLEMENTED, commit 9c163aca: the message now prints settings_ensurer._settings_path() (the resolved absolute path); one-test assertion added (redirected HOME stderr names the redirected path, tilde literal forbidden, opt-out flag delenv'd per review finding 3a). Verified: 22/22 across the two affected test files, ruff + mypy clean on changed files. Two review rounds on the implementation (round 1: MAJOR dead-branch finding was on SWSNQAZF's guard, this card's fix stood; round 2: delenv stands). Message-shape residual accepted: the normal case shows the absolute path, not '~/'. Card ready to move to testing.
2026-09-27T04:55+0200 — round-3 review (landed-record round): both commits stand conditionally; evidence debts closed — pyright on scripts/hooks/on-session-start.py: 0 errors 0 warnings (the private-symbol _settings_path() access does NOT trip reportPrivateUsage in this repo's config); post-remediation rerun of BOTH affected files: 22/22 (the earlier '22/22' claim predated the round-1 remediation edits — the wide claim is now true as stated). Round-3 minors recorded, no action: the negative tilde assertion is globally coupled (false-fails if another stderr line ever prints that literal — currently no other emitter does); thin_harness flake class accepted with sibling precedent.
- 2026-09-27T12:10:40+0200 — COMPLETE by user. owner batch acceptance 2026-09-27 (verbatim: 'complete all TRDDs').

## Acceptance

- [x] gates clean on the touched files at release (147 tests + ruff/mypy/pyright green on the release commit)
- [x] card evidence current at HEAD (re-verified this session)
