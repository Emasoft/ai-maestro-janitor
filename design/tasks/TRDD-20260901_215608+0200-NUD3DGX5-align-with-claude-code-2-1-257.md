---
trdd-id: NUD3DGX5
title: Align the janitor with Claude Code 2.1.257 — Fable 5.1 default, subagent model force, session-only effort, upstream cache-miss fixes
column: todo
created: 2026-09-01T21:56:08+0200
updated: 2026-09-01T21:56:08+0200
current-owner: janitor-main-session
task-type: feature
scope: project
project-id: ai-maestro-janitor
severity: medium
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-GK35MOXU, TRDD-0HRRZO8S, TRDD-TL5TSWK4, TRDD-DD5X4O6Z]
---

# Claude Code 2.1.257 (2026-09-01) — what the janitor must adopt or re-check

USER directive 2026-09-01 ("some new changes to claude code to align with"). Installed CC is
2.1.257 (it self-updated mid-session tonight — the update restart is what killed publish #2).

## Verified tonight — the one RISK item is benign on this host

**"Fixed background commands that detach from their shell (timeout/setsid) surviving a task
stop or Claude Code exit."** Feared: the janitor daemon, spawned detached from a heartbeat's
Bash call, would now die with its spawning session. MEASURED 2026-09-01 21:55: the live daemon
(pid 43176, etime 3d01h) runs under the OS keepalive (`daemon_keepalive_entry.py --keepalive`,
launchd-owned), not as a child of any Claude Bash call, and it survived the 2.1.257 update.
Residual: hosts WITHOUT the OS keepalive, where `ensure_daemon_running()` spawns the daemon
from a heartbeat (`global_state.py:1888`, `start_new_session=True`) — there the daemon may now
be reaped when that heartbeat's Bash call ends, and only the next heartbeat respawns it.
Verify on such a host before assuming; `daemon.log` restart cadence is the tell.

## Items

1. [ ] **No-keepalive hosts**: confirm whether a heartbeat-spawned daemon is reaped at Bash-call
       end on 2.1.257; if yes, the keepalive install must become mandatory (not best-effort)
       and `ensure_daemon_running` should say so loudly.
2. [ ] **Fable 5.1 is the default Fable** (`claude-fable-5-1`, 1M ctx, $10/$50 per Mtok,
       $0.25/Mtok cache reads): update every pricing/model table the token-report, burn-rate
       and cost detectors carry; agentlens integration (`agentlens-diagnostics-integration`)
       may carry its own.
3. [ ] `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` — add to TRDD-0HRRZO8S's launch-lever table (forces
       the subagent model over per-spawn and agent-definition overrides).
4. [ ] `/effort` `s` (session-only) + `--effort` per-session hold: GK35MOXU's effort trigger
       must count session-only changes as real switches (they are; they still rewrite the
       prefix).
5. [ ] **Upstream cache-miss sources FIXED** — record in `project_janitor_cc_changelog_currency`
       and re-read the quota-incident diagnosis (TRDD-2F3I2P18) in their light: (a) sessions
       with an ADVISOR model set missed the prompt cache on every background request
       (compaction, /recap, prompt suggestions) and re-sent the whole conversation uncached —
       this USER runs the Fable advisor, so this was plausibly a large share of the burn;
       (b) Remote Control connecting mid-session re-sent the Bash tool definition (a miss);
       (c) screenshot-heavy sessions missed on every turn past the image size cap.
6. [ ] "Proactive output style sessions busy-looping with filler while a background command or
       Monitor runs" is fixed upstream — cross-check TL5TSWK4's nudge never induces the same
       shape (a nudge must not start a turn that only re-reads a running task's log).
7. [ ] "Background sessions left running an older CC binary piling up across auto-updates" is
       fixed upstream — check the janitor's stale-binary / process-drift detectors for overlap
       and retire duplicated logic if any.
8. [ ] `defaultMode: "bypassPermissions"` in project `.claude/settings.json` is now IGNORED
       (user/managed only) — identify-environment prober note.
9. [ ] "Fixed sandbox network hosts with a trailing dot bypassing deniedDomains" +
       "Containment Escape rule in auto mode" — note for the security agent's sandbox checks.

## Acceptance

- [ ] items 1-9 each resolved (done, retired-with-reason, or split into its own card)
- [ ] memory page updated; pytest + ruff + mypy green for any code change

## Notes and lessons learned

- The changelog said "detached background commands no longer survive exit" and the first
  instinct was "the daemon is dead". The measurement said otherwise in one `ps`: the
  production path is launchd, not a Bash child. Measure the spawn PATH, not the spawn FLAG.
