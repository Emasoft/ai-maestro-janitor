---
name: janitor-memory-recall
description: RECALL — before working on a file or debugging/deciding, surface the right memory WIKI page and navigate it. Two entry points - (1) FILE-anchored - about to edit a file in some functionality (frontend, backend, db, a render engine, a parser, a controller, an endpoint…) → surface that functionality's HUB page (the tip of the iceberg) and descend through its links to the detail the task needs; (2) SYMPTOM - "have we hit this before?" → rank pages by how your symptom hits their description/title/tags. Use when you think "have we hit this before", before re-deriving architecture/gotchas, or the user says "recall memories about X", "what do we know about the frontend", "did we already solve this", "check what we learned about Y". Reads only the pages the task needs (progressive disclosure), degrading to grep when memgrep is absent. The RECALL leg of the AI-Maestro wiki-memory protocol.
---

# Janitor memory — RECALL

## Overview

RECALL is the FIND/READ leg of the memory wiki. It does two things the flat-note
recall could not: it maps **the file you're about to touch → the functionality's
hub page** (so you get the overview before you edit), and it lets you **navigate
the wiki** — read the tip, then follow only the links the task needs. Read [the
wikimem model](../janitor-memory-write/references/wikimem-model.md) for tiers,
the See-also web, and the file→functionality mapping.

Always run RECALL FIRST: before debugging a recurring problem, before a design
decision, before editing a file in an area you haven't loaded, before MEMORIZING
(so you update the right page instead of duplicating).

## Compose the scope roots (once)

```bash
LOCAL_MEM="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory"   # machine-private
PROJECT_MEM="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/memory"  # git-tracked
USER_MEM="$HOME/.claude/memory"                                    # global
ROOTS=""; for d in "$LOCAL_MEM" "$PROJECT_MEM" "$USER_MEM"; do [ -d "$d" ] && ROOTS="$ROOTS $d"; done
```

On conflicting facts the more specific scope wins: **LOCAL > PROJECT > USER**.

## Entry A — FILE-anchored (the "I'm about to work on this file" path)

Goal: surface the HUB for the functionality the file belongs to, then descend.

1. Find the hub whose `globs` own the file you're about to edit:

   ```bash
   FILE="src/frontend/panels/Login.tsx"          # the file (relative to repo root)
   # List hub pages, read each hub's globs, and pick the hub whose glob matches FILE.
   memgrep --where 'fm.tier "hub"' $ROOTS          # the hubs; inspect their globs:
   memgrep --where 'fm.functionality "frontend"' $ROOTS   # or query a functionality directly
   ```

   (When memgrep is absent: `grep -rl 'tier: hub' $ROOTS`, read each hub's
   `globs:`, and match `FILE` against them by eye / with a glob test.)

2. Read the matching **hub** page (the tip): the functionality overview, the big
   general decisions, the map of parts. This alone is often enough.

3. **Descend on demand, following the typed edges.** From the hub's parts map go
   to the COMPONENT you're touching, then read its `## Governed by` to load the
   general pages (style, protocols, configs) that rule it — and ONLY those the
   task needs. Read each governing page ONCE: if a later component shares the same
   governor, it is already in context (cached) — never re-read a sun. Load detail
   like a Skill loads a reference — only if relevant; never the whole subtree.

   ```bash
   memgrep links --from login-panel $ROOTS             # the component's Governed-by (its rulers)
   memgrep --where 'linked-from "style-system"' $ROOTS  # reverse: every element this rule governs
   memgrep links --to style-system $ROOTS              # same, via the link graph
   ```

   If you're about to CHANGE a general rule, read its `## Applies to` ray-list
   first — it shows every element you'd affect before you touch it.

## Entry B — SYMPTOM (the "have we hit this before?" path)

Query with the SYMPTOM — the user's words, the error, the problem — NOT the
answer's jargon (its author indexed `description` by the question):

```bash
SYMPTOM="the symptom in the user's / the error's words"
if command -v memgrep >/dev/null 2>&1; then
  memgrep recall "$SYMPTOM" $ROOTS          # pages ranked best-first: path — description
else
  grep -rliE "$SYMPTOM" $ROOTS 2>/dev/null  # fallback: degrade, never break
fi
```

Read the top 1-3 pages; the fact is in the body, and from there you can follow
See-also into related pages exactly as in Entry A. If recall returns nothing, the
memory doesn't exist yet — solve it, then `/janitor-memory-write` (MEMORIZE).

If memgrep is not installed, install once (it ships in this plugin):
`cargo install --path "$CLAUDE_PLUGIN_ROOT/tools/memgrep"`.

## The lessons come back for free

`recall`/`find` resolve and APPEND each page's `[^N]` lessons-learned by default,
so one call yields the facts AND every WHY. `--no-notes` = body only;
`--full-notes` = keep each lesson's `[…]` date/class prefix.

## Enriched recall (verify with `memgrep recall --help`)

- `--sort score|ocd|lmd` (default relevance), `--order asc|desc` — `--sort lmd`
  for newest-touched first.
- `--since <ISO>` / `--until <ISO>` over `--date-field ocd|lmd` — "what did we
  decide about X last week".
- `--top N` (default 10); `--use-index` forces the SQLite sidecar (auto-used when
  fresh; results always correct).
- `memgrep find "+TERM -TERM \"phrase\"" $ROOTS` — note-level boolean keyword
  search; add `--only-notes` to search ONLY the lessons.

```bash
memgrep recall "$SYMPTOM" $ROOTS --sort lmd                # newest-touched first
memgrep find "+rotator +keychain -widget" $ROOTS           # AND / exclude
memgrep links --broken $ROOTS                              # context edges to fill (→ MEMORIZE/UPDATE)
```

## The navigation contract (don't over-read)

Surface the TIP, read what the task needs, follow links on demand. Reading an
entire functionality's page tree "to be safe" defeats the wiki — its whole point
is that context spend stays proportional to the task. One hub + the component +
its two or three `## Governed by` rulers is the normal read. **Cache the suns:**
a shared general page (style, protocol) is read ONCE and reused across every
component it governs — so working across many components costs the governors only
once, not per component. That cacheability is why the wiki abstracts shared rules
into radiating pages instead of copying them into each element.

## Output

A short ranked list of `path — description` (memgrep) or paths (grep), plus the
hub you landed on for a file-anchored recall. Read the few you need; do NOT dump
full page bodies into the conversation — open the one the task requires.

## Examples

<example>
About to edit src/frontend/panels/Login.tsx
→ Entry A: find the `frontend` hub (its globs own src/frontend/**), read it, go to
  the [[login-panel]] component, read its `## Governed by` ([[style-system]],
  [[dialog-forms]]) — load those rulers once — and skip the rest of the tree.
</example>

<example>
User: the oauth rotator failed again and I had to log in manually
→ Entry B: recall "oauth rotator failed had to log in manually" → the keychain +
  resume-protocol pages with lessons appended; read them WHOLE before touching it.
</example>

<example>
User: what do we know about the frontend before I restyle the dialogs?
→ Entry A from the `frontend` hub → descend into [[dialog-forms]] + [[style-system]].
</example>

## Scope

ONLY searches + surfaces + navigates existing wikimem pages (read-only). Does NOT
write (use `/janitor-memory-write`) or modify (use `/janitor-memory-update`).
Degrades to grep when memgrep is absent; never blocks on a missing binary.

## Resources

- [../janitor-memory-write/references/wikimem-model.md](../janitor-memory-write/references/wikimem-model.md)
  — the wiki data model (tiers, file→functionality globs, See-also, the memgrep
  command map).
- `~/.claude/rules/markdown-memory-recall.md` — the "index by the QUESTION" recall
  law + schema + dual-test method.
- `$CLAUDE_PLUGIN_ROOT/tools/memgrep/SKILL.md` — the memgrep instrument reference.
- `/janitor-memory-write` (MEMORIZE) · `/janitor-memory-update` (UPDATE) — the
  write legs; run RECALL before both.
- `/search-user-mem` — searches the USER's PRIVATE store (agent-invisible); a
  separate corpus, distinct from this recall of the agent wiki.
