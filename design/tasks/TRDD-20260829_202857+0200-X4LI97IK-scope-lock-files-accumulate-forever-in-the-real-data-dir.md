---
trdd-id: X4LI97IK
title: Per-scope lock files accumulate forever in the real DATA dir and nothing names the producer
column: backburner
blocked-by: []
created: 2026-08-29T20:28:57+0200
updated: 2026-08-29T20:52:00+0200
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

## The measurement (2026-08-29)

`~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/` holds **1,137 lock
files, 1,128 of them `memory-maint-<16hex>.lock`** against 9 stable named locks. Every one is
**zero bytes**. Age spread: 18 from June, 12 from July, **1,107 from August** — 165 created
today, 11 in the last three hours.

`memory_txn._scope_lock_path` keys the lock on `sha256(resolve(scope_root))[:16]`, which is
*correct* and deliberately mirrors memgrep's Rust side (TRDD-7YHT3FNK P3). One hash = one scope
root. So **1,128 distinct scope roots have been locked on this machine.**

That is not 1,128 projects. ~~It is test runs~~ — **FALSIFIED the same evening; see Attribution.
The full suite adds ZERO locks.** The producer is in NORMAL OPERATION and is still unnamed.

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
   attribution here goes, so a component writing 165 orphan locks a day looks exactly like
   healthy operation and nothing anywhere names it.

## Attribution — step 1 partly done the same evening, and it FALSIFIED the obvious guess

**Measured, and solid:** hashing every scope root that exists on this machine (214 of them —
each `~/.claude/projects/<slug>/memory` and its `wikimem/`, the USER root, this repo's PROJECT
root) and intersecting with the 1,128 lock hashes gives **29 matches. 1,099 (97.4%) correspond
to no scope root that exists.** So the locks are overwhelmingly for roots that are gone or were
never real — that part is not in doubt.

**But the "it is the tests" guess did NOT survive its first probe.** Snapshotting the lock count
around `pytest -k "memory_txn or memory_lint_gate"` (68 tests, the ones that actually drive the
transaction core): **delta 0.** Those tests leak nothing.

So the producer is STILL UNIDENTIFIED, and this section exists so nobody re-runs that probe. What
is known: 97.4% orphan hashes, ~165/day on an active day, and the two most obviously suspicious
test modules are innocent. What is NOT known: whether the rest of the suite leaks, or whether the
daemon/heartbeat manufactures ephemeral roots of its own — the per-hour histogram for one day
(10, 42, 11, 22, 34, 35, 11) is bursty rather than heartbeat-regular, which leans toward
batch runs but does not settle it.

**FULL-SUITE PROBE RUN, and it settles it: delta 0.** `uv run pytest -q` end to end — 15,911
passed, 1 skipped, 9m53s — added **ZERO** lock files. **The test suite is not the producer.**
That was the whole hypothesis this card was filed on, and it is dead.

**So the producer is something in NORMAL OPERATION** — the daemon, the heartbeat, or a memory
agent manufacturing ~165 ephemeral scope roots on an active day. That is a more interesting
finding than the one the card started with, and it is unidentified.

**Next probe:** instrument `_scope_lock_path` to log the root it hashed, then read one day of it.
Do not guess again — this card has already burned two guesses, and each looked obvious.

**Caveat on the 97.4%, so nobody over-trusts it:** the 214 roots I probed were every
`~/.claude/projects/<slug>/memory` (+ its `wikimem/`), the USER root, and **only THIS repo's**
PROJECT root. The janitor runs in every project on this machine, so each repo contributes a
PROJECT root I did not enumerate. That could account for ~100 more matches, not 1,099 — the
conclusion survives, but the number is a floor, not a measurement.

## Scope

1. **Attribute the hashes.** ~~Are the roots tmp paths or real ones?~~ **Half done — see the
   attribution section: 1,099 of 1,128 match no existing root, and the TEST hypothesis is dead
   (full suite, delta 0).** Remaining: instrument `_scope_lock_path` to log the root it hashed.
2. ~~**If tests: give them their own state dir.**~~ **VOID — the tests are innocent.** Whatever
   the producer turns out to be, the fix is at ITS layer: either it should not be minting scope
   roots that never persist, or the lock for an ephemeral root belongs beside that root rather
   than in the machine-wide dir.
3. **Only then consider reaping.** A lock file cannot be deleted safely while a holder has it
   flocked, and a reaper racing a live commit is far worse than 1,128 empty files. If one is
   built, it deletes only locks whose flock can be acquired AND whose mtime is old.

## What NOT to do

- **Do not bulk-delete the lock dir.** RULE 0 aside, a delete racing a live `flock` breaks the
  cross-language exclusion this lock exists to provide (TRDD-7YHT3FNK).
- **Do not "fix" the write-guard by removing its live-actor exemption.** It is correct, and the
  full-suite probe PROVED it correct — these are live-actor writes. Making it louder would only
  add noise to a verdict that was already right.
- **Do not guess a third producer.** Two guesses, both obvious, both wrong. Instrument
  `_scope_lock_path` and read what it logs.

## Acceptance

- [x] ~~The provenance is established (test tmp roots vs real project roots)~~ — PARTIAL: the
      TEST hypothesis is decisively dead (full suite, delta 0). 1,099/1,128 match no existing
      root. The actual producer is still unnamed and is in normal operation.
- [ ] The producer is NAMED, by instrumenting `_scope_lock_path` — not by a third guess.
- [x] ~~No suite run adds a lock file to the real global-state dir~~ — already TRUE, measured:
      full suite, delta 0. Nothing to fix here.
- [ ] Growth is bounded — the count stops tracking "scope roots ever seen".

## Notes and lessons learned

- 2026-08-29 — **I read a guard's escape hatch as a blind spot, and the guard was simply RIGHT.**
  The write-guard said "a LIVE janitor actor, not a test leak"; I filed that as an exemption
  swallowing a real leak, and wrote a lesson to that effect. The full-suite probe then proved the
  guard correct: these ARE live-actor writes. **A check whose verdict you distrust deserves a
  probe before it deserves a lesson** — I had the probe available the whole time and wrote the
  conclusion first. What survives is smaller and true: "a live actor did it" is the CEILING of
  attribution here, so a component minting 165 orphan locks a day is indistinguishable from
  healthy operation, and nothing anywhere names it.
- 2026-08-29 — **Found while investigating something else entirely** (an agent-dispatch marker
  that could not run). The count was visible in one `ls`, and nobody had looked because nothing
  had ever failed. Zero-byte files raise no alarm anywhere — no disk pressure, no error, no test.
  A defect whose only symptom is a number nobody reads will not be found by waiting.
