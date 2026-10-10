---
trdd-id: J7RLG96D
title: Log the recent-messages tail and continuity block that a clear handoff injects
column: complete
status: archived
created: 2026-10-10T00:04:42+0200
updated: 2026-10-11T01:16:21+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T00:04:42+0200
---

# Log the recent-messages tail and continuity block that a clear handoff injects

Two testing cards wait on something nothing records. TRDD-DS3WDTPV needs a janitor clear whose last reply ended on a question, followed by a turn that makes a work tool call; TRDD-IYNS7H83 needs a clear handoff taken after 20 or more consecutive heartbeat fires that still shows the last substantive assistant message. The text the SessionStart hook injects after a clear (the Continuity block, the NEXT ACTION sentence, the recent-messages tail) is not written to any log, so today the only observer is the resumed session itself, and a later session cannot re-check it. Wanted: on the post-clear path, write the injected continuity text and recent-messages tail to a file under .janitor/logs/ or .janitor/state/ keyed by the new session id, bounded in size, with no secret-bearing content beyond what the handoff already holds. Done when both cards' checks can be made by reading that file.

## Approval log

- 2026-10-10T00:04:42+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-11T01:16:21+0200 — COMPLETE by main-agent@ai-maestro-janitor. the injected text is already in the new session's transcript; no build needed.

## Findings

2026-10-11 01:16 (clock). NOT BUILT, NOT NEEDED (git log first: the card names no file; scripts/lib/session_continuity.py line 474 builds the Continuity block). Claude Code already keeps the injected text: in the NEW session's transcript the post-clear hook run is an attachment record (hookName SessionStart:clear, command ending on-session-start-post-clear-compact.py) whose content holds the whole injected handoff, including the Continuity block, the NEXT ACTION sentence and the newest-messages tail. Read by the main session: 37 such records in this project's 40 most recent transcripts, each about 15800 characters. So the checks of TRDD-DS3WDTPV and TRDD-IYNS7H83 can be made by reading those records plus the tool calls that follow them; a read-only worker is making the DS3WDTPV check now, before and after its fix. LIMITS: the files follow Claude Code's own retention; nothing bounds or redacts them beyond what the handoff already holds; this is the transcript, not a file under .janitor as the card first asked. Those two cards are NOT closed by this.

## Acceptance

- [x] Both cards' checks can be made by reading a file: the new session's transcript holds the injected text as the post-clear hook's attachment record (37 records read on 2026-10-11). Narrowing: Claude Code's file and retention, not a janitor log.
