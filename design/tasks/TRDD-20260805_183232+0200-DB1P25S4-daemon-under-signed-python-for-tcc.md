---
trdd-id: DB1P25S4
title: Run the daemon under the signed python.org 3.12 so the existing iTerm Automation grant applies
column: blocked
created: 2026-08-05T18:32:32+0200
updated: 2026-08-13T00:44:30+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
parent-trdd: VQ4LX7ND
relevant-rules: []
blocked-by: [publish-of-75332ba0]
implementation-commits: [75332ba0]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-08-06

### 2026-08-06 ~07:35 — THE 3-PART CODE FIX IS IMPLEMENTED (the durable half). Tests green. Commit 75332ba0.

Landed in one change-set (per the 21:00 spec below), plus the pure-core guard the
agentlens/T-RVZX688P report asked for:

1. **Managed interpreter on BOTH spawn paths.** `global_state._managed_python_path()` runs
   `uv python find --system --managed-python 3.12` (`--system` is LOAD-BEARING — without it a
   project's `.venv/bin/python3` wins when cwd is inside a repo; measured). `spawn_daemon_detached`
   ladder: managed → `uv run --script` → `sys.executable`. `keepalive_install.sh::resolve_interpreter`
   (the plist/unit generator) mirrors it: managed find → `python3`/`python3.x` discovery →
   `uv run --script` LAST (was FIRST — that ordering was the ephemeral-shim identity source).
2. **Version-less own paths never evicted.** New `_is_own_stable_daemon()`: argv carrying
   `daemon_keepalive_entry.py` OR the DATA-staged `.../plugins/data/<slug>/scripts/daemon.py` →
   `daemon_needs_restart` False. Guarded in BOTH `daemon_needs_restart` (covers its
   quarantine-read-failure fallback) and the PURE `_restart_decision` (covers any caller —
   the hole the T-RVZX688P eviction loop went through).
3. **Quarantine consulted on the DECIDING version in BOTH branches** (janitor#211):
   roll-forward `current_ver not in quarantined`; roll-down
   `running_ver in quarantined and current_ver not in quarantined`. All-quarantined answer =
   refuse and let the running daemon stand (never starves: a daemon is running by definition
   in this gate).

Proof: 4 old-code probes against cached 2.4.1 all returned True (evict); new code returns
False. 99 tests in test_launchd_keepalive+test_global_state pass (incl. 9 new + 2 hermetic
fake-uv plist-rendering tests); test_daemon+test_dispatch_phases 148 pass; ruff+mypy clean.

NOTE the earlier REMAINING wording "resolve a SIGNED python (probe the framework path
first)" was SUPERSEDED by the same-evening CORRECTION: the implemented target is uv's
MANAGED interpreter; the framework python is reachable via the `python3` discovery rung.

STILL OPEN: (a) observe a fleet scan enumerate iTerm sessions post-restart (the VQ4LX7ND
alarm clears end-to-end); (b) publish, then resolution notes on GH#92 + TRDD-VQ4LX7ND.

### (superseded head) — 2026-08-05

### CORRECTION (same evening, owner) — the granted client is UV'S MANAGED CPYTHON, and the real
### mechanism is PATH STABILITY, not code signing

The owner identified the authorized runtime exactly:
`~/.local/share/uv/python/cpython-3.12.9-macos-aarch64-none/bin/python3.12`.
The plist now runs THAT; verified live: daemon pid 73578 under it, heartbeat fresh, launchd
KeepAlive (note: `launchctl kickstart` restarts the CACHED definition — a plist edit needs
`bootout` + `bootstrap` to load, and bootstrap can return transient error 5 right after a bootout;
retry). My signed-python theory below is SUPERSEDED as mechanism: the unstickable Automation
client was never "uv python" per se — it was the EPHEMERAL `~/.cache/uv/builds-v0/.tmpXXXX/bin/
python` shim that `uv run --script` mints, a NEW binary path on every respawn, so no TCC grant
could ever attach to the same client twice. The MANAGED interpreter's path never changes, which is
why the owner's grant sticks to it (adhoc signature notwithstanding). Consequence for item 2: the
detached session spawn must launch daemon.py via this managed-interpreter path (resolvable with
`uv python find` against the pinned version) — not via `uv run`, which reintroduces the ephemeral
shim identity. The framework python.org 3.12 remains a fallback candidate, not the target.

OWNER (2026-08-05, verbatim intent): the Automation toggle for iTerm cannot be enabled under
the **uv** client, but the **Python 3.12** client already has iTerm ON — so route the osascript
work through a normal python process.

VERIFIED on this host, the mechanism behind the owner's observation:
- launchd plist (`~/Library/LaunchAgents/com.ai-maestro-janitor.daemon.plist`) runs
  `/opt/homebrew/bin/uv run --script daemon_keepalive_entry.py --keepalive`.
- uv's python: `codesign` Identifier `-`, TeamIdentifier **not set** — adhoc; macOS has no
  stable identity to persist a TCC Automation grant against (the exact VQ4LX7ND/GH#92 case).
- `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12` (3.12.8):
  Identifier `python3`, TeamIdentifier **BMM5U3QVKW** (python.org) — the Settings "Python 3.12"
  client whose iTerm toggle is already ON.
- The daemon closure is stdlib-only BY DESIGN (keepalive staging), so uv is a launcher
  convenience only; the entry runs under plain python3.12 unchanged.

DESIGN — run the WHOLE daemon under the signed python, not just an osa wrapper: TCC attributes
Apple Events to the RESPONSIBLE process, and a child spawned by the uv-daemon can inherit the
uv identity — wrapping only the osascript call would not reliably change attribution. With the
daemon itself under BMM5U3QVKW, every osascript child it spawns is covered by the existing grant.

### 2026-08-05 ~21:00 — THE GRANT WORKS; the hot-apply does NOT survive the fleet. Code fix is the only durable half.

PROVEN: with the daemon under the owner's granted interpreter (pid 73578), the next heartbeat
fire carried NO iTerm-denial alarm — first clean fire in days. The TCC theory is confirmed
end-to-end.

ALSO PROVEN, within the hour: janitor#211's ping-pong reclaimed the daemon. A session's
`daemon_needs_restart` (argv mismatch: DATA path != that session's cache path) SIGTERM-ed 73578;
`ensure_daemon_running` respawned a uv EPHEMERAL-SHIM daemon (builds-v0 tmp path) — the exact
ungrantable identity this card exists to remove. The launchd entry then could not re-take the
held singleton (July-flood shape), and launchd had already dropped it ("No such process" on
bootout — it was gone before I parked it). Chore coverage never lapsed (heartbeat stayed fresh);
only the IDENTITY regressed, so the iTerm alarm will return on scans by the shim daemon.

STOP-RULE, learned tonight: do NOT keep hand-cycling processes against the fleet — the earlier
churn is what tripped the crash-loop breaker into FALSELY quarantining 2.4.1 (cleared via the
integrity writer; janitor#211 has the mechanism). Every manual win is undone within minutes by
code that doesn't know about it.

THE CODE FIX (one change-set, next session, fresh context):
1. `spawn_daemon_detached` + the plist generator resolve the MANAGED interpreter
   (`uv python find` on the pinned version → `~/.local/share/uv/python/.../bin/python3.12`;
   fall back to `uv run` only when absent) — then BOTH spawn paths carry the granted identity
   and the ping-pong's two sides finally agree.
2. `daemon_needs_restart` recognizes the DATA-staged path as current (it IS the staged copy of
   the newest cache) instead of reading it as stale argv.
3. `_restart_decision` roll-forward checks the quarantine (janitor#211's exact ask).

DONE THIS SESSION (hot-apply, owner-directed):
- [x] plist ProgramArguments switched to the framework python3.12 (backup kept beside it)
- [x] old uv-identity daemon stopped; agent bootstrapped; daemon verified under the signed python

REMAINING (the durable half — code, so a restage/reinstall does not revert the hot fix):
- [x] `keepalive_install.sh::resolve_interpreter` (the plist/unit generator): managed
      interpreter first (per the CORRECTION — not the framework probe this line originally
      asked for), stable python discovery second, `uv run` last (2026-08-06)
- [x] `global_state.spawn_daemon_detached` (the non-launchd spawn path): same resolution, same
      reason — a session-spawned daemon must not silently reintroduce the adhoc identity (2026-08-06)
- [x] tests: managed-python resolution (present/absent/non-executable), plist rendering both
      ways (hermetic fake-uv), never-evict guards, quarantine symmetry (2026-08-06)
- [x] observe the fleet scan enumerate iTerm sessions (the VQ4LX7ND alarm clears itself) — the
      end-to-end proof the grant actually applies. **OBSERVED 2026-08-13**: a live
      `fleet_scan.gather_fleet` returned 23 instances with `iterm_session_id` resolved on the
      iTerm-hosted ones, and `iterm-automation-blocked.flag` is **absent**.
      **Attributed to the DAEMON, not to the session that ran the probe** — that distinction is
      the whole card, since a TCC grant is per-binary and my own interpreter enumerating proves
      nothing about the daemon's: daemon pid 90235, heartbeat 8 s old, and its `session-liveness`
      task (the caller of `gather_fleet` → `record_iterm_automation_state`) last ran **98 s ago**.
      The flag is CLEARED on success as well as set on failure (`record_iterm_automation_state`
      docstring: *"an alarm you have to remember to silence is one you learn to ignore"*), so an
      absent flag after a fresh daemon scan is an observation, not merely an absence of one.
- [ ] publish; then GH#92 + TRDD-VQ4LX7ND get the resolution note

## Approval log

- 2026-08-12T15:39:16+0200 — RE-COLUMNED dev → todo by janitor-main-session. A WORK column
  asserts active work; nobody was working this (idle 6d). 5/7 acceptance, two remaining OPEN
  items, no external wait. No scope or acceptance changed.
- 2026-08-13T00:44:30+0200 — 6/7 acceptance. The end-to-end observation LANDED (see the box); the only remaining
  item is publish-gated, so the card is `blocked` on it rather than sitting in `todo` claiming
  workable.
