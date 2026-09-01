---
trdd-id: NUD3DGX5
title: Align the janitor with Claude Code 2.1.257 — Fable 5.1 default, subagent model force, session-only effort, upstream cache-miss fixes
column: dev
created: 2026-09-01T21:56:08+0200
updated: 2026-09-02T00:54:00+0200
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

1. [x] **No-keepalive hosts** — MEASURED 2026-09-02 on CC 2.1.257: a `start_new_session=True`
       child spawned from a foreground Bash call SURVIVES the call ending (reparented to pid 1),
       so the heartbeat's daemon spawn is not reaped by the spawn itself; 2.1.257's reaping
       targets background-task stop and CC exit. The CC-exit half is unmeasured; the next
       heartbeat's respawn already bounds it. No change — keepalive install stays best-effort.
2. [x] **Fable 5.1 pricing** — RETIRED: the janitor carries no per-model price table. The only $
       figure is the opt-in `CLAUDE_PLUGIN_OPTION_TOKEN_PRICE_PER_MTOK` knob
       (`token_report.py::_price_per_mtok`, "there is no sane universal price"); `token_burn.py`
       only tracks Fable's separate weekly window, which 2.1.257 did not change. No code change.
3. [x] `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` — row added to TRDD-0HRRZO8S's launch-lever table
       2026-09-02 (forces the subagent model over per-spawn and agent-definition overrides).
4. [x] `/effort` `s` (session-only) — RESOLVED: `external_clear.prefix_invalidated` diffs the
       per-turn `(model, effort)` pair from the statusline series, so a session-only effort
       change is counted exactly like a persistent one. No change.
5. [x] **Upstream cache-miss sources FIXED** — recorded 2026-09-02 as ATOM-L1OG-ZN6M on
       `project_janitor_cc_changelog_currency` (validate NONE, lint INFO-only). Was: record in `project_janitor_cc_changelog_currency`
       and re-read the quota-incident diagnosis (TRDD-2F3I2P18) in their light: (a) sessions
       with an ADVISOR model set missed the prompt cache on every background request
       (compaction, /recap, prompt suggestions) and re-sent the whole conversation uncached —
       this USER runs the Fable advisor, so this was plausibly a large share of the burn;
       (b) Remote Control connecting mid-session re-sent the Bash tool definition (a miss);
       (c) screenshot-heavy sessions missed on every turn past the image size cap.
6. [x] Busy-loop shape — CROSS-CHECKED: the nudge carries the board and issue counts only,
       never a running task. The "re-read a running task's log each fire" shape did appear
       tonight while publish #4 ran, but as the agent's own choice bounded to one `tail` per
       fire, not induced by the nudge text. No change.
7. [x] Stale CC binary — RETIRED: the janitor has no stale-CC-binary detector; its only
       "stale binary" logic is `issue_catalog.py` MEMGREP-010, about the memgrep binary. No
       overlap, nothing to retire.
8. [x] `defaultMode: "bypassPermissions"` — RETIRED: nothing in `scripts/` reads `defaultMode`
       or `bypassPermissions` (grep: 0 hits), so the prober has nothing to note.
9. [x] Sandbox deniedDomains / Containment Escape — RETIRED: no janitor code touches sandbox
       network rules (`deniedDomains`, "sandbox network": 0 hits in `scripts/`); the security
       agent's checks are supply-chain, secrets, workflows and branch protection.

## Acceptance

- [ ] items 1-9 each resolved (done, retired-with-reason, or split into its own card)
- [ ] memory page updated; pytest + ruff + mypy green for any code change

## Notes and lessons learned

- The changelog said "detached background commands no longer survive exit" and the first
  instinct was "the daemon is dead". The measurement said otherwise in one `ps`: the
  production path is launchd, not a Bash child. Measure the spawn PATH, not the spawn FLAG.
