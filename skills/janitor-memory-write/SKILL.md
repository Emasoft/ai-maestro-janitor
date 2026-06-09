---
name: janitor-memory-write
description: Capture a durable, reusable fact as a markdown memory note so a future session recalls it from the SYMPTOM. Use after solving a non-trivial bug (a bug-autopsy gotcha), learning a project constraint not derivable from code, a confirmed user preference, or any "we should remember this" moment — or when the user says "remember this", "save a memory", "capture this gotcha", "note that for next time". Writes a schema-valid note (name/description/metadata + body) with the description indexed by question/symptom vocabulary, and appends the MEMORY.md index line. The reference implementation of the AI-Maestro memory-write protocol (see the markdown-memory-recall rule).
---

# Janitor memory-write

## Overview

Capture one durable fact as a memory note so a future session — which will have
the SYMPTOM, not the answer — can recall it. The load-bearing decision is the
`description`: it MUST carry the words the problem will present with (the user's
words, the error, the symptom), because recall ranks on `description`
(+ `title` + `tags`). Put the symptom in `description`; put the answer in the body.

Only capture what is NON-OBVIOUS and reusable: gotchas, constraints not in the
code, confirmed preferences, hard-won debugging facts. Do NOT capture what the
repo already records (code structure, git history, CLAUDE.md) or what only
matters to the current conversation.

## Instructions

1. Resolve the memory dir (same as recall):

   ```bash
   MEMDIR="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory"
   [ -d "$MEMDIR" ] || MEMDIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/memory"
   mkdir -p "$MEMDIR"
   ```

2. Choose `type` ∈ `user | feedback | project | reference` and a kebab slug
   (prefix the slug with the type, e.g. `feedback_…`, `reference_…`).

3. Check for an existing note that already covers this (update it rather than
   duplicate): `command -v memgrep >/dev/null && memgrep recall "<symptom>" "$MEMDIR"`.

4. Write `"$MEMDIR/<type>_<slug>.md"` with the Write tool (NOT echo), schema:

   ```yaml
   ---
   name: <type>_<slug>
   description: "<the SYMPTOM in the user's / the error's words — the words a future session will search with, NOT the answer's jargon>"
   metadata:
     node_type: memory
     type: <user|feedback|project|reference>
   ---
   <the one fact. For feedback/project, follow with **Why:** and **How to apply:** lines.
   Link related notes with [[their-name]].>
   ```

5. Append a one-line pointer to `"$MEMDIR/MEMORY.md"` (create if missing):
   `- [<Title>](<type>_<slug>.md) — <one-line hook>.`

6. Sanity-check: would a future session, having only the SYMPTOM, find this note
   by searching `description`? If the description reads like the *answer*, rewrite
   it to read like the *question*.

## Output

One note file + one MEMORY.md index line. Report the note path and the
one-line description; do NOT echo the whole note back into the conversation.

## Examples

```text
After fixing a flaky pipe-truncation bug:
  description: "command output looks truncated / wrong line count when piping through tee | head"
  body: explains the SIGPIPE-kills-tee mechanism + the capture-to-file-first fix.

User: remember that automating my own paid Claude accounts is fine, don't over-flag ToS
  → type: feedback; description carries "is it ok to automate / rotate my own Claude accounts".
```

## Scope

ONLY authors/updates memory notes + the MEMORY.md index. Does NOT recall (use
`/janitor-memory-recall`). One fact per note. Symptom-indexed description is
mandatory — it is what makes the note recallable.

## Resources

- `~/.claude/rules/markdown-memory-recall.md` — the protocol (the law, schema,
  dual-test method).
- The harness `# Memory` directive — the authoring source-of-truth this skill
  follows.
