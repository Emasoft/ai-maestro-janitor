# The wikimem model — memory as a collaborative, navigable wiki

This is the shared data model the three core memory skills (**MEMORIZE**,
**UPDATE**, **RECALL**) all build on. Read it once; the skills cite it instead of
repeating it.

## Table of contents

- [A wiki, not a pile — and collaborative like Wikipedia](#a-wiki-not-a-pile--and-collaborative-like-wikipedia)
- [The editorial decision flow (run this on any change worth remembering)](#the-editorial-decision-flow-run-this-on-any-change-worth-remembering)
- [EXPAND and REDUCE — radiating suns vs receiving terminals](#expand-and-reduce--radiating-suns-vs-receiving-terminals)
- [The three tiers (a page's role in the pyramid)](#the-three-tiers-a-pages-role-in-the-pyramid)
- [The edge model — EVERY link is bidirectional (the link law)](#the-edge-model--every-link-is-bidirectional-the-link-law)
- [Page anatomy](#page-anatomy)
- [Atoms — first-class body elements (block-properties)](#atoms--first-class-body-elements-block-properties)

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

## The edge model — EVERY link is bidirectional (the link law)

**The one law of wikimem links: if A links to B, B links to A. ALWAYS.** No
exceptions, no link type exempt. Every edge in the wiki is one relation stored on
BOTH endpoints, so the graph is fully navigable from ANY page in ANY direction —
an agent landing on a component can climb to every rule that governs it, and an
agent landing on a rule can descend to every element it affects, without any
reverse-lookup machinery. A one-sided link is a defect (the janitor librarian
detects and backfills it, but the authoring agent wires both ends NOW).

Links also carry MEANING based on the two endpoints' tiers — the SAME edge is
named differently on each side. Every page stores the half relevant to ITS side:

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
  binds, the db table behind it, a related aspect. **Also bidirectional:** if
  `login-panel`'s See-also lists `[[user-model]]`, then `user-model`'s See-also
  lists `[[login-panel]]`.

How the law maps to the sections — the same edge, two spellings:

| Edge kind | On the A side | On the B side |
|---|---|---|
| govern (general ↔ element) | general's `## Applies to` → `[[element]]` | element's `## Governed by` → `[[general]]` |
| hub ↔ part | hub's parts map / `## Applies to` → `[[part]]` | part's `## Governed by` (or hub link) → `[[hub]]` |
| lateral (peer ↔ peer) | A's `## See also` → `[[B]]` | B's `## See also` → `[[A]]` |

When you create/extend one side, add the reciprocal on the other in the SAME
edit (the janitor librarian backfills any you miss and flags one-sided edges).
Links are `[[page-name]]` wikilinks (memgrep parses them); a link to a
not-yet-written page is fine — it marks one to create, and the librarian
surfaces it as a broken link until the page (and its back-link) exists.

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
  commits: ["<sha>", ...]          # PROVENANCE (code-change memories): the commit(s) the fact came from
  trdd: TRDD-<8hex>                # the TRDD that designed that change (corroborated by its implementation-commits:)
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

**The lead — one-topic discipline.** A page that carries MORE THAN ONE fact or
facet — a hub, an aspect, or a freshly *merged* page — OPENS with a one-sentence
**lead** that names its single subject, so the page reads as ONE topic rather than
a pile (the Wikipedia lead). An atomic single-fact `component` needs none — its one
fact *is* the lead. The lead only ORIENTS the reader; it never asserts a claim the
body doesn't already support, so it never adds an unverifiable fact. This is the
structural half of one-element-one-page: the no-third-page / same-subject gates keep
*distinct* subjects apart; the lead keeps the *surviving* page reading as the single
subject it is.

## Atoms — first-class body elements (block-properties)

A page body is not opaque prose — it is a sequence of **atoms**, the body
counterpart of `[^N]` lessons. An atom is one durable fact (it may span several
paragraphs, a table, a code block) and it carries **its own metadata** so memgrep
can index and recall it **individually**, by its own keywords, not just as part of
its page. This is the second of the **two metadata levels** — do NOT conflate them:

1. **PAGE metadata** — the YAML `---` frontmatter (`name`, `description`, `tier`, …).
   One per file; the page's identity.
2. **ATOM metadata** — a per-atom **block-properties** marker attached to each fact
   in the body. This is what delimits one atom from the next.

**The syntax is the Obsidian Block-Properties plugin** (`^<block-id> [key: value,
…]`), placed at the **END** of the block(s) it identifies:

```markdown
The rotator drains the live (near-limit) account first, then rotates to a safe
alternate that is below SAFE on BOTH the 5h and 7d windows.
^rotate-drain [keywords: rotator drain rate-limit oauth alternate, type: reference, ocd: 2026-06-23, lmd: 2026-06-23]
```

Parsing grammar (memgrep implements exactly this):
- a **comma splits properties** (a `[[wikilink]]`/`^ref` value is depth-protected,
  so a comma inside `[[A, B]]` is not a split);
- the **first colon splits** `key: value` (colons inside a value — a URL — are kept);
- the trimmed value is **split on whitespace into a VALUE ARRAY** (the AI-Maestro
  extension — `keywords: a b c` is three values; a value with no space is a 1-array).

**`keywords:` is the only REQUIRED prop** — it is the atom's **recall surface**, the
array of terms a future search will use to find THIS fact (the page's `description`
does the same job for the whole page). `ocd`/`lmd`/`type` are optional (an atom with
none inherits the page's). Two more props are stamped only on **harvested** atoms (an
atom imported from the Claude `MEMORY.md` buffer system): `claude_mem_ref:
<buffer-rel-path>` + `claude_mem_hash: <sha256-16>` — its provenance back to the
source buffer note, which `memgrep find-claude-mem-ref <buffer.md>` queries.

**How recall returns an atom:** `memgrep recall` ranks atoms by their keyword surface
and prints them `path#atom-id — <keywords>`, interleaved with whole-page results by
score. An atom has NO `[^N]` lessons of its own (its WHY/provenance lives in its
block-props); a superseded ATOM fact is still demoted to a page-level `[^N]` lesson
(the invariant below), the atom body cleaned to the new truth.

**Authoring discipline:** give each durable fact its own `^id [keywords: …]` marker
so it is findable on its own. Block-ids are page-unique kebab/`^memory-<uid>` slugs.
A page whose body is still free prose (no markers) is valid — its facts are simply
recalled at page granularity until the atomize migration (or a manual edit) gives
them markers. One fact = one atom, mirroring one element = one page.

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

## Provenance — `commits:` / `trdd:` and the WHY-resolution chain

A memory that records a **code change** SHOULD carry its provenance: the
`commits:` (the SHA[s] the fact came from) and, when one exists, the `trdd:`
(the TRDD that designed the change). These are optional and forward-going —
existing notes without them stay valid — but they are what makes the
**superseded-memory WHY sourceable rather than inferred**.

When the autonomous conflict / fact-verification pass finds an **obsolete**
memory, it resolves the WHY for the `[^N]` demotion in this fixed order, and
**never invents one**:

`memory.commits:` → `memory.trdd:` → that TRDD's `implementation-commits:` →
`git show <sha>` (commit message **+** diff **+** code comments at the site).

That chain is only as good as the discipline that fed it — see
`~/.claude/rules/commit-discipline.md` (commit often; WHY in the commit message
AND the code comments; `TRDD-<8hex>` in the subject). It is also the test the
pass uses to tell a **false** memory (no trace anywhere in git → safe to delete)
from a **superseded** one (traceable → demote, never delete): a memory with **no
provenance and no git trace is NOT deleted** — provenance is the precondition for
the destructive path.

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

memgrep is the *tool*; these skills are the *rules*. Command semantics below are
EMPIRICALLY VERIFIED against memgrep 0.1.0 — note especially the `links` flags:
**`--to NOTE` = NOTE's OUT-links (where NOTE points); `--from NOTE` = NOTE's
BACKLINKS (who points at NOTE)** — read them as "links to/from, relative to the
named note".

| Operation | memgrep |
|---|---|
| Symptom recall (pages + `[^N]` lessons + body atoms, interleaved) | `memgrep recall "<symptom>" <roots…>` |
| Atoms harvested FROM a Claude buffer note (provenance) | `memgrep find-claude-mem-ref <buffer.md> <dir>` |
| List hub pages (then match their `globs` against the file you're editing) | `memgrep -l <dir> --where 'fm.tier "hub"' \| sort -u` |
| EXPAND: all elements to radiate onto | `memgrep -l <dir> --where 'fm.tier "component" and fm.functionality "<fn>"' \| sort -u` |
| Where does this page point? (out-links) | `memgrep links --to <page> <dir>` |
| Who points at this page? (backlinks) | `memgrep links --from <page> <dir>` |
| Files that link to N (semijoin) | `memgrep -l <dir> --where 'links-to "<N>"' \| sort -u` |
| Files N links to (semijoin) | `memgrep -l <dir> --where 'linked-from "<N>"' \| sort -u` |
| Bidirectionality audit (the link law) | for each page: out-links (`links --to`) minus backlinks (`links --from`) must be empty both ways → librarian backfills |
| Pages of a functionality | `memgrep -l <dir> --where 'fm.functionality "frontend"' \| sort -u` |
| Dangling / unreferenced pages | `memgrep links --broken <dir>` / `memgrep links --orphans <dir>` |
| Refresh the index | `memgrep reindex <dir>` |

(`fm.KEY` matches the key ANYWHERE in the frontmatter — `fm.tier` finds the
nested `metadata.tier`; a dotted path like `fm.metadata.tier` does NOT work.)

When memgrep is absent, every operation degrades to `grep`/`ls` over the same
plain-markdown files — the wiki never *breaks*, it only gets slower to navigate.

## Link hygiene (simulation-verified constraints)

Empirically verified against memgrep 0.1.0 (simulations, TRDD-bc16d602):

- **Links are SCOPE-LOCAL.** A `[[wikilink]]` may only target a page in the SAME
  scope root. The link graph is computed per root, so a LOCAL→PROJECT wikilink
  is forever "broken" to the per-scope librarian — and a PROJECT→LOCAL back-link
  (required by the link law) would be broken for every other dev who clones the
  repo. Cross-scope references go in PROSE (name the page and its scope), never
  as a wikilink.
- **Link the PAGE, not an anchor.** `[[page#section]]` resolves, but the law's
  reciprocal is page-level; prefer bare `[[page]]`.
- **Targets are the page name exactly** — `[[name|alias]]` works; resolution is
  case-insensitive (keep canonical casing anyway); SPACES in a target do NOT
  resolve (use the kebab page name).
- **Lessons' links count.** A `[[link]]` inside a `[^N]` lesson is a real graph
  edge — the link law applies to it like any other.
- **Fenced code is invisible** to the link graph AND the librarian's shape scan
  — a doc example showing `## Applies to` or `[[x]]` inside ``` fences is inert.
- **Keep page names unique across scopes** unless deliberately shadowing —
  recall surfaces same-named pages from every scope and only the path
  distinguishes them (precedence LOCAL > PROJECT > USER is the reader's rule).
- **Globs match repo-RELATIVE file paths.** Entry A must normalize the file to
  repo-relative before matching (`fnmatch` of an absolute path against
  `src/frontend/**` is False).

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
