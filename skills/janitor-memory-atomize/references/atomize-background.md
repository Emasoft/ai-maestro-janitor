# ATOMIZE — background detail (moved from the SKILL body for the token budget)

## Table of contents

- Why `desc:` is the LISTING surface
- Block-id uniqueness rules

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
