---
trdd-id: 3VW434Q8
title: The ai-maestro fleet-inject channel reports success on spawn, not on delivery — a failed inject is invisible
column: complete
created: 2026-07-13T23:32:16+0200
updated: 2026-08-05T17:22:57+0200
current-owner: janitor-session
task-type: bugfix
scope: project
implementation-commits: [e7c4624]
severity: high
labels: [fleet-recovery, ai-maestro, observability]
relevant-rules: [1]
---

# The ai-maestro fleet-inject channel reports success on spawn, not on delivery

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-13

**The defect (verified in source, not inferred):** `fleet_inject.fire()` spawns the `aimaestro`
channel with a **detached `Popen`**, `stdout`/`stderr` → `DEVNULL`, **no `wait()`, no returncode
check** (`scripts/lib/fleet_inject.py`, the `plan["channel"] == "aimaestro"` branch), then
returns `True`. `True` therefore means *"a process was spawned"*, **not** *"the keystrokes were
delivered"*.

For the `iterm` / `tmux` / `wtype` / `xdotool` channels that conflation is defensible — they are
local keystroke senders with no meaningful exit code, and the detachment exists for a specific
reason: **the ESC those plans send would otherwise kill the daemon that launched them.**

The `aimaestro` channel is **not** a keystroke sender. It is an **RPC to a server** through the
frozen CLI (`aimaestro-agent.sh session command <tmux> --newline -- <cmd>`). It *does* have a
meaningful exit code — auth failure, server down, unknown session, and (once ai-maestro closes
their issue #54) a **403**. The ESC rationale does not apply to it at all: it sends no ESC to the
daemon's pane. So it inherited a detachment it never needed, and paid for it with the one thing it
actually had to offer: **the truth about whether the command landed.**

**Blast radius (why this is HIGH, not cosmetic):**
- `daemon.py::_fire_fleet_stop` — `ok = fleet_inject.fire(cmd_plan)`; on `ok` it calls
  `gs.record_fleet_injection(pid, flag_state, now)`, whose explicit contract is *"stamp ONLY on a
  successful fire, so a transient fire failure retries next beat."* With an always-`True` `ok`,
  a **machine-wide `/janitor-global-disarm` that never reached an ai-maestro agent is stamped as
  delivered and is never retried while the flag is held.** That session's cron keeps firing
  billable turns straight through a stop the user believes is in effect.
- `daemon.py::_run_gentle_recovery` — logs `FIRED` and writes `_audit(inst, "fired", …)`. The F3
  recovery-audit chain, which exists to be the forensic record of what recovery actually did,
  records a delivery that never happened.

**This is not hypothetical and does not depend on ai-maestro shipping anything.** Three failure
modes produce it *today*: the server is down, the CLI is not authenticated, the tmux session name
is stale. The pending 403 (ai-maestro#54) is simply a fourth — and the one that would turn an
occasional silent miss into a *permanent* one.

**The janitor already knows the right pattern — the fleet path just doesn't use it.** The
self-trigger path (`terminal_trigger._try_ai_maestro_send`) runs the SAME CLI verb **synchronously
with `timeout=6.0`**, checks `sent.returncode != 0`, and on failure returns `None` so the caller
**degrades to the local tmux keystroke send**. That path is correct and needs no change. Only the
daemon's fleet path threw the outcome away.

**FIX (shipped):** in the `aimaestro` branch of `fire()`, the detached `Popen` is replaced with a
**bounded** `subprocess.run(argv, timeout=AIMAESTRO_CLI_TIMEOUT_S, capture_output=True,
check=False)` returning `proc.returncode == 0`. A timeout → `False` (`TimeoutExpired` subclasses
`SubprocessError`, which the branch's existing guard already renders as `False`). This is *not* a
return to blocking-the-daemon: the call is a short bounded RPC (the self-trigger path proves 6 s is
the right bound — the constant is shared so the two callers cannot disagree), and the "never block"
comment on that branch was defending against the **ESC-kills-its-launcher** hazard, which this
channel does not have. The other four channels keep their detached spawn unchanged.

Once `ok` is truthful, **every downstream consumer becomes correct for free** — no new machinery:
`_fire_fleet_stop` stops stamping an undelivered stop (so it retries next beat), the daemon logs
`FIRE-FAILED`, and the audit records `fire_failed`. That is the whole of "detect/surface a failed
inject": the signal already has three consumers; it was only ever the *sender* that lied.

**STATUS: IMPLEMENTED + tests green (commit e7c4624).** `column: testing`. Two existing tests had
**pinned the broken shape** (asserting the detached `Popen` and its unconditional `True`) — they
encoded the bug, so they were replaced by delivery-outcome tests: non-zero exit → `False`, timeout
→ `False`, zero → `True`, plus the bound and `check=False` asserted. Full suite **12887 passed, 1
skipped**; ruff clean. **Falsification verified:** neutering the check to `return True` failed
`test_fire_aimaestro_nonzero_exit_is_a_failure`; reverted.

**2026-08-02 triage (idle-19d reminder):** item (2) below is DONE — verified the dependency is posted on BOTH ai-maestro#54 and janitor#76 (one 3VW434Q8/fleet-inject mention each, checked via gh). Items (1) and (3) remain gated: (1) on the AWXK0RFT publish, (3) on a machine where `aimaestro-agent.sh` exists. The card is honestly `testing`, not stalled.

**NEXT ACTION:** (1) ships on the next `publish.py` release — rides with the other unpushed commits,
do NOT push standalone. (2) Post the janitor's dependency on ai-maestro#54 + janitor#76 (the gate
must leave a headless-daemon path, or fleet recovery loses this channel). (3) The end-to-end
confirmation needs a machine where `aimaestro-agent.sh` is actually installed — it is absent here,
so the channel is dormant and cannot be exercised locally. Then → `complete`.

**Load-bearing facts / gotchas:**
- The CLI is `aimaestro-agent.sh`, resolved `$AIMAESTRO_CLI` → `~/.local/bin` → `PATH`
  (`terminal_trigger._resolve_aimaestro_cli`). It is **absent on the current machine**, so the
  `aimaestro` channel is dormant here and the bug is not observable locally — which is exactly why
  it survived: the channel that lies is the one nobody can see lying.
- **Route claim, corrected:** an earlier note in this work asserted the CLI hits
  `PATCH /api/agents/[id]/session` (the route ai-maestro#54 is about). **Unverified.** The
  janitor's own comment says the frozen CLI wraps `POST /api/sessions/<tmux>/command`, and it is
  handed a *tmux session name*, not an agent id. From this machine the CLI's internals are not
  inspectable. **The fix does not depend on which route it is** — a non-zero exit is a non-zero
  exit. Do not re-assert the route without evidence.
- Do NOT "fix" this by falling back from `aimaestro` to `tmux` on failure. `build_command_plan`
  selects one channel; adding a cross-channel fallback is a separate design decision and is not
  needed to make the outcome honest. Speculative machinery, not now.

**SUPERSEDED — do NOT carry forward:** the framing that "the janitor's inject is broken because it
rides an ungated verb". The janitor calls the **CLI**, which is exactly what janitor#76 / #42
mandate; riding whatever route the CLI chooses is correct behavior. The bug is entirely ours and
entirely local: **we discard the CLI's answer.** Gating (their #54) only raises the cost of that
discard.

## Relationship to ai-maestro#54

ai-maestro intends to strict-classify the keystroke-inject route (their issue #54: the gate is
"inverted with respect to blast radius" — enqueue and kill are strict, inject-now is not). When
they do, an unprivileged caller of that verb gets a **403**.

The janitor is a legitimate consumer of that verb (fleet recovery: waking a frozen agent, and
delivering a machine-wide stop). Two things follow, and they are independent:

1. **Ours, regardless:** surface the failure (this TRDD). A 403 must not be silently swallowed.
2. **Theirs, ours to state:** the janitor's daemon is a *shell* caller, not a browser session, so
   whatever gate they choose must leave a path a headless daemon can use — or fleet recovery loses
   the ai-maestro channel entirely and degrades to the local tmux/iTerm channels only. This is
   ai-maestro's `R32.2` question ("may strict verbs be callable from a shell?"), which their Claude
   explicitly says is **not theirs to decide** — it needs the USER. Post the dependency on their
   #54 and on janitor#76 so the decision is made with the janitor's need visible, not discovered
   after the gate lands.

## Verification

1. `uv run pytest tests/test_fleet_inject.py -q` — the new outcome tests.
2. Falsify: neuter the returncode check (`return True` unconditionally) → the non-zero-exit test
   MUST fail. Revert.
3. `uv run pytest -q` full green + `uv run ruff check`.
4. The four keystroke channels' existing tests must still pass unchanged (no regression in the
   detached-spawn path that the ESC hazard requires).

## Notes and lessons learned

[^1]: [ocd:2026-07-13 lmd:2026-07-13] This bug is a textbook instance of the standing lesson *"a
  selector/sender that discards its outcome fails silently in both directions"*. The detached
  `Popen` was copied from the iTerm branch, where discarding the outcome is CORRECT (there is no
  outcome to discard, and the ESC would kill the launcher). Copying the *mechanism* without
  re-deriving the *rationale* carried the mechanism into a channel where the rationale is absent —
  and the cost is a `True` that means nothing. Lesson: when reusing a defensive pattern, restate
  the threat it defends against and check that the new call site actually faces that threat.
