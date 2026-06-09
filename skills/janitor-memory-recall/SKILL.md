---
name: janitor-memory-recall
description: Recall durable project memories from a SYMPTOM before debugging, deciding, or acting on a recurring problem. Searches the project's markdown memory notes with memgrep (degrading to plain grep when memgrep is absent), ranking notes by how well your symptom query hits each note's description/title/tags, and returns the top notes to read. Use when you think "have we hit this before?", or the user says "recall memories about X", "did we already solve this", "search the memory notes", "check what we learned about Y", or before re-deriving architecture/gotchas a past session may have written down. The reference implementation of the AI-Maestro memory-recall protocol (see the markdown-memory-recall rule).
---

# Janitor memory-recall

## Overview

Recall is the FIRST step before debugging a recurring problem, making a design
decision, or acting on a recurring alert — "have we hit this before?". It
searches the project's curated markdown memory notes (the `memory/` dir the
harness maintains) and returns the notes whose `description`/`title`/`tags` best
match your SYMPTOM. The answer is in the matched note's body.

This is distinct from conversation/transcript search: it recalls *curated,
symptom-indexed notes*, not raw chat history.

## The one law

Query with the SYMPTOM — the user's words, the error text, the problem — NOT the
answer's jargon. A note is findable from the symptom because its author put
symptom vocabulary in `description`. (If you query "keychain" you only find it
once you already know the answer; query "rotator failed, had to log in" and you
find it from the problem.)

## Instructions

1. Resolve the project memory dir (the harness per-project notes dir):

   ```bash
   MEMDIR="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory"
   # If that path doesn't exist, fall back to a project-local memory/ dir:
   [ -d "$MEMDIR" ] || MEMDIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/memory"
   ```

2. Build a SYMPTOM query from the user's words / the error / the problem (never
   the answer's jargon), then recall — memgrep if present, plain grep otherwise:

   ```bash
   SYMPTOM="the symptom in the user's / the error's words"
   if command -v memgrep >/dev/null 2>&1; then
     memgrep recall "$SYMPTOM" "$MEMDIR"        # notes ranked best-first: path — description
   else
     grep -rliE "$SYMPTOM" "$MEMDIR" 2>/dev/null # fallback: degrade, never break
   fi
   ```

   If `memgrep` is not installed, install it once (it lives in this plugin):
   `cargo install --path "$CLAUDE_PLUGIN_ROOT/tools/memgrep"` — until then the
   grep fallback works on note frontmatter + bodies.

3. Read the top 1-3 notes the recall returns; the fact you need is in their
   bodies. If recall returns nothing, the memory doesn't exist yet — solve the
   problem, then capture it with `/janitor-memory-write`.

## Read the notes too (the lessons come back for free)

Reading a memory means reading its lessons too. `recall` resolves and APPENDS
each note's `[^N]` lessons-learned by default (so does `find`) — one call yields
the facts AND every linked WHY, no second search. The render is minimal: an
inline reference shows as a bare number `[9]`, and the appended list reads
`[9] - <lesson WHY text>.`

- `--no-notes` — body only (suppress the lessons).
- `--full-notes` — keep each lesson's leading `[…]` metadata prefix (dates,
  class). URLs and image links in a lesson are ALWAYS kept regardless.

## Enriched recall — sort, date-range, keyword find

The shipped `recall`/`find` accept (verify with `memgrep recall --help`):

- `--sort score|ocd|lmd` (default `score` = relevance), `--order asc|desc`
  (default `desc`) — e.g. `--sort lmd` for newest-modified first.
- `--since <ISO>` / `--until <ISO>` over `--date-field ocd|lmd` (default `lmd`)
  — "what did I learn last week", "every lesson about X between two dates".
- `--top N` (default 10); `--use-index` forces the SQLite sidecar (auto-used
  when fresh, else the live walk — results are always correct).

`memgrep find "<query>" <memdir>` is note-level keyword search with a `+`/`-`/
wildcard/phrase DSL (NOT line grep): `+TERM` mandatory, `-TERM` exclude, bare
`TERM` optional (ranks), `*` wildcard, `"quoted phrase"` verbatim. Add
`--only-notes` to search ONLY the resolved lessons (returns matching `[N] - …`
lessons, not pages).

```bash
memgrep recall "$SYMPTOM" "$MEMDIR" --sort lmd                 # newest-touched first
memgrep recall "$SYMPTOM" "$MEMDIR" --since 2026-06-01         # only recent notes
memgrep find "+rotator +keychain -widget" "$MEMDIR"           # AND/exclude keyword search
memgrep find "+max_retries" "$MEMDIR" --only-notes            # search the lessons only
```

Optional speed-up: `memgrep reindex "$MEMDIR"` builds the persistent
`.memgrep/index.db` (gitignored, git-incremental). Recall auto-uses it when
fresh; you never have to manage it.

## Output

A short ranked list of `path — description` lines (memgrep) or matching paths
(grep fallback), best first. Read the top few; do NOT dump full note bodies into
the conversation — open the one you need.

## Examples

<example>
User: the oauth rotator failed again and I had to log in manually
→ recall "oauth rotator failed had to log in manually" → surfaces the keychain
  + resume-protocol notes #1/#2 with their lessons appended; read them WHOLE
  (facts + the `[N] - WHY` lessons) before touching the rotator.
</example>

<example>
User: what did we learn about the rotator in the last week?
→ memgrep recall "oauth rotator" "$MEMDIR" --since 2026-06-02 --sort lmd
  → recent rotator notes, newest-modified first, each with its lessons.
</example>

<example>
User: find the memory that mentions max_retries but not the widget
→ memgrep find "+max_retries -widget" "$MEMDIR"
  → note-level keyword search (mandatory term, exclude term).
</example>

```text
User: recall what we decided about branch protection rulesets
User: have we seen this head/tee truncation before?
User: check the memory notes about compaction resume
```

## Scope

ONLY searches + surfaces existing memory notes (read-only). Does NOT write notes
(use `/janitor-memory-write`). Degrades to plain grep when memgrep is absent;
never blocks on a missing binary.

## Resources

- `~/.claude/rules/markdown-memory-recall.md` — the recall protocol (the law,
  the schema, the read-the-notes rule, the dual-test method).
- `$CLAUDE_PLUGIN_ROOT/tools/memgrep/SKILL.md` — the memgrep tool reference.
- `/janitor-memory-write` — the WRITE side (authoring + the correction protocol).
- `/search-user-mem` — searches the USER's PRIVATE memory store (a separate
  corpus, agent-invisible); distinct from this recall of the agent's notes.
