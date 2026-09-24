---
trdd-id: 4P4Y2KBR
title: A clear injected a stale model-authored handoff from another session instead of a summary of the cleared session
column: testing
created: 2026-09-24T11:21:17+0200
updated: 2026-09-24T13:37:57+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T11:21:17+0200
implementation-commits: [737b4d6c]
---

# A clear injected a stale model-authored handoff from another session instead of a summary of the cleared session

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-24

- 2026-09-24 13:39 — column testing. The fix is in HEAD and UNRELEASED: 737b4d6c (the no-sidecar fallback prints a pointer, never an unverified handoff body) plus the card-5 sync hook, which Jev-compacts the transcript a per-pane sidecar names. The installed v3.5.7 still injects the newest handoff in the state dir, which is why the bug recurred at 13:17 (see Review corrections).
- A replay of the 13:17 clear PASSED both paths, but on the working tree, not a commit (see Review corrections).
- NEXT: release; re-run V3 and V12 of TRDD-DQXMND59 on the release commit; then close.

Seen at the start of the session that followed the 2026-09-24 morning clear, on the INSTALLED v3.5.7 (no Jev code). The SessionStart injection was agent-handoff 3df0142c, written 2026-09-23 22:56 about a security review, while the session actually cleared was, inferred from transcript modification times, b2bf5b7b (the rotation incident, TRDD-K0PMVRN6). A resumed session was told the wrong story. Find which path chose that handoff (key match, newest-group selection, age limit) and whether the Jev lane on HEAD can make the same choice. Acceptance: a test where an older session's handoff exists and a different session is cleared, and the injection names the cleared session or none.

## Approval log

- 2026-09-24T11:21:17+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24T12:12:49+0200 — column → testing by janitor-main-session. fix landed in 737b4d6c; the end-to-end check is row V3 of the verification matrix

## Review corrections 2026-09-24

Likely root cause (not verified): no handoff was written for the cleared session, and the newest-group selection fell back to another session's newest handoff. If HEAD's Jev lane can make the same choice, this card is a continuity blocker for TRDD-RAEGS1D5.
Investigation (reports/compaction-replacement/20260924_115901+0200-4P4Y2KBR-investigation.md): v3.5.7 injected the newest handoff in the state dir with no match check; HEAD's post-clear hook composes the cleared transcript itself via the per-pane sidecar, and 737b4d6c removed the last unchecked body injection (the legacy agent-handoff.md exemption). Known older gap, not a blocker: a clear on a pane the sidecar cannot name (Apple Terminal, plain xterm) gets a pointer, never a body.
Correction to the 12:12:49 testing reason: 737b4d6c changed the no-sidecar fallback in scripts/hooks/on-session-start.py (Lane B), so this card's end-to-end check is row V12 of TRDD-DQXMND59 (clear flag, no sidecar, a foreign or legacy handoff newest -> pointer, never body), not V3; V3 covers the sync hook with a sidecar.
RECURRENCE 2026-09-24 13:17, same foreign handoff, on the INSTALLED 3.5.7: the Stop-hook context gate cleared session accccb8b (.janitor/logs/token-meter.log lines 157-176: deferred 12:56-13:08 with 1-6 background agents live below the 92% ceiling, then "past ceiling (92% >= 92%) -- clearing regardless" from 13:09:34, chain spawned six times up to 13:17:05 at 94%, 851,646 tokens). The fresh session aed1e7eb was injected agent-handoff-3df0142c-20260923_225646+0200-44296.md, last night's security-review handoff, the same file this card's morning incident injected. The cleared session's own summary did not exist yet: .janitor/logs/session-summary.log 13:17:12 "holding this session while llm-ext summarizes accccb8b-...jsonl" (llm-ext has timed out at 600 s on every run since 2026-09-24 03:12), so /janitor-resume found no cue and the owner saw a session with the wrong context. The prior session had saved its own state to docs_dev/20260924_1320-jev-session-state.md, which nothing pointed to. HEAD is believed to fix the injection (unreleased); a replay of this exact clear against HEAD with the real accccb8b transcript was dispatched at about 13:25 (reports/compaction-replacement/*-stale-handoff-replay.md).
Replay result, 2026-09-24 ~13:29 (reports/compaction-replacement/20260924_132937+0200-stale-handoff-replay.md): PASS / PASS. (1) The real sync hook scripts/hooks/on-session-start-post-clear-compact.py, run through hooks/hook-run.sh with a real per-pane sidecar naming accccb8b's 7.5 MB transcript, exited 0 in 18.3 s with a real Jev compose (not the template) and injected 6,899 bytes about session accccb8b, with no trace of the 3df0142c handoff; the real .janitor/state gained or lost no file. (2) scripts/hooks/on-session-start.py with a clear flag, NO sidecar and the 3df0142c handoff as the newest file printed only the pointer line ('NOT injected because no per-pane sidecar named this session's own transcript...'), never the body. CAVEAT: both checks ran on the WORKING TREE (HEAD 12351362 plus the then-uncommitted F1 and F3), not on a commit; they are provisional until V3 and V12 of TRDD-DQXMND59 are re-run on the release commit. Harness pitfall found: scripts_dev/jev_verify/run_hook.py needs an ABSOLUTE scratch_root; a relative one silently yields empty stdout and exit 0.
