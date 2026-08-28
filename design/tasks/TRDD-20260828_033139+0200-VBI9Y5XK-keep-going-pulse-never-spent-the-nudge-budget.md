---
trdd-id: VBI9Y5XK
title: The keep-going pulse advertised pending agents without spending the nudge budget
column: complete
created: 2026-08-28T03:31:39+0200
updated: 2026-08-28T03:31:39+0200
current-owner: janitor-session
task-type: bugfix
project-id: ai-maestro-janitor
min-approval-requirement: none
---

# A corpse could be re-advertised for 7 days, under a note promising 3

Reported by the ai-maestro hub 2026-08-28, from the RECEIVING end: five consecutive heartbeats
named one pending agent (a DIED `claude-code-guide`, terminal "Prompt is too long" — a
janitor#75 corpse), and `nudges` read **2 before the first fire and 2 after the fifth**.

## Root cause — two emit paths, one payer

| path | what it emits | pays? |
|---|---|---|
| `pending_agents.directive_lines()` | LISTS each agent | yes — `e["nudges"] += 1` per listed entry |
| `dispatch._phase_keep_going_nudge` | a COUNT + a pointer to the manifest | **no** |

The count path calls `_pending_agent_count()` → `pending()`, a pure reader. So an entry
surfaced ONLY by the pulse could never reach `nudges >= MAX_NUDGES`. It could not reach the
age sweep either: that route is guarded on `nudges == 0`, and such an entry sits above 0. It
therefore rode the full 7-day `MAX_AGE_S` backstop, re-inviting a resume on every fire.

**Why it is not just noise.** `directive_lines()`' own note says it: a DIED agent RE-RUNS the
request that killed it, which is how janitor#75 burned tokens for a week. The 3-nudge cap IS
that mitigation — and it was absent on the path that keeps naming the corpse. The note also
promised "listed at most 3 times, then dropped", which was FALSE there.

## Fix — the advertiser pays

`pending_agents.spend_nudges()` charges every non-`stopped` entry, called from the pulse
**after** the line is appended, never inside `_pending_agent_count()`. A spend must correspond
to an advertisement the reader actually saw; a counter that charges for a line it did not emit
is the same bug pointing the other way. A COUNT advertises every entry it counts, so it charges
all of them — unlike `directive_lines()`, which pays only for the `MAX_DIRECTIVE_AGENTS` it named.

**The rejected alternative, and why.** Dropping the `nudges == 0` guard on the age sweep is a
smaller diff and would cover any future third path — but it shrinks the window for a
legitimately-listed, still-RUNNING agent from 7 days to `UNNUDGED_MAX_AGE_S` (1 h). A long
background agent would vanish from the manifest while alive, and the session would stop being
told about work still in flight. Losing a live agent to fix a dead one is the wrong trade.

## Acceptance

- [x] The pulse spends; after `MAX_NUDGES` fires the entry is evicted and no longer advertised.
- [x] A `stopped` entry — excluded from the count, kept for audit — is never charged.
- [x] Driven END TO END through `dispatch._phase_keep_going_nudge()`, not `directive_lines()`.
- [x] 536 dispatch/pending tests pass; ruff + mypy clean (492 files).

## Notes and lessons learned

- **Two paths that pass separately is the gap.** Both had tests; neither test crossed the seam,
  so the count path's missing spend was invisible. The reporter said this outright and was
  right — the new test drives the real pulse.
- The bug was only visible from OUTSIDE, by someone reading the same line five times and
  checking whether the counter moved. A detector's own tests cannot see "this advertisement
  did not cost anything".
