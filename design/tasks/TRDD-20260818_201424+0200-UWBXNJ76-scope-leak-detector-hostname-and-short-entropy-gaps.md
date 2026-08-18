---
trdd-id: UWBXNJ76
title: memory-scope-leak misses bare hostnames and sub-24-char high-entropy ids
column: todo
created: 2026-08-18T20:14:25+0200
updated: 2026-08-18T20:14:25+0200
current-owner: janitor-main-session
task-type: security
priority: low
approval-tier: 0
scope: project
external-refs: [ai-maestro TRDD-BRRJK57P @ 9562b2a4]
npt: []
eht: []
---

# Scope-leak detector gaps: bare hostnames + short high-entropy ids

## Why (hub-verified P3, ledgered in ai-maestro TRDD-BRRJK57P)

Two enumerable coverage gaps in the PROJECT-scope privacy gate (which, since AZ6QRK0D's
verdict, is the SOLE enforcement point for publish-globally pages — raising its stakes):

1. `private_path_patterns.py:215` anchors the hostname pattern to `.local|.lan` — a bare
   hostname (`emasofts-mac-mini`, an mDNS name without suffix, an internal DNS name on another
   TLD) passes.
2. `memory-scope-leak.py:96` sets `_ENTROPY_MIN_LEN = 24` — shorter high-entropy identifiers
   (16-23 char API key fragments, short ULIDs/tokens) are never even tokenized.

## What

Enumerate the classes deliberately (hub's instruction) rather than just widening regexes:
which hostname shapes and which id lengths/alphabets are IN scope, with a **positive control
per class** in the test suite (a fixture that must fire) so coverage cannot silently regress —
the a-guard-disarmed-by-the-event-it-guards lesson. Mind the FP budget: bare-hostname matching
is FP-prone (any short word matches "a DNS label"); require corroborating context (e.g.
hostname-position in a path/URL/ssh string) rather than matching every bare token.

## Acceptance

- [ ] class enumeration recorded in the detector docstring (in-scope vs out-of-scope shapes)
- [ ] one positive control test per class (fires today, pinned)
- [ ] measured FP pass over the live 3-scope corpus before shipping (no new FP findings)

## Approval log
