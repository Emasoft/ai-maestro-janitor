---
trdd-id: X4LI97IK
title: scope_root_for falls back to the page's parent dir so the write lock key is unbounded
column: complete
blocked-by: []
implementation-commits: [d27c718f]
created: 2026-08-29T20:28:57+0200
updated: 2026-08-29T22:05:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 5
severity: LOW
effort: S
min-approval-requirement: none
task-type: bugfix
labels: [memory, state, tests, isolation, write-guard]
release-via: publish
test-requirements: [unit]
---

# TRDD-X4LI97IK — 1,128 scope-lock files, +165 in one day, in the real plugin DATA dir

## ⏵ FIXED 2026-08-29 — commit `d27c718f`, option 2 as recommended

`lock_path_for` now maps any root whose basename is not `memory` onto ONE shared sentinel,
`memory-maint-out-of-scope.lock` — deliberately not hex-shaped, so it can never alias a real
`<sha16>` key. Applied to `memory_txn._scope_lock_path` in the SAME commit (TRDD-7YHT3FNK).

**`scope_root_for` was deliberately NOT changed**, against this card's own "where the fix belongs"
paragraph. Reading the call sites is what changed the answer: three of its nine callers
(`mem_split.rs:730`, `mem_delete.rs:120/178/432`) use the returned path as a REAL scope root for
reindex/lineage/delete, not as a lock key. Handing them a sentinel would have broken them. The
lock key is the only thing that needed bounding, so the fix went where the key is made.

**The half this card did not anticipate:** `acquire_two` compared SCOPE ROOTS to decide whether one
lock covers both pages. Once two distinct roots can share a lock, that test takes the same flock
twice from one process — a self-deadlock that surfaces only as a `MEMGREP_LOCK_TIMEOUT_S` timeout,
never as a wrong answer. It now compares lock paths. Anyone porting this fix elsewhere must carry
that second edit too.

Both regression tests were confirmed to FAIL without the guard (disabled behind `#[cfg(any())]`,
suite re-run, both FAILED, restored). One pre-existing test had to be repaired to stay meaningful:
`test_scope_lock_path_resolves_symlinks` used `real-memory`/`link-memory`, whose basenames are not
`memory`, so under the new rule it would have compared two sentinels and passed no matter what
`resolve()` did.

Verified end to end with `JANITOR_GLOBAL_STATE_DIR` redirected: two writes to pages in two
different out-of-scope directories minted exactly ONE lock file. The 1,128 existing orphans are
NOT reaped — see step 4, unchanged.

## The measurement (2026-08-29)

`~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/` holds **1,137 lock
files, 1,128 of them `memory-maint-<16hex>.lock`** against 9 stable named locks. Every one is
**zero bytes**. Age spread: 18 from June, 12 from July, **1,107 from August** — 165 created
today, 11 in the last three hours.

`memory_txn._scope_lock_path` keys the lock on `sha256(resolve(scope_root))[:16]`, which is
*correct* and deliberately mirrors memgrep's Rust side (TRDD-7YHT3FNK P3). One hash = one scope
root. So **1,128 distinct scope roots have been locked on this machine.**

That is not 1,128 projects, and it is not test runs. **The producer is
`write_gate.rs::scope_root_for`'s fallback — identified and proven below.**

## Why it is worth a card despite being harmless in bytes

Zero bytes each, so this is not a disk-space problem and MUST NOT be treated as one. Two real
costs:

1. **Unbounded growth**, proportional to "distinct scope roots ever seen", with no reaper. Inodes
   and directory-listing time only, but nothing bounds it.
2. **Nothing attributes writes in this dir.** The write-guard reports mutations under the plugin
   DATA dir and then excuses them: *"attributed to a LIVE janitor actor (daemon pid …) — not a
   test leak. These paths are shared."*

   **Read this the right way round now that the test hypothesis is dead:** the guard's verdict
   was CORRECT — these really are live-actor writes, not test leaks. It was right and I did not
   believe it. The cost is not a missed leak; it is that "a live actor did it" is as far as any
   attribution here goes, so the component writing 165 orphan locks a day looked exactly like
   healthy operation — and stayed unnamed until someone read the resolver.

## Probes already run — do not repeat these

| probe | result |
|---|---|
| hash every scope root that EXISTS on this machine (214) and intersect | **29 match, 1,099 (97.4%) match nothing** — solid, and the shape the fix must explain |
| `pytest -k "memory_txn or memory_lint_gate"` (68 tests), lock count before/after | delta **0** |
| the FULL suite, `uv run pytest -q` (15,911 passed, 9m53s) | delta **0** — the test suite is not the producer |
| `memgrep lint` on an out-of-scope page | delta **0** — lint takes no WRITE lock and looks innocent |

Two hypotheses died here — "it is the test suite" (the premise this card was filed on) and,
before that, "it is the daemon minting ephemeral roots". Both looked obvious. What finally named
the producer was READING the resolver, not more measuring.

**Caveat on the 97.4%, so nobody over-trusts it:** the 214 roots probed were every
`~/.claude/projects/<slug>/memory` (+ its `wikimem/`), the USER root, and **only THIS repo's**
PROJECT root. The janitor runs in every project here, so each repo contributes a PROJECT root I
did not enumerate — worth ~100 more matches, not 1,099. A floor, not a measurement.

## ✅ PRODUCER IDENTIFIED — `scope_root_for`'s fallback, proven not guessed (2026-08-29)

**`write_gate.rs::scope_root_for` walks up looking for a directory literally named `memory`, and
when it finds none it FALLS BACK to the page's own parent directory.** That fallback becomes the
lock key. So every memgrep WRITE verb aimed at a page outside a `…/memory/…` tree mints a lock
named for *that directory* — and the key is unbounded by construction, not by accident.

Proven end to end, with `JANITOR_GLOBAL_STATE_DIR` redirected so the probe added nothing to the
real pile:

```
# one atom written to a page in a fresh tmp dir, NOT under any `memory/` ancestor
$ JANITOR_GLOBAL_STATE_DIR=$S memgrep new-mem-atom --page $D/notmemory/probe.md …
$ ls $S            → memory-maint-c676f3395ef29bee.lock
$ sha256($D/notmemory)[:16] → c676f3395ef29bee        # exact match
```

It accounts for the observed shape exactly: **29 hashes match real `…/memory` scope roots; 1,099
match nothing** — the 1,099 are fallback parents, one per directory ever written to outside a
memory tree. It also explains the delta-0 suite: the tests do not drive the memgrep BINARY's
write verbs against scratch paths, which is why both earlier hypotheses missed.

**Note the earlier `lint` probe returned delta 0 too** — read-only, or an autofix with nothing to
fix, takes no write lock. Only a real write verb reproduces it; a lint alone will look innocent.

### Where the fix belongs

In `scope_root_for`, not in a reaper and not in the lock. A page with no `memory` ancestor **is
not in any scope**, so a per-directory lock buys no mutual exclusion anyone wants — it just names
a file after a directory nobody will revisit. Options, in preference order:

1. **No scope ⇒ no machine-wide lock.** Lock beside the page (or not at all), so the global dir
   only ever holds real scope roots. Needs the Python side (`memory_txn._scope_lock_path`) to
   agree, or the two languages stop excluding each other — the corruption class TRDD-7YHT3FNK
   exists to prevent. **Change both or neither.**
2. **One shared out-of-scope lock.** Bounded and trivially parity-safe, at the cost of
   serialising unrelated out-of-scope writes — which are rare by definition.

Option 2 is the lazy correct one unless someone shows the contention matters.

## Scope

1. ~~**Attribute the hashes.**~~ **DONE — the producer is named and proven; see above.**
2. ~~**If tests: give them their own state dir.**~~ **VOID — the tests are innocent.**
3. **Fix `scope_root_for`** per "Where the fix belongs" — option 2 (one shared out-of-scope lock)
   unless someone shows the contention matters. **Change the Rust and Python sides together or
   neither**, or they stop excluding each other (TRDD-7YHT3FNK).
4. **Only then consider reaping.** A lock file cannot be deleted safely while a holder has it
   flocked, and a reaper racing a live commit is far worse than 1,128 empty files. If one is
   built, it deletes only locks whose flock can be acquired AND whose mtime is old.

## What NOT to do

- **Do not bulk-delete the lock dir.** RULE 0 aside, a delete racing a live `flock` breaks the
  cross-language exclusion this lock exists to provide (TRDD-7YHT3FNK).
- **Do not "fix" the write-guard by removing its live-actor exemption.** It is correct, and the
  full-suite probe PROVED it correct — these are live-actor writes. Making it louder would only
  add noise to a verdict that was already right.
- **Do not probe with `lint` alone.** It takes no write lock, so it returns delta 0 and looks
  innocent. Only a real WRITE verb reproduces this.

## Acceptance

- [x] The provenance is established: 1,099/1,128 match no existing root, the test hypothesis is
      dead (full suite, delta 0), and the producer is NAMED and proven — `scope_root_for`'s
      no-memory-ancestor fallback.
- [x] The producer is NAMED: `scope_root_for`'s no-memory-ancestor fallback. Proven by probe,
      not by instrumentation — reading the resolver was cheaper than logging it.
- [x] An out-of-scope page no longer mints a per-directory machine-wide lock, and the Rust
      and Python sides still agree byte-for-byte (TRDD-7YHT3FNK parity) — the Python test reads
      the sentinel back OUT of `write_gate.rs` rather than re-declaring the literal, so a drift
      fails the suite instead of being discovered by a corrupted page.
- [x] ~~No suite run adds a lock file to the real global-state dir~~ — already TRUE, measured:
      full suite, delta 0. Nothing to fix here.
- [x] Growth is bounded — the count stops tracking "scope roots ever seen". It is now exactly
      "real scope roots on this machine, plus one".

## Notes and lessons learned

- 2026-08-29 — **I read a guard's escape hatch as a blind spot, and the guard was simply RIGHT.**
  The write-guard said "a LIVE janitor actor, not a test leak"; I filed that as an exemption
  swallowing a real leak, and wrote a lesson to that effect. The full-suite probe then proved the
  guard correct: these ARE live-actor writes. **A check whose verdict you distrust deserves a
  probe before it deserves a lesson** — I had the probe available the whole time and wrote the
  conclusion first. What survives is smaller and true: "a live actor did it" is the CEILING of
  attribution here, so a component minting 165 orphan locks a day is indistinguishable from
  healthy operation — which is why it went unnamed for months.
- 2026-08-29 — **The card named the right fix and the wrong place for it, and only reading the
  CALL SITES caught that.** "Where the fix belongs: in `scope_root_for`" was written from the
  resolver alone; nine callers later, three of them use its return value as a real scope root, so
  editing it would have broken reindex, lineage and delete to fix a lock. **A function's correct
  behaviour is not decidable from its own body — grep every caller before changing what it
  returns.** The same reading turned up the `acquire_two` self-deadlock, which no measurement in
  this card would ever have surfaced: it fails as a timeout, and timeouts read as contention.
- 2026-08-29 — **Found while investigating something else entirely** (an agent-dispatch marker
  that could not run). The count was visible in one `ls`, and nobody had looked because nothing
  had ever failed. Zero-byte files raise no alarm anywhere — no disk pressure, no error, no test.
  A defect whose only symptom is a number nobody reads will not be found by waiting.
