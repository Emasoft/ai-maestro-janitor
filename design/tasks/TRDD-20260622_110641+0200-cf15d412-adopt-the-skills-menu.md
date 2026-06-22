---
trdd-id: cf15d412-ed7c-46bd-96b8-093f923a6572
title: Adopt the-skills-menu architecture — progressive skill discovery for the janitor's 38 skills
column: backburner
created: 2026-06-22T11:06:41+0200
updated: 2026-06-22T11:06:41+0200
current-owner: claude-janitor-dev
task-type: refactor
release-via: publish
priority: 5
relevant-rules: []
test-requirements: [unit]
impacts: [public-api]
external-refs: []
---

# Adopt the-skills-menu architecture (progressive skill discovery)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-22

USER (2026-06-22, explicitly "no rush"): *"the janitor should embrace the the-skills-menu
architecture (one skill listing all the others skills inside the plugin, so the agents can
discover and use the skills only when they need them. a sort of 'progressive discovery for
agents'). I made the CPV plugin migrating to this architecture the plugins that adopt the
publish pipeline canon, but you can directly ask the cpv migrate agent to implement it.
But I'm not sure you are compliant with the CPV validation rules right now. verify first.
but make a TRDD out of it, there is no rush."*

### WHAT
The janitor ships **38 skills** — too many to keep all their descriptions resident in every
agent's context. The-skills-menu pattern adds ONE entry-point skill (`the-skills-menu`) that
LISTS all the others with one-line intents; an agent loads the full skill only when it needs
it (progressive discovery), instead of carrying 38 descriptions. CPV made this the canon for
publish-pipeline plugins.

### HOW (the migration path)
- CPV ships `the-skills-menu` + `the-skills-menu-create` skills, and a migrate agent. The
  canonical route: invoke the CPV migrate flow (`/cpv-upgrade-plugin` or the the-skills-menu
  create skill) to generate the menu skill + wire the intent→skill map for all 38 janitor
  skills. Do NOT hand-roll it — use the CPV tooling so it matches canon (and so the publish
  gate's the-skills-menu adoption check passes).
- DERIVED tasks (evaluate before doing):
  1. **Verify CPV compliance FIRST** (user's instruction) — a full `cpv-remote-validate
     plugin . --strict` must be GREEN before/after. (In progress in the v0.16.0 publish:
     allowlisted by-design persistence FPs, fixed agent ref path, trimming oversized skills,
     excluded design/ from markdownlint. Finish that publish before starting this.)
  2. The menu skill must stay UNDER the CPV skill-body/description token limits (the same
     limits that are biting janitor-memory-split/consolidate now) — so the menu is terse,
     one line per skill, detail in the listed skills.
  3. Re-check every existing skill's `description:` is a crisp intent line (the menu reads
     from these) — several are currently over the 200-token cap.
  4. The control/heartbeat skills (janitor-arm, the memory markers) are dispatched by the
     CRON prompt, not discovered via the menu — confirm the menu does not break that path.
  5. Update README + CLAUDE.md skills inventory to point at the menu as the entry point.

### WHY
Progressive discovery cuts the per-agent context cost of a 38-skill plugin and aligns the
janitor with the publish-pipeline canon (so it stops drifting from CPV's the-skills-menu
adoption check). Net: agents see one small menu, load only what they need.

### NOT NOW
`column: backburner` — the user said no rush. Promote to `todo` only after the v0.16.0
publish (the fail-safe split + size limit + subconscious agent) ships and CPV is green.

## Notes and lessons learned
