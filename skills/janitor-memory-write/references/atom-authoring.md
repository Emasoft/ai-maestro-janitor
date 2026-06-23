# Atom authoring — page schema and block-property grammar

## Table of contents

- Full page schema
- Atom block-property grammar

## Full page schema

Author `"$MEMDIR/<slug>.md"` with the following schema. Set `ocd`/`lmd` to TODAY.
Include the **typed edge section for the page's tier** AND the standing
`## Notes and lessons learned` section (the janitor's page-shape validator flags
a page that omits its edges or the lessons section).

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
<each durable fact ends with its atom marker, e.g.:>
^<id> [keywords: <the search words for THIS fact>, type: <type>, ocd: <today>, lmd: <today>]

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
^widget-retry [keywords: <terms a future search will use>, type: <type>, ocd: <today>, lmd: <today>]
The widget retries 3× then fails.[^1][^2]

## Lessons Learned
[^1]: [ocd:<old> lmd:<today>] earlier this said 5×; the cap is 3 — <concise WHY it changed>.

## See also
[^2]: [[backoff-policy]]
```

`keywords:` is the only REQUIRED prop — it is the atom's recall surface (the
question words, NOT the answer's jargon); `ocd`/`lmd`/`type` are optional (an atom
without them inherits the page's). notes/lessons/see-also are **per-ATOM** (tied to
it by the inline `[^N]` footnotes it cites — a see-also is a footnote defined under
`# See also`), NOT page-wide.

Full grammar (comma→property / first-colon→key-value / whitespace→value-array):
see the wikimem-model.md [Atoms section](wikimem-model.md#atoms--first-class-body-elements-block-properties).

A free-prose page (no markers) stays valid — its facts are recalled at page
granularity — but NEW facts SHOULD be atoms.

memgrep returns an atom as its FULL record (`path#atom-id — <keywords>`, then the
content, then its `[^N]` footnotes grouped as `notes:` / `lessons learned:` /
`see also:`), not just a slice of the page.
