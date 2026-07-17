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
