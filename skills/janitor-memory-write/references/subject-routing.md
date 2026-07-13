# Subject routing — CASE fact vs METHODOLOGY lesson

## Table of contents

- [The decision](#the-decision)
- [Why it matters — off-topic pollution](#why-it-matters--off-topic-pollution)
- [Splitting an incident that yields both](#splitting-an-incident-that-yields-both)
- [Cleaning up an existing violation](#cleaning-up-an-existing-violation)

Shared by MEMORIZE (step 0, "Route the SUBJECT") and UPDATE (step 0, "STAY ON
TOPIC"). Run this check FIRST — before scope, before choosing a page, and on
EVERY fact and EVERY `[^N]` lesson before you append it. **One page = one
subject.**

## The decision

> **Ask:** *is this true only of THIS subject, or would it still be true of a
> completely different bug in a completely different system?*

| The fact/lesson is… | It belongs in… |
|---|---|
| specific to the subject (this API's quirk, this daemon's flag, this keychain's ACL behavior) | **the subject's own page** |
| a transferable way of WORKING (how to diagnose, verify, falsify, decide; a reasoning trap to avoid) | **the methodology page that owns it** — e.g. `debugging-methodology` |

## Why it matters — off-topic pollution

A general lesson parked inside a case page is **off-topic pollution**: someone
recalling `claude-client-authentication` wants auth facts, not lessons about
falsification. It is doubly wrong because it *scatters* the methodology across
every page that happened to teach it — written into each of the several pages
that taught it, and owned by none, so the page that should own it owns nothing.

## Splitting an incident that yields both

A single incident often yields BOTH. **Split it:** the subject fact stays on
the subject's own page; the transferable lesson goes to the methodology page.
**Before minting a NEW methodology page, survey the ones that exist** and add
to the owner instead of creating a fifth near-synonym:

```bash
memgrep recall "debugging methodology how to diagnose verify falsify" "${ROOTS[@]}"
```

Methodology is nearly always **USER** scope (a way of working is true across
all projects), even when the case that taught it is PROJECT or LOCAL. Then
**cross-link both ends** per THE LINK LAW: `[[debugging-methodology]]` in the
subject page's `## See also`, and the subject page in the methodology page's
`## See also`.

## Cleaning up an existing violation

**Cleaning up an existing violation is a MOVE, never a delete** — relocate the
lesson to its owner, leave the link behind. No knowledge is ever lost, only
re-homed.
