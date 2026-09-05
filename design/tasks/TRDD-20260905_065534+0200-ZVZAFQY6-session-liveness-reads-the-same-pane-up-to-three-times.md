---
trdd-id: ZVZAFQY6
title: session-liveness reads the same pane up to three times per instance on the field-busy path
column: todo
created: 2026-09-05T06:55:34+0200
updated: 2026-09-05T10:04:18+0200
current-owner: main-session
task-type: docs
priority: low
severity: low
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [daemon, session-liveness, redundant-io, deliberate-redundancy]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [TRDD-QJ5LP4W2, TRDD-8BXMNQ4T]
---

# session-liveness reads the same pane up to three times per instance

## ⏵ STATE — READ THIS FIRST — 2026-09-05: THE FIX THIS CARD PROPOSED IS UNSAFE AND IS REFUSED

**The three reads are DELIBERATE. Do not deduplicate them.** Investigated the same day the
card was filed (read-only analysis, then the two load-bearing claims verified against
source). Each read is fresh for a reason, and two of the three have an UNSAFE direction:

| read | drives | stale in the unsafe direction ⇒ |
|---|---|---|
| 1 · `daemon.py:1999` | the RETRY_WEDGE decline (`:2000-2011`) and `state=` into `pane_actuate.act` (`:2052`, `:2107`) | wedge appears after the read ⇒ `plan()` branches on a screen it never saw — **covered ON THIS BRANCH ONLY**, because read 2 runs strictly later and refuses. On the field-EMPTY branch read 2 returns `False`, read 3 never runs, and read 1's staleness is unmitigated |
| 2 · `fleet_inject.py:430` | whether the field is non-empty RIGHT NOW, gating the whole fire path | **empty → busy**: a permission dialog opens between read and keystroke and we type into it — the 2026-07-17 incident class (`fleet_inject.py:404-411`). **That race is IRREDUCIBLE and freshness does not close it; what dedup does is WIDEN it** by everything between read 1 and read 2. Hence: as late as possible |
| 3 · `fleet_inject.py:489` | whose text occupies an already-busy field | **ours → a human's**: reusing read 2's text still matches our vocabulary, so `ours` is wrongly truthy and `act(OWN_COMMAND_UNSUBMITTED)` fires a bare `Enter` — **onto the human's line** |

**Read 3 is the decisive one, and the reason is that nothing downstream re-checks.**
`pane_policy._submit` (`pane_policy.py:235-245`) tests ONLY
`state.input_field.kind == InputFieldKind.EMPTY` before emitting the `Enter`; it never
re-verifies the content is still ours. So read 3's freshness is the *sole* thing standing
between the janitor and submitting a human's unrelated input. **Read first-hand at exactly two
sites** — `_submit`, and `field_holds_our_command`'s exact-match rule
(`fleet_inject.py:470-475`). `pane_policy.plan()`'s dispatch arm was NOT read: the argument
there is structural — `plan()` receives only a `PaneState`, whose `input_field.kind` is an
EMPTY/non-EMPTY classification and carries no ownership information, so the check could not
live there. Strong, but reasoned rather than observed.

**The code already anticipated this CLASS of refactor and rejected it.** That function's own
docstring (`fleet_inject.py:459-468`) argues against caching the field content as a second
source of truth, naming *"staleness and pane-reuse questions"* — i.e. this card — and
concluding *"the field content is already the record."*

**So the cost is real and it is the price of the guard.** Up to ~45 s per instance on the
osascript channel is what it costs to check, twice, as close to the keystroke as possible,
that we are not typing into someone's dialog or over their line. **A cheaper design must
come from making the READ cheaper or the path rarer — never from reusing a capture.**

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

## What is left of this card

Only the comment. `daemon.py:1995` says routing every keystroke through the policy table
"costs no extra osascript (Proposal §5)" — true of `pane_actuate.act`, which receives
`state=pane` and skips its own read (`pane_actuate.py:174`), and NOT true of the field-busy
guard added beside it. Narrow its scope so a reader does not carry the claim onto the guard.

**The ~45 s/instance cost is left UNADDRESSED, and that is deliberate.** If it ever becomes
worth attacking, the directions are a cheaper `read_pane_text` or a rarer field-busy path —
**never a shared capture**. File then, with a measurement; there is nothing to scope today,
and a speculative card would just sit in `todo`.

*Noted and NOT opened as a card: read 1's staleness on the field-EMPTY branch is a narrow,
unmeasured gap in the wedge guard. Unrelated to dedup, unchanged by this card's disposition,
and an unmeasured hazard does not deserve a card — but somebody should know it exists.*

Full analysis: `reports/zvzafqy6-pane-read-staleness/20260905_071916+0200-staleness-safety-per-call-site.md` (gitignored).

## Acceptance criteria

- [x] `daemon.py:1995`'s comment names which paths it covers. **Done 2026-09-05:** a SCOPE
      paragraph says "no extra osascript" is true of the POLICY TABLE (`act()` gets `state=`
      and skips its own read) and is NOT a claim about the beat, since the guard below takes
      two more captures and the comment predates it.
- [x] A comment at the field-busy guard records WHY the two reads are independent.
      **Done 2026-09-05:** both unsafe directions named at the guard (stale EMPTY ⇒ type into
      a dialog; stale OURS ⇒ Enter on a human's line, with `pane_policy._submit` testing only
      `EMPTY` and never whose text it is), plus the rule that the cheaper design must make the
      READ cheaper or the path rarer, never share a capture.
- [ ] ~~At most one `read_pane_text` per instance per beat~~ **REFUSED, see STATE.**
- [ ] ~~A test pins the read count~~ **REFUSED — it would pin the unsafe design.** If
      anything is pinned it is the opposite: that reads 2 and 3 each take their OWN capture.

## Notes and lessons learned

- **A helper that resolves its own inputs cannot be composed cheaply — and sometimes that
  is the point.** `command_plan_field_busy(terminal, plan)` takes the terminal, not the
  text, so every caller pays a capture even when one is already in hand. That reads as a
  design flaw until you ask what the function is FOR: it answers *"is the field busy right
  now"*, and a parameter carrying text someone else read cannot answer *now*. **Taking the
  terminal rather than the text is how the signature makes staleness unrepresentable.**
- **Redundancy that costs 15 s a call is not obviously waste — find out what it buys before
  removing it.** This card was filed as a redundant-IO fix on a real, correctly-measured
  cost, and the fix would have let the janitor press Enter on a human's half-typed line. The
  measurement was right and the conclusion did not follow from it.
- **The refusal belongs at the CODE, not only here.** A future reader meets the three reads
  in `daemon.py` long before they find this card, and will re-derive the same wrong fix. That
  is why an acceptance box now asks for a one-line why at the guard — a card nobody opens
  cannot defend an invariant.
