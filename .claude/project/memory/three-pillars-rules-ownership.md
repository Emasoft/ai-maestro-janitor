---
name: three-pillars-rules-ownership
description: "which repo owns trdd-design-tasks / prrd-design-rules / universal-kanban / I edited a rule file in the repo and nothing changed on disk / two plugins install rules with the same filename / an agent seems to be reading two different generations of the same governance rule / where do the aimaestro-* overlays come from / a rule in ~/.claude/rules matches no repo / who owns aimaestro-trdd-approval aimaestro-prrd-governance aimaestro-kanban-multiagent / why do overlay filenames matter as a cross-repo contract / does editing a rule file in the repo change anything on disk without a stamp file / what is install-governance-rules.cjs stamp guard / are trdd-approval-tiers.md and manager-approval-defaults.md orphan files / does the janitor's orphaned-rule sweep ever delete a foreign rule file / which repo installs universal rules at user scope versus workdir scope"
ocd: 2026-07-22
lmd: 2026-07-22
metadata:
  node_type: memory
  type: project
  tier: component
publish-globally: false
---

# 3-pillars rules — who owns which file, and where it lands

## Governed by

- [[janitor-architecture]] — the janitor installs the universal half via
  `rules_installer`. This page owns the CROSS-REPO ownership map, which no single
  repo's code can show you.

## Three tiers, three owners (verified 2026-07-22)

| tier | files | ships to | owner |
|---|---|---|---|
| **IND universal** | `trdd-design-tasks.md`, `prrd-design-rules.md`, `universal-kanban.md` | `~/.claude/rules/` (user scope) | **janitor** (issue #73, TRDD-DE9757LJ) |
| **DEP harness overlay** | `aimaestro-trdd-approval.md`, `aimaestro-manager-approval-defaults.md`, `aimaestro-prrd-governance.md`, `aimaestro-kanban-multiagent.md`, `aimaestro-agent-rules.md` | each agent **workdir**'s `.claude/rules/` | **ai-maestro server** (`rules/aimaestro/` + `lib/agent-rules-seed.ts`) |
| **retired** | pre-split copies of the two universal ones + `trdd-approval-tiers.md`, `manager-approval-defaults.md` | `~/.claude/rules/` | ai-maestro-plugin (CORE) — retirement filed as `ai-maestro-plugin#35` [^2] |

The owner's directive (2026-07-22): universal → janitor repo; harness-specific →
ai-maestro repo, *"since it keeps the rules right with the ai-server code that
enforces it."*

## The overlay filenames are a CROSS-REPO CONTRACT

Each IND base names its overlay **in prose** — that pointer is the only way a
reader gets from base to overlay, because the overlay seeds into a *workdir*,
not user scope, so it is invisible from anywhere else.

| IND base (janitor) | names |
|---|---|
| `prrd-design-rules.md` | `aimaestro-prrd-governance.md` |
| `universal-kanban.md` | `aimaestro-kanban-multiagent.md` |
| `trdd-design-tasks.md` | `aimaestro-trdd-approval.md` (added `6417b47`) |

ai-maestro accepted the pin on `ai-maestro#83` and is adding a CI test asserting
all four `aimaestro-*.md` filenames, so a rename fails there before it can orphan
a pointer here. **Do not "tidy" these names.**

## Why this is hard to see from inside one repo

Each side is half-blind by construction: the janitor cannot see the workdir
overlays (they seed into agent workdirs it never visits), and ai-maestro cannot
see what CORE installs at user scope. Two agents each verified their own half and
each concluded the other half was missing. The only reliable move is to measure
the INSTALLED bytes on disk, not to reason from either repo's installer. [^1]

## Notes and lessons learned

[^1]: [id:ATOM-3PRO-0001, status:valid, keywords:"rule_file_edit_has_no_effect stamp_guarded_installer_preserves no_stamp_file installer_is_inert", ocd:2026-07-22, lmd:2026-07-22]
  DO NOT conclude a plugin's rule shipment reaches disk because its installer
  runs at SessionStart, BECAUSE a stamp-guarded installer (CORE's
  `install-governance-rules.cjs`) overwrites ONLY bytes it itself last wrote, and
  with `~/.claude/rules/.ai-maestro-governance-stamps.json` absent it preserves
  everything and installs NOTHING — so editing that repo's rule changes no
  machine, silently and forever. DO check for the stamp file and diff the live
  bytes against the repo before reasoning about which generation is in force.

[^2]: [id:ATOM-3PRO-0002, status:valid, keywords:"rule_in_home_matches_no_repo orphan_rule_double_coverage two_generations_loaded agent_workdir_user_scope", ocd:2026-07-22, lmd:2026-07-22]
  DO NOT assume every file in `~/.claude/rules/` belongs to some current repo,
  BECAUSE `trdd-approval-tiers.md` (231 ln) and `manager-approval-defaults.md`
  (97 ln) match NONE of the three (CORE 653/304, ai-maestro 898/313, janitor
  none) — they are orphans from an earlier generation, and being user-scope they
  load INSIDE agent workdirs alongside the newer `aimaestro-*` overlays, so an
  agent reads two generations of the same rule at once. DO diff a rule against
  every candidate repo before attributing it, and remember retiring an
  installer's list does not delete what it already wrote.

[^3]: [id:ATOM-3PRO-0003, status:valid, keywords:"janitor_will_not_delete_foreign_rule provenance_marker_gate orphan_sweep_skips_unmarked", ocd:2026-07-22, lmd:2026-07-22]
  DO NOT expect the janitor's orphaned-rule sweep to clean a stale governance
  rule it did not install, BECAUSE `remove_orphaned_rules` is
  provenance-marker-gated so it can never delete a user's own or another
  plugin's file — correct by design, and it means nothing automatic will ever
  remove such an orphan. DO treat that deletion as a deliberate,
  human-authorized act, after the owning plugin has confirmed it no longer
  claims the file.
