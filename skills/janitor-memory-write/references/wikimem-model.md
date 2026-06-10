# The wikimem model — memory as a collaborative, navigable wiki

This is the shared data model the three core memory skills (**MEMORIZE**,
**UPDATE**, **RECALL**) all build on. Read it once; the skills cite it instead of
repeating it.

## A wiki, not a pile — and collaborative like Wikipedia

Claude Code's default memory is a flat accumulation of atomic notes — one fact
per file, found only by a lucky symptom match. No overview, no navigation, no
context, and the SAME shared fact (the palette, the error protocol) gets
re-copied into every note that touches it until the corpus is mostly redundancy.

A **wikimem** is a real wiki over the same `memory/` directory. Like Wikipedia it
is **collaborative**: ANY agent or sub-agent that changes code asks "is this
worth remembering?" and, if so, edits the wiki — adding to an existing page,
correcting one, or creating a new page. Every editor follows the same discipline,
so the wiki stays coherent no matter how many agents contribute.

## The editorial decision flow (run this on any change worth remembering)

```
A change worth remembering (non-obvious, reusable — not derivable from the code)
        │
        ├─ Does it CONTRADICT an existing memory? ───────────► UPDATE the page.
        │     (a protocol changed, a value flipped)            The OLD memory is
        │                                                      demoted to a dated
        │                                                      lesson with the WHY
        │                                                      (never deleted).
        │
        ├─ Does it FIT an existing page's subject? ──────────► ADD it there.
        │     (the one-page-per-subject rule)
        │
        └─ Needs a NEW page? Decide its SHAPE:
              ├─ General impact — a style / protocol / config that affects
              │   MANY components or functionalities ────────► EXPAND  (a radiating page)
              └─ Specific to ONE element, governs nothing
                  else ─────────────────────────────────────► REDUCE  (a receiving page)
```

The "worthy of a new page or fold into an existing one?" judgment is the
Wikipedia-editor instinct; EXPAND/REDUCE is how you shape the page once you've
decided it is new.

## EXPAND and REDUCE — radiating suns vs receiving terminals

The wiki runs from abstract/general at the top to particular/specific at the
bottom, but **the bottom is not bigger than the top** — the opposite. Two moves:

- **EXPAND → a GENERAL page that RADIATES** (a `hub` or `aspect`). It holds a rule
  that applies to many elements — a style, a protocol, a config, a brand, a
  convention. It is a *sun*: it carries links DOWN to **every** element the rule
  governs (`frontend-style` links ALL the component pages, because the whole site
  shares the style). Authoring it EXPANDS because its rules extend their impact
  across many pages — it increases the *configurations* of the system (every
  fixed component × the general styles/protocols/configs that may apply to it).

- **REDUCE → a SPECIFIC page that RECEIVES** (a `component`). It holds the details
  of ONE element — a particular dialog, one reusable component, one endpoint. It
  is a *terminal*: it collects the rays of the general pages that govern it, and
  defines only ITSELF. It links UP to the abstract pages affecting it (style,
  protocols, configs); it lists **nothing** downstream, because it governs no
  other element. Authoring it REDUCES because it pins one fixed, lean element at
  the receiving end of the general rules.

> Analogy: a fixed cast of people can wear infinite combinations of the same
> wardrobe. The **components are the people** (fixed, lean); the **general pages
> are the wardrobe** (styles/protocols/configs). EXPAND grows the wardrobe;
> REDUCE adds a person. The combinations are implicit in the links — you never
> write them out.

### Why this is the whole point — the pyramid SLIMS toward the base

Without abstraction you'd copy the style + protocol + config rules into every
button, function, and endpoint page — a page with a hundred memories, the same
rules repeated everywhere. EXPAND writes each shared rule **ONCE** in its
radiating page; every governed component just carries a **pointer up** to it. So:

- A 100-memory component page collapses to ~a dozen memories + governed-by links.
- The base layer (components) can be **less populated** than the abstract layers
  above it — no per-element rule duplication.
- The corpus stays **compact, non-redundant**, and **cacheable**: an agent reads
  a shared general page ONCE into context and reuses it across every component
  that points at it — so navigating from a component to the rules affecting it
  costs only the strict minimum tokens for the task.

This is the success criterion: going abstract→particular must NOT generate
gigabytes of one-page-per-element. EXPAND/REDUCE keeps it small.

## The three tiers (a page's role in the pyramid)

Every page declares a `tier` — the output of the EXPAND/REDUCE decision:

| `tier` | Role | Radiates? | Example | Created by |
|---|---|---|---|---|
| **`hub`** | a functionality's overview — the tip of the iceberg + the map of its parts + the file `globs:` it owns | yes (to its parts) | `frontend`, `backend`, `db`, `render-3d`, `scraper` | seeding a functionality |
| **`aspect`** | a GENERAL rule shared across many elements (a sun) | yes (to ALL it governs) | `style-system`, `fonts`, `dialog-forms`, `error-envelope`, `logging-format` | **EXPAND** |
| **`component`** | ONE element's full details (a terminal) | no — only receives | `login-panel`, `user-model`, `checkout-endpoint`, `markdown-parser` | **REDUCE** |

`hub` and `aspect` are GENERAL/radiating; `component` is SPECIFIC/receiving. Many
suns (hub + aspects) all radiate DOWN onto the same shared component terminals,
so the graph CONVERGES rather than fanning out forever.

## The directional edge model (typed links, not a flat "see also")

Links carry MEANING based on the two endpoints' tiers. Every page stores the
edges relevant to ITS side:

- **On a GENERAL page (`hub`/`aspect`) → `## Applies to`** — the ray-list: a
  `[[link]]` to EVERY element this page's rule governs. The `frontend-style`
  aspect lists every component that wears that style. This is what makes "show me
  everything affected by this protocol" a single read.
- **On a COMPONENT page → `## Governed by`** — a `[[link]]` UP to EVERY general
  page that affects this element (its style, its protocols, its configs). This is
  what makes "what rules must I obey to touch this component?" a single read. A
  component lists NOTHING downstream — it governs nothing.
- **`## See also`** (optional, any tier) — genuinely LATERAL relations that are
  not a govern edge: a sibling component it interacts with, the view/model it
  binds, the db table behind it, a related aspect.

`Applies to` and `Governed by` are the two halves of ONE edge: if `style-system`
*Applies to* `login-panel`, then `login-panel` is *Governed by* `style-system`.
When you create/extend one side, add the reciprocal on the other (the janitor
librarian backfills any you miss and flags one-sided edges). Links are
`[[page-name]]` wikilinks (memgrep parses them); a link to a not-yet-written page
is fine — it marks one to create, and the librarian surfaces it as a broken link.

## Page anatomy

```yaml
---
name: <kebab-slug>                 # == filename stem (frontend, login-panel, style-system)
description: "<symptom/topic surface — the words a future search will use>"
ocd: <YYYY-MM-DD>                  # Original Creation Date — set once
lmd: <YYYY-MM-DD>                  # Last Modified Date — bump on every edit
metadata:
  node_type: memory                # unchanged — wikimem pages ARE memory pages
  type: project | reference | feedback | user
  tier: hub | aspect | component   # the pyramid role (absent ⇒ treat as component)
  functionality: <hub-slug>        # which functionality this lives under (frontend, backend…)
  globs: ["src/frontend/**", ...]  # files this page's subject OWNS (REQUIRED on hubs)
---

<THE MEMORIES — the durable decisions for this page's subject, kept LEAN. A hub:
the overview + the big general decisions + the parts map. An aspect: the shared
rule itself. A component: only what is specific to this element — DO NOT re-copy
a governing rule, link up to it instead.>

## Applies to            # GENERAL pages only (hub/aspect) — the radiating ray-list
- [[login-panel]] · [[settings-panel]] · [[checkout-page]]   # every element this rule governs

## Governed by           # COMPONENT pages only — the up-links to its governors
- [[style-system]] — the palette + spacing tokens this element uses.
- [[error-envelope]] — the API error shape it returns.

## See also              # any tier (optional) — lateral relations, not govern edges
- [[user-model]] — the data this element binds.

## Notes and lessons learned
[^N]: [ocd:… lmd:…] <a superseded memory, demoted here with its WHY>
```

A `component` uses `## Governed by` (+ optional `## See also`); a `hub`/`aspect`
uses `## Applies to` (+ optional `## See also`). The point is the same: a page is
its (lean) memories PLUS its typed context edges. A page with memories but no
edges is a dead end, not a wiki node.

## The superseded-memory invariant (updates never delete)

Whenever an update **supersedes** a memory — a corrected fact, a reversed
decision, a changed value, an abandoned approach — the old memory is **never
deleted or silently overwritten**. The body is cleaned to the new truth, and the
superseded statement is demoted to a dated `[^N]` lesson under `## Notes and
lessons learned` carrying the **WHY** (what it was + why it changed), which the
corrected body links to. RULE 0 + the Bug-Autopsy directive applied to memory:
the fact moves forward clean; the history/WHY persists as a guardrail so the next
session can't repeat the old mistake or re-litigate a settled flip. Mechanics are
in the UPDATE skill.

## File → functionality (the RECALL entry point)

When an agent is about to work on a FILE, surface that file's functionality HUB:

1. Hub pages carry `globs:` — the file patterns the functionality owns.
2. RECALL takes the file(s) being touched, finds the hub whose `globs` match, and
   surfaces THAT hub (the tip) + its parts map.
3. The agent descends: reads the hub, then follows the relevant component's
   `## Governed by` up-links to load the governing aspects — each read ONCE,
   reused (cached) across components — and ignores the rest.

Keep `globs` precise and non-overlapping across hubs (one file → one
functionality); overlap means the functionalities aren't cleanly split.

## Navigation contract — progressive disclosure + cache the suns

RECALL surfaces the **tip**, never the whole subtree. Descend by following the
typed edges the task needs:

- editing a component → read its `## Governed by` general pages (the rules you
  must obey), each loaded ONCE and reused across every component that shares it
  (the cacheability win — never re-read a sun you already have in context);
- changing a general rule → read its `## Applies to` ray-list to see every
  element you'd affect before you change it.

Never dump an entire functionality's page tree into context "to be safe" — the
whole point is that token spend stays proportional to the task.

## memgrep — the instrument (which command does what)

memgrep is the *tool*; these skills are the *rules*.

| Operation | memgrep |
|---|---|
| Symptom recall | `memgrep recall "<symptom>" <roots…>` |
| Find the hub for the file being edited | list hubs (`--where 'fm.tier "hub"'`), match each hub's `globs` against the file |
| EXPAND: all elements to radiate onto | `memgrep --where 'fm.tier "component" and fm.functionality "<fn>"'` → link them in `## Applies to` |
| Descend (component → its governors) | read the page's `## Governed by`, or `memgrep links --from <component>` |
| Reverse (general → all it affects) | `memgrep --where 'linked-from "<general>"'` / `memgrep links --to <general>` |
| Reciprocity audit (one-sided edges) | compare `links --to <general>` against the general's `## Applies to` list → librarian backfills |
| Pages of a functionality | `memgrep --where 'fm.functionality "frontend"'` |
| Context edges to fill | `memgrep links --broken` / `--orphans` |
| Refresh the index | `memgrep reindex <root>` |

When memgrep is absent, every operation degrades to `grep`/`ls` over the same
plain-markdown files — the wiki never *breaks*, it only gets slower to navigate.

## Scope (LOCAL / PROJECT / USER) is orthogonal to tier

The wiki exists at each scope (machine-private LOCAL, git-tracked PROJECT, global
USER) per the markdown-memory-recall rule. A `frontend` hub can be PROJECT
(shared, pushed) while `frontend-local-paths` is LOCAL (machine-specific). RECALL
searches all scopes with LOCAL > PROJECT > USER precedence. Tier is the pyramid;
scope is visibility; they compose.

## Backward compatibility

Existing atomic notes (`node_type: memory`, no `tier`) are valid — treat a page
with no `tier` as a `component`. The wiki structure is *additive*: MEMORIZE/UPDATE
add `tier`, `functionality`, `globs`, and the typed edges as pages are touched,
and the janitor librarian backfills missing context + reciprocity over time. No
migration event is required; the pile becomes a wiki incrementally.
