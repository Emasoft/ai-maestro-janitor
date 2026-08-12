# REPAIR — background and rationale

## Why REPAIR exists

The wikimem corpus accumulates malformed pages: notes the harness `# Memory`
directive wrote with a partial schema, pages an agent created before the skill
enforced the full frontmatter, pages whose tier is inverted (an `aspect` built
with `## Governed by` instead of `## Applies to`), pages with no frontmatter at
all (invisible to ranked recall), or a one-sided `[[link]]`. REPAIR is the
autonomous pass that completes and corrects ONE page at a time, in place,
through the transaction core so it can never lose a fact. It is the 4th
wikimem-editor pass (alongside split / consolidate / conflict) and the executor
for priority #4 of the memory-curation mission (TRDD-87935f21).

## What REPAIR is (and is not)

REPAIR is additive and structural — it backfills metadata, adds the standing
Notes section, sets/corrects the tier, makes a page findable, and adds a page's
OWN missing edges. It NEVER rewrites a fact, never changes `ocd` (a page's birth
date), never merges/splits/deletes. Editorial judgment that changes meaning is
the job of the other three passes; REPAIR only makes a page well-formed.
