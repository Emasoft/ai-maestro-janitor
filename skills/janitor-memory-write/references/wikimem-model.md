# The wikimem model — memory as a navigable wiki, not a pile of notes

This is the shared data model the three core memory skills (**MEMORIZE**,
**UPDATE**, **RECALL**) all build on. Read it once; the skills cite it instead
of repeating it.

## Why a wiki, not a folder of `.md` files

Claude Code's default memory is a flat accumulation of atomic notes — one fact
per file, found only by a lucky symptom match. That has no *structure*: no
overview, no navigation, no context. You cannot answer "what do I need to know
before touching the frontend?" because there is no frontend *page* — only N
scattered facts that each mention the frontend.

A **wikimem** is a real wiki over the same `memory/` directory: a pyramid you
enter at the **tip** (a functionality's overview page) and descend through links
to exactly the detail you need — and no more, like a Skill that links references
you read only if relevant. The structure is what turns an accumulation into
knowledge.

## The three tiers (a page's role in the pyramid)

Every wikimem page declares a `tier`. The tier is the page's place in the
pyramid and is the output of the **expand/reduce** decision (below).

| `tier` | What it holds | Example | Created by |
|---|---|---|---|
| **`hub`** | The OVERVIEW of one whole functionality — the tip of the iceberg. The big, general decisions; the map of the parts; links down to aspects + components. | `frontend`, `backend`, `db`, `render-3d`, `scraper`, `auth` | seeding a functionality |
| **`aspect`** | A GENERAL rule/decision SHARED ACROSS MANY components or procedures (cross-cutting). | `style-system`, `fonts`, `dialog-forms`, `error-envelope`, `logging-format` | **EXPAND** |
| **`component`** | The SPECIFIC decisions for ONE element only. ALL of that element's memories live here — never fragmented across pages. | `login-panel`, `user-model`, `checkout-endpoint`, `markdown-parser` | **REDUCE** |

A `hub` is the functionality's front door. `aspect` pages generalize a subject
across the functionality (or across several). `component` pages are the leaves —
one element, one page.

> The pyramid is NOT strictly tree-shaped. It EXPANDS where a subject is shared
> by many (an aspect), and REDUCES where a subject is one element (a component).
> Many aspects and the hub all link DOWN to the same shared component pages, so
> the graph converges rather than fanning out forever.

## EXPAND vs REDUCE — the decision you make when no page fits

When you have a new memory and no existing page is the right home, you create a
new page — but FIRST decide its shape:

- **EXPAND → author an `aspect` page** when the memory is a *general aspect or
  rule shared by many components/procedures* ("all dialogs confirm destructive
  actions with a red secondary button", "every API error uses this envelope",
  "the palette is these 6 tokens"). The subject generalizes; the page is the one
  place that rule lives, and every component that obeys it links to it.
- **REDUCE → author a `component` page** when the memory is *specific to one
  element* ("the login panel's 'forgot password' link routes to /reset", "the
  user model's `email` is unique-indexed"). The subject is singular; the page
  collects ALL of that element's details.

The same incoming fact can go either way depending on its *generality*, and that
is exactly the judgment the MEMORIZE skill encodes.

## The one-component-one-page invariant (anti-fragmentation)

A component has **exactly one** page. Every page that needs to reference that
component — the hub, the style aspect, the interaction aspect — links to the
**same** component page. Do NOT create `login-panel-style` and
`login-panel-behavior`: that scatters one element across two files and the next
agent finds only half. Keep everything about one element in its one page;
different *subjects* (style, behavior, data) become *sections* within it, or
links OUT to the shared aspect — not new component pages.

Rule of thumb: **expand by SUBJECT, reduce by ELEMENT.** A new page is justified
when it is a new shared subject (aspect) or a new element (component) — never
when it is the same element seen from another subject's angle.

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
  functionality: <hub-slug>        # which functionality this belongs under (e.g. frontend)
  globs: ["src/frontend/**", ...]  # file patterns this page's subject OWNS (mainly on hubs)
---

<THE MEMORIES — the durable decisions/facts for this page's subject. For a hub:
the overview + the big general decisions + a short map of the parts. Concise;
detail lives in the linked pages.>

## See also
- [[style-system]] — the palette + spacing tokens this panel uses.
- [[user-model]] — the data this panel reads/writes.
- [[auth-endpoints]] — the login/reset API calls it makes.
<every page that RELATES TO or INFLUENCES this subject: general styles, the
view/model design, the api functions, graphic items, animations, the db, …>

## Notes and lessons learned
[^N]: [ocd:… lmd:…] <a corrected error, demoted here with its WHY>
```

Three load-bearing keys:

- **`description`** — the recall surface. Carry the *symptom/topic* a future
  session searches with, not the answer's jargon (see the markdown-memory-recall
  rule's "index by the QUESTION").
- **`globs`** — the **file→functionality** map. A hub lists the file patterns its
  functionality owns, so RECALL can map "the file the agent is editing" back to
  the hub to surface. This is the linchpin of goal #1.
- **the `## See also` section** — the **context web**. NOT optional. A page is
  its memories PLUS its context; without See-also you have a fact, not a wiki
  node. Each link says *why* it relates, so the reader decides whether to follow
  it (progressive disclosure).

## The `## See also` discipline — context is mandatory

Every page links, in `## See also`, to everything that *relates to or influences*
its subject. For a UI component that is: the general style aspect, the view/model
it binds, the API functions it calls, graphic items/animations it uses, the db
tables behind it. For a backend service: its data models, the endpoints, the
auth aspect, the logging aspect, downstream consumers.

This is what makes the wiki *explorable*: an agent reading the `login-panel` page
sees it depends on `style-system`, `user-model`, `auth-endpoints` and follows
only the ones its current task needs — exactly how a Skill exposes references it
may or may not read. A page with memories but no See-also is a dead end.

Links are `[[page-name]]` (the wikilink memgrep parses for the graph). A link to
a page that doesn't exist yet is fine — it marks a page worth creating (the
janitor's librarian surfaces these as broken links to fill).

## The superseded-memory invariant (updates never delete)

A wikimem page records the current truth in its body AND its own history of
changed decisions in `## Notes and lessons learned`. Whenever an update
**supersedes** a memory — a corrected fact, a reversed decision, a changed
value/threshold, an abandoned approach — the old memory is **never deleted or
silently overwritten**. The body is cleaned to the new truth, and the superseded
statement is demoted to a dated `[^N]` lesson carrying the **WHY** (what it was +
why it changed), which the corrected body statement links to.

This is RULE 0 (never lose information) + the Bug-Autopsy directive applied to
memory: the fact moves forward clean; the history/WHY persists as a guardrail so
the next session can't repeat the old mistake or re-litigate a settled flip. It
is a top-level invariant of the UPDATE skill — see that skill for the mechanics.

## File → functionality (the RECALL entry point)

Goal #1: when an agent is about to work on a FILE, surface that file's
functionality HUB. Mechanism:

1. Hub pages carry `globs:` — the file patterns the functionality owns.
2. RECALL takes the file(s) the agent is touching, finds the hub whose `globs`
   match, and surfaces THAT hub (the tip), plus its top-level See-also.
3. The agent then descends — reads the hub, follows links to the aspect/component
   pages relevant to the specific file, ignores the rest.

Keep `globs` precise and non-overlapping across hubs (one file → one
functionality). Overlap is a signal the functionalities aren't cleanly split.

## Navigation contract — progressive disclosure

RECALL surfaces the **tip**, never the whole subtree. The agent reads the hub,
then chooses which `[[links]]` / See-also edges to follow based on the task —
loading detail pages on demand, not all at once. This keeps context spend
proportional to the task, the same principle as Skill reference autodiscovery.
Never dump an entire functionality's page tree into context "to be safe".

## memgrep — the instrument (which command does what)

memgrep is the *tool*; these skills are the *rules* for using it.

| Operation | memgrep |
|---|---|
| Symptom recall | `memgrep recall "<symptom>" <roots…>` |
| Find a hub by the file being edited | list hubs (`--where 'fm.tier "hub"'`), match each hub's `globs` against the file |
| Follow the context web outward | `memgrep links --from <page>` / `--where 'linked-from "<page>"'` |
| Who links INTO this page (back-context) | `memgrep links --to <page>` / `--where 'links-to "<page>"'` |
| Pages of a functionality | `memgrep --where 'fm.functionality "frontend"'` |
| Missing context to fill | `memgrep links --broken` / `--orphans` |
| Refresh the index | `memgrep reindex <root>` |

When memgrep is absent, every operation degrades to `grep`/`ls` over the same
files — the wiki is plain markdown, so it never *breaks*, it only gets slower to
navigate.

## Scope (LOCAL / PROJECT / USER) is orthogonal to tier

The wiki exists at each scope (machine-private LOCAL, git-tracked PROJECT, global
USER) exactly as the markdown-memory-recall rule describes. A `frontend` hub can
exist at PROJECT scope (shared design decisions, pushed) while a
`frontend-local-paths` component lives at LOCAL (machine-specific). RECALL
searches all scopes with LOCAL > PROJECT > USER precedence; tier is about the
pyramid, scope is about visibility. They compose.

## Backward compatibility

Existing atomic notes (`node_type: memory`, no `tier`) are valid — treat a page
with no `tier` as a `component`. The wiki structure is *additive*: MEMORIZE/UPDATE
add `tier`, `functionality`, `globs`, and `## See also` as pages are touched, and
the janitor's librarian backfills missing context over time. No migration event
is required; the pile becomes a wiki incrementally.
