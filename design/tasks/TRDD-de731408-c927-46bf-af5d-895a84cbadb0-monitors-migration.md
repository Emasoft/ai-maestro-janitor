# TRDD-de731408-c927-46bf-af5d-895a84cbadb0 — Migrate heartbeat from `CronCreate` skill to plugin `monitors:` manifest key

**TRDD ID:** `de731408-c927-46bf-af5d-895a84cbadb0`
**Filename:** `design/tasks/TRDD-de731408-c927-46bf-af5d-895a84cbadb0-monitors-migration.md`
**Tracked in:** this repo (design/tasks/ is git-tracked)
**Status:** Not started
**Originated:** 2026-05-02 (after reviewing Claude Code changelog 2.1.83 → 2.1.126)

---

## Origin

Claude Code v2.1.105 (released 2026-04-13) added a top-level `monitors:`
manifest key for plugins:

> Added background monitor support for plugins via a top-level `monitors`
> manifest key that auto-arms at session start or on skill invoke

This is the feature the janitor plugin has been emulating since day one.
The plugin's entire bootstrap surface — `/janitor-arm` skill, 7-day expiry
tracking in `.janitor/state/heartbeat-armed-at.ts`, the `[janitor-renew]`
nudge inside `scripts/dispatch.sh`, the renewal-threshold knob in
`userConfig`, the SessionStart hook reminder, the troubleshooting advice
in README — all exists because `CronCreate` cannot be invoked from a hook
or a skill auto-fire. **Only an in-session model turn can call it.** The
2.1.105 manifest key delegates that bootstrap to the harness, not the
model.

If the migration works as the changelog suggests, this TRDD's deliverable
is a substantially smaller plugin: drop the arm/disarm/renew dance,
declare a monitor in `plugin.json`, ship.

## Open questions (block migration until answered)

1. **Schema of `monitors:`.** What does a `monitors` block look like in
   `plugin.json`? Does it accept a cron expression, an interval in
   seconds, or both? Does the prompt body interpolate
   `${CLAUDE_PLUGIN_ROOT}` like the `command:` field of a hook does?
2. **Lifecycle.** "Auto-arms at session start or on skill invoke"
   suggests two trigger points. Is the monitor *re-armed* on every
   session start, or arming-once persists durably? What happens on
   `claude --resume` of a session that previously armed the monitor —
   does it survive (per v2.1.110's scheduled-task resurrection) or get
   re-created from the manifest?
3. **Recurrence and expiry.** `CronCreate` recurring jobs auto-expire
   after 7 days. Does a `monitors:` declaration auto-expire? If yes,
   does the harness silently re-arm before expiry, or does the plugin
   still need an in-session renewal? If no expiry, the entire `[janitor-renew]`
   logic in dispatch.sh becomes dead code.
4. **Rate-limit window behavior.** The current dispatch.sh relies on
   the property that cron fires queue during a 429 window and deliver in
   batch when it clears — that is what makes the `[janitor-resume]`
   pattern work. Do `monitors:` fires preserve that property?
5. **Prompt context delivery.** The current heartbeat fires arrive as
   *fresh user turns* (the cron prompt becomes a UserPromptSubmit-shaped
   event). Stdout from dispatch.sh becomes part of the model's context
   for that turn. Does a `monitors:` fire deliver the same way? If it
   skips UserPromptSubmit hooks, the plugin's idle-timer refresh in
   `on-prompt-submit.sh` would silently stop ticking on heartbeat fires.
6. **Concurrency / overlap.** What does the harness do when two monitor
   fires would overlap (long-running detector vs. a fast next-fire)? The
   current dispatch.sh uses internal-cadence guards
   (`last-run-<detector>.ts`) to avoid this; do they still apply?
7. **Configurability of `cron` expression at install time.** The
   plugin's `userConfig.heartbeat_cron` lets users tune to `*/10 * * * *`
   or `*/20 * * * *` for token-cost reasons. Does `monitors:` accept a
   userConfig-bound expression, or is it baked into the manifest?
8. **Disable / pause.** Today the user runs `/janitor-disarm` to pause
   the heartbeat. Does `monitors:` honor `claude plugin disable
   ai-maestro-janitor`? Is per-monitor toggling possible without
   uninstall?
9. **Backward compatibility.** What happens on Claude Code < 2.1.105
   when `plugin.json` declares a `monitors:` block? Silent ignore?
   Install error? If install error, the plugin needs a `min_version`
   field (currently absent from `.claude-plugin/plugin.json`).
10. **MCP server / tool exposure.** Does the monitor's prompt see the
    same tool surface as a normal user turn (Bash, Read, Write, etc.)?
    dispatch.sh needs Bash to fork detector scripts.

## Pre-work — research the schema

Cannot proceed with the implementation work below until the questions
above are answered. Concrete steps:

- [ ] Re-read the v2.1.105 entry on https://code.claude.com/docs/en/changelog.md
- [ ] Read https://code.claude.com/docs/en/plugins for the `monitors:`
      schema (likely living in the plugin reference docs by 2026-05)
- [ ] Search the official `claude-code-plugins` GitHub
      org for any first-party plugin shipping `monitors:` and study its
      manifest layout
- [ ] If docs are silent, file an upstream Anthropic question or open
      an issue against the docs repo
- [ ] If the schema turns out to NOT support cron expressions (interval-only),
      decide whether the loss of cron flexibility is acceptable; if yes,
      proceed; if no, this TRDD is shelved and the current `CronCreate`
      pattern remains canonical

## Migration plan (after questions are answered)

Phased to keep each step reversible.

### Phase A — feature flag

Add `userConfig.use_native_monitors` (boolean, default `false`). When
unset or `false`, the plugin behaves exactly as today. When `true`, the
SessionStart hook skips the "run /janitor-arm" reminder.

This phase ships first to confirm the flag itself doesn't break anything,
without yet declaring `monitors:` in the manifest.

### Phase B — declare `monitors:` in plugin.json

Add a top-level `monitors:` block (exact schema TBD from research).
Speculative shape:

```json
{
  "monitors": {
    "heartbeat": {
      "cron": "${CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON:-*/5 * * * *}",
      "prompt": "[janitor-heartbeat]\nbash ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.sh\nSurface stdout verbatim. `[janitor-resume]` = resume prior task. No output = silent. One pass, no sub-agents."
    }
  }
}
```

Verify on a test project: install the plugin, do NOT run `/janitor-arm`,
confirm the heartbeat starts firing on its own.

### Phase C — deprecate the arm/disarm skills

When `use_native_monitors=true`:

- `/janitor-arm` becomes a no-op that prints "monitors auto-armed by
  v2.1.105 manifest, no action needed"
- `/janitor-disarm` becomes a no-op that prints "to pause the heartbeat,
  run `claude plugin disable ai-maestro-janitor`"
- Remove the `[janitor-renew]` emission in dispatch.sh
- Remove the `heartbeat_renewal_threshold_days` userConfig entry
- Remove the SessionStart hook's "run /janitor-arm" reminder

### Phase D — flip the default

Once Phase B has shipped for a release cycle and no regressions surface,
change `use_native_monitors` default to `true` and update the README to
recommend native monitors as the canonical path. Keep the old path
behind the flag for one more release as an escape hatch.

### Phase E — drop the legacy code

Remove:
- `skills/janitor-arm/` (or convert to a no-op stub for users who still
  type the slash command out of habit)
- `skills/janitor-disarm/`
- `dispatch.sh`'s renewal logic (lines around the 6+ day check)
- `.janitor/state/heartbeat-armed-at.ts` and `heartbeat-renew-seen.txt`
  state files
- The `use_native_monitors` flag itself (now always-on)
- README's "## Auto-renewal of the 7-day cron" section

### Phase F — bump min Claude Code version

Update `.claude-plugin/plugin.json` to declare a minimum Claude Code
version of v2.1.105 (or whatever Phase D shipped against). Document the
break in CHANGELOG.

## Risks and open concerns

- **The 7-day expiry might still exist for `monitors:`.** If so, the
  renewal logic doesn't disappear, it just moves into the harness. The
  plugin still benefits (less code) but the win is smaller.
- **Cron expressions might not be configurable per-install.** If
  `monitors:` demands a static interval, the `heartbeat_cron`
  userConfig knob has to be dropped, which is a UX regression for
  users who want a 20-minute heartbeat to save tokens.
- **Backward-compat break.** Pre-2.1.105 users will lose the heartbeat
  if Phase D ships without a fallback. The Phase A feature flag covers
  the upgrade window but the `min_version` bump in Phase F is the real
  break point.
- **Discovery cost.** The pre-work block above is the gating risk: if
  the docs are silent on the unanswered questions, the migration might
  stall waiting for upstream clarification.

## Definition of done

- `monitors:` declared in `.claude-plugin/plugin.json` and verified to
  drive the heartbeat without `/janitor-arm` ever being run
- `[janitor-renew]` emission removed from dispatch.sh
- `heartbeat_renewal_threshold_days` removed from userConfig
- README updated: install section says "no manual arm step required";
  troubleshooting "Heartbeat stopped firing after 7 days" entry replaced
  with "If the harness lost the monitor, `claude plugin reinstall
  ai-maestro-janitor` should restore it"
- `min_version` declared in plugin.json
- CHANGELOG entry: "BREAKING: requires Claude Code v2.1.105+"
- All eight detectors continue to fire on schedule under the new
  delivery mechanism (verified via `.janitor/logs/dispatch.log`)
- End-to-end rate-limit recovery (the validated 2026-04-19 scenario in
  README) reproduces successfully under `monitors:`-driven fires

## Out of scope

- Changing the detector logic itself
- Migrating other CronCreate uses elsewhere (none in this plugin)
- Adding new detectors as part of this TRDD (separate tasks)
- Removing the GitHub Actions weekly-audit fallback (still useful for
  week-long gaps when no session is open)

## Cross-references

- Origin report:
  `reports/changelog-relevance/20260502_194736+0200-cc-2.1.83-2.1.126.md`
- Related changelog entries: v2.1.105 (`monitors:`), v2.1.110
  (`--resume`/`--continue` resurrects scheduled tasks)
- Affected files (for the eventual implementation):
  - `.claude-plugin/plugin.json`
  - `scripts/dispatch.sh`
  - `scripts/hooks/on-session-start.sh`
  - `skills/janitor-arm/SKILL.md`
  - `skills/janitor-disarm/SKILL.md`
  - `README.md`
  - `CHANGELOG.md`
