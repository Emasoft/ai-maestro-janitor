# ATOMIZE — background detail (moved from the SKILL body for the token budget)

## Table of contents

- Why `desc:` is the LISTING surface
- Block-id uniqueness rules
- Operational detail moved from the SKILL body

## Why `desc:` is the LISTING surface

`desc:` is a REQUIRED ≤200-char PROSE summary of the atom's body, QUOTED (`desc:"…"` — the
quotes protect commas/colons in prose from the property-splitter). It is the LISTING surface:
memgrep shows `desc` — not the full body — when it lists the atoms matching a `recall`/`find`
query, so the reader triages by `desc` and opens only the one atom worth reading. Write a true
summary, as short as possible, never a slug; do NOT duplicate keywords into it. Legacy atoms
with the old ≤64-char snake_case-slug `desc` stay valid — upgrade a legacy slug to prose
whenever you touch its atom.

## Block-id uniqueness rules

**Block-ids are CORPUS-WIDE-UNIQUE 8-char `[A-Z0-9]` UUIDs** (`^9K3ZP7QW`) — unique across ALL
pages and ALL scopes, not per page (TRDD-0NGYP3IG): atoms are MOBILE (editorial ops move them
between pages), the id travels with the atom, and memgrep resolves id→owning-page-path off the
index — a reused id breaks that resolution. COLLISION-CHECK a candidate id across all three
scope roots (grep `\^<id>` in LOCAL + PROJECT + USER) before assigning. Legacy ids (kebab slugs
`^rotate-drain`, `^memory-<uid>`) remain valid on existing atoms — never rename them; only NEW
atoms get the UUID form.

## Operational detail moved from the SKILL body

### Recording a free-prose-leaf-no-distinct-facts judgment

**WRITE DOWN EVERY `free-prose-leaf-no-distinct-facts` judgment.** A page can look markable
(non-empty, non-heading prose) and still be genuinely un-atomizable in your own semantic
judgment — a boilerplate bootstrap stub ("This is the entry point... replace this stub the
first time you write real knowledge here") is the measured case. That page re-qualifies as a
candidate on EVERY precheck otherwise, so an unrecorded call costs a full dispatch to
re-derive the same "no" next pass. Record it before you emit the `skipped … (free-prose-leaf-
no-distinct-facts)` output line:

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/memory_refusal_cli.py" record \
  --intervention atomize --scope "$SCOPE" --root "$SCOPE_ROOT" \
  --page <slug>.md --reason "<why this page has no distinct atomizable fact>"
```

The refusal re-arms by itself when the page's bytes change, and after 7 days — so it is a
verdict with an expiry, not a permanent silence. `--reason` is the deliverable: the next
reader has to be able to re-check it.

### Per-atom notes, lessons and see-also are automatic

An atom OWNS the `[^N]` footnotes its body
references inline — those are already in the prose, so you DO NOT move them; marking the fact is
enough, memgrep aggregates the rest. memgrep groups each referenced `[^N]` by which bottom
section DEFINES it: `# Notes` → notes, `# Lessons Learned` → lessons, `# See also` → see-also
(see-also is a `[^N]` footnote whose def links out, NOT a bare `[[wikilink]]` in the body). A
footnote can be SHARED by multiple atoms, which is why the defs live POOLED at the page bottom.

### Scope

ONLY adds atom markers to FREE-PROSE wikimem pages in ONE memory scope per pass, IN PLACE through
the memgrep whole-page replace verb. Does NOT create pages (`/janitor-memory-write`), merge
(`/janitor-memory-consolidate`), split (`/janitor-memory-split`), resolve contradictions
(`/janitor-memory-conflict`), backfill shape/metadata (`/janitor-memory-repair`), or harvest stray
artifacts (`/janitor-memory-harvest`). Never moves a page across scopes. PROJECT-scope editing is
opt-in, never pushed standalone.

### Why the candidate set comes from the scheduler predicate

A `memgrep`-driven marker scan can disagree with the scheduler's own precheck (the same janitor#227 class of bug
`memory-repair` hit: a page the scheduler flagged could look "already atomized" to a
differently-scoped grep), so scanning independently risks finding nothing to work while the
marker keeps re-firing.

### Why the pass never stamps the cadence

Do NOT call `memory_settings.mark_ran` after a clean pass — the SCHEDULER already stamped the cadence at emit
(`memory-maintenance.py`); a second agent-side stamp is redundant, and re-checking/re-stamping
the cadence is exactly the double-gate TRDD-VJ8L465M removed (scheduler owns cadence, agent owns
content work).

### Original SKILL-body wording (verbatim, before the token-budget trim)

The passages below are the pre-trim text of SKILL.md, kept verbatim so no content is lost.

```text
Precondition 1 (claim step), sentence:
   The scheduler already gated the cadence, so re-checking `memory_settings.is_due`
   here would abstain on the very scope it scheduled (TRDD-VJ8L465M: scheduler
   owns cadence, agent owns content).

Precondition 2:
2. **Candidate set — run the SCHEDULER's own predicate, not `memgrep -l`.** A `memgrep`-driven
   marker scan can disagree with the scheduler's own precheck (the same janitor#227 class of bug
   `memory-repair` hit: a page the scheduler flagged could look "already atomized" to a
   differently-scoped grep), so scanning independently risks finding nothing to work while the
   marker keeps re-firing. Get the real list from the same code the scheduler gates on:

Per-atom bullet:
- **Per-atom notes/lessons/see-also are AUTOMATIC.** An atom OWNS the `[^N]` footnotes its body
  references inline — those are already in the prose, so you DO NOT move them; marking the fact is
  enough, memgrep aggregates the rest. memgrep groups each referenced `[^N]` by which bottom
  section DEFINES it: `# Notes` → notes, `# Lessons Learned` → lessons, `# See also` → see-also
  (see-also is a `[^N]` footnote whose def links out, NOT a bare `[[wikilink]]` in the body). A
  footnote can be SHARED by multiple atoms, which is why the defs live POOLED at the page bottom.

EXECUTE section, after the gate call:
**On a refusal:** the gate wrote nothing. Read the named violations (a dropped/reworded
fact → restore it verbatim in the scratch copy; a smuggled non-marker line → remove it;
no marker → actually add one) and re-run. On a `--base-sha256` STALE refusal the page
changed since you read it: re-read, re-mark, recompute. **Bounded retry ≤3**; after the
3rd refusal surface a finding, mutate nothing.

After a clean pass: `memgrep reindex "<scope_root>"` (so the new atoms are searchable). Do NOT
call `memory_settings.mark_ran` here — the SCHEDULER already stamped the cadence at emit
(`memory-maintenance.py`); a second agent-side stamp is redundant, and re-checking/re-stamping
the cadence is exactly the double-gate TRDD-VJ8L465M removed (scheduler owns cadence, agent owns
content work).

EXIT contract bullets:
- **Bounded + disable-able:** one scope/pass, top-K pages; `atomize_per_day=0` or the kill-switch /
  `WIKIMEM_EDITOR_ENABLED=off` stops it.
- **Never destructive** — additive markers only; the gate refuses anything else.

Resources bullets:
- [atomize-background](references/atomize-background.md) — the `desc:` listing-surface
  rationale + block-id uniqueness rules.
- [wikimem-model](../janitor-memory-write/references/wikimem-model.md) — the shared data model; its
  **Atoms — first-class body elements** section defines the block-property syntax, the keyword
  recall surface, and the per-atom notes/lessons/"also see" the aggregated record returns. Its
  table of contents:
```

### What to do on a gate refusal

The gate wrote nothing. Read the named violations (a dropped/reworded
fact → restore it verbatim in the scratch copy; a smuggled non-marker line → remove it;
no marker → actually add one) and re-run. On a `--base-sha256` STALE refusal the page
changed since you read it: re-read, re-mark, recompute. **Bounded retry ≤3**; after the
3rd refusal surface a finding, mutate nothing.
