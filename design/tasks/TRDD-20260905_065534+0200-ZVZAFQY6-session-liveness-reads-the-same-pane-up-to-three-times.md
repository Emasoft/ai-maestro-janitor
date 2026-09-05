---
trdd-id: ZVZAFQY6
title: session-liveness reads the same pane up to three times per instance on the field-busy path
column: todo
created: 2026-09-05T06:55:34+0200
updated: 2026-09-05T06:55:34+0200
current-owner: main-session
task-type: refactor
priority: low
severity: low
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [daemon, session-liveness, redundant-io]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [TRDD-QJ5LP4W2, TRDD-8BXMNQ4T]
---

# session-liveness reads the same pane up to three times per instance

## The finding

On the field-busy branch of `task_session_liveness`, ONE instance's pane is captured
by THREE independent `terminal_trigger.read_pane_text` calls in a single loop
iteration:

| # | reached from | the read |
|---|---|---|
| 1 | `daemon.py:1999` | `pane_state.read(inst.terminal)` |
| 2 | `daemon.py:2033` | `fleet_inject.command_plan_field_busy` → its own read at `fleet_inject.py:430` |
| 3 | `daemon.py:2041` | `fleet_inject.field_holds_our_queued_command` → its own read at `fleet_inject.py:489` |

Neither helper accepts already-read text; each resolves the terminal and reads again.
`read_pane_text` is capped at 10 s on the tmux branch and **15 s on the iTerm/osascript
branch** (`terminal_trigger.py:485` / `:498`), so three reads are **up to ~45 s per
instance on osascript (~30 s on tmux)** — the headline number is channel-specific, not
universal. The loop at `daemon.py:1652` is a plain `for` with no concurrency, so the
cost is additive across every instance that lands on this branch in the same beat.

**The comment above read #1 is true of the code it describes and was overtaken by a
guard added beside it.** `daemon.py:1995` says routing every keystroke through the
policy table "costs no extra osascript (Proposal §5)" — correct for `pane_actuate.act`
at `daemon.py:2104`, which passes `state=pane`, so `pane_actuate.py:174`'s `if state is
None and read_pane:` guard is false and it adds no read. The field-busy guard at
`:2033`/`:2041` came later and does add reads, and the comment's scope was never
narrowed. Not a false comment; a comment whose scope a reader will over-apply, which
is the thing that stops them checking.

## What this card is NOT

- **Not TRDD-QJ5LP4W2's remedy.** That card is a scheduling-bound design decision whose
  own box 1 gates any `daemon.py` scheduling change on a fable-advisor consult. This is
  a redundant-IO fix that needs no such consult, and folding it in would gate a cheap
  fix behind a blocked one. Split per TRDD clause 13's third branch (its own TRDD, no
  `parent-trdd:`, no `eht:` gate).
- **Not established as a cause of any measured stall.** It was found by reading the code
  while answering QJ5LP4W2's "why 78 s?" question; that question's answer turned out to
  be a different, fixed cost (`probe_iterm_sessions`' 15/30/45 s retry ladder). The
  triple read is a real redundancy with a real worst case, and no measurement here
  attributes an observed stall to it. **Do not write a commit message claiming it fixed
  one** unless a measurement says so.

## The task

Make one pane capture serve the whole iteration. The shape is already established by
`pane_actuate.act`, which takes `state=` and skips its own read — give
`command_plan_field_busy` and `field_holds_our_queued_command` the same optional
parameter and pass the `pane` already read at `daemon.py:1999`.

**The one real design question, which is why this is not a two-line change:** the three
reads are at three different instants, and the guard exists precisely because the field
can change under it (a permission prompt appearing between reads is the 2026-07-17
incident the guard was added for). Re-using one capture makes the check cheaper and
STALER. Decide deliberately whether staleness is acceptable at each site, and record
the reasoning — if it is not, the correct fix may be to drop read #1 or #2 rather than
share one.

## Acceptance criteria

- [ ] At most one `read_pane_text` per instance per beat on the field-busy path, OR a
      written justification on this card for each read that survives.
- [ ] The staleness question above is answered explicitly, not silently resolved by
      whichever refactor was convenient.
- [ ] `daemon.py:1995`'s "costs no extra osascript" comment is either true of all
      neighbouring code or corrected to say which paths it covers.
- [ ] A test pins the read count for one instance on the field-busy path, so a future
      helper cannot quietly add a fourth.

## Notes and lessons learned

- **A helper that resolves its own inputs cannot be composed cheaply.**
  `command_plan_field_busy(terminal, plan)` takes the terminal, not the text, so every
  caller pays a capture even when one is already in hand. The version that takes the
  data and a version that fetches it are not the same function; the second silently
  costs whatever fetching costs, at every call site, forever.
