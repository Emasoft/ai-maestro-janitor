---
trdd-id: Q8ZT5NW3
title: The apply audit line reports updated for a ruleset a no-op PUT did not change
column: ai_review
created: 2026-08-21T03:57:42+0200
updated: 2026-08-21T08:34:07+0200
implementation-commits: [342f3f6f]
current-owner: janitor-main-session
task-type: bugfix
priority: normal
approval-tier: 0
scope: project
external-refs: [TRDD-DD0M4QL7]
npt: []
eht: []
---

# `updated` means "a PUT was issued", not "the ruleset changed"

## Measured 2026-08-21

`branch_protection_lib.py:719` sets `verb = "updated"` whenever the applier PUTs an EXISTING
ruleset — regardless of whether the payload differed from what was already there. An identical
PUT is a server-side no-op: GitHub does not move `updated_at`.

The audit line for this repo's 2026-08-20 apply reads:

    2026-08-20T08:21:58+0200  OK  Emasoft/ai-maestro-janitor  main
      baseline-history-protect=updated id=17286452; baseline-pr-and-checks=updated …;
      baseline-tag-protect=updated …

Three "updated". The live API says exactly ONE changed:

| ruleset | `updated_at` | who |
|---|---|---|
| baseline-history-protect | 2026-08-20T01:50:54 | the ai-maestro hub's fleet apply |
| baseline-pr-and-checks | 2026-08-20T08:21:55 | **this applier** |
| baseline-tag-protect | 2026-06-11T11:06:07 | neither — untouched since June |

**Why it matters enough to file.** This log was cited as EVIDENCE — by me, to close
TRDD-DD0M4QL7's unattended-repair box, and by the hub when auditing the fleet. The closure
survives (the drift line named `baseline-pr-and-checks` specifically and the API confirms that
one changed at 08:21:55), but an audit line that cannot distinguish "I changed this" from "I
sent a PUT that changed nothing" is weak evidence for exactly the question an audit log exists
to answer. It also inflates any future "N rulesets repaired" count by the number of no-ops.

## What

Report the EFFECT, not the action. Cheapest honest form: compare the response's `updated_at`
(or the pre/post payload) and emit `updated` / `unchanged` accordingly — the applier already
holds the existing ruleset for the id lookup, so the before-state is in hand.

Do NOT drop the line to silence on a no-op: "checked and already correct" is the trace
TRDD-DD0M4QL7 added on purpose, and losing it re-creates the silent-no-op ambiguity that card
exists to end.

## Acceptance

- [x] the audit line distinguishes `updated` from `unchanged` per ruleset — `by_name` now
      carries `(id, updated_at)`, and `_post_or_patch_ruleset` compares the PUT response's
      `updated_at` against the one the list returned. **Verified against the live API that the
      list endpoint actually carries the field** (`updated_at: 2026-08-20T01:50:54.680+02:00`
      on this repo's `baseline-history-protect`) — the comparison is real, not theoretical.
- [x] a no-op apply still logs one honest line (no regression of DD0M4QL7's anti-silence trace)
      — pinned by `test_apply_reports_unchanged_when_the_put_moved_nothing`, which asserts the
      `[guard] applied …` announcement is STILL present alongside `unchanged id=42`.
- [x] a test pins both: a changed ruleset reports `updated`, an identical PUT reports
      `unchanged` — plus a THIRD state the card did not ask for and the code needs:
      **`put-unverified`**, when either side lacks `updated_at`. Folding "cannot tell" into
      "updated" would be the same defect in a new place: someone grepping the audit log for
      repairs must not count a guess. Three tests, one per state.
- [x] pytest, ruff, mypy, pyright clean — 116 passed across the four branch-protection /
      github-config suites; ruff clean; mypy clean over 486 files; pyright 0 errors.

No consumer parses the verb (swept `scripts/` — `_audit_append` writes the summary verbatim),
so widening the vocabulary breaks nothing downstream.

## Self-review (testing → ai_review, 2026-08-21T08:34+0200)

**Test gate PASSED:** full suite 15,716 passed / 0 failed (9m53s) — +2 over the pre-change
count, which are this card's own new tests. ruff, mypy (486 files) and pyright clean.

**What a reviewer should push on:**

1. **`put-unverified` is a vocabulary I added, not one the card asked for.** The card asked for
   two states. I added a third because the code genuinely has three, and folding "cannot tell"
   into "updated" is this card's own defect one level down. If you'd rather the log kept a
   two-word vocabulary, the alternative is to treat a missing timestamp as a hard error rather
   than a third word — but silently guessing is not on the table.
2. **The comparison trusts GitHub's `updated_at` semantics** — specifically that an identical
   PUT does not move it. That is the card's premise and it matches the observed data (three
   PUTs, one moved timestamp), but it is an API behaviour, not a contract I can pin in a test.
   The live-API check confirms the FIELD is present; it does not prove GitHub will never touch
   it on a no-op.
3. **No live re-verification of a real apply.** The three states are proven against the gh stub.
   A real apply against a real repo would be the stronger evidence, and it is not worth causing
   a ruleset write just to watch the log line.

**Not moved to `complete`:** `ai_review → human_review → complete` is the USER's gate.
