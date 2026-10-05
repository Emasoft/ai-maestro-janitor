---
trdd-id: FWDZDB7W
title: The janitor installs a fast pre-commit privacy-leak scan in every project it runs in
column: blocked
created: 2026-09-24T07:42:31+0200
updated: 2026-10-05T11:12:46+0200
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
status: tasked
implementation-commits: [f7fb03f6]
blocked-by: [ASHLUQ6O]
pre-block-column: testing
---

# The janitor installs a fast pre-commit privacy-leak scan in every project it runs in

## Owner directive 2026-09-24 (verbatim)

> why the janitor did not setup a privacy scan? its the janitor responsability to ensure no private data is accidentally committed. the janitor should create a commit hook with a fast privacy leaks scan.

## Why this card exists

On 2026-09-24 commit 2ef3b1f8 added TRDD-K0PMVRN6 to design/tasks/ carrying three personal e-mail addresses and the macOS username, and nothing stopped it. The privacy checks the janitor has all run too late or cover the wrong thing:
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
2026-10-05 — Outline steps 1, 2 and 4 landed in f7fb03f6 (in v3.7.0) and verified end to end; outline step 3 (install in other projects) moves to TRDD-ASHLUQ6O and this card closes.
2026-10-05 — correction: this card is NOT closed yet. Closing waits on a re-run of its tests, correction of its acceptance boxes for outline steps 1, 2 and 4, and its implementation-commits field (empty; the code is f7fb03f6).
2026-10-05 — CLOSING. Verified on 2026-10-05: f7fb03f6 is in v3.7.0; tests/test_staged_privacy_scan.py re-run: 24 passed, 0 failed. Outline step 3 is not done here; it is TRDD-ASHLUQ6O. Approver: the session's own agent, on the rule that outside the multi-agent harness the session's agent approves a card whose required approval is none.
2026-10-05 — correction: the CLOSING line above is void; the card tool refused the close because acceptance box 3 (install into other projects) is unticked, and that work is TRDD-ASHLUQ6O, which waits on the owner. This card is therefore blocked on TRDD-ASHLUQ6O: it completes when that card is done or dropped. Verified the same day: its test file re-run gave 24 passed; f7fb03f6 is in v3.7.0.

## Approval log

- 2026-09-24T07:42:31+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24 — identity correction: issuer fields changed from the host username (a trddgrep default) to the session id before the card was first committed.
- 2026-09-27T17:43:34+0200 — column → testing by user. steps 1-2 landed (commit f7fb03f6), main-verified; step 3 (fleet install) remains

## Test cases

- trddgrep new stamps $USER into created-by/approval-judge and the approval log unless --author is passed: the hook must catch a host username in a staged TRDD card (the 2026-09-24 incident on K0PMVRN6, PWIAEW40 and this card).
- trddgrep writes a `blocker-probe:` field containing the absolute --design-dir path (a home path) when a card is moved to blocked: the hook must catch it (2026-09-24, ADIGRD0T).
- trddgrep move stamps $USER into the approval-log transition line (for example 'COMPLETE by <user>') unless --approver is passed: the hook must catch it (2026-09-24, AW4XD53Q).

## Implementation

2026-09-27 steps 1-2 landed (commit f7fb03f6) via lean-worker, main-verified: scripts/lib/staged_privacy_scan.py + pre-commit stage 1; reuses G1b/private_path_patterns/privacy_patterns; grandfathering vs HEAD; fail-closed. 7 tests green. Step 3 (fleet install, chaining, per-project opt-out) still open.

## Acceptance

- [x] staged-diff scanner refuses personal e-mail/home-path on ADDED staged lines (outline 1): tests/test_staged_privacy_scan.py 7 tests green (run 2026-09-28 exit 0; landed f7fb03f6, main-verified)
- [x] wired into this repo's git-hooks/pre-commit (outline 2): pre-commit stage-1 invocation of scripts/lib/staged_privacy_scan.py verified by source read of git-hooks/pre-commit:24 (landed f7fb03f6)
- [ ] fleet install chaining existing hooks + per-project opt-out (outline 3): OPEN - remains on the card
- [x] real-repo end-to-end: stage e-mail -> refused; stage noreply -> passes; existing hook still runs (outline 4): e2e run 2026-09-28 (lean-worker, temp repo, main-read) — personal e-mail REFUSED exit 1 (masked, chained hook not run), noreply PASSES exit 0 (chained STAND-IN hook ran — worker-authored marker script, not the repo's real stage-2; the real stage-1+stage-2 pair is de facto exercised on every in-repo commit this session, e.g. 8792ca19/bbe20017/677fe33e); 2nd commit proves per-commit chaining; evidence docs_dev/20260928-fwdzdb7w-e2e.md
2026-09-28 e2e evidence (lean-worker, main-read): outline 4 discharged — real temp-repo commits: personal e-mail REFUSED exit 1 (BLOCKED, masked, chained hook correctly not run), noreply PASSES exit 0 (chained hook ran, 2nd commit proves per-commit chaining), home-path bonus caught 2 rules. Load-bearing Finding 0 for outline 3: copy-modules layout fails-closed at import (publish.py:312 reads .cpv-version at module load) — fleet install must invoke the scanner by absolute path from the janitor tree. Full evidence: docs_dev/20260928-fwdzdb7w-e2e.md. Outline 3 stays OPEN as a design proposal (default-on for mandated repos + opt-out sentinel, or ask-once — owner question).

## STATE

2026-10-05 — what closes this card: the owner's answer on TRDD-ASHLUQ6O (install the staged privacy scan into the other repositories: default-on, ask once, or never). If never: ASHLUQ6O is cancelled, acceptance box 3 is struck as not wanted, and this card closes. Otherwise it closes when ASHLUQ6O completes. The question was listed for the owner in the session's status message on 2026-10-05; no answer yet.
