---
trdd-id: EZ3PMQYX
title: iTerm alarm must branch on the daemon's launch context — launchd-spawned means the grant remedy cannot succeed
column: todo
created: 2026-08-08T10:36:31+0200
updated: 2026-08-16T10:58:00+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#92, janitor#233, janitor#235, janitor#236, janitor#237, TRDD-88ZVEQY7]
---

# iTerm alarm — distinguish error from timeout at the call site; never recommend a remedy against live success evidence

## ⏵ 2026-08-16 03:20 — FOUR FACTS FOR THE LAUNCHD BRANCH, measured on this host. The obvious predicate is WRONG.

Probed before building, and the probe killed the naive implementation — which is why this is a
findings block and not a commit.

1. **The thesis applies HERE, it is not hypothetical.** `~/Library/LaunchAgents/` carries
   `com.ai-maestro-janitor.daemon.plist` (`Label: com.ai-maestro-janitor.daemon`,
   `KeepAlive: True`), and the live daemon (pid 29903, up 2h18m, logging normally) has
   **PPID = 1**. So on this machine the daemon IS launchd-spawned and the alarm's
   System-Settings remedy is the futile advice this card is about.
2. **`PPID == 1` IS NOT A SUFFICIENT DISCRIMINATOR — do not implement it.** A double-forked,
   session-spawned daemon is also reparented to 1. That is precisely the case this card contrasts
   launchd with (the 0/254-vs-56 provenance at `fleet_scan.py:208`), so the one predicate that
   looks obvious cannot tell the two apart and would mislabel every detached session daemon as
   launchd-spawned.
3. **The correct discriminator is the daemon's OWN environment at boot.** launchd sets
   `XPC_SERVICE_NAME` to the job label in the process it spawns; a double-forked child inherits
   its parent's environment instead. So the daemon should read `os.environ.get("XPC_SERVICE_NAME")`
   at startup and record the answer into `global_state` — exact, one dict lookup, and it needs no
   cross-process introspection (reading another process's env is not portable and `ps -E` is
   restricted). The flag patch then reads that recorded value, exactly like `rescue_warranted` and
   `iterm_only_count`.
   **Why this was not built tonight:** it changes the daemon's BOOT path, and the daemon is
   long-lived — the change cannot be exercised until it next restarts, and there is no
   `iterm-automation-blocked.flag` here to drive the branch either. Building two unverifiable
   layers at once is how a "fix" ships that nobody can show works.
4. **INDEPENDENT FINDING (2026-08-16 03:20): the plist still names a uv-managed interpreter, so
   the signed-python migration never completed.** — **THE RETRACTION BELOW WAS ITSELF WRONG.
   UN-RETRACTED 2026-08-16 10:57: the original finding was CORRECT and is now fixed.**

   The owner stated it directly — *"you cannot use uv to launch the scripts that control iTerm;
   only python3 or python3.12 directly"* — and `codesign -dv` shows why: uv's managed CPython is
   **ad-hoc** signed with `Identifier=-`, while python.org's framework 3.12 carries
   TeamIdentifier `BMM5U3QVKW`. TCC binds an Automation grant to the code-signing IDENTITY, so a
   fixed path with no durable identity cannot hold one. Fixed in
   `global_state.automation_python_path()` + `keepalive_install.sh::resolve_interpreter`; the
   live plist now names the framework build. Full record on TRDD-DB1P25S4.

   **Why this matters beyond the bug:** the retraction below is a case of a written ratification
   out-arguing a fresh measurement. I looked at the live plist, saw the truth, then read a card
   that said the opposite and un-saw it — in six minutes, without re-measuring either claim. The
   retraction's own closing lesson ("read the card that owns the subject") is exactly half a
   lesson: the card WAS read, and the card was wrong. Reading the owning card is how you find
   the disagreement; **re-measuring is how you resolve it.**

   ~~**WRONG — RETRACTED 2026-08-16 03:26, ~6 minutes after I wrote it. Checked TRDD-DB1P25S4
   instead of stopping at the plist.**~~ (retained verbatim below as the record of the mistake)

   The live plist DOES name `~/.local/share/uv/python/cpython-3.12-…/bin/python3.12`, and a
   python.org framework 3.12 IS installed on this host, so the two together looked like a
   half-done migration. They are not. DB1P25S4's box records an explicit **CORRECTION**:
   `resolve_interpreter` picks the **managed interpreter FIRST — "not the framework probe this
   line originally asked for"** (2026-08-06). Preferring the uv-managed CPython is the ratified
   design, not drift. The `.bak-pre-signed-python-20260805` backup names `/opt/homebrew/bin/uv`,
   which is the identity the migration moved AWAY from — so the backup is evidence the migration
   RAN, not that it reverted.

   And the end-to-end proof is already on that card: **OBSERVED 2026-08-13**, a live
   `fleet_scan.gather_fleet` returned **23 instances with `iterm_session_id` resolved**. The grant
   applies under this interpreter. Consistent with there being no `iterm-automation-blocked.flag`
   on disk right now.

   **What actually remains is a wording inconsistency INSIDE DB1P25S4**, not a machine-state
   problem: its earlier box still says "switched to the framework python3.12" while the later,
   ratified box says managed-first. Harmless to the running system, misleading to the next reader
   — which is exactly how I was misled.

   **The lesson, and the reason this retraction is kept rather than deleted:** I read one artifact
   (the plist), recognised a shape I had a story for, and wrote the story into a commit message
   before reading the card that owned the subject. The check that would have caught it cost one
   `grep` on a TRDD id.

## ⏵ 2026-08-14 17:45 — THE `dispatch.py` SURFACING GAP IS PARTIALLY CLOSED (stays `todo`)

Did the narrow, well-defined half of the NEXT ACTION the 2026-08-13 entry named: `dispatch.py`'s
`_phase_iterm_automation_alarm` now reads `probe_outcome` from the flag (already plumbed by
`a0dfb901`) and, when it is `"timeout"`, prints a THIRD branch — names the timeout + system load
as the likely mechanism, and drops the Automation-grant remedy (a timeout is not a denial) —
instead of falling into the base two-cause hedge. `probe_outcome == "error"` (or empty/unset)
still falls through to the unchanged base alarm, matching "only `probe_outcome: error` … ⇒ the
grant advice" from the What section below (the base alarm already IS that grant advice; no new
branch was needed for it). Precedence, low to high: base < timeout-branch < rearm-downgrade <
TRDD-9PDH8G0W's rescue-warranted hard-negative (implemented alongside this in the same session,
sharing the same `fleet_scan` import block). Tests:
`tests/test_dispatch_phases.py::test_iterm_alarm_names_the_timeout_and_drops_the_remedy`,
`test_iterm_alarm_rescue_warranted_outranks_the_timeout_branch`,
`test_iterm_alarm_error_probe_outcome_keeps_the_base_alarm`.

**What is NOT done, and why the card stays `todo`:** the **host-type surfacing** acceptance box
(#240 ask 2 + #235 — naming how many currently-scanned claude instances are iTerm-hosted, and the
"run under tmux" operational guidance) is a SEPARATE, larger ask: `dispatch.py`'s alarm only ever
reads the flag file, it has no access to the current scan's `fleet` list, so surfacing a live count
needs new plumbing (the flag would have to carry it, written from `gather_fleet` the same way
`rescue_warranted` now is) that was out of scope for this pass — implementing it without that
design would have been exactly the "half-implement, redesign later" outcome the dispatch
instructions for this session warned against. Also not done: the `#233 #235 #236 #237` / `#92` /
`#240` GitHub replies (outside this session's scope — no `gh` calls were made). NEXT ACTION for
whoever picks this up: design the host-iTerm-count field on the flag (written from
`gather_fleet`, alongside `rescue_warranted`), then wire it into a fourth `dispatch.py` branch.

## ⏵ 2026-08-13 15:1x — THE LOAD HYPOTHESIS GAINS A MEASUREMENT, AND IT EXPLAINS THE PEERS' NULLS

janitor#92 has peer agents eliminating candidates for a `probe-failed:timeout` by measurement:
invocation shape (tty / stdin / detached — all `rc=0`, 0.37–0.46 s), self-contention (6
concurrent, 0.65 s worst), and — read from `fleet_scan.py:707-729` — the fact that the osascript
and the CLI probe are strictly SERIAL, so neither can block the other.

**Every one of those was measured on an idle machine, which is why they all come back null.**
The CHIEF-OF-STAFF says so of their own experiment: *"my experiment structurally cannot reach
the failing state."*

Measured on THIS host just now, while the fleet is busy:

```
loadavg  34.63 / 29.00 / 19.21      # severe for this machine
probe-failed events in the entire daemon log:  0
```

Two things follow. First, a 0.4 s command can plainly exceed a 15 s bound at load 34 — so the
load-correlation reading this card already recorded (the 2026-08-08 retraction, "intermittent
osascript hangs/timeouts, plausibly load-correlated — host loadavg hit 195") remains the best
surviving explanation, and it is the one candidate the peers' method cannot test, because
reproducing it requires the machine to be under load at the moment of measurement.

Second — and this is the caveat on my own datum — **this host has logged ZERO `probe-failed`
events ever**, so the timeout under discussion in #92 is not from this log. I am contributing a
mechanism that FITS, not a reproduction of their incident. Do not let it harden into "the cause
is load" on this evidence: it is an untested hypothesis that survives while the tested ones died,
which is weaker than it sounds and is exactly the distinction this card was re-written once
already for blurring.

**The falsifiable prediction, for whoever takes it:** timeouts should cluster with high loadavg
and be absent at low load. Nothing samples load at probe time today, so the correlation cannot be
checked after the fact — capturing loadavg alongside `probe_outcome` would make the next
occurrence self-diagnosing, and that is a natural extension of the plumbing below.

## ⏵ 2026-08-13 12:5x — THE PLUMBING LANDED; THE SURFACING DID NOT (stays `todo`)

`a0dfb901` shipped the **recording** half only: `fleet_scan` now carries `probe_outcome` and a
rearm-evidence AGE, so an `iterm-automation-blocked` observation records WHY it was reached and
how old its evidence is — the exact discriminator the revision below says the alarm is missing.
58 tests pass; ruff + mypy green.

**What is NOT done, and why the card is not closer to done than that:** the alarm TEXT still
reads the old way, because the wiring lives in `dispatch.py`, which was out of scope for that
pass. So the richer fields are written and **nobody reads them yet** — the same
recorded-but-inert shape this corpus keeps producing. Do not read `a0dfb901` as "the alarm now
distinguishes error from timeout"; it does not. NEXT ACTION: consume `probe_outcome` +
evidence-age in `dispatch.py`'s alarm line, and drop the System Settings remedy whenever recent
success evidence exists.

## ⚠ REVISED 2026-08-08 ~16:20 — the launch-context CAUSE claim is RETRACTED

The original Why below asserted a confirmed structural cause ("launchd-parented daemon cannot
receive Apple Events"). **Refuted the same day by the daemon's own log**: the launchd daemon
(pid 61025, parent 1, up since 05:03) fired MULTIPLE successful `FIRED rearm → iterm` today
(13:12, 13:14, 13:40+; 99 all-time). A systematic context barrier cannot produce those. The
webdesign peer retracted the same over-generalization on #233 first; this card repeats the
correction rather than hiding it. The honest reading: **intermittent osascript hangs/timeouts**
(plausibly load-correlated — host loadavg hit 195 today), against a grant that demonstrably
works. The 0/254-vs-56 datum (TRDD-VQ4LX7ND) described an EARLIER regime, not today's daemon.
Lesson (same one, both of us): parentage + timing correlation were correct measurements
published as a stronger conclusion than they supported.

## Why (revised)

- The alarm names two causes it cannot distinguish (denied grant vs hung osascript), and the
  reader cannot tell which they have. The v2.8.1 rearm-evidence downgrade resolves it by
  CORRELATION (a recent success), which works but is indirect and windowed.
- With success evidence on the SAME day, the System Settings remedy is wrong to recommend —
  a grant that works intermittently is not a missing grant (this part of the original card
  SURVIVES, on different grounds: the discriminator is success evidence, not parentage).

## What (revised)

1. **The primary fix — the #233 peer's call-site log line**: where the fleet scan invokes
   osascript for iTerm enumeration, log DISTINGUISHABLY "Apple Event returned an error: <err>"
   vs "call exceeded timeout (<N>s)" vs "returned empty". The flag payload carries that
   outcome (`probe_outcome: error|timeout|empty`), so the alarm can say WHICH failure this
   scan actually had instead of naming two causes it cannot tell apart — making the rearm
   correlation a corroborator instead of the only signal.
2. **Alarm text weighs evidence, not parentage**: recent success (any daemon context) ⇒ the
   v2.8.1 transient downgrade; `probe_outcome: timeout` ⇒ name the timeout + system load as
   the likely mechanism, no remedy trip; only `probe_outcome: error` with a TCC-shaped error
   AND no recent success ⇒ the grant advice. Parentage may be RECORDED as context but must
   not gate any branch (it discriminates nothing on this host).
3. **Flag carries evidence age** (#237's ask): at write time, include the age of the newest
   `FIRED rearm → iterm` line so the flag is self-contained for other consumers (the alarm's
   own 6h-window parse, shipped v2.8.1, stays authoritative).
4. Notes folded in: #235's uv-path grant-anchor fragility becomes second-order under cause (c)
   (keep the existing warning only in the `session` branch); #236's blast-radius prediction is
   PARTIALLY disconfirmed — session-side self-triggers (compact/reload typing) run
   terminal-parented in the SESSION's own context, the population #233 measured working; only
   daemon-side rescue is context-bound.

## Acceptance

- [ ] Payload round-trip + branch tests (launchd text has NO System Settings trip; session
      text unchanged) — **THE CARD'S CORE THESIS, AND STILL THE ONLY THING UNBUILT.** Checked
      2026-08-16: the alarm mentions launchd in prose (`dispatch.py:1674`, `:1713`) but never
      BRANCHES on it, and no `launch_context` field exists on the flag. So a launchd-spawned
      daemon is still told to go grant Automation to a binary the grant cannot help — the exact
      thing the title says must stop. Needs the daemon's own launch context recorded on the
      flag, then a branch that DROPS the System Settings remedy rather than caveating it.
      NEXT ACTION for whoever picks this up; the exposure plumbing shipped above is the
      template (pure predicate → late compare-and-write patch → fail-open reader → clause).
- [x] Flag includes rearm-evidence age; absent evidence → field absent, not 0 — shipped
      (`fleet_scan.py:232` the parameter, `:263-264` the guarded write). The absent-not-zero half
      holds BY CONSTRUCTION: the key is only assigned inside `if rearm_evidence_age_s is not
      None`, so there is no code path that can write a 0 standing in for "unknown". Verified by
      reading it, 2026-08-16.
- [x] The 0/254-vs-56 provenance stays cited in code comment or docstring — `fleet_scan.py:208`,
      verbatim: *"…0 times in 254 beats while a session-spawned daemon resolved 56
      (TRDD-VQ4LX7ND)"*.
- [x] **Host-type surfacing (#240 ask 2 + #235) — SHIPPED 2026-08-16, and it turned out much
      smaller than the 08-14 note estimated.** That note called it "a SEPARATE, larger ask"
      needing new plumbing. It needed almost none: `iterm_rescue_warranted` already evaluates
      the exact channel predicate, as `any()`. The count is the same test with `sum()`.

      What the alarm now says, when the flag carries it: *"SCOPE: 3 of 11 scanned instance(s)
      have NO channel but iTerm, so they are unrescuable for as long as this lasts — those are
      the ones to move under tmux first."* That turns the existing tmux advice from a
      suggestion into a sized one, which is the whole of #240 ask 2.

      **Deliberately a DIFFERENT predicate from `rescue_warranted`**, and this is the design
      point rather than an implementation detail: that one is channel-test AND
      `diagnosis == "cron_dead"` — "did a rescue fail just now". This one drops the diagnosis —
      "how many are one stall away from being unrescuable". Counting only the cron_dead ones
      would report ZERO on a fully-exposed fleet right up until the first casualty, i.e. it
      would go quiet exactly while the guidance was still preventive.

      `fleet_scan.iterm_only_exposure` (pure) → `record_iterm_host_exposure` (late
      compare-and-write patch, same discipline and same reasons as `record_iterm_rescue_
      warranted`) → `iterm_automation_host_exposure` (fail-open reader) → the alarm clause.

      **An unmeasured exposure renders NOTHING, never "0 exposed"** — a pre-upgrade flag, or a
      nonsensical pair like 7-of-3, yields no SCOPE clause at all. A missing measurement
      shown as a reassuring zero would make the alarm worse than silent on exactly the hosts
      that never measured. Bools are rejected too (a bool IS an int, so `true` would have read
      as the count 1). Tests: `test_iterm_alarm_names_how_many_instances_have_no_channel_but_iterm`,
      `test_iterm_alarm_omits_the_scope_clause_when_the_flag_predates_the_field`,
      `test_exposure_counts_iterm_only_instances_regardless_of_diagnosis`,
      `test_host_exposure_reader_returns_none_rather_than_a_misleading_zero`. Falsified by
      dropping the clause from the f-string — the wiring test reddens, which is the
      TRDD-OO301H7D failure (a value computed and never passed) this repo has hit before.

      **What this does NOT prove: the production path is UNEXERCISED.** There is no
      `iterm-automation-blocked.flag` on this host right now, so the alarm is not firing and
      the clause has only ever been driven by tests. Recorded rather than left implicit.
- [x] #233 #235 #236 #237 answered when it ships — **MOOT, verified rather than assumed.** All
      four are CLOSED (three on 2026-08-12, #233 on 08-08), as is #240. #92 was updated
      2026-08-16 (`#issuecomment-5304813279`) under TRDD-9PDH8G0W. Posting fresh comments on
      five closed threads would be noise, not an answer — the debt this box tracked was
      settled by whoever closed them.
