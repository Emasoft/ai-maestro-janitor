---
trdd-id: KEEPQRTN
title: Immortality C4-at-L0 — keepalive quarantine-aware version selection + OS-respawn crash signal
column: dev
created: 2026-06-25T09:06:05+0200
updated: 2026-06-25T09:06:05+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 2
severity: HIGH
effort: M
labels: [immortality, os-keepalive, self-integrity, c4-rollback, quarantine, cross-group]
task-type: bugfix
parent-trdd: TRDD-324223a6
relevant-rules: []
release-via: publish
delivery: pull-request
target-branch: main
test-requirements: [unit]
runtime-targets: [macos, linux]
impacts: []
external-refs: []
---

# TRDD-KEEPQRTN — extend C4 auto-rollback to the daemon/L0 (keepalive) path

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-25

### Status: dev — the whole-immortality-surface final review (the plan's mandated final audit) found a REAL cross-group gap: C4 auto-rollback covers the HEARTBEAT path but NOT the DAEMON/L0 path. SAFE to fix (fail-open, non-destructive — unlike E2/E3). Core invariants were SOUND (no CRITICAL: fail-open, never-kill, trust-anchor all held).

- **THE EVALUATION (durable artifact — read before acting, has file:line + the concrete scenarios):**
  `reports/immortality-final-review/20260625_090258+0200-whole-surface-audit.md` (HIGH-1, HIGH-2, MEDIUM-1).

- **THE GAP (one root cause, three findings):** C4's quarantine (the rollback mechanism for a bad self-update)
  is consulted ONLY by the dispatcher-stub. The OS keepalive (L0) + the launchd/systemd respawn path are BLIND
  to it, so a bad self-update whose *daemon* (not its *heartbeat*) crash-loops is NOT rolled back at the OS level —
  launchd resurrects the quarantined version indefinitely. NOT a brick (sessions survive on the stub's fail-open
  backstop), but it defeats C4's intent for the daemon half (which owns marketplace refresh, user-plugin updates,
  the fleet guardian, OAuth keepalive, the OOM guard).
  - **HIGH-1** — `launchd_keepalive.latest_cache_scripts_dir()` (~:120-139) selects the NEWEST cache version
    REGARDLESS of quarantine; `_setup_os_keepalive`/`_keepalive_self_heal` (daemon.py ~:900-942) restage it; launchd
    relaunches it forever. The C3 quarantine file is read only by the stub (`dispatcher-stub.py:232-263`).
  - **HIGH-2** — launchd/systemd respawns exec `daemon_keepalive_entry.py` → `import daemon; daemon.main()` directly,
    NEVER `spawn_daemon_detached` (the only caller of `_record_spawn_attempt`, global_state.py ~:482-497). So an
    OS-respawned die-on-start daemon loops `launchd → main() → crash → launchd …` and `daemon.spawn-history` stays
    empty → `crash_loop_active()` (global_state.py ~:739-752) returns False → C4's `_phase_crash_loop_rollback`
    early-returns → N is never quarantined.
  - **MEDIUM-1** — `_setup_os_keepalive` restages the newest (possibly-quarantined) version into DATA on EVERY
    session-spawned daemon startup, so even a healthy older daemon re-arms the keepalive to relaunch the bad N. Same
    root cause; no convergence away from N until N is GC'd or N+1 ships.

- **NEXT ACTION — two parts that close the daemon-rollback loop end-to-end:**

  **Part A — quarantine-aware keepalive version selection (fixes HIGH-1 + MEDIUM-1).** Teach
  `launchd_keepalive.latest_cache_scripts_dir()` (and any `_keepalive_self_heal` restage target) to SKIP any version
  in `version_update_lib.read_quarantine()` and fall back to the newest NON-quarantined runnable version — the exact
  walk the stub already does (`dispatcher-stub.py` C3 skip). **FAIL-OPEN MANDATORY:** if `read_quarantine()` raises
  or the quarantine set is unreadable → treat as EMPTY (select newest, never worse than today); if EVERY version is
  quarantined → select the newest runnable anyway (a running daemon beats none — the stub's cardinal rule). Never
  return None/nothing-runnable due to quarantine.

  **Part B — OS-launched daemon records a spawn attempt (fixes HIGH-2).** When the daemon is launched by the OS
  keepalive (the `--keepalive` / `_KEEPALIVE_INSTANCE` path), record a spawn-attempt stamp early in `daemon.main()`
  (call `global_state._record_spawn_attempt()` — the same stamp the session path writes) so `crash_loop_active()`
  observes the OS-driven crash loop and C4's `_phase_crash_loop_rollback` can quarantine N. **FAIL-OPEN:** wrap the
  stamp call so it can never break daemon startup; record it ONLY on the keepalive path (don't double-count the
  session path, which already records via `spawn_daemon_detached`).

  Together: a crash-looping OS-respawned daemon now (B) feeds the crash signal → (C4) quarantines N → (A) the
  keepalive restages the newest non-quarantined version → launchd launches the GOOD older version = auto-rollback at L0.

- **Load-bearing constraints / gotchas:**
  - DEEPEST layer (keepalive + daemon startup) — FAIL-OPEN/FAIL-LOUD, never brick the respawn.
  - Quarantine-aware selection must REUSE the stub's walk semantics (newest non-quarantined; all-quarantined →
    newest anyway). Do NOT invent a different policy — consistency with the stub's C3 skip is the point.
  - Part B must record ONLY on the keepalive path (avoid double-counting → false crash-loop trips on the session path).
  - Verify the existing keepalive + crash-loop tests stay green; add tests for: quarantined-newest → older selected;
    all-quarantined → newest selected; quarantine-read-raises → newest selected (fail-open); keepalive-spawn records
    a stamp, session-spawn doesn't double-record.

## Scope guards / non-goals
- Do NOT change the stub's C3 skip (it's correct) — only make the KEEPALIVE honor the same quarantine.
- Do NOT touch the never-kill / fleet-restart path (E2/E3, held) or F3.
- LOW-1 (stub JANITOR_DATA_DIR asymmetry) is INTENTIONAL env-immunity — do NOT make the stub honor the env var
  (that would make the trust anchor env-controllable = a security downgrade). Leave as-is.
- The HIGH-1 Mode-A sub-case (a crash-looping dispatch.py can't self-quarantine because the C4 producer lives
  inside dispatch.py) is narrower + harder (needs the stub or daemon to detect a dispatch crash loop) — OUT OF
  SCOPE here; note it for a follow-up. Part A+B close the DAEMON loop, which is the HIGH finding.

## Why this exists
The final whole-surface review proved the immortality chain is fail-open/never-kill/trust-anchor sound, but C4's
auto-rollback — the "a bad self-update is rolled back" promise — silently does not extend to the daemon/L0 layer
because the keepalive's version selection is quarantine-blind and the OS-respawn path doesn't feed the crash signal.
This closes that gap so the daemon half self-heals from a bad update exactly as the heartbeat half already does.
