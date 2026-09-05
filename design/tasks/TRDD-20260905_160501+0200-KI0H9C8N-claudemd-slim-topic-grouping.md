---
trdd-id: KI0H9C8N
title: claudemd_slim cannot read metadata.topic so hub grouping degenerates to a flat list
column: backburner
created: 2026-09-05T16:05:01+0200
updated: 2026-09-05T16:05:01+0200
current-owner: main-session
task-type: refactor
priority: low
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [claudemd-slim, wikimem, index-rendering]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [janitor#299]
---

# claudemd_slim cannot read metadata.topic so hub grouping degenerates to a flat list

## Why

`claudemd_slim`'s `PageInfo` carries only `name, filename, description, tier,
lmd, wikilinks` — `metadata.topic:` is invisible to it, appearing in the
module only in a docstring, a comment, and the literal `"**Other topics**"`
heading. `render_index` groups by non-overview `tier: hub` pages, and on this
project's own 69-page PROJECT corpus that yields exactly two hubs
(`amp-messaging`, `password-and-credential-system`). With only 2 hubs the
index is structurally incapable of being a real grouping — it degenerates to
two small groups plus ~60 entries dumped under a single "Other topics"
heading, and nothing encourages the hub count to grow as the corpus grows.
By contrast this project's own topic-grouped generator produces 11 named
sections (`architecture-and-runtime`, `agents`, `teams-and-governance`,
`messaging`, `plugins-and-marketplaces`, `security-and-auth`,
`design-system`, `reliability-patterns`, `tooling-and-testing`, `overview`)
over the same pages, because `metadata.topic:` is a flat, closed vocabulary
every page can carry independently — it does not have the "too few hubs"
failure mode.

## What

- `scan_pages`: read `metadata.topic:` into `PageInfo`.
- `render_index`: if any page carries a `topic`, group by topic (order by a
  caller-supplied or alphabetical topic order), with untopiced pages falling
  under the existing `**Other topics**` heading. If no page carries a topic,
  render exactly as today (fully back-compatible — a corpus with no `topic:`
  anywhere renders byte-identically).
- Keep the overview page first regardless of grouping mode.
- Note: if janitor#298 (digest the rendered body, not a hand-picked field
  list) lands first, this change needs no separate digest work — `topic`
  reaches the digest through the body automatically. Landing #298 first makes
  this one strictly cheaper.

## Acceptance criteria

- [ ] A corpus where every page's `metadata.topic:` is absent renders
      byte-identically to the current output.
- [ ] A corpus with `metadata.topic:` set on pages groups the rendered index
      by topic instead of by hub, with untopiced pages under "Other topics".
- [ ] The overview page still renders first in both grouping modes.

## Notes and lessons learned
