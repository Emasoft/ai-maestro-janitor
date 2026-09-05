---
trdd-id: 3VIXO8FA
title: The keychain denied-latch treats a load-induced security timeout as a denial and blinds rotation
column: todo
created: 2026-09-05T15:16:36+0200
updated: 2026-09-05T15:16:36+0200
current-owner: main-session
task-type: bugfix
priority: high
severity: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [oauth-rotator, keychain, continuity, safe-storage]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [TRDD-EQJPPZ2L, TRDD-K3WQ7XM9, TRDD-FQXBURNR, ai-maestro TRDD-MFTDMSJY]
---

# The keychain denied-latch treats a load-induced `security` timeout as a denial

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-05

Filed from the incident report `reports/oauth-rotator/20260905_151600+0200-rotation-failure-keychain-latch-under-load.md`
(machine-local, gitignored — the numbers that matter are repeated here). Column `todo`; the
implementation is to be delegated to one worker with the spec below. NEXT ACTION: implement
in `scripts/oauth_rotator/safe_storage.py` + tests, gates, commit.

## Why (measured 2026-09-05)

The owner had to `/login` by hand at ~14:55 after the live account hit its 5h cap. The
rotator that owned the beat was the ai-maestro server's TypeScript port (the janitor daemon
had correctly yielded `oauth-rotator-tick` at 09:45:43), ticking every ~60 s. At 14:30:36 its
`safe-storage` latched the machine: "3 consecutive `security` ops TIMED OUT past 5s — cause
NOT observed" (slot reads, host loadavg 18–27 on 14 cores). Every beat from then on read
"no live credential / STUCK"; a 14:45 probe recovered, three more 5001–5003 ms timeouts
re-latched at 14:48:50, the 14:59:13 half-open probe timed out at 5004 ms and re-latched
again. Rotation was blind 14:30 → 15:09 — the window in which the live account went from 82%
to the cap (slope ≈0.8 %/min; the only trigger is 97%).

**The janitor's own python path is one step worse.** `safe_storage.run_security`
(`scripts/oauth_rotator/safe_storage.py:303-305`) sets the latch on a SINGLE
`subprocess.TimeoutExpired`, while the TS port already requires 3 consecutive
(TRDD-MFTDMSJY, measured 2026-08-28: 26 of 29 slow ops recovered). Outside the harness —
the standalone daemon this repo must keep alive on its own — one slow read under load
blinds rotation for a 600 s cooldown, and a half-open probe that is itself a 5 s `-w` read
re-latches under the same load.

A timeout on an ATTRIBUTE-ONLY read (`find-generic-password` without `-w`) can never be a
prompt hang — the code's own comments on `_primary_last_modified` / `_primary_live_item_absent`
say those reads never prompt — yet they route through the same latch-on-timeout gate.

## What

In `scripts/oauth_rotator/safe_storage.py` (python side only; the TS port is the peer's):

1. `run_security(argv, *, timeout, may_prompt: bool)` — a new REQUIRED keyword. On
   `TimeoutExpired`: if `may_prompt` is False, return `spawned=True, denied=False,
   returncode=None` and NEVER touch the latch; if True, count it in a per-process
   consecutive-timeout counter and latch only when the count reaches
   `_TIMEOUT_LATCH_THRESHOLD = 3` (same value and same per-process semantics as the TS port's
   `TIMEOUT_LATCH_THRESHOLD`; an answered op resets the count). Denial markers
   (`_is_denial`) still latch immediately. The half-open probe path is unchanged except that
   a probe that times out re-stamps only when `may_prompt` is True.
2. Callers classified by argv shape, verified at each site: `-w` reads
   (`_read_primary_macos_keychain`, `_slot_keychain_read`) and writes/deletes
   (`_security_add_password_via_stdin`, `_slot_keychain_delete`) → `may_prompt=True`;
   attribute-only reads (`_keychain_item_exists`, `_primary_last_modified`,
   `_primary_live_item_absent`, `detectors/keychain-health.py`) → `may_prompt=False`.
3. SLOW-op visibility: log to stderr any `security` call at or past 2500 ms (the TS port's
   `SLOW_SECURITY_LOG_MS`), including timeouts, with verb + service — never the account or
   the secret — so the python side is measurable the way pm2-error made the TS side today.
4. Tests (`tests/test_safe_storage*.py`): an attribute-only timeout never latches; a single
   `-w` timeout does not latch; the third consecutive does; an answer in between resets; a
   denial marker latches at once; the half-open probe on a non-prompting op does not
   re-stamp on timeout. Drive `subprocess.run` through a seam — no real `security`.

Out of scope (recorded so it is not lost): raising the 5 s slot-read timeout to the
module's 10 s default. Three timeouts sat at 5001–5004 ms (killed at the budget) so their
true duration is unknown; decide after item 3 has produced a distribution. The burn-gate
gap in the TS port and the attribute-read exemption there are the peer's (message sent
2026-09-05 15:16 to the ai-maestro session).

## Acceptance criteria

- [ ] An attribute-only `security` timeout leaves `keychain-denied.latch` absent (test).
- [ ] A `-w` read latches on the 3rd consecutive timeout, not the 1st; an answered op resets (test).
- [ ] Every `run_security` call site passes `may_prompt` explicitly (grep: zero calls without it).
- [ ] `uv run ruff check scripts tests`, `uv run mypy scripts/ --ignore-missing-imports`,
      `uvx --with pyright pyright`, and `tests/test_safe_storage*.py` + `tests/test_oauth_rotator*.py` green.

## Notes and lessons learned

- A timeout is not a denial. The latch's text already admitted it ("cause NOT observed"); the
  policy still acted on it. Under host load a 5 s `security` call is routine, and the breaker
  built to stop a prompt flood became the thing that stopped rotation.
