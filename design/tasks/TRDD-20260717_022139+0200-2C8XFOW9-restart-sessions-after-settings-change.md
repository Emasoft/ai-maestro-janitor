---
trdd-id: 2C8XFOW9
title: Restart Claude sessions after the janitor changes ~/.claude/settings.json (apply-on-restart)
column: backburner
created: 2026-07-17T02:21:39+0200
updated: 2026-07-17T02:21:39+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
release-via: publish
relevant-rules: [7]
implementation-commits: []
---

## ⏵ ARCHITECTURE CORRECTION (2026-07-17, AUTHORITATIVE — supersedes the per-session framing below)

The USER re-scoped this: **settings-enforcement + restart is a DAEMON GLOBAL command, NOT a
per-session hook.** v0.47.0 shipped the enforcer in `on-session-start` (per-session) — that was the
wrong altitude. It must MOVE to the daemon, because restarting agents + a machine-wide settings write
are global-scope single-writer ops (issue #7), and R42's "no agent drives another" has an explicit
**"except the janitor daemon"** exception for machine-wide switches.

**Two plugins, two agent GROUPS, NO overlap:**
- **#J (ai-maestro-tailored):** the daemon *is the ai-maestro server*. It performs the global commands
  (set the 8 env keys + `askUserQuestionTimeout` add-if-missing-OR-different, RESTORE on drift, and
  restart all SAME-HOST agents) **directly via server API / function calls — NO scripts**. Acts ONLY on
  ai-maestro-harness agents. Restart auto-fires when the ai-maestro-plugins marketplace updates. Built
  in the **ai-maestro repo** (Family-A) — NOT here.
- **#N (non-ai-maestro):** retains the current standalone daemon (`scripts/daemon.py`). It handles the
  same global commands for **all agents OUTSIDE the ai-maestro harness**. Built HERE.

**Both daemons edit the SAME `~/.claude/settings.json` with the SAME values ⇒ no conflict.** The
`settings_ensurer` LOGIC (2 merge modes + supersecure verified write, already shipped) is REUSED by
both; only the CALLER moves (hook → daemon task) and gains drift-restore + post-change restart.

**Global disarm/arm/pause/resume stay DAEMON-ONLY** (the janitor skills do only the LOCAL versions
directly) — already true via `global_control_cli.py` + the daemon.

**JANITOR-SIDE (#N) work, buildable now — the daemon already has the fleet machinery:**
1. New daemon `Task("settings-enforce", …)` calling `settings_ensurer.ensure_recommended_settings()`
   (single-writer, global scope) + DRIFT-RESTORE (re-apply on the periodic beat if a value drifts).
2. On a change, daemon-driven fleet-restart of the #N agent group, reusing `fleet_restart`
   (build_relaunch/force_restart/resurrect + fire_restart) + `task_fleet_stop`'s injection pattern.
3. **CRITICAL GATE:** the daemon spawns UNCONDITIONALLY today (the #N/#J split, PZLVT2RN, is NOT done),
   so the daemon restart MUST be gated to the NON-ai-maestro group (skip ai-maestro-managed sessions —
   the server owns those, with its automated launch string) until PZLVT2RN lands. The settings WRITE is
   safe either way (idempotent, same values). Reuse the same idle-safe/presence gate as the local path.
4. Retire the per-session hook enforcer (EQ792YPX) once the daemon task is the sole #N writer — OR keep
   it as a fallback for hosts where the daemon is disabled. DECISION PENDING.

**ai-maestro-side (#J) work (their repo, coordinated on Emasoft/ai-maestro#75 + the new chat):** the
server settings-enforcer + restore watchdog + fleet-restart + the R42 wording extension (USER-gated
IRON rule). They confirmed no host-settings.json editor exists there yet and no `aimaestro-manage-clients.sh`
(the real self-restart verb is `aimaestro-agent.sh restart <id>` → POST /api/sessions/[id]/restart).

**This is entangled with PZLVT2RN (the daemon #N/#J migration).** Likely the #N daemon-enforcer lands
here as its own TRDD; the #J half is an ai-maestro Family-A TRDD. NEXT: confirm with USER whether to
(a) build the #N daemon-enforcer now (gated to non-ai-maestro), (b) fold into PZLVT2RN, and (c) keep or
retire the per-session hook. Do NOT build the daemon fleet-restart before the idle-safe/scope
decisions are confirmed (high blast radius).

## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-07-17

**Why.** The settings-ensurer (TRDD-EQ792YPX, shipped v0.47.0) writes recommended settings into
`~/.claude/settings.json`, but Claude Code reads `env` + settings at **startup**, so a change does
NOT apply to the running session — the session must RESTART. The user wants the janitor to
restart sessions automatically after it applies a change. This is the EHT (effects-handling task)
of EQ792YPX: it handles the consequence of the settings write.

**Trigger.** `on-session-start.py`'s `settings_ensurer.ensure_recommended_settings()` returns a
NON-EMPTY change summary → a change was just applied → a restart is needed to activate it.

**Two modes** (branch on `state.in_ai_maestro_agent_env()`):
- **Normal mode:** self-restart via the existing self-trigger / fleet infra — type `/exit`, then
  relaunch `claude --continue --dangerously-skip-permissions --add-dir /tmp` into the pane
  (reuse `terminal_trigger` / `fleet_inject` / `fleet_restart.build_relaunch`). NB the real CC flag
  is **`--dangerously-skip-permissions`** (the user's "--dangerously-bypass-permission" was a
  misremember — verified via `claude --help`), and `-c/--continue`, `--add-dir <dirs...>` are real.
- **ai-maestro mode:** the janitor is workdir-restricted (cannot write `~/.claude/settings.json` at
  all — so the ensurer already no-ops there) AND does not own its launch string → call the SERVER
  restart script. The user believes it is `aimaestro-manage-clients.sh cli-client-restart --aid <id>`.

**BLOCKED ON (do not implement past the open decisions until these clear):**
- **ai-maestro#75** (filed this session) — needs from the ai-maestro server: (1) the exact
  CLI-client-restart command + how the janitor gets its own `--aid`; (2) a sanctioned server
  API/script to edit `~/.claude/settings.json` for workdir-restricted agents (or confirmation the
  server owns it and the janitor should skip settings in ai-maestro mode).
- **USER confirmation** on the disruptive behavior — an AskUserQuestion was posed this session but
  timed out unanswered (user AFK). The three open decisions below are what it asked.

**OPEN DECISIONS (carry these to the user before building):**
1. **Scope** — self-only (the session that applied the change restarts itself) vs FLEET-WIDE (the
   triggering session signals the daemon → the daemon injects a restart into every session's pane).
   The user said "restart all agents" ⇒ fleet-wide, but confirm the disruption is wanted.
2. **Safety/timing** — RECOMMENDED DEFAULT: **idle-safe** (restart only at an idle boundary, no
   in-flight turn, presence-gated, soft-enqueued `/exit`) so active work is never interrupted / lost.
   Alternatives the user may pick: immediate (interrupts mid-turn) or notify-only (fully manual). The
   away-default this session is idle-safe.
3. **Default on/off** — auto-relaunching with `--dangerously-skip-permissions` is security-sensitive;
   gate behind a userConfig (`restart_after_settings_enabled`). Confirm default. (User requested the
   behavior, so likely default-on, but the blast radius argues for a deliberate opt-in.)

**Load-bearing gotchas:**
- **Never leave a session dead.** If a relaunch fails, the session is gone. Reuse `fleet_restart`'s
  resurrect rungs; verify the new process came up before considering the old one done.
- **Bounded / once-per-change.** A settings change happens ~once per machine (the first session
  after the ensurer ships), so the restart should fire once, not on every heartbeat — gate on the
  actual change summary, and de-dupe so a restart is not re-triggered on the next SessionStart.
- **Presence gate** — never `/exit` a pane a human is actively typing in (reuse the per-pane
  presence gate from TRDD-T7N67AQP).

**NEXT ACTION:** when the user is back — resolve the 3 open decisions (AskUserQuestion) and check
ai-maestro#75 for the server answers; then plan + implement (normal-mode first; ai-maestro-mode once
#75 lands). Do NOT build the fleet-wide auto-restart before the user confirms the disruption.

## Approval log

PROJECT-scope feature (janitor's own repo), requested by the USER this session ("the janitor must
exit and restart all agents after changing the settings.json …"). HIGH-BLAST-RADIUS (auto-restarts
the user's Claude sessions with a permission-bypass flag) → held for explicit USER confirmation of
the disruptive behavior before implementation, and blocked on ai-maestro#75 for the ai-maestro path.
