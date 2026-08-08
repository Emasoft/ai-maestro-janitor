---
trdd-id: EZ3PMQYX
title: iTerm alarm must branch on the daemon's launch context — launchd-spawned means the grant remedy cannot succeed
column: todo
created: 2026-08-08T10:36:31+0200
updated: 2026-08-08T10:36:31+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#92, janitor#233, janitor#235, janitor#236, janitor#237]
---

# iTerm alarm must branch on the daemon's launch context

## Why — the peer-issue cluster converges on ONE cause, confirmed on this host

- #233 (assistant-manager): the EXACT binary the alarm names enumerates **32 sessions**
  sub-second when run terminal-parented — cause (b) does not reproduce; the peer correctly
  flagged TCC responsible-process semantics (a shell child is attributed to the TERMINAL app).
- The janitor's own prior data (dispatch.py alarm docstring, TRDD-VQ4LX7ND): **0 channel
  resolutions in 254 launchd-spawned beats vs 56 from a session-spawned daemon.**
- Confirmed live 2026-08-08 10:35: daemon.pid 61025 = `daemon_keepalive_entry.py --keepalive`,
  **parent launchd (pid 1)** — while the day's 18 successful `FIRED rearm → iterm` (#237,
  02:51–04:32) predate the launchd takeover.
- #92's "toggle will not persist" observation is CONSISTENT with this: a grant aimed at a
  context that cannot receive Apple Events looks exactly like a grant that will not stick.

**Cause (c): the LAUNCH CONTEXT.** A launchd-parented, adhoc-signed uv-python daemon is not a
context macOS grants interactive Automation to. The System Settings trip the alarm recommends
CANNOT succeed while the daemon is launchd-spawned — a repeated instruction that cannot succeed
(#233's phrasing) trains the reader to ignore the channel (#234's point).

## What

1. **Record parentage in the flag**: `fleet_scan.record_iterm_automation_state` payload gains
   `daemon_context: "launchd" | "session"` (from ppid==1 or equivalent), compare-and-write
   stable.
2. **Branch the alarm text** (`dispatch._phase_iterm_automation_alarm`):
   - `launchd` → structural: "iTerm injection is unavailable under the OS-keepalive daemon —
     this is a launch-context limit, NOT a missing grant; do NOT toggle System Settings. tmux
     panes remain covered. Options: run agents under tmux, or a session-spawned daemon covers
     iTerm while its parent session lives." Cite the 0/254-vs-56 measurement.
   - `session` → today's two-cause text (grant advice is then plausible).
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
      text unchanged)
- [ ] Flag includes rearm-evidence age; absent evidence → field absent, not 0
- [ ] The 0/254-vs-56 provenance stays cited in code comment or docstring
- [ ] **Host-type surfacing (#240 ask 2 + #235):** the alarm names how many currently-scanned
      claude instances are iTerm-hosted (the unprotected set) — fleet_scan already resolves
      per-instance terminal identity, so "unreadable" and "healthy" stop looking identical to
      a fleet-continuity reader; the launchd branch states the operational guidance plainly
      (run fleet agents under tmux — rescued with no grant, moots #92 for them, #240 ask 3)
- [ ] #233 #235 #236 #237 answered when it ships (#92 updated, #240 noted)
