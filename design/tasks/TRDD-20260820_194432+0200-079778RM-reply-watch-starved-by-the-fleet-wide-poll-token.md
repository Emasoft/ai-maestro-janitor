---
trdd-id: 079778RM
title: gh-reply-watch is starved by the fleet-wide poll token — 3 real polls in 3 weeks
column: testing
created: 2026-08-20T19:44:32+0200
updated: 2026-08-20T23:20:05+0200
implementation-commits: [b49541f4]
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

- [x] One poll per floor window fleet-wide, regardless of how many projects are armed
      — the daemon's `gh-notify-inbox` Task at 60 s is now the ONLY caller, so the
      account's rate equals the interval no matter how many projects are armed
      (`test_the_daemon_registers_the_inbox_fetch_as_a_foreground_task`,
      `test_reading_the_inbox_makes_no_gh_notifications_call`)
- [x] Every armed project sees every reply, with a bounded worst-case latency stated in the code
      — `gh_notify_inbox.RETAIN_S` (24 h) IS the bound and says so at its definition
      (`test_with_a_fresh_inbox_EVERY_project_on_the_host_sees_the_reply`)
- [x] Daemon absent / chore absorbed ⇒ today's behaviour exactly (fail-open, proven by test)
      — absent / stale / corrupt / wrong-shaped each fall back to the gated poll
      (`test_a_stale_inbox_falls_back_to_todays_exact_behaviour`,
      `test_a_corrupt_inbox_is_treated_as_absent_not_as_empty`)
- [x] A test that N projects sharing the host all receive a reply, which the current design fails
      — BOTH directions pinned: `test_without_the_inbox_only_ONE_project_on_a_host_sees_the_reply`
      asserts the old behaviour (1 of 4), the fresh-inbox test asserts 4 of 4
- [x] pytest, ruff, mypy, pyright clean — 15671 passed, 1 skipped; ruff/mypy/pyright 0 findings

## Outcome (2026-08-20)

Implemented in `b49541f4`. Two things worth carrying forward beyond the fix itself:

- **Sharing the FETCH must not share the FILTER.** The notification list is account-scoped
  and identical for every project; `registry.json` is per-project. That asymmetry is what
  makes one shared call safe, and it is pinned by
  `test_the_inbox_does_not_leak_another_projects_threads` rather than left to review.
- **A stale inbox is not an empty one.** Empty means "nothing new" (stay quiet); stale means
  "nobody is fetching" (spend a poll token). Collapsing them would make a dead daemon look
  like a quiet inbox and silence the lane entirely — a worse failure than the starvation
  this card fixes, because it would be undetectable.

**Known residue, accepted:** the chore is UNABSORBED, so on a host running a live
ai-maestro server (which suppresses the daemon) nothing writes the inbox and every reader
degrades to the old gated poll. Absorbing it would be worse — the roster would claim an
owner that cannot execute the lane. The blackout therefore costs the IMPROVEMENT, not the
feature, and `global-chore-blackout` makes it visible. Closing it is a cross-repo ask on
ai-maestro, the same shape as ai-maestro#111.

## Live observation still owed (why this is `testing`, not `complete`)

Every acceptance box is proven by automated tests, but the whole VALUE of this card is a
fleet behaviour no unit test can observe: that the daemon on THIS host actually writes the
inbox and the deferrals stop. After the next publish + daemon pickup, confirm:

```bash
ls -l ~/.claude/janitor-control/gh-notify-inbox.json          # exists, mtime within ~60s
tail -20 .janitor/logs/gh-reply-watch.log                     # deferral lines should stop
```

Until that is seen, the honest column is `testing` — the code is done, the effect is not
yet witnessed.

## Approval log
