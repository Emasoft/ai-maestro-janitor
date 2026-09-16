---
trdd-id: EBVZJ6GU
title: convert agent-relevant janitor commands to skills — commands are invisible to the agent, skills are not
column: complete
created: 2026-07-21T14:52:59+0200
updated: 2026-07-21T16:45:00+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
scope: project
implementation-commits: [63637d9, 4d0e31c]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-21

**RELEASE-DAY CORRECTION (2026-07-21, during the v0.57.0 publish).** Two facts below were WRONG and
are fixed:
1. **"NO test references the removed command files" was FALSE.** `tests/test_oauth_helper_scripts.py::
   test_refresh_logins_command_shipped` asserted `commands/janitor-refresh-claude-logins.md` exists.
   The publish test-gate caught it. Lesson: grepping `tests/` for `commands/<name>.md` must be done
   PER name (the LOAD-BEARING-FACTS line even said "Verify none assert commands/<name>.md exists" —
   it was not actually run for all 7).
2. **`janitor-refresh-claude-logins` could NOT become a skill under that name.** CPV
   `validate_skill_comprehensive.py` **rule N11 MAJORs any skill whose name contains "claude"**
   (`if "claude" in name_lower` — an anti-impersonation guard; commands carry no such rule). This is
   the SAME reason TRDD-3T4DZWXA shipped it as a command. **USER decision (2026-07-21): RENAME it
   `janitor-refresh-cc-logins`** — drop "claude" so it ships as a DISCOVERABLE skill (the point of
   this TRDD) while passing N11. So the final tally is **convert 6 as-named + 1 renamed (claude→cc);
   keep 3**. The rename rippled to 12 code refs (daemon/detectors/rotator/supervisor/lifetime-status/
   dispatch/cascade + auto-manage-oauth skill), 3 test files, and the `.integrity` manifest.

**SHIPPED (skills 63637d9, command removals 4d0e31c; rename + fixes this release) — verified.** 7
commands converted to skills (1 renamed per above); only the 3 `janitor-memory-user-*` commands
remain (privacy). **NEXT ACTION:** none for the conversion — COMPLETE at v0.57.0.

**FOLLOW-UP (non-blocking, deferred to the memory agent):** the PROJECT memory page
`oauth-rotation-renew-reauth.md` still names `/janitor-refresh-claude-logins` and its `[^9]` lesson
(ATOM-MG05-0009) still concludes "ships as a COMMAND, never a skill" — now SUPERSEDED (it is a skill
renamed to drop 'claude'). The N11 rule fact stays valid; the command-vs-skill CONCLUSION must be
demoted via the correction protocol. Hand to `janitor-memory-subconscious-agent` (transaction+verify
gate) rather than a hasty hand-edit of a shared git-tracked page.

**CAVEATS (not blockers):** (1) plugin file changes need a `/reload-plugins` (or a fresh session) to
go live in a RUNNING session — the files are correct; discovery is on next load. (2) UNRELEASED —
these commits sit on repo HEAD, not in the released v0.56.0; they ship + become live for installs on
the next janitor release. (3) The CLAUDE.md auto-generated project-map fence still names some `/name`
as if commands — it regenerates separately (repomap) and its `/name` refs already resolve to skills;
left untouched deliberately.

**DECISION (owner, 2026-07-21):** convert the janitor's agent-relevant slash-COMMANDS to SKILLS,
because a plugin's commands are NOT surfaced to the agent's context (proven empirically this session:
asked to list the 10 janitor commands from context alone, I named 7, MISSED 2 real ones, and
FABRICATED 3 that don't exist), whereas skill `description`s ARE surfaced (discovery channel) and
skills are ALSO user-slash-invocable (`/name` keeps working — Skill tool: "Users may ask by name
`/<name>`"). Net: agent gains awareness + invocability, user loses nothing.

**SCOPE — convert 7, KEEP 3 (owner chose "Convert 7, keep 3"):**
- CONVERT → skills: `janitor-findings`, `janitor-show-global-status`, `janitor-token-report`,
  `janitor-token-attribution`, `janitor-identify-environment`, `janitor-memory-frequency`,
  `janitor-refresh-claude-logins` → **RENAMED to `janitor-refresh-cc-logins`** (CPV N11 forbids
  "claude" in a skill name; see the RELEASE-DAY CORRECTION above).
- KEEP as commands (HARD CONSTRAINT — privacy): `janitor-memory-user-{add,search,share}`. Their
  privacy IS the command+hook mechanism: `on-prompt-submit-user-mem.py` returns `decision:block` to
  ERASE the typed prompt so the private text NEVER reaches the model. A skill invocation ALWAYS
  routes through the model → the private text would land in context → leak. There is no
  agent-invisible skill. DO NOT convert these, and DO NOT touch that hook.

**LOAD-BEARING FACTS / GOTCHAS:**
- Commands are auto-discovered from `commands/`; there is NO manifest registration to edit (verified:
  plugin.json has no command roster). Same for skills (auto-discovered from `skills/<name>/SKILL.md`).
- NO name collisions: none of the 7 target names already exist under `skills/`.
- Backing scripts stay put and unchanged (`findings_cli.py`, `token_report.py`, `fleet_status.py`,
  `identify_environment.py`, `memory_settings_cli.py`, the oauth refresh script). Their tests
  (`test_identify_environment.py`, `test_token_report_*`, `test_findings_ledger.py`, the oauth
  tests) target the SCRIPTS, not the command files — so they stay green. Verify none assert
  `commands/<name>.md` exists.
- Arg passing differs: a command uses `$ARGUMENTS`/`$1`; a skill receives args via the Skill tool's
  `args`, surfaced as an `ARGUMENTS:` block. Adapt each body accordingly.
- `janitor-refresh-claude-logins` is INTERACTIVE (OAuth/browser login, TTY). The skill must be honest
  that it GUIDES/triggers a human-driven login, not that the agent performs it headlessly.
- 17 cross-references to the 7 names to reconcile: CLAUDE.md ×9, README.md ×5,
  `skills/janitor-auto-manage-oauth-on/SKILL.md` ×3. `/name` refs keep resolving (now to the skill);
  update prose that calls them "commands" to "skills".

## Derived tasks (DERIVED, depth-1)

- After conversion, RUN the `cross-scope-reference-drift` detector — it flags a `/<name>` reference
  whose definition no longer resolves to a tracked file. Prove 0 dangling refs to the 7 names.
- Update CLAUDE.md's command/skill inventory prose + the auto-generated project map region is
  regenerated separately (do not hand-edit inside the fences).
- Confirm the privacy hook (`on-prompt-submit-user-mem.py`) and the 3 user-mem commands are
  UNTOUCHED (grep: the 3 command files still exist; the hook file unchanged).

## Verification

Each of the 7 skills: `/name`-invocable, frontmatter has `name` + a `description` that says WHEN to
use it, body runs the same backing script with the same effect. `ls commands/` shows exactly the 3
user-mem commands remaining. `uv run pytest` green (backing-script tests unaffected). The
`cross-scope-reference-drift` detector reports 0 dangling refs. `ruff check` green. Commit per phase,
do not push.

## Notes and lessons learned
