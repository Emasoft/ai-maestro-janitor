# Atom authoring — page schema and block-property grammar

## Table of contents

- Full page schema
- Atom block-property grammar

## Full page schema

Author `"$MEMDIR/<slug>.md"` with the following schema. Set `ocd`/`lmd` to TODAY.
Include the **typed edge section for the page's tier** AND the standing
`## Notes and lessons learned` section (the janitor's page-shape validator flags
a page that omits its edges or the lessons section).

> **`name:` is the page's TOPIC, never a memory's description (TRDD-NM4TPCQ9).** A page
> collects the atoms of ONE broad topic, so its slug is a short reusable topic noun —
> `agents-tracing`, `claude-telemetry-and-logging` — NEVER a sentence describing the one
> memory being saved (`implementation-of-duckdb-ingestion-of-otel-logs`). A candidate name
> that reads like a description of one fact means the topic page already exists (go UPDATE
> it) or your name must broaden to the topic before you write.

```yaml
---
name: <slug>                             # the broad TOPIC (see the naming rule above)
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
<each durable fact OPENS with its atom marker on the line ABOVE it (LEADING —
the marker line opens the atom; the prose below is its body), e.g.:>
^<id> [desc: "<≤200-char PROSE summary of this fact>", keywords: <the search words for THIS fact>, type: <type>, ocd: <today>, lmd: <today>]
<the fact's prose goes HERE, below its marker>

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

## Atom block-property grammar

Make each durable body fact an **ATOM** that owns its notes. When you write a fact
into the body, open it with an Obsidian block-property marker LEADING that fact's
block (the marker line above, the fact's content below) so the fact is individually
recallable, and attach the fact's **own** history + relations as INLINE `[^N]` footnote
references — defined in the page's bottom pool under section headings:

```markdown
^widget-retry [desc: "Widget retries 3× with backoff, then fails permanently — the retry cap is 3, not configurable.", keywords: <terms a future search will use>, type: <type>, ocd: <today>, lmd: <today>]
The widget retries 3× then fails.[^1][^2]

## Lessons Learned
[^1]: [keywords:"<key_phrase> <key_phrase> …", desc:"<≤200-char prose summary of this lesson>", ocd:<old>, lmd:<today>] DO NOT <X>, BECAUSE <why>. DO <Y> instead.

## See also
[^2]: [[backoff-policy]]
```

> The pooled `## Lessons Learned` / `## See also` headings above are the ATOM-pool
> convention; the page must STILL carry the standing `## Notes and lessons learned`
> section (mandatory even when empty — the write checklist, REPAIR, and the wikimem
> model all enforce it). The pools coexist with it; they never replace it. (L8)

**Link every project concept the atom names (the Wikipedia discipline — see
[wikimem-model.md](wikimem-model.md#link-every-concept-you-name--the-wikipedia-discipline)).**
Before an atom is done, turn every project element in its prose — a component, a
protocol/procedure, a config, a functionality, a topic — into a `[[wikilink]]`. If the
target page does not exist yet, CREATE it (a stub in the SAME scope, both link ends
wired); if the concept is this page's OWN subject, self-link it anyway (so the edge
survives a future split); and when ≥2 atoms cite the same link, pool it ONCE as a shared
`[^N]` under `## See also` instead of repeating the inline `[[link]]`.

TWO props are REQUIRED on every atom: `keywords:` — the atom's recall surface (the
question words, NOT the answer's jargon) — and `desc:` — a ≤200-char PROSE summary of
the atom's body (see below). `ocd`/`lmd`/`type` are optional (an atom without them
inherits the page's).

**A LESSON (`[^N]`) is an atom too, and its metadata block obeys the SAME grammar** —
`[keywords:"<key_phrase> …", desc:"…", ocd:…, lmd:…]` — except that on a lesson **all FOUR are
REQUIRED**. A lesson cannot inherit dates from a page (the librarian moves lessons BETWEEN
pages, so its dates must be intrinsic), and without `keywords:` it has no recall surface at
all: memgrep matches `--only-notes` against `keywords + text` and indexes `notes.keywords`,
so a keyword-less lesson is findable only by accident of phrasing. Full shape + the DO-NOT /
BECAUSE / DO prose form: [wikimem-model.md](wikimem-model.md#the-lesson-form--mandatory-metadata-then-one-terse-shape).

**`desc:` — REQUIRED, ≤200-char PROSE summary of the atom's body (TRDD-AP2X9A0H).** The
per-atom analogue of a skill's `description`, quoted (`desc:"…"`) so it can carry spaces
and punctuation. WHY it is load-bearing: memgrep shows `desc` — NOT the full atom body —
when it LISTS the atoms matching a `recall`/`find` query, so the reader triages every hit
by its `desc` and opens the full body of only the ONE atom worth reading. A missing/weak
`desc` makes the atom invisible-at-a-glance and costs tokens (bodies must be opened to
triage). Write a true summary of the body, as short as possible, never a slug. `desc` is
the LISTING surface; `keywords` remains the RECALL surface — distinct roles, and `desc` is
a distinct key from the page frontmatter `description:`. (Legacy atoms written under the
old optional ≤64-char snake_case-slug form remain valid — memgrep falls back to a
body-prefix; upgrade a legacy `desc` to prose whenever you touch its atom.)
notes/lessons/see-also are **per-ATOM** (tied to it by the inline `[^N]` footnotes it
cites — a see-also is a footnote defined under `# See also`), NOT page-wide.

Full grammar (comma→property / first-colon→key-value / whitespace→value-array):
see the wikimem-model.md [Atoms section](wikimem-model.md#atoms--first-class-body-elements-block-properties).

A free-prose page (no markers) stays valid — its facts are recalled at page
granularity — but NEW facts SHOULD be atoms.

memgrep returns an atom as its FULL record (`path#atom-id — <keywords>`, then the
content, then its `[^N]` footnotes grouped as `notes:` / `lessons learned:` /
`see also:`), not just a slice of the page.
