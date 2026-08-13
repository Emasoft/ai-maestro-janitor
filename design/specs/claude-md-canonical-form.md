---
status: normative
spec: claude-md-canonical-form
version: 1.0
updated: 2026-08-04T20:10:00+0200
governs: [CLAUDE.md, scripts/claudemd_slim.py, scripts/lib/repomap/claudemd_slim.py, scripts/repomap_generate.py]
relevant-rules: [7.1, 8.1, 9.1, 10.1]
---

# CLAUDE.md canonical form

Normative spec for the shape of a janitor-managed `CLAUDE.md` and for the chore that keeps
it that shape. Implements `PRRD G7.1`, `G8.1`, `G9.1`, `G10.1`.

## Why the constraint is this strict

`CLAUDE.md` is injected into **every session's context on every turn**. Measured on this
project 2026-08-04: one heartbeat fire re-read its context **6 times** in a single turn
(`agentlenspro heartbeat-cost` — 3,239,112 tokens, $1.72). So a paragraph parked in
`CLAUDE.md` is not paid once; it is paid per turn, per tool call, per agent, forever —
including by every agent for whom it is irrelevant. Wikimem inverts that: the knowledge
costs nothing until a symptom query asks for it.

That is the entire rationale. The rules below are consequences of it, not style.

## CM-1 — The five elements (`G7.1`)

`CLAUDE.md` MUST contain exactly these, in this order, and nothing else:

| # | Element | Owner |
|---|---|---|
| 1 | One-paragraph project description | human / agent |
| 2 | Project URLs (repo, marketplace, related) | human / agent |
| 3 | Dev-ops commands | human / agent |
| 4 | Project-map fence (`<+-+-JANITOR-REPO-MAP-…>`) | **janitor, generated** |
| 5 | Wikimem index fence (`<+-+-JANITOR-WIKIMEM-INDEX-…>`) | **janitor, generated** |

Both fenced regions are machine-owned: never hand-edit between the markers. Everything
outside them is the "narrative", and the narrative is budgeted — this project's is
**1,029 bytes**.

## CM-2 — Migration is automatic, not advisory (`G8.1`)

A line that appears outside the five elements is a **defect to be repaired**, not a warning
to be surfaced. The janitor's scheduled chore MUST:

1. detect narrative beyond the permitted elements,
2. RECALL the wikimem page that owns the subject (never create a duplicate page),
3. write the content as a new atom, **or** fold it into the owning atom plus a `[^N]`
   lesson learned,
4. remove the migrated lines from `CLAUDE.md`,
5. prove nothing was lost before committing (see CM-5).

An advisory nudge is explicitly NOT sufficient. The failure this replaces is documented:
the memorize-nudge measured *when a note was last written* rather than *what was
uncaptured*, so it went silent while seven commits of new mechanism went unrecorded
(fixed 2026-08-04, `db7a6c5f`). A rule enforced only by an agent noticing a reminder is
not enforced.

## CM-3 — The dev-ops exemption is closed (`G9.1`)

Exempt, and nothing else: **git, commit, branching, merging, linting, building, testing,
tagging, pushing, CI, publishing, installing, deploying.**

The test is whether the line is a *command an agent runs to operate the repo*. Architecture,
gotchas, incident history, design rationale, conventions, and "why it is like this" are NOT
exempt regardless of how short they are. The list is a closed enumeration: an agent may not
extend it by analogy.

## CM-4 — Index completeness (`G10.1`)

Every ROOT topic of the PROJECT wikimem MUST appear in the index fence. A root topic absent
from the index is unreachable for any agent that does not already know it exists — which
would make CM-2 a knowledge shredder rather than a knowledge mover. The project-map fence
MUST likewise be regenerated when code structure changes.

## CM-5 — Preservation is proven, never assumed

A migration MUST NOT be committed until a preservation oracle proves every fact line and
load-bearing token survived (`claudemd_slim verify --old <pre-migration CLAUDE.md>`), and
that the map fence is byte-identical when only narrative moved. The 2026-08-02 migration was
verified exactly this way: narrative 48,165 → 1,031 bytes, map fence byte-identical across
150,823 bytes, oracle re-run from git history.

`memgrep validate` + `memgrep lint` MUST pass on every page the migration touched.

## Conformance

- `claudemd_slim check` — exit 0 iff the file conforms and the index is fresh.
- `claudemd_slim verify --old <file>` — the preservation oracle, run AFTER a migration
  against a pre-migration copy.
- `claudemd_slim plan` — reports which narrative blocks are excess and which are the
  permitted elements of CM-1. Writes nothing (TRDD-LFSWY0C6).
- `claudemd_slim apply --blocks <json> [--dry-run]` — performs the removal, gated BEFORE
  the write on: the block being excess rather than a CM-1 permitted element, a unique
  location, both fences unchanged, the repo URL surviving, and the preservation oracle.
  Any gate failing means nothing is written. Note that preservation alone is INSUFFICIENT
  — content folded into a wiki page satisfies the oracle while its removal from CLAUDE.md
  may still violate CM-1, so the permitted-element gate is separate and runs first.
- `repomap_generate` — regenerates element 4.

## Does NOT apply to

A project with no PROJECT wikimem corpus (bootstrap first with
`/janitor-memory-bootstrap`), or a `CLAUDE.md` outside janitor management.
