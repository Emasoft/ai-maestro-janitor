---
trdd-id: UWBXNJ76
title: memory-scope-leak misses bare hostnames and sub-24-char high-entropy ids
column: complete
created: 2026-08-18T20:14:25+0200
updated: 2026-08-21T03:55:00+0200
implementation-commits: [07bf1d16]
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

## ⏵ STATE — 2026-08-19: measured; entropy gap = MEASURED REFUSAL, hostname gap = suffix-widen only

Grounded in code + a live 3-scope measurement this session (still `todo`, not started editing
the detector). Read this before touching a regex.

**Machinery (verified):** `memory-scope-leak.py::main()` self-scan-guards the janitor's own repo
(`is_self_scan_target()` → 0) and only scans PROJECT scope, so any FP measurement must call
`_scan_page` directly over all three roots. A reusable harness that does exactly that, plus an
entropy-floor sweep, are in the session scratchpad (throwaway — re-create from this block, not
committed): `scopeleak_fp_probe.py` (per-page class labels, 3 roots → JSON baseline) and
`entropy_floor_sweep.py` (offending tokens at floors 24/20/16).

**Live-corpus baseline (this session):** PROJECT 1 page fires `credential`; LOCAL 3 pages
(`credential`/`high-entropy secret`/`pii:us_ssn`); USER 10 pages (7 on the existing
`machine-host` `.local`/`.lan` rule — legitimate for USER scope). These are the pre-change
firings; any NEW firing after a change is an FP candidate to diff against this.

**Gap 2 (entropy floor 24 → lower) — DECISION: MEASURED REFUSAL, keep `_ENTROPY_MIN_LEN = 24`.**
Sweeping the floor 24→20→16 across all 3 roots adds **zero** new convictions; the only two
tokens that convict at ANY floor are already-present FPs ≥73 chars (descriptive `snake_case`
strings, not secrets: `GROUP_B_immortal-janitor_commit_…`, `baseline-history-protect_deletion_…`).
So the live corpus is too clean to exhibit either the FP COST or the BENEFIT of a lower floor —
it lacks the 16–23-char base64-ish shapes entirely. A "no new FP on live corpus" pass would
therefore FALSELY green-light a floor drop that is known-dangerous on real-world content
(git short hashes, encoded ids, base64 of ~12 bytes = 16 chars). Refuse the pure-floor drop; the
region-aware path already catches short ids that ALSO carry a known secret shape/prefix, which is
the only safe way to convict at <24. (This is the parent's own recurring base64-floor-trap lesson.)

**Gap 1 (hostname) — SAFE WIN = widen the suffix-anchored internal-TLD set only.** `_LOCAL_HOSTNAME`
(`private_path_patterns.py`) anchors to `(?:local|lan)`; widen to also include the conventional
internal TLDs `internal|intranet|corp|home` (still suffix-anchored → a token ending `.corp` in
ordinary prose is rare, low FP). Bare SUFFIXLESS hostnames (`emasofts-mac-mini`) stay
**OUT of scope** (matching any hyphenated token is the FP minefield the card itself flags); the
one corroborating position that matters — `user@bare-host` — is ALREADY convicted by
`_SSH_USER_HOST`. Record this in/out split in the detector docstring per acceptance box 1.

**NEXT ACTION (one focused pull, no free-pool needed):** (1) add `internal|intranet|corp|home` to
`_LOCAL_HOSTNAME`; (2) docstring class enumeration (in: `.local/.lan/.internal/.intranet/.corp/.home`
suffixes + `user@host` ssh position; out: bare suffixless token, with rationale + the entropy
refusal); (3) one positive-control test per in-scope class (`host.corp` fires, `host.internal`
fires, `deploy@build-box` fires) pinned in the suite; (4) re-run `scopeleak_fp_probe.py`, diff vs
the baseline above → assert no NEW firing on PROJECT + the benign LOCAL/USER pages; (5) run
`uv run pytest` + `uv run ruff check` + `uv run mypy scripts/`. Then `todo → dev → testing`.

## Why (hub-verified P3, ledgered in ai-maestro TRDD-BRRJK57P)

Two enumerable coverage gaps in the PROJECT-scope privacy gate (which, since AZ6QRK0D's
verdict, is the SOLE enforcement point for publish-globally pages — raising its stakes):

1. `private_path_patterns.py:232-233` (`_LOCAL_HOSTNAME`) requires a dotted suffix —
   `(?:local|lan|internal|intranet|corp|home)` — so a bare hostname (`emasofts-mac-mini`, an
   mDNS name without suffix, an internal DNS name on another TLD) passes.

   *Citation repaired 2026-08-21.* It read `:215` until the ai-maestro hub tried to re-derive
   it and found that line had ROTTED onto a comment; the regex had moved to `:232-233`. A
   line-number citation decays silently every time the file above it changes, and the cost is
   paid by whoever next tries to verify the claim — the hub lost a session to a rotted
   citation this week. When a citation must survive, anchor it to the SYMBOL (`_LOCAL_HOSTNAME`)
   and treat the line number as a hint, which is what this bullet now does.
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

- [x] class enumeration recorded in the detector docstring (in-scope vs out-of-scope shapes) —
      `_LOCAL_HOSTNAME` docstring, commit `07bf1d16`.
- [x] one positive control test per class (fires today, pinned) — `test_corp_hostname_flagged`,
      `test_internal_hostname_flagged`, `test_bare_hostname_still_flagged_via_ssh_user_host`.
- [x] measured FP pass over the live 3-scope corpus before shipping (no new FP findings) —
      3-scope `_scan_page` diff pre/post = byte-identical (0 new firings), verified twice (worker
      + main). A `Path.home()` FP that widening WOULD have introduced was caught in measurement
      and fixed with the `(?!\()` lookahead before shipping. `_ENTROPY_MIN_LEN` unchanged
      (measured refusal). 57 passed, ruff + mypy clean.

## Approval log
