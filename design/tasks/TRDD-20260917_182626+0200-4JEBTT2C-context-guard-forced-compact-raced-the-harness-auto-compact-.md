---
trdd-id: 4JEBTT2C
title: context guard forced compact raced the harness auto-compact so two compactions ran 20 s apart
column: backburner
created: 2026-09-17T18:26:26+0200
updated: 2026-09-17T18:26:29+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-17T18:26:26+0200
labels: [continuity, compaction, terminal-trigger]
---

# context guard forced compact raced the harness auto-compact so two compactions ran 20 s apart

## Symptom timeline

In one Claude Code session (project ANIME2SVG, session 61f17503, ai-maestro-janitor 3.5.0, Claude Code 2.1.272) the context was compacted twice back-to-back, the second time on a context that had just been compacted.
14:28:07 a terminal-trigger send of /compact timed out after 10s verification. 14:28:15 a retry sent and verified. Both PreCompact hooks then fired one second apart (trigger=auto), and SessionStart source=compact plus the post-compact resume ran twice, 20 s apart (14:30:37 and 14:30:57).
Cost: transcript was ~865k tokens; the second compaction summarized an already-reduced context and bought nothing, and each SessionStart source=compact re-injected the 44KB precompact-handoff.md plus other payloads, so the re-injection was paid twice too.

## Two candidate mechanisms (logs cannot decide which)

1. The forced /compact keystroke raced Claude Code own auto-compact: the keystroke queued in a busy pane at 14:28:15, the turn ended at 14:28:46, Claude Code own auto-compact fired on the fresh context first, then the queued /compact ran again.
2. The terminal trigger sent /compact twice: the 14:28:07 send timed out on verification but the keystroke may still have landed, and the 14:28:15 retry landed a second time.

## Proposed guards (candidate fixes; any one removes the double)

1. Before the /compact keystroke lands, re-check at send time AND again at land time whether a compaction already happened since the decision (last-compact.ts / the PreCompact log); cancel the queued send if so.
2. When autoCompactEnabled is true, do not type /compact inside the window where Claude Code own auto-compact is about to fire; a prepare nudge is enough.
3. Treat a send whose verification timed out as possibly delivered: do not retry it blindly; verify by observing the PreCompact stamp instead of resending.
4. Debounce the post-compact side: a second SessionStart source=compact within N seconds of the first should not re-inject the handoff or rewrite the resume flag.

Source: GitHub issue #306 (filed 2026-09-15 by the ANIME2SVG session).

priority: high

## Approval log

- 2026-09-17T18:26:26+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
