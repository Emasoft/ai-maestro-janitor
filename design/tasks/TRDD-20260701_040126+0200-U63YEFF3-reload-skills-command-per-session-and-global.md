---
trdd-id: U63YEFF3
title: /janitor-reload-skills (+ global) — reload STANDALONE non-plugin skills/commands, with --soft
column: complete
created: 2026-07-01T04:01:26+0200
updated: 2026-07-01T04:01:26+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: MEDIUM
effort: M
task-type: feature
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
impacts: []
attempts: 0
implementation-commits: [0cfa0ef]
---

# /janitor-reload-skills (+ global) — reload STANDALONE non-plugin skills/commands, with --soft

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-01

- **USER DIRECTIVE (verbatim intent):** "add a /janitor-reload-skills command (and the global
  version /janitor-global-reload-skills), that will execute the /reload-skills command of claude
  code that will reload skills and commands. this is a command necessary after a new skill is
  installed (either local scope/project scope or user scope), when the skill or the command is not
  included in any plugin but is standalone, so the /reload-plugins command of claude code is not
  useful. be sure to add the option --soft to this new janitor command too. and update
  the-skills-menu of the janitor plugin and any other documentation to make sure its visible to the
  agents and clear when to use it."
- **WHY:** CC's `/reload-plugins` reloads ONLY plugin-bundled skills/commands; a STANDALONE skill
  or command dropped into `~/.claude/skills`, `.claude/skills`, `~/.claude/commands`, etc. needs
  CC's `/reload-skills` instead. The janitor had no trigger for `/reload-skills`.
- **SHIPPED (this session, all tested):**
  - **Per-session `/janitor-reload-skills`** — skill `skills/janitor-reload-skills/SKILL.md` +
    backing `scripts/reload_skills_trigger.py` (mirror of `reload_trigger.py`): types
    `/reload-skills` into this session's own pane (iTerm osascript / tmux send-keys), `--soft`
    omits the ESC (enqueue vs interrupt), prints `RELOAD_SKILLS_FIRED` / `NO_ITERM`.
  - **Machine-wide `/janitor-global-reload-skills`** — skill
    `skills/janitor-global-reload-skills/SKILL.md` + `global_control_cli.py reload-skills`, which
    stamps a NEW never-cleared epoch generation in `skills-reload-needed.flag`
    (`global_state.set_skills_reload_flag` / `skills_reload_generation` — a SEPARATE flag file from
    the plugin `reload-needed.flag` so a plugin update never forces a skills reload, and vice-versa).
  - **Heartbeat wiring** — `dispatch.py _phase_skills_reload` emits a bare `[janitor-reload-skills]`
    once-per-session when the generation exceeds this project's `skills-reload-acked.ts` ack
    (per-project ack ⇒ no session starves another — the exact design of `_phase_plugin_reload`).
    `on-session-start.py` seeds `skills-reload-acked.ts` to the at-start generation (a fresh
    session already carries current skills → silent until a NEW global-reload-skills). The
    `janitor-arm` cron prompt gained the `[janitor-reload-skills]` → "silently run
    /janitor-reload-skills" clause.
  - **Shared substrate** — `terminal_trigger.send_self_command` / `build_tmux_steps` now
    parameterize `esc_first` (hard=ESC-interrupt / soft=enqueue) + multi-command sends (built for
    TRDD-LQU7OXXV's `--handoff`; `/reload-skills` reuses `esc_first`).
- **ROLLOUT CAVEAT (same as TRDD-RQ9FIFX6 / the memory markers):** the `[janitor-reload-skills]`
  marker is baked into the cron prompt at ARM time, so already-armed sessions honor it only after a
  re-arm (`/janitor-arm`) or the 7-day `[janitor-renew]`. Documented in the global skill.
- **THE-SKILLS-MENU:** the janitor has NOT yet adopted the-skills-menu (only planned —
  TRDD-cf15d412). "Visible to agents" is satisfied via the skill `description:` fields, the CLAUDE.md
  skills map, and the README skill list. When cf15d412 lands, add these three commands to the menu.
- **NEXT ACTION:** none — shipped. If extending: a genuinely daemon-DRIVEN fleet reload (inject into
  every RUNNING pane immediately, no rollout lag) belongs in TRDD-ME8V2YJF, which reuses the same
  `terminal_trigger`/`fleet_inject` substrate.

## Why

`/reload-plugins` ≠ `/reload-skills`. Standalone (non-plugin) skills/commands installed at any scope
need `/reload-skills`; there was no janitor trigger for it. The per-session command is the workhorse
(immediate, `--soft`-capable); the global variant reloads standalone skills fleet-wide by stamping a
generation every session honors on its next heartbeat — the proven, low-risk `[janitor-reload]`
pattern, NOT keystroke injection into other panes.

## Acceptance

- `/janitor-reload-skills` types `/reload-skills` (ESC→ hard, enqueue with `--soft`) at this pane;
  `RELOAD_SKILLS_FIRED` on success, `NO_ITERM` when no automatable terminal.
- `/janitor-global-reload-skills` stamps ONLY `skills-reload-needed.flag` (never the kill-switch or
  pause); each live session emits `[janitor-reload-skills]` once and runs `/janitor-reload-skills`.
- The two reload generations (plugin vs skills) are independent (separate flags + acks).
- Real unit tests: reload_skills_trigger (hard/soft/no-iterm/injection), global_state skills-reload
  family, global_control reload-skills, dispatch `_phase_skills_reload` (emit/ack/no-starvation/
  independence). ruff + pyright clean.

## Notes and lessons learned
