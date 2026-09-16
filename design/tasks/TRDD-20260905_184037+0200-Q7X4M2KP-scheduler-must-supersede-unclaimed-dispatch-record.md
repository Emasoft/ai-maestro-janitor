---
trdd-id: Q7X4M2KP
title: Scheduler must supersede its own unclaimed dispatch record for the same scope root and intervention instead of stacking a new one
column: todo
created: 2026-09-05T18:40:37+0200
updated: 2026-09-16T12:33:54+0200
current-owner: main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
npt: []
eht: []
external-refs: [github:Emasoft/ai-maestro-janitor#300]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-05T21:15

A previous worker died mid-work leaving all the code and tests uncommitted but essentially
complete. This session (takeover) verified and finished it:

- `_supersede_older_unclaimed` + `_SUPERSEDED_PREFIX` in `scripts/detectors/memory-maintenance.py`
  were already implemented (rename-based, race-safe against `claim_one`'s `except OSError`).
- `_prune_old_pending` already walks the 3-prefix tuple including `_SUPERSEDED_PREFIX`.
- All 4 required tests already existed in `tests/test_memory_maintenance.py`:
  `test_write_pending_supersedes_older_unclaimed_same_key`,
  `test_write_pending_leaves_claimed_and_other_keys_alone`,
  `test_superseded_prefix_is_pruned_under_keep_cap`, plus the legacy-slot rewrite test.
- The peer-claim race test already existed in `tests/test_memory_dispatch_claim.py`:
  `test_claim_one_skips_a_record_superseded_under_it`.

Nothing left to write for this card. Verification below.

**2026-09-05T21:52** — code and tests committed in af6340a5; moved to `testing`. The only
remaining acceptance box is the full-suite run at the publish gate (deferred per the
Gatekeeper-flake finding above, unrelated to this card's files).

**Verification run (this session):**
```
uv run pytest tests/test_memory_maintenance.py tests/test_memory_dispatch_claim.py -q -p no:cacheprovider
→ 76 passed
uv run pytest tests/test_memory_maintenance.py -k supersede -q -p no:cacheprovider
→ passes (subset of the above 76)
uv run ruff check scripts/detectors/memory-maintenance.py tests/test_memory_maintenance.py tests/test_memory_dispatch_claim.py → All checks passed!
uv run mypy scripts/ --ignore-missing-imports → Success: no issues found in 504 source files
uvx --with pyright pyright <same files> → 0 errors, 0 warnings, 0 informations
```

**Full-suite box left OPEN per orchestrator instruction** (not run this session — a coordinator
run separately found `tests/test_dispatch_defang.py::test_stale_marker_gate_is_scoped_to_memory_maintenance`
flaky when run alongside `test_memory_maintenance.py`. INVESTIGATED and diagnosed: this is a
**macOS Gatekeeper/quarantine exec-scan delay** on a freshly `chmod +x`'d script written into a
pytest `tmp_path` — reproduced with a bare, unrelated `/tmp/t1.py` (`print(...)` only, no repo
code): direct execution took 32s wall-clock vs 0.03s user+system CPU time. The test's detector
subprocess (spawned via `subprocess.run(..., timeout=5)`) times out waiting on that OS-level scan
and returns empty output. Verified this is NOT caused by anything in the files this card touches:
reverting `scripts/detectors/memory-maintenance.py` alone made one run pass, but re-running the
SAME combination minutes later reproduced the failure again — genuinely flaky, not a deterministic
shared-state leak between the touched files. No fix applied — `tests/test_dispatch_defang.py` is
out of this card's scope (owned by TRDD-LDSCQ0NU) and the root cause is an OS security-scan race,
not a code defect in either file.

**2026-09-05T21:52 — Gatekeeper hypothesis REFUTED, not confirmed.** A Python-written fresh
tmp `.py` carries only `com.apple.provenance` (no `com.apple.quarantine` xattr) and executed
in 0.08s real — not 32s. A first-exec Gatekeeper scan would also predict a uniform delay on
every run, which contradicts the observed pass/fail pattern (same file, same combination,
sometimes fast, sometimes 32s). The 32s wall / 0.03s CPU signature instead matches scheduler
starvation on a loaded host (`sysctl -n vm.loadavg` read 20-144 during these runs) — TRDD-
7NSRD8OV's category-D class, not an OS security scan. The hypothesis text above is kept for
the record but is superseded by this measurement; treat the flake as load-induced timeout,
not Gatekeeper.

## Symptom

`scripts/detectors/memory-maintenance.py:256 _write_pending` never supersedes an older
unclaimed record for the same `(scope, root, intervention)` key — the only bound is
`_PENDING_KEEP = 20` (line 197, prune at 238-251). `scripts/memory_dispatch_claim.py:70`
sorts candidates oldest-first and `claim_one` (line 110) claims the OLDEST — so every new
fire's record joins the pile while agents work the stalest dispatch first.

Measured on this host 2026-09-05: 4 unclaimed `split` records for the SAME PROJECT root
(10, 15, 34, 46 h old) and 2 unclaimed records for the USER root (34, 46 h old).

## Mechanism

This is NOT a missing dedupe of independently-arriving duplicate requests. It is what
happens when `global_state.memory_root_inflight()` (`scripts/lib/global_state.py:1114`,
`MEMORY_INFLIGHT_TTL_S = 30 * 60`, fail-open) times out without ever being claimed: the
30-minute in-flight stamp lapses, the scheduler's next pass (`memory-maintenance.py:592-599`
returns early only while the stamp is live) writes a fresh pending record for the same key,
and the old one is left behind because `_write_pending` never looks for it. A second, distinct
path to the same pile-up: `memory_root_inflight()` (`scripts/lib/global_state.py:1142-1157`)
fails OPEN on an unreadable/corrupt stamp — it returns `None` — so a fresh pending record can
also be written WITHOUT the 30-minute TTL ever lapsing (V3). Both paths land in the same place:
an unclaimed record for a key that already has one. Card N1CPV1QV
(agent-side state-dir mismatch) explains why a spawned agent can fail to claim the record at
all; card IB5B14QQ makes the resulting pile visible to the scheduler. This card is the third
leg: even once an agent looks in the right directory and the pile is visible, the pile keeps
growing on every lapsed TTL unless the scheduler stops stacking a duplicate record per lapse.

## Fix requirement

At `_write_pending` time, before writing the new record: find any unclaimed record with the
same `(scope, root, intervention)` key already in the pool and remove it from the pending
pool by RENAMING it to a `memory-maint-superseded-<id>.json` prefix (never unlinked BY THE
SUPERSEDE — rename only; the ordinary keep-20 prune still ages superseded files out like
pending and claimed) before the new record lands. This bounds the pool to
at most one pending record per key, so `claim_one`'s oldest-first pick can no longer hand out
stale, duplicate work for a key that has since been re-dispatched.

The rename-based supersede is race-safe against a peer claiming the record concurrently:
`memory_dispatch_claim.py::claim_one` (`scripts/memory_dispatch_claim.py:110`) wraps its own
`os.rename(path, target)` claim attempt in `try … except OSError: continue`, so a peer that
loses the race to the scheduler's supersede-rename simply moves on to the next candidate
instead of erroring. Do not remove or narrow that except clause.

This also restores the intent of TRDD-LDSCQ0NU's relay-suppression gate: with duplicates
present in the pool, that gate always finds *some* match for the key and never actually
suppresses a redundant relay; with at most one record per key it becomes meaningful again.

The new `memory-maint-superseded-` prefix joins the prune tuple at `memory-maintenance.py:238`
under the same `_PENDING_KEEP` cap: today that prune loop only walks `(_PENDING_PREFIX,
_CLAIMED_PREFIX)`, so a third, un-pruned prefix would accumulate one file per lapse forever.

## Acceptance criteria

- [x] `_write_pending` removes (renames or unlinks) any existing unclaimed record sharing
      `(scope, root, intervention)` with the new record, before writing the new one.
- [x] A new test in `tests/test_memory_maintenance.py` (e.g.
      `test_write_pending_supersedes_older_unclaimed_same_key`) seeds two unclaimed pending
      records for the same key at different ages, calls `_write_pending` again for that key,
      and asserts exactly one pending record for that key remains afterward.
- [x] A new test asserts a CLAIMED record for the same key is left untouched (only unclaimed
      records are superseded).
- [x] A new test pins the `claim_one` `except OSError: continue` behavior against a record
      concurrently renamed out from under it by a supersede (the peer-claim race stays benign).
- [x] `uv run pytest tests/test_memory_maintenance.py -k supersede` passes.
- [ ] Full suite still green: `uv run pytest`. (NOT run this session per orchestrator
      instruction — see STATE block for the flaky, unrelated `test_dispatch_defang.py`
      finding.)
- [x] A new test seeds `_PENDING_KEEP + N` superseded lapses for distinct keys and asserts the
      `memory-maint-superseded-` count never exceeds `_PENDING_KEEP` after the prune pass runs.

## Notes

Filed as the follow-on to TRDD-N1CPV1QV (agent-side state-dir mismatch) and TRDD-IB5B14QQ
(detector blind to the pending pool) — this card is the third, scheduler-side leg: even once
the agent looks in the right directory and the detector can see the pile, the pile itself
keeps growing unless the scheduler stops stacking duplicate unclaimed records.

## Approval log
- 2026-09-16T12:33:54+0200 — column → todo. no session working it for 7-13 days while column claimed testing; re-columned honest (triage 2026-09-16)
