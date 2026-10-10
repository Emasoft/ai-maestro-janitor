---
trdd-id: WOI8GO1S
title: A janitor detector that walks the project tree was not ruled out for a project with a very large ignored folder
column: dev
status: tasked
created: 2026-10-05T22:11:20+0200
updated: 2026-10-10T19:25:07+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:20+0200
---

# A janitor detector that walks the project tree was not ruled out for a project with a very large ignored folder

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

In a project holding a folder of more than 100 GB, heartbeat fires were cleared of the 2026-10-05 spikes by timing only. No detector's tree walk was read to confirm that it prunes ignored and oversized folders.

## Approval log

- 2026-10-05T22:11:20+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings

2026-10-10 19:24. CONFIRMED, by reading and in the field. READ by the main session: typosquat-watcher.py lines 257 to 259 and 314 to 316 call sorted(project_root.rglob(lockname)) once per lockfile name and only then git_utils.drop_gitignored, which pipes every path to one git check-ignore; so an ignored folder is enumerated in full, six times in the scan and six more in the signature that runs before the dedupe check. A worker's inventory (reports/board/20261010_192042+0200-woi8go1s-tree-walks.md, read whole) finds the same shape in repo-trust-score.py (lines 126, 251, 281 to 284) and supply-chain-fingerprints.py (322, 664, 769), and a different one in binary-magic-scanner.py (os.walk pruning a fixed name list). All four run by default: typosquat-watcher every 3600 s, the others every 21600 s; a detector is killed at 120 s and a killed one never writes its dedupe hash, so it pays the whole walk again at every cadence and never reports. FIELD, the card's own case: across 27 projects' dispatcher logs, 175 'timed out after 120s' lines name these detectors, 151 of them in one project whose tree holds 77.8 GB, 38.1 GB and 10.0 GB top-level folders: typosquat-watcher 127 (last 2026-10-10 15:08), repo-trust-score 17, supply-chain-fingerprints 7. Load is ruled out as the cause there: every other detector in that project's log timed out at most twice. binary-magic-scanner has no timeout in any of the 27 logs and is left alone. So in that project the typosquat check has not completed for as long as the log reaches, and it costs two minutes of disk walking an hour. Not measured: how far back that log reaches; whether the big folders are ignored at directory level (git check-ignore on the three top-level names printed nothing, so the ignore rules sit deeper). DESIGN, decided, NOT BUILT YET: one helper in scripts/lib/git_utils.py that lists the project's own files with ONE 'git ls-files -z --cached --others --exclude-standard' per fire (tracked plus untracked-not-ignored, so ignored folders are never entered), returning None when git cannot answer; the three detectors filter that list by file name instead of walking, share the one listing between signature and scan, and on None keep today's rglob path unchanged, because drop_gitignored documents that a security scanner must fail open and their tests run on plain folders. KNOWN NARROWINGS to state in the code: files inside a nested independent repository or a submodule are no longer seen (ls-files lists such a folder as one entry); an ignore rule written as folder/* instead of folder/ still makes git enter the folder. DETECT after a release: grep -c 'typosquat-watcher.*timed out' on that project's dispatch.log, expected to stop growing. Cost so far: 1 read-only worker (0.15 million tokens), 1 advisor call.
2026-10-10 19:25. Review of 9a848f7a (0.39 million tokens): no blocker; its main objection, that the proposed listing was never timed where it matters, is MEASURED now: in the worst project 'git ls-files -z --cached --others --exclude-standard' returns 2030 entries in under one second, twice in a row, where the walk is killed at 120 s. Its ignore rules: rust-core/target/ at directory level, /.trashcan/* by pattern; .claude/ is not ignored. ACCEPTED as limits and corrections: 'has not completed for as long as the log reaches' counts 127 timeouts and no successes, and the log's span was not read; that the 78, 38 and 10 GB folders are ignored is shown only for rust-core/target and the trashcan; lockfiles inside nested repositories and submodules drop out of a supply-chain scan, which is a loss of coverage, not only a narrowing; the '0 git init' count on the three test files came from a grep that also counted 0 tests, so the fixtures must be read before the brief. RULE FOR THE BUILD: the helper returns None only when the folder is not a git repository or git is missing; a git timeout or error must NOT fall back to the full walk in a large project without a log line, since that re-enters the slow path exactly where it hurts.
