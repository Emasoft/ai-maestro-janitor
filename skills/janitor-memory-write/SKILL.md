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

1. **Route the SCOPE first** (the wiki is layered LOCAL / PROJECT / USER like
   Claude Code's own memory). Decision tree:
   - contains a local path / username / hostname / secret / machine-specific
     detail → **LOCAL** (machine-private, never pushed);
   - project knowledge ANY dev working on the repo needs → **PROJECT**
     (git-tracked + pushed; sensitive/local data FORBIDDEN — the janitor's
     `memory-scope-leak` detector polices it);
   - about the user across ALL projects → **USER** (global);
   - **UNSURE → LOCAL** (promotion to PROJECT is a deliberate later act).

   ```bash
   case "$SCOPE" in
     local)   MEMDIR="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory" ;;
     project) MEMDIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/memory" ;;
     user)    MEMDIR="$HOME/.claude/memory" ;;
   esac
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

## Correcting a memory — the 2-step non-destructive protocol

When a new discovery CONTRADICTS an existing memory, you (an agent) MUST change
the memory — never the janitor. Do it non-destructively, in exactly two steps:

1. **Clean the fact in place.** Replace the wrong statement in the body with the
   correct one, so the page's record of the FACTS is always clean and true — no
   "we used to think X" clutter inline. The body is the current truth.
2. **Demote the error to a lesson — the WHY is the point.** Record the error that
   caused the false memory as a **numbered entry** in a `## Notes and lessons
   learned` section at the BOTTOM of the page, and connect the corrected fact to
   it with a standard-markdown footnote `[^N]`. The load-bearing content is
   *why* the previous statement was wrong / *why* the plan failed — the root
   cause, not merely "this was wrong". A lesson without a WHY cannot stop the
   next repeat.

This mirrors the CLAUDE.md Bug Autopsy directive (every fixed bug becomes a
guardrail) and RULE 0 (never lose information): the *fact* is corrected, the
*error* is never deleted — it is demoted to a linked lesson so future readers
don't repeat it. Lessons thereby accrue in the topic's own page, so all
lessons-learned for a topic collect in one findable place (recallable with
`memgrep find "<symptom>" <memdir> --only-notes`).

## Lesson format (footnotes + per-element dates)

Lessons use **standard markdown footnotes** — `[^N]` in the body, `[^N]: …`
under `## Notes and lessons learned`. A lesson is a first-class memory element:
give it the SAME metadata a fact has, including two intrinsic dates in a leading
`[…]` prefix:

- **OCD — Original Creation Date** (when first written),
- **LMD — Last Modified Date** (when last changed).

These survive when the background librarian later moves the memory between
pages, so they — not the file mtime — are the authoritative age. memgrep strips
the `[…]` prefix from the default render and restores it under `--full-notes`;
its `--since`/`--until` filters read these dates.

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

A corrected memory page (the 2-step protocol applied — fact clean in the body,
error demoted to a dated `[^3]` lesson with the WHY):

```markdown
---
name: reference_widget_retry_cap
description: "widget kept retrying / how many times before it gives up"
metadata:
  node_type: memory
  type: reference
---
The widget retries 3× then fails.[^3] Tune via the `max_retries` config key.

## Notes and lessons learned
[^3]: [ocd:2026-06-09 lmd:2026-06-09] earlier this page said "retries 5×" — wrong,
  the cap is 3. The error: the constant was read off the variable name
  `max_attempts` (which doesn't exist) instead of the actual key `max_retries`.
  Lesson: verify a constant against the SOURCE, not a guessed variable name.
```

## Scope

ONLY authors/updates memory notes + the MEMORY.md index. Does NOT recall (use
`/janitor-memory-recall`). One fact per note. Symptom-indexed description is
mandatory — it is what makes the note recallable.

## Resources

- `~/.claude/rules/markdown-memory-recall.md` — the protocol (the law, schema,
  the lessons-learned conventions, dual-test method).
- The harness `# Memory` directive — the authoring source-of-truth this skill
  follows.
- `/janitor-memory-recall` — the RECALL side (find a note before you duplicate
  or correct it; lessons come back appended).
- `/to-user-mem` — saves a memory to the USER's PRIVATE store (agent-invisible);
  distinct from authoring an agent note here.
