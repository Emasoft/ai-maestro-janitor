---
trdd-id: B07VPT2G
title: IDLE_TTL_EXPIRY was 47 percent of one session's cache waste and no OPEN card carries it
column: todo
created: 2026-08-12T10:54:24+0200
updated: 2026-08-12T11:30:00+0200
current-owner: janitor-main-session
task-type: spike
approval-tier: 0
scope: project
severity: high
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-I6ZZWVDN, TRDD-SLFMG704, TRDD-K1RJUYGK, TRDD-EUWIHP0G]
---

# The janitor's own largest measured cost has no OPEN card

## Why — the finding, and the two hand-offs that left it with no workable home

Measured 2026-08-02 in session `e804d2c9` (opus-5, 221 cache breaks, 5,643,196 wasted tokens,
$32.45 total): **`IDLE_TTL_EXPIRY` alone accounted for 81 occurrences / 2,676,704 tokens /
$15.39 — 47% of that one session's entire cache waste.** That is larger than the subject of
the card that measured it, and larger than anything else on the janitor's cost ledger.

### CORRECTION 2026-08-12, minutes after filing — this card's own premise was overstated

I filed this claiming the finding "has never had a card", from a `git grep IDLE_TTL_EXPIRY`
over `design/` that returned only two hits. **TRDD-I6ZZWVDN names an owner two lines above the
section I read**: *"That is TRDD-EUWIHP0G's subject (cold-cache compact), measured live."* The
grep missed it because EUWIHP0G's card never spells the constant. I concluded from one string
search what one more line of reading would have refuted — precisely the failure the corpus
already warns about, committed while writing a card about findings that get lost.

**The relationship, stated correctly:**

- **TRDD-EUWIHP0G** (`column: complete`) owned the **REMEDY** — auto-compact a large context on
  resume after a cold-cache gap — and shipped it, with its own honest correction recorded (a
  `/compact` cannot avoid the immediate cold write; it makes every FUTURE resume cheap).
- The 47% measurement is dated **2026-08-02**, *after* that remedy shipped.

So this card is **not** a duplicate and **not** an orphan: it is the question EUWIHP0G's
completion leaves open — *the remedy shipped, and `IDLE_TTL_EXPIRY` was still 47% of a
session's waste; does the remedy not cover this case, or is the cost irreducible?* That is a
sharper question than the one I filed, and it only exists because EUWIHP0G is done.

What survives of the original framing is narrower and still true: **no OPEN card carried it.**
EUWIHP0G is terminal and cannot be worked, so the follow-up had nowhere to live on the board —
which is why it sat in a section for ten days. Add EUWIHP0G to the reading list before starting.

**Diagnosed twice, and left without an OPEN card each time:**

1. It began as an inline "NPT" **bullet** on TRDD-SLFMG704, whose own scope (hand the
   cache-thrash finding to OTHER plugins) then finished — leaving the bullet attached to a
   card nobody would open again.
2. TRDD-I6ZZWVDN extracted it on 2026-08-02 with an explicit, correct rationale, quoted here
   because it indicts what happened next: *"an NPT written as a bullet is a task nobody can
   see on the board (rule 9: derived tasks are their own depth-1 TRDDs)"* — and then recorded
   it as an inline **section** of I6ZZWVDN, marked "Not started", where it has sat for ten
   days.

So the finding has now survived being buried in a bullet, being correctly identified as
buried in a bullet, and being re-buried in a section by the card that identified it. **A
routing decision is not a routing action.** Writing down that something needs its own card is
the cheapest possible substitute for creating one, and it reads identically in the transcript.

## What (a SPIKE — the mechanism is not established, and must not be assumed)

`IDLE_TTL_EXPIRY` is a cache-break reason: the prompt cache aged out between turns. The
janitor is a plausible contributor — a `*/5` heartbeat fires turns into an otherwise idle
session — but **plausible is not measured**, and this card must not repeat the attribution
error TRDD-K1RJUYGK had to retract (its title still carries "attribution of the cost
RETRACTED").

1. Establish WHO pays it: is the break caused by the gap BEFORE a heartbeat fire (idle human,
   janitor wakes into a cold cache) or by the janitor's own inter-fire spacing? A session with
   no janitor armed is the control.
2. Establish whether it is even avoidable. A cache TTL expiring during genuine idleness may be
   the correct, unavoidable cost of a session existing — in which case the finding is
   "the heartbeat's true price", and the honest deliverable is a documented number, not a fix.
3. Only then decide a remedy. Existing levers that already touch this: the external
   handoff-and-clear gate (`external_clear.next_fire_misses_cache`, which already reasons
   about a fire landing past the TTL) and the cadence itself.

## Acceptance

- [ ] TRDD-EUWIHP0G (complete) is read first — it shipped the remedy, and this card exists
      because the 47% was measured AFTER it
- [ ] The 47% figure is reproduced or refuted on a second session, with the measurement command recorded
- [ ] WHO pays `IDLE_TTL_EXPIRY` is established from a control, not inferred from plausibility
- [ ] An explicit verdict: avoidable (with a named lever) or the unavoidable price of an idle armed session
- [ ] If avoidable, a derived TRDD per lever — not a bullet, and not a section of this card
