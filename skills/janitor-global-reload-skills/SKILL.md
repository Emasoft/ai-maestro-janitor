---
name: janitor-global-reload-skills
description: Machine-wide reload of freshly installed STANDALONE (non-plugin) skills and commands across EVERY running Claude Code session, without visiting each one. Stamps a machine-wide skills-reload generation; each session's next heartbeat emits [janitor-reload-skills] once and runs /reload-skills locally, so a standalone skill/command added at local/project/user scope loads fleet-wide. The all-sessions sibling of /janitor-reload-skills (which reloads only THIS session). Note /reload-skills is DISTINCT from /reload-plugins — the latter reloads only plugin-bundled skills. Trigger with /janitor-global-reload-skills, "reload skills everywhere", "reload standalone skills in all sessions".
---

# Janitor global reload-skills (machine-wide standalone-skills reload)

## Overview

Reloads **STANDALONE** (non-plugin) skills and commands across **every** running
janitor session — the machine-wide sibling of `/janitor-reload-skills` (this session
only). Use it after installing or editing a standalone skill/command that many live
sessions should pick up, so you don't have to run `/reload-skills` in each pane by
hand.

Mechanism (mirrors the proven `[janitor-reload]` plugin-reload path — a flag every
session honors on its own heartbeat, NOT a keystroke injected into other panes):

- this skill stamps a machine-wide **skills-reload generation** (an epoch in
  `skills-reload-needed.flag`) via the backing CLI;
- each armed session's next heartbeat (`dispatch.py` `_phase_skills_reload`) compares
  that generation to its own per-project ack and, if newer, emits a bare
  `[janitor-reload-skills]` marker **once** — the standing heartbeat posture maps that
  marker to "silently run `/janitor-reload-skills`", which types `/reload-skills` into
  that session's pane;
- the generation is **never cleared** and each session acks independently, so no
  session starves another — every live session reloads exactly once per bump.

This reloads only **non-plugin** skills/commands. For plugin-bundled skills use the
plugin auto-update path (which emits `[janitor-reload]` → `/reload-plugins`).

## When NOT to use

- Reload standalone skills in only THIS session → `/janitor-reload-skills` (local;
  soft/enqueue by default, `--hard` for immediate).
- Reload PLUGIN-bundled skills/commands → `/reload-plugins` (or wait for the janitor
  auto-update, which triggers it fleet-wide via `[janitor-reload]`).

## Instructions

1. Stamp the machine-wide skills-reload generation via the backing CLI (single source
   of truth for the flag path — never write the flag file by hand):

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py" reload-skills "via /janitor-global-reload-skills"
   ```

2. Report the one-line result the CLI prints. Each live session picks up the marker on
   its next heartbeat (≤ the cron interval, typically ~5 min) and reloads once.

## Rollout caveat

The `[janitor-reload-skills]` marker is baked into the heartbeat cron prompt at
**arm time**, so a session whose cron was armed BEFORE this shipped will not act on the
marker until it re-arms (`/janitor-arm`) or the 7-day auto-expiry forces a
`[janitor-renew]`. In such a session, run `/janitor-reload-skills` (or `/reload-skills`)
once by hand. New sessions armed after this version honor the marker automatically.

## Output

One line confirming the machine-wide skills-reload was requested, with the reminder
that each live session reloads once on its next heartbeat and the rollout caveat for
pre-existing crons.

## Error Handling

- `${CLAUDE_PLUGIN_ROOT}` unset → abort "plugin not installed".
- The CLI never blocks; it writes the flag atomically and returns immediately.
- The generation is monotonic and never cleared by a reader, so re-running it simply
  bumps the generation and triggers another one-time reload everywhere.

## Examples

```text
User: /janitor-global-reload-skills
User: reload standalone skills in every session
User: I added a user-scope command — reload it everywhere
```

## Scope

ONLY stamps the machine-wide skills-reload generation via the backing CLI. It does NOT
type into other panes, does NOT touch the daemon kill-switch or pause flags, does NOT
disarm any cron. Each session self-applies `/reload-skills` on its own heartbeat.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/global_control_cli.py` — backing CLI (`reload-skills`
  stamps the generation; also `disarm`/`arm`/`pause`/`unpause`/`status`).
- `/janitor-reload-skills` — the per-session variant (soft/enqueue by default;
  `--hard` for immediate).
- `/janitor-reload-plugins` — the sibling for PLUGIN-bundled skills/commands.
