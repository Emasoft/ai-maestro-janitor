---
trdd-id: FWDZDB7W
title: The janitor installs a fast pre-commit privacy-leak scan in every project it runs in
column: design
created: 2026-09-24T07:42:31+0200
updated: 2026-09-24T08:23:05+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T07:42:31+0200
---

# The janitor installs a fast pre-commit privacy-leak scan in every project it runs in

## Owner directive 2026-09-24 (verbatim)

> why the janitor did not setup a privacy scan? its the janitor responsability to ensure no private data is accidentally committed. the janitor should create a commit hook with a fast privacy leaks scan.

## Why this card exists

On 2026-09-24 commit 3185baac added TRDD-K0PMVRN6 to design/tasks/ carrying three personal e-mail addresses and the macOS username, and nothing stopped it. The privacy checks the janitor has all run too late or cover the wrong thing:
- publish.py's G1b personal-address lint and CPV --strict (home paths) run only at PUBLISH, when the leak is already in history and can only be removed by rewriting it;
- git-hooks/pre-push runs trufflehog, which covers secrets, not PII;
- scripts/lib/privacy_patterns.py (PII shapes) is used by scan-time detectors, not at commit;
- git-hooks/pre-commit only checks executable bits;
- nothing installs any commit hook in the OTHER projects the janitor runs in.

## Outline (to be approved before code)

1. A staged-diff scanner. It scans only the ADDED lines of staged files (`git diff --cached -U0`), so it stays well under a second. It reuses G1b's address logic (with its allow-list: noreply addresses, reserved .test/.invalid domains, the grandfather list), home-path shapes, this host's username and hostname, privacy_patterns PII shapes and secret shapes. On a hit it refuses the commit, printing file:line and a MASKED value. It has no silent bypass.
2. Wire it into this repo's git-hooks/pre-commit.
3. The janitor installs or chains the same hook in every project repo it runs in, CHAINING any existing hook (husky, the pre-commit framework, core.hooksPath), never overwriting one, with a per-project opt-out.
4. Real tests: a temporary git repo; stage an e-mail or home path and the commit is refused; stage a noreply address and it passes; an existing hook still runs.

## Open

- Whether step 3 needs the owner's approval per project, or runs by default.
- K0PMVRN6 already carries the addresses. The owner accepted that commit, but publish.py's G1b will likely refuse the release until the card is redacted.

## Approval log

- 2026-09-24T07:42:31+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24 — identity correction: issuer fields changed from the host username (a trddgrep default) to the session id before the card was first committed.

## Test cases

- trddgrep new stamps $USER into created-by/approval-judge and the approval log unless --author is passed: the hook must catch a host username in a staged TRDD card (the 2026-09-24 incident on K0PMVRN6, PWIAEW40 and this card).
- trddgrep writes a `blocker-probe:` field containing the absolute --design-dir path (a home path) when a card is moved to blocked: the hook must catch it (2026-09-24, ADIGRD0T).
