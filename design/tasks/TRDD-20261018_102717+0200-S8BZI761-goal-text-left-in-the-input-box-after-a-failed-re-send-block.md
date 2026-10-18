---
trdd-id: S8BZI761
title: Goal text left in the input box after a failed re-send blocks every later janitor clear
column: todo
status: tasked
created: 2026-10-18T10:27:17+0200
updated: 2026-10-18T10:29:48+0200
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
approval-datetime: 2026-10-18T10:27:17+0200
npt: [85NZX5RJ]
---

# Goal text left in the input box after a failed re-send blocks every later janitor clear

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-18
MAIN-SESSION READ of .janitor/logs/clear-trigger.log (2026-10-18 10:35), replacing the worker-read symptom below. 13:41:14 s:3a6129dd 'clear landing at 664869 tokens'; 14:41:21 s:3a6129dd 'chain: FAILED — /goal ... not sent: gave up after 3600s'. Session c436b9d9 first appears at 16:40:41 (log line 331) and logs NO goal inject or chain start of its own; its only failures are '/clear not sent: gave up after 3600s (field not empty (' only on verified facts. commit often.'))' at 17:40:08, 18:40:15 and 19:40; every other c436b9d9 line until 20:30 is 'another clear chain is already pending — skipping'; at 20:30:08 a clear landed (748621 tokens, 74%) and 20:31:12 'chain: OK — chain complete'. READING: c436b9d9 is most likely the post-clear session of the same pane, and the field held the goal tail from the 14:41 give-up until something emptied it before 20:30 (about 6 hours); explanation 2 (c436b9d9's own failed re-sends) is ruled out because it logged none. NOT SHOWN: that the pane was the same (the log records no pane id), who or what emptied the field before 20:30, and how much text was really in the field (the reader may be the faulty part, TRDD-85NZX5RJ). SAFETY: a fix may clear only text that exactly matches what the janitor typed; that comparison needs a correct field reader, so this card depends on TRDD-85NZX5RJ (npt). If clearing is not safe, the stuck state must at least be reported (finding or alert), never left to block clears silently. NEXT ACTION: after 85NZX5RJ's post-clear capture, read the inject loop's give-up path (scripts/lib/terminal_trigger.py around 1119) and find whether anything ever empties the field after a give-up.


Split from TRDD-85NZX5RJ on 2026-10-18 (review of 40171956). SYMPTOM, worker-read from .janitor/logs/clear-trigger.log (reports/board/20261018_102008+0200-85NZX5RJ-probe.md): after the 2026-10-13 14:41 goal re-send gave up (field not empty), the same goal tail was read in the input field at 17:40, 18:40 and 19:40 (session c436b9d9) and each later /clear was not sent: the unsent goal text stayed in the box and switched off the clear lever for over 5 hours. TO DO FIRST: read the log lines yourself, then the give-up path of the chain (TRDD-B3PY3HV7 owns the goal chain; terminal_trigger inject loop around scripts/lib/terminal_trigger.py:1119) and say whether a give-up leaves typed text behind and whether anything clears it. Any fix must never erase text the user typed. Acceptance: a give-up never leaves janitor-typed text in the field, shown by a test, or a recorded reason why it cannot be cleared safely.

## Approval log

- 2026-10-18T10:27:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
