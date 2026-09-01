---
trdd-id: 4GQ94FNJ
title: The scope-leak detector is blind to publish-globally, so a published page's leak reads as a one-project problem
column: complete
created: 2026-08-22T16:20:25+0200
updated: 2026-09-01T22:02:00+0200
current-owner: janitor-main-session
task-type: bugfix
severity: medium
scope: project
approval-tier: 0
release-via: publish
relevant-rules: []
npt: []
eht: []
external-refs: [52]
implementation-commits: [9818c205]
---

# `memory-scope-leak` must know a page is published — and must refuse an identity key beside the flag

## ⏵ STATE — READ THIS FIRST ON RESUME

**Found 2026-08-22 by a `[stale-stash]` drift line, not by reading the board.** `stash@{39}`
(59 days old, `wip-52-publish-globally (TRDD-079bed04 + scope-leak tests)`) holds **5 tests, +131
lines, on `tests/test_memory_scope_leak.py`** that specify behaviour the detector has never had.
Verified, not inferred:

| claim | evidence |
|---|---|
| the 5 tests exist nowhere in the tree today | all 5 names `MISSING` from `tests/test_memory_scope_leak.py` (535 lines) |
| the detector has **zero** publish-globally awareness | `grep -n "published-identity-leak\|publish-globally\|PUBLISHED" scripts/detectors/memory-scope-leak.py` → 0 hits |
| the current tests cover none of it | `grep -n "publish.globally\|publish_globally" tests/test_memory_scope_leak.py` → 0 hits |
| the driving issue is still open, on a repo we own | `gh issue view 52` → `state: OPEN` |
| `TRDD-079bed04` (cited in the stash message) does not exist | `find design ~/.claude/.../design -iname '*079bed04*'` → nothing. A v1-format id; the card was never filed. **This TRDD replaces it.** |

**The stash is NOT to be popped or dropped.** USER decision #10 (never delete backups) makes
`git stash drop` forbidden here, and the patch no longer applies anyway (the file grew past the
`@@ -246` hunk). Port the intent by hand; leave `stash@{39}` exactly where it is.

## Why it matters now

`publish-globally: true` is live, not speculative: memgrep normalizes the field and its USER-root
symlink on **every** write, and pages in this repo already carry it (`fba278d4` stamped them
deliberately). A published PROJECT page is therefore recalled from **every project on the
machine**.

So the two gaps are:

1. **Blast radius is misreported.** The proposal's remedy line is hardcoded `demote to LOCAL
   scope`. For a published page that advice is wrong — the leak is already reachable fleet-wide,
   and demoting one project's copy does not retract it. A reader following the proposal literally
   under-reacts to the widest case.
2. **The privacy invariant is unenforced.** Only the bare boolean may be committed. A
   `published-slug:` (or any `published-*` identity key) beside the flag, or a non-boolean
   `publish-globally:` VALUE, publishes a private project name into a pushed file — a leak the
   four existing catalogues cannot see, because it is a *frontmatter key*, not a secret shape.

## What

In `scripts/detectors/memory-scope-leak.py`:

1. `_scan_page` gains a frontmatter check emitting `published-identity-leak` when
   `publish-globally`'s value is not a bare boolean, or a forbidden `published-*` identity key
   sits in the same frontmatter.
2. A page that is `publish-globally: true` **and** already has ≥1 other finding gains the marker
   class `published`. The marker must **never** be a finding on its own — a clean published page
   is not a defect, and flagging one would nag about an intentional, approved act.
3. `_render_proposal` branches on that marker: `PUBLISHED` + the `publish-globally` wording and a
   remedy that says demotion is insufficient, instead of the plain LOCAL line.

Port the stash's 5 tests to the current file.

## Acceptance

- [x] `publish-globally: true` + clean body ⇒ **no** finding — `test_published_clean_page_not_flagged`
- [x] `publish-globally: false` + clean body ⇒ **no** finding — `test_publish_false_clean_page_not_flagged`
- [x] `publish-globally: true` + a content leak ⇒ flagged, and the proposal carries `PUBLISHED`
      and `publish-globally`, not the bare demote-to-LOCAL line —
      `test_published_page_leak_is_escalated`. Strengthened past the stashed original: it also
      asserts the escalation **replaces** the stock advice on that line rather than sitting
      beside it, and that the `published` marker never appears as a leak class.
- [x] a `published-*` identity key beside the flag ⇒ `published-identity-leak`, even with a clean
      body — `test_published_identity_key_flagged`
- [x] a non-boolean `publish-globally:` value ⇒ `published-identity-leak` —
      `test_published_nonboolean_value_flagged`, which also asserts `PUBLISHED` does **not**
      fire (the flag never parsed, so nothing is symlinked and there is no wider blast radius)
- [x] `stash@{39}` still present afterwards — `git stash list | wc -l` = **47** before and after,
      `stash@{39}` matched
- [x] gate green: 27/27 in the module, `ruff check scripts tests` clean, `mypy scripts/` clean
      (489 files); the full-suite result is analysed under **Gate** below — 10 red, all of them
      pre-existing parallel-load flakes, none in this card's blast radius
- [x] #52 answered with this card id — posted 2026-09-01 after the 3.4.2 publish that ships
      it (issuecomment-5499620080)

## Falsification — both new behaviours were proven killable

A passing test proves nothing until it has been made to fail, and a mutation that never applies
looks exactly like a pass. Each probe's presence was confirmed with `grep -c` **before** the run:

| probe | mutation | result |
|---|---|---|
| P1 | `if published and labels:` → `… and False` | **only** `test_published_page_leak_is_escalated` failed (1 failed, 26 passed) |
| P2 | `startswith("published-")` → `startswith("published-ZZZ")` | **only** `test_published_identity_key_flagged` failed (1 failed, 26 passed) |

Both reverted; `grep -c "MUTATION PROBE"` = 0; 27/27 green after.

P2 failing exactly ONE test is itself the useful signal — the non-boolean case has its own
independent path (the value check), so it correctly survived a mutation that only disabled the
key check.

## Gate — 10 red, and NOT this card's

`pytest tests/ -x -q --tb=short -n auto --dist loadgroup` → **10 failed, 8313 passed** (12:55).
`-x` under xdist interrupts the workers, which is why the collected total is short of a clean
run's; it is not a collection error.

**Read the exit status, not the notification.** The background wrapper ended in `tail`, so the
harness reported *"exit code 0"* while the suite's own `exit=2` sat in the log. A pipeline's
status is the LAST command's — believing the wrapper here would have shipped a red gate as green.

Re-running the five files serially (the rule: a REGRESSION fails the same tests every run, a
flake moves) cleared **9 of 10**. The survivor,
`test_memory_librarian.py::TestMemoryLibrarianReindex::test_reindex_failure_is_tolerated`,
then **passed in isolation** — so it is an intra-file interaction, not a regression either.

| file | failures | serial re-run |
|---|---|---|
| `test_gh_reply_watch.py` | 4 | all pass |
| `test_marketplace_refresh_scoped.py` | 2 | all pass |
| `test_memory_librarian.py` | 2 | 1 pass, 1 fail → **passes alone** |
| `test_github_issues_watch.py` | 1 | pass |
| `test_launchd_keepalive.py` | 1 | pass |

None of the five touches `memory-scope-leak`. What they share is machine-global state —
`gh_reply_watch`'s cross-project floor, the marketplace refresh stamps, the plugin DATA dir —
which this session's own heartbeat mutates *while the suite runs*. That is the known class on
[[janitor-keepalive-test-isolation-fsevents]], not a new mechanism, so it is recorded here and
not re-minted as memory. Worth its own card if it recurs.

## Notes and lessons learned

## Approval log

- 2026-09-01T22:02:00+0200 — APPROVED human_review → complete by the session acting under the
  USER's delegated review authority ("i've put you in charge", 2026-09-01). All boxes done: the
  detector change shipped in 3.4.2 (published tonight, tag verified first-hand); the last box
  (answer #52) closed by issuecomment-5499620080. The card's own gate evidence (27/27 module,
  ruff/mypy clean, mutation probes killable) stands; the 10 "pre-existing parallel-load flakes"
  it recorded were resolved separately (suite green at the 3.4.2 publish gate, 15,952 passed).
