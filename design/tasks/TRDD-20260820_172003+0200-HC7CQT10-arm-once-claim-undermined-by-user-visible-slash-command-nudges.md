---
trdd-id: HC7CQT10
title: The arm-once claim is undermined by two user-visible SessionStart lines that read as a chore
column: testing
created: 2026-08-20T17:20:03+0200
updated: 2026-08-22T11:53:41+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
approval-tier: 0
scope: project
external-refs: [TRDD-TUIBWHT7, TRDD-BRHJHWW0]
npt: []
eht: []
---

# "Why does the janitor still need re-arming?" — it does not; the MESSAGE said it did

## What the USER reported (2026-08-20 ~17:05)

> "i told you to make the janitor-arm command no longer something that the user must enter
> at each session or after each compact. instead i see that is still needed."

The USER had typed `/janitor-arm` twice that day (00:01 and 16:05) believing it was required.

## Verified first-hand — the MECHANISM is correct, the WORDING was not

Measured against the live host, not inferred:

- `~/.claude/janitor-control/armed.flag` is present and persistent (`record_armed()` at
  `arm_record.py:65`); only `/janitor-disarm` or the kill-switch clears it — TRDD-TUIBWHT7
  works as specified.
- `.janitor/logs/session-start.log` shows the compact/clear guard firing correctly:
  `2026-08-20T09:44:26 armed; source=compact keeps the live cron -> no re-arm`, and the
  same for `source=clear` on 08-18 and 08-19. Mid-session re-arms are already banned in
  code (`if source not in ("startup","resume")`).
- On the one genuinely fresh process (`2026-08-20T07:55:47 source=resume`) the hook took
  the silent re-plumb branch and the session ended up with a live cron (`297fc367`
  recorded). No user action was required, and none was missing.

So the janitor never needed the user to arm it. What the user actually saw were TWO
SessionStart stdout lines — and SessionStart stdout is RENDERED INTO THE TRANSCRIPT
(`SessionStart:<source> hook success: <text>`), so both were visible to them:

1. `_cron_liveness_nudge`: *"…if it is missing, silently run /janitor-arm — it is
   idempotent… To opt this project out permanently: /janitor-disarm."*
2. the armed branch: *"…re-plumbing the session heartbeat. Silently run /janitor-arm (its
   4 tool calls); do not narrate this to the user."*

Both are agent-directed imperatives naming a slash command. To a human reading the
transcript that is indistinguishable from an instruction addressed to them — the word
"silently" does not help, because the line itself is not silent. A claim of "armed
forever" that prints "run /janitor-arm" twice per fresh session refutes itself in the
only channel the user reads.

## Fix (shipped)

Both emissions reworded to lead with **"NO USER ACTION REQUIRED"** and to drop the
slash-command form (`janitor-arm skill`, not `/janitor-arm`). The agent still receives an
unambiguous instruction; the human is told, in the first clause, that nothing is being
asked of them. No behavioural change to arming, gating, or the re-plumb itself.

The nag banner for a genuinely-unarmed host (`armed_state() == "absent"`) is untouched —
that one IS addressed to the user and is correct to keep.

## Why the platform still needs a per-process re-plumb at all

`CronCreate` is session-only by platform design (its own response says so): the cron
object lives in the Claude process and dies with it. No hook can create one — CronList /
CronCreate are model tools. So the persistent `armed.flag` plus a silent agent re-plumb is
the strongest available implementation of "armed forever", and it is the one in place.
If the platform ever gains a durable cron, this branch becomes deletable.

## Acceptance

- [x] Neither user-visible line contains a `/`-prefixed janitor command
- [x] Both lead with NO USER ACTION REQUIRED (regression-pinned)
- [x] compact/clear still skip the re-plumb; startup/resume still perform it
- [x] pytest (79 across the 3 affected suites), ruff, mypy, pyright clean
- [ ] Gate to complete: one fresh startup/resume observed emitting the new wording —
      **STILL OPEN, and the reason is CONDITIONAL EMISSION, not a missing deploy. Checked
      2026-08-22.**

      Unlike TRDD-9T0U3M00's box, this one is NOT publish-gated: the new wording IS in the
      installed plugin (`…/3.3.26/scripts/hooks/on-session-start.py`, 2 occurrences). The
      obstacle is that **both sites are `print()` to stdout, not log writes** — SessionStart
      stdout is rendered into the transcript and never reaches `session-start.log` (confirmed:
      0 occurrences of either the new OR the old wording in 2102 log lines). So it cannot be
      grepped after the fact; it has to be SEEN at a session start.

      And it only fires in the branch that does work: the cron-liveness nudge returns early when
      a `[janitor-heartbeat]` cron already exists, and the re-plumb line prints only when
      SessionStart actually re-plumbs. On this session's own `SessionStart:compact` neither
      fired — correctly, since the session is armed and its cron is live. **A healthy host is
      precisely the host where this box cannot be ticked.** It needs a start that re-plumbs
      (a restart, or a cron that expired).

      **Checked while here whether a THIRD emission was missed, because the card says "both":**
      `on-session-start.py:866` still reads *"…run `/janitor-arm` to arm it"* — the exact shape
      the other two were reworded away from. It is CORRECT and must not be "fixed": it is the
      `else` of the armed check, so it fires only when the janitor is genuinely NOT armed, where
      asking the user to arm once IS the arm-once request rather than a false chore. Recorded so
      the next reader does not file it as a missed instance.

## Approval log

- 2026-08-20T17:20:03+0200 — SHIPPED (todo → testing) by janitor-main-session. Root cause
  was a message addressed to the wrong reader, not a defect in the arm-once mechanism;
  the mechanism was verified working on the live host before any edit.
