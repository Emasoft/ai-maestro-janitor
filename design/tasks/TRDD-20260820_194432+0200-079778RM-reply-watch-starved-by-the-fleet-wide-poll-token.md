---
trdd-id: 079778RM
title: gh-reply-watch is starved by the fleet-wide poll token — 3 real polls in 3 weeks
column: todo
created: 2026-08-20T19:44:32+0200
updated: 2026-08-20T19:44:32+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
approval-tier: 0
scope: project
external-refs: [janitor#215]
npt: []
eht: []
---

# The reply lane looks alive and is almost entirely no-ops

## Measured 2026-08-20 (owner reported it as "it does not monitor the answers to the posts")

`scripts/detectors/gh-reply-watch.py` is CORRECT and has surfaced a real reply (2026-08-12,
a reply on janitor#242). It is gated behind a MACHINE-WIDE 60 s poll floor
(`_GLOBAL_MIN_INTERVAL_S = 60`, janitor#215) shared through
`~/.claude/janitor-control/gh-reply-watch-global-poll.last-run.ts`.

- This host now runs **40** janitor-armed project control dirs (`ls ~/.claude/janitor-control
  | wc -l` = 40).
- `.janitor/logs/gh-reply-watch.log` holds **3 non-deferred lines in the entire log**. Every
  other entry is `deferred — machine-wide poll floor not yet elapsed`.
- The global stamp turns over roughly every ~11 s (measured twice, 11 s apart), so the
  aggregate fleet rate is far above one poll/60 s and this project's fire essentially never
  wins the race.

**The floor is not the bug.** GitHub's `X-Poll-Interval: 60` is scoped to the ACCOUNT, and
all 40 projects share one owner identity, so a per-project interval would multiply the
account's poll rate by 40. The bug is that the token is **first-come with no fairness**:
crons fire on synchronised 5-minute boundaries, so the same early project wins nearly every
round and the rest starve indefinitely.

**Why the log hides it:** an entry appears every heartbeat, so the lane looks healthy. The
entries are almost all no-ops. A reply can sit undetected for weeks.

## What (recommended shape — do NOT just raise the floor)

A per-project bypass was considered and REJECTED: 40 projects × any useful bypass rate pushes
the account past the documented poll interval, trading a silent lane for rate-limit failures
across every project on the host.

1. Move the poll to the DAEMON, which already owns machine-wide chores and is a singleton:
   one `gh` notifications poll per floor window, fleet-wide.
2. The daemon writes a per-project inbox (or one shared, project-keyed notification file);
   `gh-reply-watch.py` READS that inbox instead of calling `gh` itself.
3. The detector's existing dedupe/report path is unchanged — only its SOURCE changes, so the
   surfacing logic that already works is not touched.
4. Fail-open: no inbox (daemon down, server absorption) ⇒ behave exactly as today, including
   the deferral line, so this can never make the lane worse than it is.

Verified 2026-08-20 that no such daemon lane exists yet: `gh_notify_poll` has exactly three
callers (`dispatch.py`, `gh_register_hook.py`, `gh-reply-watch.py`), all session-side.

## Acceptance

- [ ] One poll per floor window fleet-wide, regardless of how many projects are armed
- [ ] Every armed project sees every reply, with a bounded worst-case latency stated in the code
- [ ] Daemon absent / chore absorbed ⇒ today's behaviour exactly (fail-open, proven by test)
- [ ] A test that N projects sharing the host all receive a reply, which the current design fails
- [ ] pytest, ruff, mypy, pyright clean

## Approval log
