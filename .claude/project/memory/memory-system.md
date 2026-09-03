---
name: memory-system
description: "how does the wiki-memory system work / where do memories live / how to recall before acting / what is memgrep / how do I install the memory system in a new project / why did my PROJECT memory page get flagged for a leak / LOCAL vs PROJECT vs USER scope precedence / memgrep binary is stale on this host / another host reports lint errors I cannot reproduce / cargo install does not roll forward with the plugin update / memgrep refused my write because the atom is too big / can I raise the atom budget knob / add-atom inserts a new atom in the wrong place / atom-after-footer lint defect never converges / what is the private user-memory subsystem / how does janitor-memory-user-share work / what is the retro-lesson chore and why does it exist / a superseded atom has no lesson attached / does memgrep ever refuse a write outright / publish-globally-missing never drains / should I add publish-globally to repair_defect / widen a precheck predicate signature / scope=None suppresses a finding in a fail-open module / an argument whose failure mode has zero live instances / code implements a variant nothing exercises"
ocd: 2026-06-13
lmd: 2026-09-03
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: janitor
  globs: ["scripts/memgrep/**", "scripts/lib/memory_*.py", ".claude/project/memory/**"]
  originSessionId: memory-audit-draft
publish-globally: false
split-lineage: c89f02722a424b5385204031e5db35ce
---


# The wiki-memory system (janitor functionality)

The janitor **owns the reference implementation** of the markdown wiki-memory
system — the engine (`memgrep`), the three authoring/recall/update skills, the
two heartbeat detectors that police it, and the recall-discipline rule. Other
plugins/projects adopt it; this page is the component page for that functionality
as the janitor ships it.

**Why:** sessions are stateless across context windows; a durable, symptom-indexed
markdown corpus + a recall engine lets a future session find "have we hit this
before?" instead of re-deriving (badly) what was already learned. The whole
discipline is "index by the QUESTION, not the answer" — a memory is found from
the SYMPTOM (the user's words / the error text), and the note's body holds the
fix.

**How to apply:** run RECALL before debugging a recurring problem, before a design
decision, before editing a file in an unloaded area, and before MEMORIZE (so you
update the right page instead of duplicating). Then MEMORIZE only what is
NON-OBVIOUS and reusable; UPDATE non-destructively when a fact changes.


## Parts

This page is the overview; the detail lives in four sub-pages (split
2026-09-03, the page had grown past the split cap):

- [[memory-system-scopes-and-format]] -- the LOCAL/PROJECT/USER 3-scope model
  and the note frontmatter/format every wikimem page follows.
- [[memory-system-tooling-and-protocol]] -- the `memgrep` engine, the three
  authoring/recall/update skills, the heartbeat detectors that police the
  wiki, and the hub/aspect/component tier layer + the link law.
- [[memory-system-editor-gotchas]] -- the private user-memory store, and the
  wikimem editor's accumulated operational gotchas (footer anchor, atom
  budget, edit_project_scope, publish-globally, the retro-lesson chore,
  per-host memgrep version skew).
- [[memory-system-superseded-history]] -- the retired predecessor atoms of
  the publish-globally reasoning chain, kept per the correction protocol.

## Applies to

- [[memory-system-scopes-and-format]]
- [[memory-system-tooling-and-protocol]]
- [[memory-system-editor-gotchas]]
- [[memory-system-superseded-history]]

## See also

## See also

- [[claude-md-canonical-form]] — CLAUDE.md is the index over this corpus; what may live in it, and the migration contract.
- [[feedback_memory_system_is_more_than_memgrep]] — the system is {tool · rules ·
  skills · hooks}, not just the memgrep binary.
- `[[reference_memgrep_links_to_from_semantics]]` — the `links --to`/`--from`
  directional-flag gotcha (intuition inverts them).
- [[janitor-is-not-a-role-agent]] — why PROJECT scope is the ONLY memory that
  survives a maintainer-agent takeover (it clones the repo; everything uncommitted
  is lost), and why the janitor carries no role plugin.
- `[[wikimem-retrieval-engine]]` — how recall actually RANKS and PRINTS: the
  two-hop contract, the tiered scorer, why a locator is an identity rather than a
  path, and the lint severity model.
- [[reference_cpv_dotclaude_gitignore_fp]] — why memory lives under `.claude/` in
  the first place, and the CPV `--strict` false-positive that decision trips.

## Notes and lessons learned
