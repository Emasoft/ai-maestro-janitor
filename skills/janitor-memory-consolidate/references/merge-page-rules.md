# Merge page construction rules

## Table of contents

- [What verify_merge enforces at commit](#what-verify_merge-enforces-at-commit)
- [What you must ensure (not verifier-checked)](#what-you-must-ensure-not-verifier-checked)
- [Frontmatter and link web](#frontmatter-and-link-web)

Rules for building the merged survivor page `C` in step 7 of the consolidation procedure. These constraints are enforced by `verify_merge` at commit time (lessons, ocd/lmd, no-new-duplicates, no-dangling-refs) or are your responsibility (lead sentence, body-fact preservation).

## What verify_merge enforces at commit

- **Every `[^N]` lesson from BOTH A and B survives byte-identical** — copy each verbatim (you may compound, never reword/drop); keep its `[ocd:… lmd:…]` stamp.
- **Intra-page dedup** — when A and B carry the same lesson/fact, keep the better-sourced copy; the result must have **no duplicate content line** (`no_new_duplicate_lines`). Merging removes redundancy, never adds it.
- **`ocd = min(A.ocd, B.ocd)`**, **`lmd = today`** (`date +%F`, ≥ both sources).
- **No `[[link]]` to a retired slug** — C must not link `[[B]]`; step 6 covers holders.

## What you must ensure (not verifier-checked)

- **Preserve EVERY distinct body fact.** The verifier DOES guard body facts —
  `body_facts_preserved` (issue #48) requires every substantive body line to survive as a
  SUBSTRING of the result, so it allows reorganization, an added lead and dedup, but catches a
  DROPPED or PARAPHRASED fact. It is a COARSE, sentence-shaped net with two blind spots BY
  DESIGN: it ignores lines shorter than 24 chars, and every `#` heading. So a fact carried only
  in a short bullet or a heading is still yours to protect, and the rule stands — dedup only
  identical facts, unsure → keep both.
- **Open C with a one-sentence lead** naming the merged subject (wikimem-model → "The lead") so it reads as ONE topic, then facets as `##` sections + one deduped `## Notes and lessons learned`.

## Frontmatter and link web

Keep the frontmatter shape (`name`, `description`, `ocd`, `lmd`, `metadata.{tier,type,…}`); `name` stays the survivor's slug. Merge `## See also` / `## Governed by` / `## Applies to` edges from both (deduped) so the link web stays intact.

**`publish-globally:` (PROJECT pages only):** the survivor is `true` if EITHER A or B was `true` — publishing is a claim about the knowledge, and a merge must never silently un-publish a fact another project already relies on. memgrep's always-on normalization then reconciles the USER-root symlink to match (`markdown-memory-recall.md` §`publish-globally:`).
