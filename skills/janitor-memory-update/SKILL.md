---
name: janitor-memory-update
description: UPDATE — modify an existing memory WIKI page when something changes — ADD a decision to the page that owns the subject, CORRECT a memory a new discovery contradicts (the 2-step non-destructive protocol), or RESHAPE a page that outgrew its tier (expand a shared rule into an aspect, reduce element-specific detail into its component page). Use when a decision changes, a memory turns out wrong, a page mixes too many subjects, or the user says "update the memory", "that's no longer true", "fix the note about Y", "this memory is outdated". Keeps the See-also web, the hub map, and the lessons trail consistent. The UPDATE leg of the wiki-memory protocol.
---

# Janitor memory — UPDATE

## Overview

UPDATE is the MODIFY leg of the memory wiki — distinct from MEMORIZE (create a
page) and RECALL (find one). It edits an existing wikimem page while keeping the
wiki *consistent*: the See-also context web, the hub→parts map, and the
lessons-learned trail all stay true after the change. Read [the wikimem
model](../janitor-memory-write/references/wikimem-model.md) for tiers, See-also,
and the expand/reduce shapes. The model doc's table of contents:

- A wiki, not a pile — and collaborative like Wikipedia
- The editorial decision flow (run this on any change worth remembering)
- EXPAND and REDUCE — radiating suns vs receiving terminals
- The three tiers (a page's role in the pyramid)
- The edge model — EVERY link is bidirectional (the link law)
- Page anatomy

Three kinds of update, below. Always: **find the page first**, then bump `lmd:`
to today on any edit.

## THE UPDATE INVARIANT — a superseded memory is NEVER deleted; it becomes a lesson

This governs EVERY update, not just explicit corrections. Whenever an edit
**supersedes** an existing memory — a corrected fact, a reversed decision, a
changed value/threshold, an abandoned approach, a renamed thing — the old memory
is **never silently overwritten or erased**. Instead, in two moves:

1. **The body is cleaned to the current truth** (no "we used to think X" clutter
   inline — the body always reads as the present state).
2. **The superseded statement is DEMOTED to a dated lesson-learned/note** — a
   `[^N]` footnote under `## Notes and lessons learned` — carrying the **WHY**
   (what it used to be + the root cause it changed). The corrected statement in
   the body links to it with `[^N]`.

This is RULE 0 (never lose information) + the Bug-Autopsy directive (every fixed
mistake becomes a guardrail) applied to memory: the FACT moves forward clean, the
HISTORY/WHY is preserved as a lesson so the next session can't repeat the old
mistake or wonder why the decision flipped. The full mechanics are in §2; §1 and
§3 below MUST apply this same invariant whenever they replace prior content.

## 0. Find the page

```bash
LOCAL_MEM="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory"
PROJECT_MEM="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/memory"
USER_MEM="$HOME/.claude/memory"
ROOTS=""; for d in "$LOCAL_MEM" "$PROJECT_MEM" "$USER_MEM"; do [ -d "$d" ] && ROOTS="$ROOTS $d"; done
memgrep recall "<the subject + symptom>" $ROOTS        # land on the owning page
```

If no page exists, this is a CREATE → use `/janitor-memory-write` (MEMORIZE).

## 1. ADD a memory to the page that owns the subject (common case)

The new decision belongs to an existing page's subject (it fits the element/aspect
the page is about — the one-component-one-page invariant means it goes HERE, not
in a new page):

1. Add the decision to the body, in the right section. **If it SUPERSEDES a
   statement already on the page** (replaces a value, reverses a prior choice),
   this is not a plain add — apply THE UPDATE INVARIANT: clean the body to the
   new truth AND demote the old statement to a `[^N]` lesson with the WHY (§2).
   Only a genuinely NEW, additive fact skips the demotion.
2. Update the edges if the change adds/removes a relation — and per THE LINK LAW
   (every link bidirectional, always), edit BOTH ends in the same pass: a
   component now obeying a new rule → the component's `## Governed by` AND that
   rule's `## Applies to`; a general rule covering a new element → its
   `## Applies to` AND the element's `## Governed by`; a new lateral relation →
   `## See also` on BOTH pages. Remove dead edges on both ends too.
3. Bump `lmd:`. Reindex / fix the MEMORY.md hook line only if the title or
   `description` changed.

## 2. CORRECT a memory — the 2-step NON-DESTRUCTIVE protocol

When a new discovery CONTRADICTS an existing memory, an AGENT must change it
(never the janitor), in exactly two steps — so the FACTS stay clean but the ERROR
is never lost (RULE 0 + the Bug-Autopsy directive: every fixed mistake becomes a
guardrail):

1. **Clean the fact in place.** Replace the wrong statement in the body with the
   correct one. The body is always the current truth — no "we used to think X"
   clutter inline.
2. **Demote the error to a dated lesson — the WHY is the point.** Add the error
   as a numbered entry under `## Notes and lessons learned` and connect the
   corrected fact to it with a markdown footnote `[^N]`. The load-bearing content
   is *why the previous statement was wrong / why the plan failed* — the root
   cause. A lesson without a WHY cannot stop the next repeat.

```markdown
The widget retries 3× then fails.[^3] Tune via the `max_retries` config key.

## Notes and lessons learned
[^3]: [ocd:2026-06-09 lmd:2026-06-09] earlier this page said "retries 5×" — wrong,
  the cap is 3. The error: the constant was read off the guessed variable name
  `max_attempts` (which doesn't exist) instead of the real key `max_retries`.
  Lesson: verify a constant against the SOURCE, not a guessed name.
```

Lessons are first-class: a leading `[ocd:… lmd:…]` prefix carries the lesson's
own dates (they survive the librarian later moving the lesson between pages, so
they — not file mtime — are the authoritative age). memgrep strips the prefix in
the default render and restores it under `--full-notes`; `--since/--until` read
these dates. All of a subject's lessons thus collect in its own page, recallable
with `memgrep find "<symptom>" $ROOTS --only-notes`.

## 3. RESHAPE — the page outgrew its tier (keep the pyramid honest)

Editing reveals a page is the wrong shape. Three moves (each = a real content
move + relink, NOT a silent copy):

- **EXPAND (extract a now-shared rule):** a `component` page accumulated a rule
  that other components ALSO follow. Move that rule OUT into a new RADIATING
  `aspect` page; replace it in the component with a `## Governed by` link UP to
  the aspect; and on the aspect's `## Applies to`, radiate DOWN to that component
  AND every other follower (find them:
  `memgrep -l . "$MEMDIR" --where 'fm.tier "component" and fm.functionality "<fn>"' | sort -u`).
  Now the rule has one home and every follower points up to it — the duplication
  is gone.
- **REDUCE (push element-specific detail down):** a general page (`aspect`/`hub`)
  collected detail that affects only ONE element. Move it INTO that element's
  `component` page (create it if absent). If the general page still governs the
  element for OTHER rules, keep the `## Applies to`/`## Governed by` edge;
  otherwise the moved detail is purely the component's own (no edge). The general
  page stays general.
- **MERGE (heal fragmentation):** two pages describe the SAME element from
  different subjects (`login-panel-style` + `login-panel-behavior`). Merge into
  the single `component` page (`login-panel`), make the subjects SECTIONS within
  it, repoint every inbound `[[link]]` to the survivor, and delete the duplicate
  ONLY after it is committed (RULE 0). Prefer handing large merges to the janitor
  librarian, which deduplicates corpus-wide.
- **RENAME (inbound links FIRST):** renaming a page breaks EVERY inbound
  `[[link]]` at once (simulation-verified: one component rename = one broken
  link per governor + the hub). Order matters:
  1. list who points at it: `memgrep links --from <old-name> <memdir>`;
  2. repoint every inbound `[[old-name]]` → `[[new-name]]` on those pages;
  3. rename the file AND its frontmatter `name:` (they must stay equal) + the
     MEMORY.md index line;
  4. re-audit: `memgrep links --broken <memdir>` must show nothing new.
  Never rename by just moving the file — that strands the whole inbound web.

After any reshape: fix See-also on BOTH endpoints, update the hub's parts map,
bump `lmd:` on every touched page, and re-run `memgrep links --broken` to confirm
you left no dangling edge.

## Consistency checklist (run after every UPDATE)

- `lmd:` bumped on every page you touched.
- THE LINK LAW holds: EVERY link bidirectional — each `## Applies to` ray matched
  by a `## Governed by` on the element (and vice versa), each `## See also`
  mirrored on the other page. Fix both ends of any move; no one-sided link of
  any kind survives the update.
- No fact was deleted outright — a contradicted fact was demoted to a `[^N]`
  lesson with its WHY, not erased.
- `memgrep links --broken` over the scope shows no new dangling `[[link]]` you
  introduced (an intentional link to a yet-to-write page is fine; note it).
- One-component-one-page still holds (you didn't fragment an element).

## Output

The page(s) edited + a one-line "what changed" (added decision / corrected fact +
WHY / reshaped X→Y). Do NOT echo full page bodies back into the conversation.

## Scope

ONLY modifies existing wikimem pages (add / correct / reshape) and the links and
index lines the change implies. To CREATE a new page use `/janitor-memory-write`
(MEMORIZE); to FIND one use `/janitor-memory-recall` (RECALL). Corrections are
non-destructive (fact cleaned, error demoted to a lesson) — never delete the WHY.

## Resources

- [../janitor-memory-write/references/wikimem-model.md](../janitor-memory-write/references/wikimem-model.md)
  — the wiki data model (tiers, expand/reduce, See-also, memgrep map). Its table
  of contents:
  - A wiki, not a pile — and collaborative like Wikipedia
  - The editorial decision flow (run this on any change worth remembering)
  - EXPAND and REDUCE — radiating suns vs receiving terminals
  - The three tiers (a page's role in the pyramid)
  - The edge model — EVERY link is bidirectional (the link law)
  - Page anatomy
- `~/.claude/rules/markdown-memory-recall.md` — the recall law + lessons-learned
  conventions + dual-test method.
- `/janitor-memory-write` — MEMORIZE (create a page); the shape rules for the new
  page a reshape extracts.
- `/janitor-memory-recall` — RECALL (find the page to update, step 0).
