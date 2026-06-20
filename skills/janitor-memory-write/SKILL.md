---
name: janitor-memory-write
description: MEMORIZE — capture a durable decision/fact into the project's memory WIKI as a navigable page, not a loose note. Use after a bug-autopsy gotcha, a design/architecture decision, a project constraint not derivable from code, a confirmed user preference, or when the user says "remember this", "memorize this", "save a memory". Finds the right existing wikimem page first so it never duplicates; only when none fits, creates a HUB / ASPECT / COMPONENT page via the expand/reduce decision, wires it into the See-also web, and indexes it by symptom. The MEMORIZE leg of the wiki-memory protocol.
---

# Janitor memory — MEMORIZE

## Overview

MEMORIZE is the CREATE/CAPTURE leg of the memory wiki. It places a new durable
decision into the right wikimem page so a future session can navigate to it — not
dump a loose `.md` into a pile. Read [the wikimem model](references/wikimem-model.md)
once: pages have a **tier** (hub / aspect / component), a **See-also** context
web, and a **file→functionality** mapping. This skill is the rules for growing
that wiki correctly. The model doc's table of contents:

- A wiki, not a pile — and collaborative like Wikipedia
- The editorial decision flow (run this on any change worth remembering)
- EXPAND and REDUCE — radiating suns vs receiving terminals
- The three tiers (a page's role in the pyramid)
- The edge model — EVERY link is bidirectional (the link law)
- Page anatomy

Only memorize what is NON-OBVIOUS and reusable: design decisions, gotchas,
constraints not in the code, confirmed preferences, hard-won debugging facts. Do
NOT memorize what the repo already records (code structure, git history,
CLAUDE.md) or what only matters to this conversation.

## PROACTIVE-USE CONTRACT — write AFTER solving, unprompted (commitment 2)

This is the CAPTURE leg of THE PROACTIVE-USE CONTRACT (full text in
`~/.claude/rules/markdown-memory-recall.md`). **After you solve a non-trivial
problem, fix a bug, or make a decision** that isn't derivable from the code,
memorize it **without waiting to be asked** — RECALL first (so you ADD to the
owning page, never duplicate), then write/update. Route the scope BEFORE
authoring — **any wiki structure page (a hub / aspect / component describing the
project's code, architecture, conventions, or pipeline) is project knowledge by
definition → PROJECT** (git-tracked, shipped with the repo, shared with every
dev). Route to **LOCAL** ONLY when the content is specifically about THIS machine
(local absolute paths, this host's name, this machine's credentials/tokens).
Cross-project machine-independent facts → **USER**. The privacy backstop
(machine-specific *and* unsure → LOCAL) NEVER demotes a structure page —
architecture is not "unsure", it is PROJECT. To keep the PROJECT wiki current as you go — the
architecture hub, key-solution component pages, the publish/deploy pipeline page
— this skill is the tool; if the project has no wikimem yet, run
`/janitor-memory-bootstrap` once first.

## The algorithm

### 1. Route the SCOPE (machine-private vs shared vs global)

```bash
# DECIDE BY CONTENT — a wiki structure page (hub/aspect/component about the
#   project's code/architecture/conventions/pipeline) is PROJECT by DEFINITION:
# PROJECT = anything a teammate cloning the repo needs (git-tracked + pushed; NO secrets) — the DEFAULT for structure pages
# LOCAL   = ONLY machine-specific facts: local absolute paths, this host's name, this machine's creds/tokens (never pushed)
# USER    = true across ALL projects (a preference / machine-independent lesson)
# Privacy backstop: machine-specific AND unsure → LOCAL; project structure is NOT unsure → PROJECT.
case "$SCOPE" in
  local)   MEMDIR="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory" ;;
  project) MEMDIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.claude/project/memory" ;;  # in-repo, namespaced under .claude/ (add a !.claude/project/memory/** gitignore exception if .claude/ is ignored)
  user)    MEMDIR="$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory" ;;  # janitor's FIXED data dir, hard-coded — NOT ${CLAUDE_PLUGIN_DATA} (that is the running plugin's dir, not the janitor's, in an agent shell); untouchable, survives --keep-data
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

Pick exactly one (see the model for the full definition + the WHY):

- **New functionality entirely** (no hub yet for this area) → seed a **`hub`**
  page: the overview + the big general decisions + the parts map + the file
  `globs:` the functionality owns. The tip of the iceberg.
- **EXPAND → a GENERAL, RADIATING page** (`aspect`) — the memory is a *general
  rule shared by many elements* (a style, protocol, config, brand, convention:
  `style-system`, `error-envelope`, `dialog-forms`). It is a sun: it will carry
  links DOWN to EVERY element it governs.
- **REDUCE → a SPECIFIC, RECEIVING page** (`component`) — the memory is *specific
  to ONE element and governs nothing else* (`login-panel`, `user-model`,
  `checkout-endpoint`). It is a terminal: it only links UP to the general pages
  that govern it.

Keep the new page LEAN — never re-copy a governing rule into a component; link up
to it. This is what keeps the pyramid from exploding (the model's core WHY).
Honor the **one-component-one-page** invariant: if a component page for this
element already exists, the memory goes THERE (→ UPDATE), even if you arrived
from a different subject. Never make `login-panel-style` beside `login-panel`.

### 4. WRITE the page (Write tool, not echo)

Author `"$MEMDIR/<slug>.md"` with the model's schema. Set `ocd`/`lmd` to TODAY.
Include the **typed edge section for the page's tier** AND the standing
`## Notes and lessons learned` section (the janitor's page-shape validator flags
a page that omits its edges or the lessons section):

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
<the memories — LEAN. A hub: overview + parts map. An aspect: the shared rule.
A component: only what is specific to this element (never re-copy a governing
rule — link up to it). For feedback/project add **Why:** and **How to apply:**.>

## Applies to          # GENERAL pages (hub/aspect) ONLY — the radiating ray-list
- [[governed-element-1]] · [[governed-element-2]]   # EVERY element this rule governs

## Governed by         # COMPONENT pages ONLY — up-links to its governors
- [[style-system]] — the palette/spacing it uses.
- [[error-envelope]] — the error shape it returns.

## See also            # any tier (optional) — lateral relations, not govern edges
- [[user-model]] — the data this element binds.

## Notes and lessons learned
```

Use `## Applies to` on a hub/aspect, `## Governed by` on a component (+ optional
`## See also` either way). Each link says *why*; a `[[link]]` to a not-yet-written
page is fine (it flags one to create later).

### 5. WIRE the context — radiate or receive (this is what makes it a wiki)

A page with no edges is a dead note. **THE LINK LAW: every link is bidirectional
— if A links to B, B links to A, ALWAYS, See-also included.** Wire BOTH ends of
every edge in the same edit. Links are **scope-local**: a `[[wikilink]]` may only
target a page in the SAME scope root (LOCAL/PROJECT/USER) — reference another
scope's page in prose instead (see the model's Link hygiene). The wiring follows
the page's SHAPE:

- **If you EXPANDED (a general/radiating page):** in `## Applies to`, link DOWN to
  EVERY element this rule governs (find them:
  `memgrep -l "$MEMDIR" --where 'fm.tier "component" and fm.functionality "<fn>"' | sort -u`).
  Then the reciprocal: on each of those component pages, add this page to their
  `## Governed by`. Also link the new aspect from its hub's parts map (and the
  hub into the aspect's edges).
- **If you REDUCED (a component/receiving page):** in `## Governed by`, link UP to
  EVERY general page that affects this element (its style, protocols, configs).
  Then the reciprocal: on each of those general pages, add this element to their
  `## Applies to`. Link the new component from its hub's parts map (and the hub
  into the component's `## Governed by`).
- **Any `## See also` lateral link** gets its mirror See-also on the other page,
  same edit.

The janitor librarian backfills any reciprocal you miss and flags one-sided
edges, but it is a safety net — the author wires both ends now.

### 6. Index it (memgrep only — do NOT touch MEMORY.md)

The index is 100% memgrep's — the agent-invisible, unlimited SQLite
`.memgrep/index.db`. Do **NOT** append a pointer to `MEMORY.md` (it is a retired
deprecation stub; hand-maintaining a human index is what grew unbounded and
corrupted memories). Just refresh the search index: `memgrep reindex "$MEMDIR"`
if memgrep is present (optional — recall auto-reindexes). Recall finds the new
page by its `description`/body, never by a human index.

### 7. Sanity-check

- Would a future session find this from the SYMPTOM via `description`? If the
  description reads like the *answer*, rewrite it as the *question*.
- Is EVERY link bidirectional — each `## Applies to` ray matched by a
  `## Governed by` on the element (and vice versa), and each `## See also`
  mirrored on the other page? No one-sided link of ANY kind (the link law).
- Is the page LEAN — no governing rule re-copied that should be a link up?
- Did you respect one-component-one-page (no fragmenting an element)?
- If you created a hub, are its `globs` precise and non-overlapping with other
  hubs (one file → one functionality)?
- Is the frontmatter COMPLETE — `name`, `description`, `ocd`, `lmd`,
  `metadata.{node_type: memory, type, tier}` (+ `functionality`, and `globs` on a
  hub) — and is the `## Notes and lessons learned` section present (even if empty)?
  A page missing any of these is malformed and ranks/repairs poorly.
- Does the SHAPE match the tier — a `hub`/`aspect` RADIATES via `## Applies to`
  (NEVER `## Governed by`); a `component` RECEIVES via `## Governed by` (NEVER
  `## Applies to`)? Inverting these is the most common authoring error.

## Output

The page path + its one-line description + the See-also targets you wired. Do NOT
echo the whole page back into the conversation.

## Examples

<example>
Decision: "all destructive dialogs use a red secondary 'Delete' button, primary is Cancel."
→ general rule shared by many dialogs ⇒ EXPAND ⇒ RADIATING aspect `dialog-forms`
  (functionality: frontend). `## Applies to`: [[login-panel]], [[settings-panel]],
  … every dialog. Reciprocal: each of those gets `dialog-forms` in its
  `## Governed by`. Linked from the `frontend` hub's parts map.
</example>

<example>
Decision: "the checkout endpoint is idempotent on the Idempotency-Key header."
→ specific to one element ⇒ REDUCE ⇒ RECEIVING component `checkout-endpoint`
  (functionality: backend). `## Governed by`: [[error-envelope]] (the protocol it
  obeys); `## See also`: [[order-model]], [[payment-gateway]] (lateral). Reciprocal:
  `error-envelope`'s `## Applies to` gains `checkout-endpoint`. If
  `checkout-endpoint` already exists ⇒ UPDATE it instead.
</example>

<example>
User: remember that automating my own paid Claude accounts is fine, don't over-flag ToS
→ type: feedback, USER scope, component page; description carries the QUESTION
  "is it ok to automate / rotate my own Claude accounts".
</example>

## Scope

ONLY creates/seeds wikimem pages and wires their See-also (the index is memgrep's
— never touch MEMORY.md). To MODIFY an existing page (including correcting a wrong memory) use
`/janitor-memory-update`. To FIND pages use `/janitor-memory-recall`. One subject
per page; symptom-indexed `description` + non-empty `## See also` are mandatory.

## Checklist

Copy this checklist and track your progress:

- [ ] Scope routed — structure/architecture/code → PROJECT; machine-specific → LOCAL; cross-project → USER
- [ ] RECALL ran first — no existing page already covers this fact
- [ ] Editorial decision made (new page vs UPDATE an existing page)
- [ ] Frontmatter COMPLETE: `name`, `description`, `ocd`, `lmd`, `node_type: memory`, `type`, `tier` (+ `globs` on hubs)
- [ ] Page written: one subject, symptom-indexed `description:`, correct tier
- [ ] Tier SHAPE correct: hub/aspect → `## Applies to`; component → `## Governed by` (NOT inverted)
- [ ] `## Notes and lessons learned` section present (even if empty)
- [ ] Every `[[link]]` added on BOTH ends (the bidirectional link law)
- [ ] `memgrep reindex` run if present — the index is memgrep's; do NOT touch `MEMORY.md`

## Resources

- [references/wikimem-model.md](references/wikimem-model.md) — the wiki data
  model (tiers, expand/reduce, See-also discipline, file→functionality, memgrep
  map). The source of truth all three memory skills share. Its table of contents:
  - A wiki, not a pile — and collaborative like Wikipedia
  - The editorial decision flow (run this on any change worth remembering)
  - EXPAND and REDUCE — radiating suns vs receiving terminals
  - The three tiers (a page's role in the pyramid)
  - The edge model — EVERY link is bidirectional (the link law)
  - Page anatomy
- `~/.claude/rules/markdown-memory-recall.md` — the "index by the QUESTION" law +
  schema + dual-test method.
- `/janitor-memory-update` — MODIFY a page / correct a memory (the 2-step
  non-destructive correction protocol lives there).
- `/janitor-memory-recall` — RECALL: find the right page (run it BEFORE creating,
  step 2).
- `/janitor-memory-user-add` (legacy `/to-user-mem`, still works) — saves to the
  USER's PRIVATE store (agent-invisible); distinct from authoring an agent wikimem
  page here.
