---
trdd-id: B07VPT2G
title: IDLE_TTL_EXPIRY was 47 percent of one session's cache waste and no OPEN card carries it
column: complete
created: 2026-08-12T10:54:24+0200
updated: 2026-08-13T00:42:24+0200
current-owner: janitor-main-session
task-type: spike
approval-tier: 0
scope: project
severity: high
relevant-rules: []
npt: []
eht: [IJ94O8YD]
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

## ⏵ MEASURED 2026-08-13 — the 47% is NOT reproducible, and the real avoidable cost is elsewhere

Report (commands + tables + raw JSON beside it):
`reports/b07vpt2g/20260813_004101+0200-idle-ttl-expiry-refutation.md`

    agentlenspro get_cache_break_causes --out <file>                 # default minTokens=5000
    agentlenspro get_cache_break_causes --minTokens 500 --out <file> # 10x lower, to rule out filtering

**`TTL_EXPIRY` does not appear at all** — across 412 request bodies / 16 sessions, at BOTH
thresholds. It is one of the classifier's own named causes, so this is an observed absence and
not an unsupported query; and dropping the threshold 10x multiplied classified events 20x
(9 → 183) without surfacing one, so it is not a filtering artifact either.

| threshold | events | total cache_creation | ranking |
|---|---|---|---|
| 5000 | 9 | 675,299 | COLD_START 47.7% · COMPACTION 22.6% · CLAUDE_MD_CHANGED 22.3% · NORMAL_GROWTH 6.1% |
| 500 | 183 | 1,073,769 | COLD_START 30.3% · COMPACTION 28.3% · NORMAL_GROWTH 25.7% · CLAUDE_MD_CHANGED 14.0% |

**What this refutes, precisely.** Not the 2026-08-02 measurement of session `e804d2c9` — that
session's 81 occurrences at ~33k each would clear even the default threshold, so it happened.
What falls is the GENERALISATION this card was built on: `IDLE_TTL_EXPIRY` is not the janitor's
steady-state cost. Over 16 sessions it is not a cost at all.

**The finding that replaces it, and it indicts this session.** The only significant avoidable
cause in the corpus is **CLAUDE_MD_CHANGED — 150,824 cache_creation tokens**, `expected=false`,
actor *"claudemd block changed at pos 1: …/.claude"*, remediation *"Do not edit instruction files
during a live session."* That session is this one and the edits were mine: the rules trim
(`29121d8b`) and the INERT preamble dedup (`83a68674`) both rewrote files under `~/.claude/rules/`,
which are injected into the prefix. **Two changes that BOUGHT context-floor headroom cost 150k
cache_creation tokens to make, in the session that made them.** Both were right to do — the floor
is charged to every cold subagent on this machine forever — but the timing was free to fix: the
same edits made by a subagent, or before the session's prefix is warm, cost the live prefix
nothing. Everything else measured is `expected=true`.

## Acceptance

- [x] TRDD-EUWIHP0G (complete) is read first — it shipped the remedy, and this card exists
      because the 47% was measured AFTER it
- [x] The 47% figure is reproduced or refuted on a second session, with the measurement command
      recorded — **REFUTED** at two thresholds, commands and coverage above
- [x] WHO pays `IDLE_TTL_EXPIRY` is established from a control, not inferred from plausibility —
      **moot, and answered the honest way**: nobody pays it here. Building a control session for
      a cause that does not occur across 16 sessions would be measuring a hypothesis instead of
      testing it
- [x] An explicit verdict: avoidable (with a named lever) or the unavoidable price of an idle
      armed session — **NEITHER, on this machine: it is not a cost.** The verdict the data
      supports is that the cost moved: the avoidable share now belongs to CLAUDE_MD_CHANGED
- [x] If avoidable, a derived TRDD per lever — not a bullet, and not a section of this card.
      **One lever survives** (don't edit injected instruction files mid-session) and it is
      **TRDD-IJ94O8YD**, a real card. Per this card's own history — buried in a bullet, correctly
      identified as buried in a bullet, then re-buried in a section by the card that identified
      it — writing it as a paragraph here would have been the third burial

## Approval log

- 2026-08-13T00:42:24+0200 — COMPLETED by janitor-main-session. A spike's deliverable is a verdict, and it produced
  one: the 47% is not reproducible (0 TTL_EXPIRY across 412 bodies / 16 sessions at two
  thresholds), and the avoidable cost that IS there — CLAUDE_MD_CHANGED, 150,824 tokens — is now
  TRDD-IJ94O8YD.
