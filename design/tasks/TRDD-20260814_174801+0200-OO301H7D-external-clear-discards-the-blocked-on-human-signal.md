---
trdd-id: OO301H7D
title: The external clear computes the blocked-on-human signal and then discards it
column: complete
created: 2026-08-14T17:48:01+0200
updated: 2026-08-14T19:24:00+0200
current-owner: janitor-session
task-type: security
project-id: ai-maestro-janitor
approval-tier: 0
priority: 1
severity: major
npt: []
eht: []
implementation-commits: [fde1bf40]
---

# The external clear computes the blocked-on-human signal and then discards it

## The defect (VERIFIED first-hand 2026-08-14, not inferred)

`scripts/external_handoff_clear.py:187`:

```python
idle_s, _enq, _await = fleet_scan.transcript_activity(str(root), now)
```

Both `trailing_enqueues` and `awaiting_user` are bound to throwaway names. The
third value is the signal that says **this session is parked on an unanswered
`tool_use`** — a plan approval, a permission prompt, anything waiting on a human.

It is not a missing feature. It is computed, deliberately, and thrown away:

- `scripts/lib/fleet_scan.py:643` — `awaiting_user_decision(tail)`
- `:743` — `awaiting = awaiting_user_decision(tail)`
- `:709-714` — documented as "whether that same tail ends on an unanswered
  ``tool_use``"

And the pure decision function cannot receive it even if it were passed —
`scripts/lib/external_clear.py:929-942`, `should_clear_externally(...)` takes
`active_waiting` but has **no blocked-on-human parameter**.

## Why this is severe, stated precisely

`active_waiting` and `awaiting_user` are DIFFERENT conditions and only the first
has a veto:

| condition | meaning | vetoed? |
|---|---|---|
| `active_waiting` | a resume or background agent is in flight | **yes** |
| `awaiting_user` | the session is parked on an unanswered `tool_use` (human) | **NO** |

A session parked on a plan approval is, by construction, **idle** — the human
walked away. So it satisfies the long-idle trigger perfectly, meets no veto, and
gets `/clear`ed. `/clear` discards the conversation; the on-disk handoff is the
only survivor, and an 8 KB handoff does not carry the pending decision's context.

The daemon fleet-walks this path (`scripts/daemon.py:1935`), so this is not a
hypothetical reachable only by a hand-run command.

**The failure is silent and looks like success.** The clear "worked"; nothing errors.
The user returns to a session that answered its own prompt by forgetting the question.

A stale comment at `external_handoff_clear.py:242` still claims a "user present"
veto that no longer exists — so the code reads as if it were protected.

## Fix

Thread `awaiting_user` (and `trailing_enqueues`, same discard, same line) out of
`transcript_activity` into `should_clear_externally` as a **veto**, alongside
`active_waiting`. A veto, not a trigger term: `--force` must NOT be able to
override it, exactly as it cannot override `active-waiting` today.

Correct the stale `:242` comment in the same change — a comment claiming a
protection that does not exist is worse than no comment, because it stops the next
reader from looking.

## Acceptance criteria

All six VERIFIED first-hand against the source after `fde1bf40`, not ticked from the
worker's report.

- [x] `awaiting_user` reaches `should_clear_externally` and vetoes the clear.
      `external_clear.py:941` declares it as a REQUIRED keyword param — deliberately
      NOT defaulted, so mypy refuses a future call site that omits it and this exact
      bug cannot silently return. Passed for real at `external_handoff_clear.py:228`.
- [x] `trailing_enqueues` is either used or its discard is justified in writing at
      the call site (it was discarded on the same line, so it got no scrutiny either).
      Justified in writing at `external_handoff_clear.py:188-191`: it goes log-only,
      with the reason stated.
- [x] `--force` provably CANNOT override this veto (a test asserting the forced path
      still refuses). `test_force_never_overrides_a_safety_veto` asserts
      `forced.fire is False and forced.why == "awaiting-user"` — the specific REASON,
      not merely that it did not fire, so the test cannot pass for the wrong cause.
- [x] A test at the GATHER layer, not only the pure layer: a fixture transcript
      ending on an unanswered `tool_use` must refuse. The advisor's point is that no
      mutation of a pure function can catch an input that never arrives — the bug
      here is precisely an argument that is never passed, and a pure-function test
      suite is structurally blind to it.
      **PROVEN BY NEUTER, not assumed:** the wiring was deliberately broken and the
      suite re-run — `test_awaiting_user_veto_reaches_the_watcher_end_to_end` went RED
      with `ClearVerdict(fire=True, trigger='long-idle')`, i.e. the original bug
      reproduced, while **53 of 54 tests still passed**. Every one of those 53 was a
      pure-layer test. The file was then restored and verified net-zero. That ratio is
      the measurement this card exists to record.
- [x] The stale "user present" veto comment at `external_handoff_clear.py:242` is
      corrected. It now states the opposite explicitly (`:261`): *"There is no separate
      'user present' veto — that one was removed 2026-08-13"*. A comment asserting a
      protection that does not exist is worse than no comment, because it stops the
      next reader looking.
- [x] `uv run pytest`, `uv run ruff check scripts tests`,
      `uv run mypy scripts/ --ignore-missing-imports` clean. 54 passed; ruff clean;
      mypy clean over 482 source files.

## Provenance

Found 2026-08-14 by the Fable advisor while reviewing TRDD-UQW5IOAE, and verified
first-hand against the source before this card was written. It is a distinct defect
from UQW5IOAE: that card is about the IN-MODEL self-nudge path, this is the EXTERNAL
daemon-driven path. UQW5IOAE's acceptance box 3 ("a test proving a session blocked on
`ExitPlanMode` is NEVER cleared") cannot honestly be ticked until this lands, which
is why this is filed at priority 1 rather than folded into that card.

## Notes and lessons learned

The signal existed, was correct, and was free. The bug was one line of tuple
unpacking that named it `_await` — the underscore convention announces "I considered
this and it does not matter", which is exactly the review signal that stops anyone
looking again. A discarded value on a shared line with another discarded value got
no scrutiny at all.
