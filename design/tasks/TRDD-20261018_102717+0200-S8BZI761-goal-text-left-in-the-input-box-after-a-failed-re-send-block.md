---
trdd-id: S8BZI761
title: Goal text left in the input box after a failed re-send blocks every later janitor clear
column: testing
status: tasked
created: 2026-10-18T10:27:17+0200
updated: 2026-10-18T12:04:23+0200
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
npt: []
implementation-commits: [59c6a5ac]
---

# Goal text left in the input box after a failed re-send blocks every later janitor clear

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-18
MAIN-SESSION READ of .janitor/logs/clear-trigger.log (2026-10-18 10:35), replacing the worker-read symptom below. 13:41:14 s:3a6129dd 'clear landing at 664869 tokens'; 14:41:21 s:3a6129dd 'chain: FAILED — /goal ... not sent: gave up after 3600s'. Session c436b9d9 first appears at 16:40:41 (log line 331) and logs NO goal inject or chain start of its own; its only failures are '/clear not sent: gave up after 3600s (field not empty (' only on verified facts. commit often.'))' at 17:40:08, 18:40:15 and 19:40; every other c436b9d9 line until 20:30 is 'another clear chain is already pending — skipping'; at 20:30:08 a clear landed (748621 tokens, 74%) and 20:31:12 'chain: OK — chain complete'. READING: c436b9d9 is most likely the post-clear session of the same pane, and the field held the goal tail from the 14:41 give-up until something emptied it before 20:30 (about 6 hours); explanation 2 (c436b9d9's own failed re-sends) is ruled out because it logged none. NOT SHOWN: that the pane was the same (the log records no pane id), who or what emptied the field before 20:30, and how much text was really in the field (the reader may be the faulty part, TRDD-85NZX5RJ). SAFETY: a fix may clear only text that exactly matches what the janitor typed; that comparison needs a correct field reader, so this card depends on TRDD-85NZX5RJ (npt). If clearing is not safe, the stuck state must at least be reported (finding or alert), never left to block clears silently. NEXT ACTION: after 85NZX5RJ's post-clear capture, read the inject loop's give-up path (scripts/lib/terminal_trigger.py around 1119) and find whether anything ever empties the field after a give-up.


Split from TRDD-85NZX5RJ on 2026-10-18 (review of 40171956). SYMPTOM, worker-read from .janitor/logs/clear-trigger.log (reports/board/20261018_102008+0200-85NZX5RJ-probe.md): after the 2026-10-13 14:41 goal re-send gave up (field not empty), the same goal tail was read in the input field at 17:40, 18:40 and 19:40 (session c436b9d9) and each later /clear was not sent: the unsent goal text stayed in the box and switched off the clear lever for over 5 hours. TO DO FIRST: read the log lines yourself, then the give-up path of the chain (TRDD-B3PY3HV7 owns the goal chain; terminal_trigger inject loop around scripts/lib/terminal_trigger.py:1119) and say whether a give-up leaves typed text behind and whether anything clears it. Any fix must never erase text the user typed. Acceptance: a give-up never leaves janitor-typed text in the field, shown by a test, or a recorded reason why it cannot be cleared safely.
2026-10-18 10:40 CORRECTION (review of 0cf5de3f), every item now main-session-read: the line above was written at about 10:28, not 10:35. Read in full: log line 329 (14:41:21 s:3a6129dd /goal FAILED, reason field not empty (' only on verified facts. commit often.')) and every non-skip line of 331-424: only the three c436b9d9 '/clear not sent ... field not empty' failures at 17:40:08 (355), 18:40:15 (380), 19:40:26 (404), each followed by 'resume state untouched', then 20:30:08 clear landing and 20:31:12 chain OK. 'Explanation 2 ruled out' overstates: the log records no chain START lines, so it shows only that c436b9d9 logged no goal re-send; an unlogged re-type by a resume or bootstrap step (14:41 says 'resume state KEPT (persisted at verified submit)') stays possible (TRDD-B3PY3HV7, TRDD-5ID9CQY8). Duration: the tail was read in the field at 14:41:21 and 19:40:26 and the box was empty again before 20:30:08, so between 5 h and 5 h 49 m, not 'about 6 hours'. The npt on 85NZX5RJ gates only a fix that clears the field; reading the give-up path and reporting the stuck state need nothing from it. This card is a sibling split of 85NZX5RJ, not its npt or eht.
2026-10-18 11:03 The npt on TRDD-85NZX5RJ stays: 85NZX5RJ's fix (8dae3e5e) is the normalization a safe clear needs to compare the field with what the janitor typed (an earlier review called the npt likely unneeded; that predates the shows_only: False finding). Live tmux test: the tidy C-a/C-k/C-u leaves the last wrapped row; extra C-u or Escape does not remove it, while repeated C-u from the end emptied a field in another run, so a kill-and-re-read loop is feasible. Corrections to the 10:40 line: it was appended at 10:32:16; the stuck span is 4 h 59 m to 5 h 49 m and continuous presence is inferred from four reads; the box reading empty by 20:30:08 is inferred from the clear landing.
2026-10-18 11:11 Moving to dev: the npt on TRDD-85NZX5RJ is satisfied in code (the normalization in 8dae3e5e); 85NZX5RJ's remaining field check concerns delivery after a release, not that code. Plan (two review rounds): repeat the tidy, re-reading, only while the remainder is the end of our own command; rows = max(rows seen, rows expected from the command length and box width). Text stranded before a send is split to TRDD-KXZJOZBQ; this card stays open until both land.
2026-10-18 12:03 FIX COMMITTED 59c6a5ac: _clear_ours repeats the tidy (one pass per wrapped row, measured live on tmux 2.1.302) only while the remainder is a suffix of our own command, rows = max(seen, expected from length and box width), with its own small time budget so the give-up exit also empties a wrapped exact command; a field left non-empty is logged at once (state.log_line 'inject clear:') and returned. Gates: 117 passed in the two test files, full suite 18651 passed 2 skipped, ruff/mypy/pyright clean. RESIDUALS: (1) a command of about one row's length that word-wraps to two rows, read half-drawn, still gets one pass (the +1 slack applies only to commands of 2+ rows; same as the old behaviour); (2) the local_deadline 'could not confirm' branch is untested; (3) a remainder that is not our suffix (typed into, or a no-op pass) is reported stranded, not cleared; (4) tmux 2.1.302 only, iTerm unmeasured. Acceptance holds only for text typed in this send that still matches at exit; text stranded before a send is TRDD-KXZJOZBQ, so this card cannot reach complete until that lands. FIELD CHECK: after a release, one logged 'chain: OK' after a /goal re-send (the same event as TRDD-85NZX5RJ).
2026-10-18 12:04 npt [85NZX5RJ] cleared: it named a code dependency, the normalization committed in 8dae3e5e, which this card's fix 59c6a5ac builds on; 85NZX5RJ stays open only for the same post-release delivery check this card waits for. Keeping the npt made validate report ORDER-NPT-VIOLATED for a prerequisite that is met in code.

## Approval log

- 2026-10-18T10:27:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T11:11:37+0200 — column → dev. npt satisfied in code at 8dae3e5e; plan reviewed twice
- 2026-10-18T12:03:31+0200 — column → testing. fix 59c6a5ac; field check after a release; KXZJOZBQ open
