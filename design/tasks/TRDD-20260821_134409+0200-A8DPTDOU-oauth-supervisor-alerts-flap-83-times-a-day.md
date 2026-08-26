---
trdd-id: A8DPTDOU
title: OAuth-supervisor alerts flap 83 times a day because two keys describe one condition
column: backburner
created: 2026-08-21T13:44:09+0200
updated: 2026-08-26T10:05:00+0200
current-owner: janitor-main-session
task-type: bugfix
project-id: ai-maestro-janitor
scope: project
severity: major
approval-tier: 0
labels: [oauth-rotator, alerts, noise]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# The OAuth supervisor's alerts flap because two keys describe the same condition

## Measured, not inferred — `oauth-rotator/rotator.log`, 2026-08-21

```
83 ONSET   rotator-stuck:all-maxed
83 CLEARED rotator-stuck:all-maxed
81 ONSET   cookie-leg-stuck
27 CLEARED cookie-leg-stuck
25 ONSET   reauth-needed:slot-unreadable
28 CLEARED reauth-needed:slot-unreadable
 3 ONSET   reauth-needed:refresh-dead
 3 CLEARED reauth-needed:refresh-dead
```

Two defects are visible in that table, and one of them is provable from the log text alone.

**1. `rotator-stuck:all-maxed` and `reauth-needed:refresh-dead` emit BYTE-IDENTICAL message
text**, and each CLEARS the other, so they alternate:

```
13:38:31 ONSET   rotator-stuck:all-maxed — reauth-needed: 2 alternate slot(s) have a dead refresh…
13:38:31 CLEARED cookie-leg-stuck
13:39:52 ONSET   reauth-needed:refresh-dead — reauth-needed: 2 alternate slot(s) have a dead refresh…
13:39:52 CLEARED rotator-stuck:all-maxed
13:40:30 ONSET   rotator-stuck:all-maxed — reauth-needed: 2 alternate slot(s) have a dead refresh…
13:40:30 CLEARED reauth-needed:refresh-dead
```

One underlying condition, classified under two mutually-exclusive keys, ~40–80 s apart. 14 of
these in the last hour alone. Nothing about the machine changed between them.

**2. `cookie-leg-stuck` ONSETs 81 times and CLEARS 27** — it re-onsets without clearing, so
either the ONSET is not idempotent or the clear predicate is narrower than the onset predicate.
Counts that asymmetric are a bug on their own, independent of defect 1.

## Why it matters

An alert that fires 83 times a day for an unchanged condition trains its reader to ignore the
channel — and this particular channel is the one that says the fleet is about to run out of
usable accounts. The noise is the harm, not the underlying OAuth state.

It also actively misleads. The stale `session-start.log` snapshot said *"run
`/janitor-refresh-cc-logins`"* for three accounts, while the live rotator log says the opposite
for the same accounts: *"775 refresh exchanges failed, the last one on the NETWORK
(timeout/DNS/connection) — the credential itself was never judged. Retryable: chase the
transport, do NOT re-login on this evidence."* A reader who acts on the flapping summary
re-logins three accounts that did not need it.

## What is NOT claimed here

The underlying OAuth state is a separate question and is NOT this card. The rotator tick is
ALIVE (log mtime 13:40:30, ~3 minutes before this card was written), so the `tick-stalled`
alert recorded in `session-start.log` at 12:44 was already stale when read. This card is only
about the alert layer flapping.

## Acceptance

- [ ] One condition maps to exactly ONE alert key — the identical-text pair is resolved by
      deciding which key owns "an alternate slot has a dead refresh and is expiring", not by
      suppressing either
- [ ] `cookie-leg-stuck` ONSET/CLEARED counts are symmetric over a day, or the asymmetry is
      explained in the code with a comment saying why re-onset without clear is correct
- [ ] A test that drives the same unchanged condition across N supervisor ticks and asserts
      exactly ONE ONSET — flapping must be RED, and the test must fail on today's code
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`

## ⏵ 2026-08-26 10:05 — ROOT CAUSE FOUND, and it was not the alert layer

All three accounts are live again (`oauth-health` → `status: ok`, `has_refresh: true` on
each; first clean check since 2026-08-11). What actually broke rotation:

**`slot_capture_browser.py` carried NO PEP-723 dependency header** (fixed in `41ccc80f`), so
`uv run --script` installed nothing and every capture died at
`from playwright.sync_api import …` → `ModuleNotFoundError`. Its sibling `reauth.py` HAS the
header. Two legs can re-mint a credential; the refresh leg was failing (233/576/789 recorded
failures) and the capture leg could not start at all.

**That is what makes this card's defect serious rather than cosmetic.** The alert cycled
ONSET→CLEARED all night reporting a recovery that NO code path was capable of performing —
both re-minting legs were down. A false CLEARED is not noise here: it is the reason nobody
looked for 19 days while the fleet ran on one expiring account.

The acceptance box added on 2026-08-26 (CLEARED requires positive evidence of a mint) is
exactly right and is now backed by a concrete case: a mint was impossible, and the alert
cleared anyway.

## Fresh evidence — 2026-08-26 (the flap is a FALSE RECOVERY, not just noise)

Five overnight ONSET→CLEARED cycles for `cookie-leg-stuck` / `reauth-needed:refresh-dead`
(21:27, 23:16, 01:26, 04:26, 04:47) while **nothing was ever minted** — all three credentials
stayed dead (`invalid_grant`, expired 2026-08-11/13/14, 233/576/789 failed exchanges) and
`rotation-stuck.json` stayed `all-accounts-maxed` throughout.

This raises the severity of the card beyond noise: the detector **CLEARS on a signal that is
not a real recovery**. That is precisely why this looked handled while staying broken for two
weeks — a cleared alert reads as "resolved" to every consumer, including the human. So the
acceptance box about symmetric counts is necessary but NOT sufficient: a CLEARED must be
gated on evidence a credential was actually minted, not on the absence of the failing probe.

Add to acceptance:

- [ ] `CLEARED` for any `reauth-needed:*` / `cookie-leg-stuck` key requires positive evidence
      of a successful mint (a fresh token with a future expiry), never merely a probe that
      stopped failing; a test drives "probe quiet, nothing minted" and asserts the alert
      STAYS onset

## Notes

Found incidentally while checking whether TRDD-HC7CQT10's observation gate could be closed
from `session-start.log` (it cannot — 8 `source=compact` entries since that fix shipped, no
fresh `startup`/`resume`, so its box stays open).

Filed rather than fixed: choosing which key owns the condition is a design decision about the
alert vocabulary, and the wrong choice makes a real fleet-exhaustion warning unreachable.

## Approval log
