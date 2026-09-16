# HARVEST background — deep reference

This is the deep reference for `/janitor-memory-harvest`. The SKILL.md is the
checklist; this doc is background context moved out to keep the skill under the
CPV token cap.

## The two memory systems, in full

- **The BUFFER** — `MEMORY.md` + the raw `*.md` notes at the scope ROOT. This is
  Anthropic/harness-owned (the harness `# Memory` directive writes it and auto-loads
  it every session; Claude Code keeps evolving it). It is an unorganized,
  freely-growing buffer. **The janitor NEVER stubs, trims, or modifies it.**
- **The WIKI** — the curated pages under `memory/wikimem/`: rich frontmatter
  (`ocd`/`lmd`/`tier`), `[^N]` lessons, bidirectional links, git-versioned,
  memgrep-indexed.

HARVEST is the BRIDGE: it incrementally finds NEWLY-created buffer memories and
**MIRRORS** each into the wiki as a SEPARATE curated page. The same fact lives in
BOTH files (duplication is accepted, by USER decision — "separate parallel
copies"). A per-scope watermark tracks what has been mirrored so the pass is
idempotent.

## CREATE-a-new-page discipline (moved from the SKILL body, step 2)

When no existing wiki page covers the subject, CREATE `wikimem/<name>.md` per the
`/janitor-memory-write` discipline:

- **One subject per page; same-theme memories share ONE page.**
- **NAME = the broad TOPIC, never the buffer note's description (TRDD-NM4TPCQ9).** Harvest is
  where this failure happens most: mirroring ONE buffer note tempts a one-note page named
  like the note (`implementation-of-duckdb-ingestion-of-otel-logs`). Wrong — name the page
  for the topic many future atoms will share (`agents-tracing`, `claude-telemetry-and-logging`).
  A candidate name that reads like a sentence about one fact fails; broaden it.
- **Complete frontmatter** — `name`, symptom-indexed `description`, `ocd`, `lmd`,
  `metadata.{node_type: memory, type, tier}`.
- **Tier expand/reduce** — a general rule → `aspect` (radiates `## Applies to`); one
  element → `component` (receives `## Governed by`); a functionality overview → `hub`.
- **Bidirectional links** — every `[[link]]` wired on BOTH ends (the link law);
  `## See also` for lateral relations.
- **Atomic memories, each with its own `## Notes and lessons learned`** section.
- **Scope routing** — machine-private (local paths / hostnames / secrets) → LOCAL;
  project-shared (no secrets) → PROJECT; cross-project → USER; **UNSURE → LOCAL**.

## Current corpus status — DORMANT today

Every existing top-level `memory/*.md` already carries full wikimem frontmatter
(it was curated in-place under the old model), and `MEMORY.md` carries only the
harness's content plus the janitor's one bridge line to the wiki overview. So on
the CURRENT corpus the discriminator finds ZERO raw buffer notes and harvest is a
clean no-op. It ACTIVATES the moment the harness next writes a minimal-frontmatter
note. No bulk move is needed.
