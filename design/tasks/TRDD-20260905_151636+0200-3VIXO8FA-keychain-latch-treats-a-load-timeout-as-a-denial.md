---
trdd-id: 3VIXO8FA
title: The keychain denied-latch treats a stalled security call as a denial and blinds rotation
column: todo
created: 2026-09-05T15:16:36+0200
updated: 2026-09-05T16:01:44+0200
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
external-refs: [TRDD-EQJPPZ2L, TRDD-K3WQ7XM9, TRDD-FQXBURNR, ai-maestro TRDD-MFTDMSJY, ai-maestro TRDD-RA2ZSTOF]
---

# The keychain denied-latch treats a stalled `security` call as a denial

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
NOT observed" (slot reads). Every beat from then on read "no live credential / STUCK"; a
14:45 probe recovered (2851 ms), three more 5001–5003 ms timeouts re-latched at 14:48:50, the
14:59:13 half-open probe timed out at 5004 ms and re-latched again. Rotation was blind
14:30 → 15:09; the live account's last reading was 82% at 14:30 and the owner re-logged in by
hand at ~14:55 (the cap crossing is inferred — no 429 was recorded, the beat was blind). The
only trigger is 97%.

**Why `security` stalled is NOT established.** Host loadavg was 18–27 on 14 cores (an
untested correlation). Separately, the server's tmux keychain watchdog logged eight
`keychain_probe_timeout`s between 13:59 and 15:08 — a second process, same uid (whether one
securityd session was not checked), saw `security` hang in the same window (its onset 31 min
earlier). At loadavg
11 (15:22) a not-found attribute read on a different service took 0.01–0.02 s (which rules
out nothing — different op, different condition). Load is a correlation; securityd contention
is one other candidate; the set is not enumerated. `ps` ancestry shows pm2 and the tmux
server are both direct children of launchd, which rules out only "the watchdog watched pm2
itself" — "machine-wide", as the 2c26db5b commit subject put it, was one step past the
evidence. **Scope of this card:** it removes the false positive for isolated/transient
stalls. For a persistently blocked keychain (every `-w` read hangs to budget) it delays the
latch by two reads and changes nothing else — there the latch does what it was built for
(stop spawning `security` while calls hang) and rotation stays blind; whether the hang was a
prompt (a flood prevented) or a stall (reads needlessly suppressed) is the unmeasured cause.
Today's window looked like this — one recovered probe (14:45), two re-latches (14:48, 14:59)
— so it may have been either case. The tests must PRESERVE the third-consecutive latch; the
blindness under a persistent block is the alert path's defect, not this card's.
**Behaviour change to name and bound (corrected after review — the daemon path has NO `-w`
read):** `_read_primary_macos_keychain` returns None under `JANITOR_ROTATOR_HEADLESS=1`
before `run_security`, and `cmd_tick` stamps the beacon unconditionally; only the
session-context `refresh_beacon_if_stale` (two callers: the `beacon` CLI verb and
`detectors/oauth-beacon-refresh.py`) turns an attribute-only timeout (`_primary_last_modified`
→ None → "changed") into a `-w` read — exactly one per call by control flow, `may_prompt=True`,
counted toward the threshold. Net change: under a sustained stall the session heartbeat
attempts one `-w` per beat for up to three beats, then latches; the old code latched on the
first attribute timeout.

**The janitor's own python path is one step worse.** `safe_storage.run_security`'s
`except subprocess.TimeoutExpired: set_keychain_denied(...)` branch (read at
`scripts/oauth_rotator/safe_storage.py:303-305`) sets the latch on a SINGLE timeout, while the
TS port already requires 3 consecutive (TRDD-MFTDMSJY, measured 2026-08-28: 26 of 29 slow ops
recovered). Outside the harness — the standalone daemon this repo must keep alive on its own —
one stalled read blinds rotation for a 600 s cooldown, and a half-open probe that is itself a
5 s `-w` read re-latches under the same stall.

A timeout on an ATTRIBUTE-ONLY read (`find-generic-password` without `-w`) can never be a
prompt hang — the code's own comments on `_primary_last_modified` / `_primary_live_item_absent`
say those reads never prompt — yet they route through the same latch-on-timeout branch. The
exemption is for the TIMEOUT branch only: a denial MARKER (`_is_denial` — a locked keychain
answers attribute reads with "interaction not allowed") must keep latching on every op.

## What

In `scripts/oauth_rotator/safe_storage.py` (python side only; the TS port is the peer's):

1. `run_security(argv, *, timeout, may_prompt: bool)` — a new REQUIRED keyword. On
   `TimeoutExpired`: if `may_prompt` is False, return `spawned=True, denied=False,
   returncode=None` and NEVER touch the latch; if True, count it in a per-process
   consecutive-timeout counter and latch only when the count reaches
   `_TIMEOUT_LATCH_THRESHOLD = 3` (same value and same per-process semantics as the TS port's
   `TIMEOUT_LATCH_THRESHOLD`; an answered op resets the count). Denial markers
   (`_is_denial`) still latch immediately ON EVERY OP, `may_prompt` or not. The half-open
   probe path is unchanged except that a probe that times out re-stamps only when
   `may_prompt` is True.
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

**Shared contract (peer requirement, ai-maestro TRDD-RA2ZSTOF, 15:20):** the threshold and
the exemption rule must be ONE contract across `safe-storage.ts` and `safe_storage.py`, or the
two rotators disagree under the same load. This card's side of it: threshold `3`, and the
exemption expressed as an argv PREDICATE, not a call-site list — `find-generic-password` /
`list-keychains` WITHOUT `-w` cannot prompt (`may_prompt=False`); anything with `-w`, and
every `add-`/`delete-generic-password`, can (`may_prompt=True`). Encode the predicate as a
named helper the TS side can mirror line for line; the shared config file, if the USER wants
one, is the peer proposal's decision and not built here.

Out of scope (recorded so it is not lost): raising the 5 s slot-read timeout to the
module's 10 s default. Three timeouts sat at 5001–5004 ms (killed at the budget) so their
true duration is unknown; decide after item 3 has produced a distribution. The burn-gate
gap in the TS port and the attribute-read exemption there are the peer's (message sent
2026-09-05 15:16 to the ai-maestro session).

## Acceptance criteria

- [ ] An attribute-only `security` timeout leaves `keychain-denied.latch` absent (test).
- [ ] A `-w` read latches on the 3rd consecutive timeout, not the 1st; an answered op resets (test).
- [ ] Every `run_security` call site passes `may_prompt` explicitly, enforced by signature (a
      call missing the required `may_prompt` keyword is a pyright `reportCallIssue` error), not
      by a duplicated same-line comment: `uvx --with pyright pyright` reports 0 errors AND
      `grep -rn --exclude-dir=memgrep --exclude-dir=__pycache__ 'run_security(.*# may_prompt' scripts | wc -l` prints 0.
- [ ] An attribute-only op whose stderr carries a denial marker still sets the latch (test).
- [ ] A persistently blocked keychain still latches on the 3rd consecutive `-w` timeout (test).
- [ ] Asserted on the `run_security` seam only (argv containing `-w`; never on `subprocess.run`
      — the `secret-tool` fallback in `_read_live_primary` is a plain spawn): under
      `JANITOR_ROTATOR_HEADLESS=1` `_read_primary_macos_keychain` returns None without calling
      `run_security`; on the session path, in the STALL case (attribute read timed out AND the
      `-w` primary read timed out) `run_security` saw exactly one `-w` argv, AND that call
      spawned (`spawned=True`) — the pre-fix code would have latched on the preceding
      attribute-only timeout and made the `-w` call short-circuit CLOSED with `spawned=False`
      instead, so this is required to fail on unfixed code — the slot loop in
      `write_live_identity_beacon` is not reached when `prim` is None. (On the success path the
      slot loop legitimately issues one or two `-w` reads per configured slot; not asserted.)
- [ ] `uv run ruff check scripts tests`, `uv run mypy scripts/ --ignore-missing-imports`,
      `uvx --with pyright pyright`, and `tests/test_safe_storage*.py` + `tests/test_oauth_rotator*.py` green.

## Notes and lessons learned

- A timeout is not a denial. The latch's text already admitted it ("cause NOT observed"); the
  policy still acted on it. When `security` stalls machine-wide, the breaker built to stop a
  prompt flood becomes the thing that stops rotation.
- Pending on the wikimem page (deferred while the memory-atomize agent holds it): atom
  ATOM-4H2E-E0DY still says "correct anti-flood behaviour", "same securityd" and
  "coincidence"; lesson ATOM-0FV1-QMUK prescribes "coincidence" where "untested correlation"
  is right, and is a PROCESS lesson that belongs on the causal-claims methodology page with a
  link left here. Both to be done through memgrep verbs after the agent reports.
- The filename slug says "load-timeout"; the title was corrected at 15:26 and the slug kept so
  the commit trail resolves. Read the title, not the path.
- The first version of this card named "load" as the cause from a loadavg correlation, with
  the server's own keychain-blind watchdog lines sitting unexplained in the same log excerpt.
  Caught by review; the settling read (0.01–0.02 s at loadavg 11) only shows `security` is
  fast when the host is quieter, not why it stalled.
