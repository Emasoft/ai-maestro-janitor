---
trdd-id: XVJ30M61
title: A session stuck behind a second-scale retry banner on a stale transcript is declined, never escaped
column: dev
status: tasked
created: 2026-11-13T21:32:49+0100
updated: 2026-11-14T14:58:36+0100
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
approval-datetime: 2026-11-13T21:32:49+0100
parent-trdd: RJJGXPIK
derived: true
---

# A session stuck behind a second-scale retry banner on a stale transcript is declined, never escaped

Child of TRDD-RJJGXPIK (EHT). Blocks RJJGXPIK reaching complete: the owner's reported freeze may be this shape.

## Facts

- Real frame tests/fixtures/pane_frames/real-wedged-rate-limit-429.txt shows '429 Rate limited · Retrying in 0s · attempt 5/300'.
- scripts/lib/session_liveness.py _SECOND_SCALE_RE (line 187) rejects all-zero values. The exclusion (comment at lines 183-184, 'a hung request shows Retrying in 0s forever, a different failure') was added by an agent in ee837c54, not by the owner.
- For 0s the 3 s recheck proves nothing (0s == 0s). The only on-screen discriminator is the attempt number. A static attempt at 0s is a request in flight, indistinguishable from a slow request until Claude Code's own API request timeout.
- Any bar must come from that timeout as configured on this machine (settings env API_TIMEOUT_MS, docs, or memory page claude-code-continuity-settings), not a remembered default.

## To establish

- Does a static 0s + static attempt ever get ESC today? Trace diagnose_instance past the wedge branch (scripts/lib/session_liveness.py) and the stale-lane recovery. Suspected: only the rotation pass (daemon.py _rotation_esc_pass) ESCs it.

## Approval log

- 2026-11-13T21:32:49+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-13T22:16:42+0100 — column → dev. decision taken: option 0

## Implementation notes

2026-11-13 investigation (reports_dev/sonnet-worker/20261113_221409+0100-xvj30m61-0s-investigation.md): a static `0s` + static attempt is never wedge-confirmed; neither the fast lane nor the stale lane sends ESC. The only ESC is daemon.py _rotation_esc_pass, within 600 s of an OAuth rotation.
A live 0s retry loop advances the attempt (ARCHITECTURE.md:392); the uncovered shape is 0s with a STATIC attempt, i.e. a request in flight or hung, indistinguishable on screen from a slow request.
API_TIMEOUT_MS on this machine is 19000000 ms (5 h 17 min). A bar tied to it fires after about 5 h 21 min. A bar of about 540 s needs proof that Claude Code's 5-min stream idle watchdog aborts and bumps the attempt of a no-first-byte request (unverified, needs a captured frame).
Countdown text is not logged today, so past 0s episodes cannot be counted. Cheap prerequisite: log `retry_wedge@<attempt>[<retry_in>]` on each pane read.
OWNER DECISION NEEDED: (a) safe bar from API_TIMEOUT_MS (~5.3 h here), (b) verify the stream idle watchdog first and use ~540 s, or (c) accept the risk of ESCing a slow request with a short bar.
2026-11-13 DECISION (main agent, owner standing instruction to decide without asking; adversarial review of the options): the three timeout-bar options are superseded. Option 0 is adopted: when the stale lane diagnoses cron_dead and the rearm is declined because the pane shows a retry wedge (daemon.py `_decline("retry_wedge_on_screen", "rearm")`, ~line 2340), send ESC plus one `resume` (the esc_nudge_resume route) instead of declining. Works for every banner shape (0s, minutes, hours); bar = existing 15-minute stale gate. Evidence: recovery-audit.ndjson has 84 cron_dead/retry_wedge_on_screen declines (~60 episodes, 15 roots, 09-05..11-05), none ESCed, some escalated to the human. Cost of a false ESC: one cancelled request, retried by resume.
- Also adopted: log the countdown on each wedge read as `retry_wedge@<attempt>[<retry_in>]` so 0s episodes become countable.
- Rejected: a bar from API_TIMEOUT_MS (~5 h 21 min here): it leaves a session idle for hours, the very symptom reported. Optional follow-up only: capture a frame proving the 5-min stream idle watchdog aborts a no-first-byte request.
- Unverified premises: "a live 0s loop advances the attempt" comes from ARCHITECTURE.md:392 prose, not captured frames; the esc_nudge_resume route has no observed run on a retry-wedged pane; MAX_RETRIES=100 in settings vs /300 on the 2.1.258 frame is unresolved.
2026-11-13 CORRECTION to the investigation note above: "neither lane sends ESC" is too strong. The stale lane DOES ESC via the `frozen` diagnosis (esc_nudge_resume) when a rate-limited.flag is present; that flag is written only by turn-ending hooks or the daemon's own ESC, so a hung request normally has none. "A live 0s retry loop advances the attempt" is janitor prose (ARCHITECTURE.md:392), not captured frames: unverified. The reports_dev/ path is a local gitignored file; its decisive facts are quoted inline in the decision line.
2026-11-13 The "OWNER DECISION NEEDED" line above is SUPERSEDED by the option-0 decision above.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-13

Investigation done (2f6d9294). Decision: option 0 for a frozen 0s or any countdown no longer than the stale threshold (ESC + resume where the stale lane today declines cron_dead for retry_wedge_on_screen), plus countdown logging. Not implemented yet. This STATE block sits at the END of the card (trddgrep append cannot place it after the title); it supersedes every body line above it.
NEXT ACTION: build ONLY the countdown logging retry_wedge@<attempt>[<retry_in>] (spec section 4) as its own commit, with a test; the retry_stuck route is DEFERRED until a real static 0s line appears on the running build. Full design and review findings: design/specs/XVJ30M61-retry-stuck-route-proposal.md.
2026-11-13 SCOPE CORRECTION (review of 5c4083b6), supersedes "works for every banner shape" and "one test per banner shape (0s, 2m 50s, 5h)": option 0 applies ONLY to a second-scale or 0s countdown (no ESC while the countdown is longer than the stale gate). An hour-scale wall (`Retrying in 5h … attempt 1/5`, fixture real-wedged-fable-limit.txt) is a legitimate limit, not a stall: ESC + resume would loop every cooldown for hours; it stays with rotation and escalation. Tests: 0s and 2m 50s fixtures ESC; the 5h fixture must NOT ESC.
GUARD required (TRDD-P7WU40G9: typed input into a wedged pane only buffers): the ESC must be confirmed landed (pane re-read shows the wedge gone) before `resume` is typed, with a read-back, as in RJJGXPIK; never swap `rearm` for a bare typed resume.
Scope rule: parse the WHOLE countdown into seconds (e.g. `4h 59m 30s` = 17970 s) and compare it to `stale_threshold_for(armed, STALE_S)` (scripts/lib/fleet_scan.py), the same threshold the stale lane uses. Do NOT reuse `_SECOND_SCALE_RE` as the scope filter: it matches any `\d+s` token (so an hour wall with a seconds part) and it rejects 0s, which IS in scope.
2026-11-13 Draft implementation proposal: design/specs/XVJ30M61-retry-stuck-route-proposal.md (new diagnosis retry_stuck, own stuck_since field, ~125 prod lines + ~280 test lines). Corrections listed at its top supersede the STATE clause about "a second-scale banner whose 3 s recheck keeps failing" (dropped: it never matures). Blocked first on a check that non-liveness gather_fleet callers do not wipe the fast-lane episode (RJJGXPIK).
2026-11-14 Countdown logging BUILT (this commit): each liveness beat logs one daemon.log line per project root holding a retry-wedge episode: 'session-liveness: <project> retry_wedge@<attempt>[<countdown>] read_age=<N>s instances=<n>'. read_age comes from a read_at stamp set only by a real pane read (not file mtime: the resume marker rewrites the file); the countdown is last_retry_in, the raw parse of that beat's first capture (never the carried retry_in, which would fake [0s]). COUNTING RULE for a static-0s episode: at least two consecutive beat lines for one project with the same attempt, '[0s]' present, and read_age under 120 s on each line. Coverage limits: only roots the scan polls get a line (stale lane, or fast lane on single-instance roots in the quiet in-flight shape); a shared root logs one line for all its sessions (instances=n), not per session; an episode file from an older build has no read_at and logs nothing until the next real read. retry_wedge_token (session_liveness) is now the one spelling, shared with pane_policy._read_detail. NEXT ACTION: release, then watch daemon.log for a line matching the counting rule; the retry_stuck route stays deferred until one appears.
2026-11-14 Counting rule tightened (review of 51252521): each counted line must have read_age 0 s, i.e. the pane was read on that same beat; a line with a larger age re-logs an earlier read. A root logs whenever its episode file exists, so a root polled earlier in the episode and then spared also logs, with a growing read_age; the bar filters those. mypy and pyright re-run on the committed tree after the final test repair: both clean.
