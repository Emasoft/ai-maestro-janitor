---
trdd-id: KU3ERYFX
title: Human-only findings class — an alarm only a human can act on must say so and emit once
column: todo
created: 2026-08-08T10:36:31+0200
updated: 2026-08-13T05:11:55+0200
current-owner: janitor-main-session
task-type: feature
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#234]
---

# Human-only findings class

## Why (janitor#234, architect peer)

The iTerm Automation alarm prescribes a GUI System Settings action. An agent session
structurally cannot perform it (no CLI path to a TCC toggle), yet the drift line is delivered
to agent sessions on every fire. Three costs the peer names, all real: repeated context re-read
cost on large sessions; alarm-fatigue training agents to skim the drift channel; no way to
record "surfaced to the human, awaiting their action" — *never reported* and *reported-pending*
are indistinguishable.

Partially addressed already: v2.8.1's content-hash ack bounds repeats to one per DISTINCT
observation per session (the every-fire repeat the peer saw is 2.7.x behavior), and
TRDD-EZ3PMQYX removes the cannot-succeed remedy from the launchd branch entirely. This card is
the remaining structural half.

## ⏵ LIVE INSTANCE 2026-08-13 05:11 — delivered to an agent session that cannot act on it

The iTerm-Automation alarm fired into this session's heartbeat. It prescribes *System Settings →
Privacy & Security → Automation → allow `…/cpython-3.12-…/bin/python3.12` to control iTerm* —
a GUI toggle with no CLI path, so the reader structurally CANNOT perform it. That is this card's
premise, observed rather than argued, five days after filing.

**Two details the design should absorb, both visible in this instance:**

1. **The alarm is exemplary in every respect EXCEPT its audience.** It refuses to guess between
   its two candidate causes, states outright that a missing denial message is not evidence of a
   grant, names the only positive evidence that would settle it, and gives a fallback (tmux needs
   no grant). Nothing about its CONTENT should change. The defect is purely that a
   correctly-written human-only alarm is delivered to a reader who cannot act — which confirms
   `actor: human` must be a DELIVERY property, not a quality bar on the message.

2. **It is self-clearing** (*"this alarm clears itself on the next fleet scan once sessions
   enumerate again"*), and that interacts with the `surfaced-to-human` stamp: the stamp must not
   outlive the condition, or the ledger will show "reported-pending" for a finding that resolved
   itself. Pair the stamp with the finding's own liveness rather than treating it as a durable
   fact — otherwise this card's fix reintroduces staleness of the kind TRDD-88ZVEQY7 is about.

## What

- An `actor: human` marker on findings (issue catalog / findings ledger schema) for findings
  whose remedy requires a human at a GUI or a credential decision.
- Delivery contract for `actor: human`: emitted ONCE per session (the hash-ack generalized),
  prefixed so the agent's correct move is explicit — "surface to your human and move on; do
  not re-evaluate or attempt this yourself".
- A `surfaced-to-human` stamp (per finding, per session) so the ledger can distinguish
  never-reported from reported-pending — the ack path the peer asked for.
- Audit which existing findings qualify (Automation grant, keychain re-grant, OAuth one-time
  login, captcha) and tag them.

## Acceptance

- [ ] Schema + emission-contract tests (once per session; explicit human-only prefix)
- [ ] The iTerm alarm's session-branch grant advice carries the marker
- [ ] Ledger distinguishes never-reported vs surfaced-pending
- [ ] #234 answered when it ships
