---
name: janitor-memory-write
description: MEMORIZE — capture a durable decision/fact into the project's memory WIKI as a navigable page, not a loose note. Use after solving a non-trivial bug (a bug-autopsy gotcha), making a design/architecture decision, learning a project constraint not derivable from code, a confirmed user preference, or any "we should remember this" moment — or when the user says "remember this", "memorize this", "save a memory", "capture this decision/gotcha", "note that for next time". Finds the right existing wikimem page first (so it never duplicates), and only when none fits creates a new HUB / ASPECT / COMPONENT page via the expand/reduce decision, wires it into the See-also context web, and indexes it by symptom. The MEMORIZE leg of the AI-Maestro wiki-memory protocol.
---

# Janitor memory — MEMORIZE

## Overview

MEMORIZE is the CREATE/CAPTURE leg of the memory wiki. It places a new durable
decision into the right wikimem page so a future session can navigate to it — not
dump a loose `.md` into a pile. Read [the wikimem model](references/wikimem-model.md)
once: pages have a **tier** (hub / aspect / component), a **See-also** context
web, and a **file→functionality** mapping. This skill is the rules for growing
that wiki correctly.

Only memorize what is NON-OBVIOUS and reusable: design decisions, gotchas,
constraints not in the code, confirmed preferences, hard-won debugging facts. Do
NOT memorize what the repo already records (code structure, git history,
CLAUDE.md) or what only matters to this conversation.

## The algorithm

### 1. Route the SCOPE (machine-private vs shared vs global)

```bash
# LOCAL = local paths/usernames/hosts/secrets/machine-specific (never pushed)
# PROJECT = knowledge any dev on the repo needs (git-tracked + pushed; NO secrets)
# USER = true across ALL projects (global).  UNSURE → LOCAL.
case "$SCOPE" in
  local)   MEMDIR="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory" ;;
  project) MEMDIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/memory" ;;
  user)    MEMDIR="$HOME/.claude/memory" ;;
esac
mkdir -p "$MEMDIR"
```

The janitor's `memory-scope-leak` detector polices secrets/local paths in
PROJECT/USER scope — keep machine-specific detail in LOCAL.

### 2. FIND the home first — never duplicate

Run RECALL (or memgrep directly) for the subject AND its functionality, so you
land on the page that should already hold this:

```bash
memgrep recall "<the decision's subject + symptom>" "$MEMDIR"
memgrep --where 'fm.functionality "<functionality>"' "$MEMDIR"   # the functionality's pages
```

- A fitting page exists → this is an **UPDATE, not a create**. Stop here and use
  `/janitor-memory-update` to add the memory to that page (it keeps See-also and
  lessons consistent). MEMORIZE only proceeds when no page is the right home.

### 3. No page fits → decide the SHAPE (expand vs reduce)

Pick exactly one (see the model for the full definition):

- **New functionality entirely** (no hub yet for this area) → seed a **`hub`**
  page: the overview + the big general decisions + the file `globs:` the
  functionality owns. The tip of the iceberg.
- **EXPAND** — the memory is a *general rule shared by many components/procedures*
  → an **`aspect`** page (`style-system`, `error-envelope`, `dialog-forms`).
- **REDUCE** — the memory is *specific to one element* → a **`component`** page
  (`login-panel`, `user-model`, `checkout-endpoint`).

Honor the **one-component-one-page** invariant: if a component page for this
element already exists, the memory goes THERE (→ UPDATE), even if you arrived
from a different subject. Never make `login-panel-style` beside `login-panel`.

### 4. WRITE the page (Write tool, not echo)

Author `"$MEMDIR/<slug>.md"` with the model's schema. Set `ocd`/`lmd` to TODAY.
ALWAYS include `## See also` AND the standing `## Notes and lessons learned`
section (the janitor's page-shape validator flags a page that omits either):

```yaml
---
name: <slug>
description: "<the SYMPTOM/topic in search words — what a future session will query, NOT the answer's jargon>"
ocd: <YYYY-MM-DD>
lmd: <YYYY-MM-DD>
metadata:
  node_type: memory
  type: <project|reference|feedback|user>
  tier: <hub|aspect|component>
  functionality: <hub-slug>            # which functionality this lives under
  globs: ["<owned file patterns>"]     # REQUIRED on hubs; omit on most leaves
---
<the memories — concise; for a hub the overview + a short map of the parts.
For feedback/project add **Why:** and **How to apply:** lines.>

## See also
- [[related-page]] — why it relates / how it influences this subject.

## Notes and lessons learned
```

### 5. WIRE the context (this is what makes it a wiki)

A page with no edges is a dead note. Two link directions:

- **Out** — fill `## See also` with EVERY page that relates to or influences this
  subject: the general style aspect, the view/model it binds, the API functions
  it calls, graphic items/animations, the db, downstream consumers. Each link
  says *why*. A `[[link]]` to a not-yet-written page is fine (it flags one to
  create later).
- **Up** — add the new page to its hub's "parts" map and/or the parent aspect's
  `## See also`, so the tip can reach it. (The janitor librarian backfills any
  inbound links you miss, but do the obvious ones now.)

### 6. Index it

Append a one-line pointer to `"$MEMDIR/MEMORY.md"` (create if missing):
`- [<Title>](<slug>.md) — <one-line hook>.` Then `memgrep reindex "$MEMDIR"` if
present (optional; recall auto-reindexes).

### 7. Sanity-check

- Would a future session find this from the SYMPTOM via `description`? If the
  description reads like the *answer*, rewrite it as the *question*.
- Is `## See also` non-empty and honest (real influences, not filler)?
- Did you respect one-component-one-page (no fragmenting an element)?
- If you created a hub, are its `globs` precise and non-overlapping with other
  hubs (one file → one functionality)?

## Output

The page path + its one-line description + the See-also targets you wired. Do NOT
echo the whole page back into the conversation.

## Examples

<example>
Decision: "all destructive dialogs use a red secondary 'Delete' button, primary is Cancel."
→ general rule shared by many dialogs ⇒ EXPAND ⇒ aspect page `dialog-forms`
  (functionality: frontend). See also: [[style-system]] (the red token),
  [[interaction-patterns]]. Linked up from the `frontend` hub's parts map.
</example>

<example>
Decision: "the checkout endpoint is idempotent on the Idempotency-Key header."
→ specific to one element ⇒ REDUCE ⇒ component page `checkout-endpoint`
  (functionality: backend). See also: [[order-model]], [[payment-gateway]],
  [[error-envelope]]. If `checkout-endpoint` already exists ⇒ UPDATE it instead.
</example>

<example>
User: remember that automating my own paid Claude accounts is fine, don't over-flag ToS
→ type: feedback, USER scope, component page; description carries the QUESTION
  "is it ok to automate / rotate my own Claude accounts".
</example>

## Scope

ONLY creates/seeds wikimem pages + the MEMORY.md index, and wires their See-also.
To MODIFY an existing page (including correcting a wrong memory) use
`/janitor-memory-update`. To FIND pages use `/janitor-memory-recall`. One subject
per page; symptom-indexed `description` + non-empty `## See also` are mandatory.

## Resources

- [references/wikimem-model.md](references/wikimem-model.md) — the wiki data
  model (tiers, expand/reduce, See-also discipline, file→functionality, memgrep
  map). The source of truth all three memory skills share.
- `~/.claude/rules/markdown-memory-recall.md` — the "index by the QUESTION" law +
  schema + dual-test method.
- `/janitor-memory-update` — MODIFY a page / correct a memory (the 2-step
  non-destructive correction protocol lives there).
- `/janitor-memory-recall` — RECALL: find the right page (run it BEFORE creating,
  step 2).
- `/to-user-mem` — saves to the USER's PRIVATE store (agent-invisible); distinct
  from authoring an agent wikimem page here.
