---
trdd-id: 3MEUT9VW
title: Rich SessionStart disarmed-state reminder — a temporary global stop can't silently persist
column: complete
created: 2026-07-01T22:04:19+0200
updated: 2026-07-01T22:04:19+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 2
severity: MEDIUM
effort: S
task-type: feature
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
impacts: []
attempts: 0
implementation-commits: []
---

# Rich SessionStart disarmed-state reminder — a temporary global stop can't silently persist

## Why

On 2026-06-30 the janitor was globally disarmed (kill-switch + pause) as a TEMPORARY stop
while a token-burn concern was investigated, with the intent to re-arm after. It was never
re-armed and stayed dead ~33 h — long enough that the post-compaction auto-resume silently
stopped working and a session sat idle. Root cause of the *silence*: the SessionStart hook's
disarmed-state notice was a bare "the janitor is globally stopped" line carrying **no duration
and no reason**, so it was easy to dismiss/miss; and the long-running session that got disarmed
mid-flight predates the disarm, so SessionStart never re-fired a fresh notice for it.

The janitor's own heartbeat is DELIBERATELY silent while disarmed (RQ9FIFX6 — a cron fire is not
free), so the reminder cannot come from the heartbeat. But hooks are NOT gated by the kill-switch
and fire on every session start regardless — a zero-extra-cost surface. This TRDD enriches that
existing SessionStart notice so a forgotten temporary stop is impossible to miss.

Note: this was a DIAGNOSIS byproduct of a session that first *mis*-diagnosed the revive as a
"~100M token burn" risk — see the LOCAL wikimem note `reference_heartbeat_token_baseline` [^1],
which now records that the 5-min heartbeat is a CACHE KEEP-ALIVE (it SAVES money), the real
historical burn was the #236 no-op-spawn bug (fixed), and the weighted metric counts cache_read
at only ~10%. The correct safeguard was NOT a cadence guard (which would have KILLED the
keep-alive) — it is this out-of-band reminder.

## What changed

`scripts/hooks/on-session-start.py`:
- `_active_global_stop(gs)` — pure-ish reader: returns `(kind, reason, since_epoch)` for the
  active machine-wide stop (kill-switch DISARMED dominates a PAUSED), read straight from the
  flag file (content = reason, mtime = when-set); OSError-degrades to empty, never raises.
- `_format_stop_reminder(kind, reason, since, now)` — pure message builder naming the DURATION
  (days+hours) and the REASON, unit-testable without clock/fs. Extracting it also drops main()'s
  cognitive complexity back under the threshold.
- The disarmed branch now prints the enriched reminder (⚠ + since-when + reason + the exact
  revive command) instead of the bare line.

`tests/test_on_session_start_disarm_reminder.py` — 6 real tests (isolated JANITOR_GLOBAL_STATE_DIR,
never touches live state): flag reading, none-when-running, disarm-dominates-pause, duration+reason
rendering, hours-only + empty-reason omission, zero-mtime graceful degradation.

## Acceptance

- With a global stop set, the NEXT session start prints "⚠ … globally DISARMED since <date>
  (<N>d <N>h ago) — reason: "<reason>". … /janitor-global-arm …". MET.
- No stop set → no reminder (running state). MET.
- pyright 0 / ruff clean / 6 tests green. MET.

## Residual (documented follow-up, not in scope here)

The reminder only helps the NEXT session start. A session disarmed MID-FLIGHT that stays alive
for days still has no in-session surface (the heartbeat is silent by design). A stronger,
optional safety net — an out-of-band OS reminder, or an auto-EXPIRING disarm (auto-re-arm +
notify after N days) that reconciles "immortal" with "explicitly stoppable" — is the natural
next step if the owner wants it.

## Notes and lessons learned

[^1]: the mis-diagnosis + correction is recorded in the LOCAL wikimem note
  `reference_heartbeat_token_baseline` (updated 2026-07-01) and the cross-project USER note
  `claude-cache-ttl-and-fork-agents`, so a future session recalls the cache economics BEFORE
  alarming about the heartbeat.
