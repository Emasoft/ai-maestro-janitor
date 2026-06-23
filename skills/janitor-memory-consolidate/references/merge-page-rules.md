# Merge page construction rules

Rules for building the merged survivor page `C` in step 7 of the consolidation procedure. These constraints are enforced by `verify_merge` at commit time (lessons, ocd/lmd, no-new-duplicates, no-dangling-refs) or are your responsibility (lead sentence, body-fact preservation).

## What verify_merge enforces at commit

- **Every `[^N]` lesson from BOTH A and B survives byte-identical** — copy each verbatim (you may compound, never reword/drop); keep its `[ocd:… lmd:…]` stamp.
- **Intra-page dedup** — when A and B carry the same lesson/fact, keep the better-sourced copy; the result must have **no duplicate content line** (`no_new_duplicate_lines`). Merging removes redundancy, never adds it.
- **`ocd = min(A.ocd, B.ocd)`**, **`lmd = today`** (`date +%F`, ≥ both sources).
- **No `[[link]]` to a retired slug** — C must not link `[[B]]`; step 6 covers holders.

## What you must ensure (not verifier-checked)

- **Preserve EVERY distinct body fact** — verify guards lessons, NOT body facts, so a dropped body fact is silently lost; dedup only identical facts, unsure → keep both.
- **Open C with a one-sentence lead** naming the merged subject (wikimem-model → "The lead") so it reads as ONE topic, then facets as `##` sections + one deduped `## Notes and lessons learned`.

## Frontmatter and link web

Keep the frontmatter shape (`name`, `description`, `ocd`, `lmd`, `metadata.{tier,type,…}`); `name` stays the survivor's slug. Merge `## See also` / `## Governed by` / `## Applies to` edges from both (deduped) so the link web stays intact.
