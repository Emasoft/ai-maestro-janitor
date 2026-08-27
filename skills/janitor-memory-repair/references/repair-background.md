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

## Why `publish-globally` is NOT a repair defect

The SKILL body says do not add or flip it by hand. The reasoning, and the two ways this
instruction has already been written down WRONG here:

**The write path owns the field.** `atomic_write_page` (`memgrep/src/memory.rs`) is the sole
choke point every write verb funnels through, and it runs `normalize_page_until_clean` both
BEFORE and AFTER every single write, unconditionally — the only other caller of the byte-writer
is that normalizer itself. So a page you touch through any verb comes back with the field
correct, and a page you do not touch does not need it.

**Trap 1 — `metadata.type` is NOT the discriminator.** This checklist used to say "add it when
`type: project`". Wrong: `type` is the CONTENT class (`user|feedback|project|reference`) and is
independent of which ROOT a page lives in — a page under `.claude/project/memory/` may
legitimately carry `type: reference`. memgrep decides from the PATH
(`scope_layer(page_abs) == SCOPE_PROJECT`). Measured on this repo 2026-08-27: **10 of the 50
PROJECT-root pages (20%) carry `type: reference` or `type: feedback`**, so the old wording told
the agent to skip a fifth of exactly the pages memgrep flags.

**Trap 2 — the value is not decidable from page text.** memgrep splits "field missing" on
whether a USER-root SYMLINK exists: no field + no symlink is `MissingDefaultFalse` (→ `false`),
no field + a symlink already there is `MissingSymlinkImpliesTrue` (→ `true`, the symlink being
evidence of intent). You cannot see the symlink from the page text.

CALIBRATION (measured 2026-08-27, so nobody re-inflates this): of the 29 PROJECT pages then
missing the field, **0** had a symlink — every one was the unambiguous `MissingDefaultFalse`
case. The ambiguity is real in the CODE, not in the corpus. The reasons the repair GATE
(`memory_content_precheck.repair_defect`) still does not carry this check are the durable ones:
it is gate-silent so it can never cause a dispatch or a loop, and it self-heals on the next
write. See the rejection comment above `repair_defect` for the full record (TRDD-AO8MPK5D).
