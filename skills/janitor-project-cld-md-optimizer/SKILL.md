---
name: janitor-project-cld-md-optimizer
description: Migrate a bloated CLAUDE.md into PROJECT-scope wikimem pages, leaving only the slim janitor-managed contract (description, repo urls, build instructions, project map, wikimem index). Use when the project-map-drift detector nudges "CLAUDE.md breaks the slim contract", when the user asks to shrink/slim/restructure/optimize CLAUDE.md, or via `/janitor-project-cld-md-optimizer`.
---

# Janitor CLAUDE.md slim

## Overview

Owner directive (2026-08-02): a janitor-managed CLAUDE.md is part of the memory system. It
contains ONLY:

1. a concise description of the project,
2. the github repo url (and the urls of connected projects — plugins, marketplaces,
   dependencies),
3. the basic lint/build/compile/test/publish instructions,
4. the janitor-generated project map (the `JANITOR-REPO-MAP` fence),
5. the topic-ordered index of PROJECT-scope wikimem pages (the `JANITOR-WIKIMEM-INDEX`
   fence).

Everything else moves into PROJECT-scope wikimem pages, where it is recalled by symptom
instead of paid on every turn. This skill is the EDITORIAL half; the mechanics and the
proofs live in `scripts/claudemd_slim.py` (TRDD-H12K9JYX). You never lose content: the
`verify` gate refuses a migration that drops a fact line or a load-bearing token.

## Prerequisites

- A PROJECT wikimem corpus exists (`<repo>/.claude/project/memory/` has pages). If not,
  run `/janitor-memory-bootstrap` first — the index has nothing to point at otherwise.
- Do this at a CACHE-CHEAP moment (fresh session, post-compaction, or pre-commit):
  CLAUDE.md sits in the cached prompt prefix, and rewriting it mid-session busts the
  cache for the whole context.

## Instructions

1. **Snapshot.** `cp CLAUDE.md CLAUDE.md.pre-slim.bak` (keep it until step 6 passes; the
   verify gate needs it, and RULE-0 wants the undo mechanical).

2. **Classify the narrative.** Read CLAUDE.md. Everything outside the two janitor fences
   that is not items 1–3 above must move. Group it into TOPICS. RECALL FIRST: for each
   topic run `memgrep recall "<topic symptom>" .claude/project/memory` — most topics
   already have a page; EXTEND it (update, don't duplicate). Mint a new page only when
   no existing page owns the subject.

3. **Write the pages.** Use the memgrep write verbs (`new-mem-topic` (was: `new-page`) /
   `new-mem-atom` (was: `add-atom`) / `update-mem-atom --lesson` (was: `add-lesson`)) —
   never hand-author wikimem markdown. Descriptions carry the SYMPTOM a
   future session will search with, not the jargon of the content. Run
   `memgrep validate <page> && memgrep lint <page>` after each edit.

4. **Assemble the slim CLAUDE.md.** Keep: description, urls, build/test/publish
   instructions, the untouched `JANITOR-REPO-MAP` fence. Delete the moved narrative.
   Aim under the narrative cap (8 KiB by default —
   `CLAUDE_PLUGIN_OPTION_CLAUDEMD_NARRATIVE_MAX_BYTES`).

   Two optional tools do this half mechanically (TRDD-LFSWY0C6). `plan` writes nothing
   and reports which blocks are excess versus which are §CM-1 permitted elements:

   ```bash
   uv run scripts/claudemd_slim.py plan
   ```

   `apply` performs the deletion, but ONLY after proving it safe — it refuses to remove a
   permitted element, refuses a block it cannot locate uniquely, refuses if either fence
   would change, and refuses if the content is not yet in the corpus. Pass the exact block
   texts as a JSON array, and run `--dry-run` first (identical gates, no write):

   ```bash
   uv run scripts/claudemd_slim.py apply --blocks blocks.json --dry-run
   uv run scripts/claudemd_slim.py apply --blocks blocks.json
   ```

   Its gates run BEFORE the write, so step 3 must already have landed the content — that
   ordering is enforced, not merely advised. Step 6's `verify` is still worth running: it
   is an INDEPENDENT path over the pre-migration copy, so it corroborates rather than
   repeats.

5. **Splice the index.**

   ```bash
   uv run scripts/claudemd_slim.py index
   ```

6. **PROVE nothing was lost — the gate that decides whether step 4 stands:**

   ```bash
   uv run scripts/claudemd_slim.py verify --old CLAUDE.md.pre-slim.bak
   ```

   Exit 1 names each dropped fact line / token: move each into a wikimem page (step 3)
   and re-run until exit 0. Do NOT trim the old file or reword the finding away — the
   oracle is the point.

7. **Confirm the contract**: `uv run scripts/claudemd_slim.py check` → exit 0.

8. **Commit** CLAUDE.md + the touched memory pages by name (never `git add -A`), with
   TRDD-H12K9JYX in the subject for the first migration of a repo. Then delete the
   `.pre-slim.bak` (its content is now provably in git + the corpus).

## Output

A slim CLAUDE.md (items 1–5 only, both fences fresh), the moved knowledge living in
validated PROJECT wikimem pages, and a preservation proof (`verify` exit 0) on record.

## Scope

ONLY restructures THIS project's CLAUDE.md and PROJECT-scope memory. Does NOT touch
LOCAL/USER memory scopes, does NOT run the repo-map extraction (that is
`scripts/repomap_generate.py`), does NOT write CLAUDE.md from any background surface —
the detector only nudges; a human/agent runs this skill deliberately.

## Resources

- `scripts/claudemd_slim.py` — `index` / `check` / `verify` (the mechanics + proofs),
  plus `plan` / `apply` (TRDD-LFSWY0C6: decide what is excess, then remove it or refuse).
- `scripts/lib/claudemd_migration_plan.py` — the pure classifier behind `plan`.
- `scripts/lib/claudemd_migration_apply.py` — the pure gate chain behind `apply`.
- `scripts/lib/repomap/claudemd_slim.py` — the pure lib (fence, renderer, oracles).
- `scripts/repomap_generate.py` — the sibling map generator (same write discipline).
- `~/.claude/rules/markdown-memory-recall.md` — the recall/authoring protocol step 3
  follows.
