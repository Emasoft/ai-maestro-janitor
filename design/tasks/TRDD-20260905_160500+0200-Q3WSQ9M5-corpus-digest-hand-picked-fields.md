---
trdd-id: Q3WSQ9M5
title: corpus_digest hashes a hand-picked field subset instead of the rendered body
column: backburner
created: 2026-09-05T16:05:00+0200
updated: 2026-09-05T16:05:00+0200
current-owner: main-session
task-type: bugfix
priority: low
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [claudemd-slim, wikimem, cache-invalidation]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [janitor#298]
---

# corpus_digest hashes a hand-picked field subset instead of the rendered body

## Why

`claudemd_slim.corpus_digest` is the freshness probe deciding whether the
janitor rewrites `CLAUDE.md`'s wikimem index. Its docstring claims it mixes
"exactly the two fields the rendered index actually shows" (`name`,
`description`), but `render_index` -> `_entry` actually emits five properties:
`name`, `filename`, `_short_desc(description)` (not the full description),
`tier`, and `wikilinks`.

Two measured failures on the live corpus:
- **Over-fires:** appending text to a page's `description:` past the first
  ` / ` segment flips the digest while the rendered body is byte-identical
  (`git diff --stat` = 1 insertion/1 deletion, the marker line only). This is
  the exact `CLAUDE.md` cache-bust the docstring says the digest exists to
  prevent — `CLAUDE.md` sits in the cached prompt prefix of every turn.
- **Under-fires (more serious, silent, permanent):** a page file rename or a
  `tier: hub` -> `tier: component` change both alter the rendered body but do
  not change the digest, so `index_is_stale` returns `False` forever and the
  stale index is never regenerated.

## What

- Extract the body-producing half of `render_index` into its own
  `_render_body(pages, memdir_rel)` function.
- Redefine `corpus_digest(pages, memdir_rel)` as
  `sha256(_render_body(pages, memdir_rel))[:12]` instead of hashing
  `(name, description)` by hand.
- Have `render_index` call `_render_body` once and embed
  `corpus_digest(pages, memdir_rel)` in the fence header (digesting
  `render_index`'s own output is circular since it embeds the digest).
- Swap the digest input away from `p.description` (full string) so drift
  between the digest and the renderer becomes structurally impossible instead
  of a hand-synced field list.

## Acceptance criteria

- [ ] `corpus_digest` is unchanged when a page's `description:` is edited
      after the first ` / ` segment (no rendered-byte change -> no rewrite).
- [ ] `corpus_digest` changes when a page is renamed, and separately when a
      non-overview hub's `tier:` changes.
- [ ] Reverting `corpus_digest` to the current `(name, description)` mix
      reddens both regression tests above.

## Notes and lessons learned
