# WIRE the context — full detail for step 5

Reference for step 5 of the MEMORIZE algorithm ("WIRE the context — radiate or
receive"). See the main skill for the full algorithm context.

A page with no edges is a dead note. **THE LINK LAW: every link is bidirectional
— if A links to B, B links to A, ALWAYS, See-also included.** Wire BOTH ends in
the same edit. Links are **scope-local** — a `[[wikilink]]` may only target a
page in the SAME scope root; reference another scope's page in prose instead
(see the model's Link hygiene). The wiring follows the page's SHAPE:

- **EXPANDED (radiating page):** in `## Applies to`, link DOWN to EVERY element
  this rule governs (find them:
  `memgrep -l "$MEMDIR" --where 'fm.tier "component" and fm.functionality "<fn>"' | sort -u`);
  reciprocally, add this page to each of those pages' `## Governed by`. Also
  link the new aspect from its hub's parts map (and the hub into its edges).
- **REDUCED (receiving page):** in `## Governed by`, link UP to EVERY general
  page that affects this element; reciprocally, add this element to each of
  those pages' `## Applies to`. Link the new component from its hub's parts
  map (and the hub into the component's `## Governed by`).
- **Any `## See also`** lateral link gets its mirror on the other page, same edit.

The librarian backfills missed reciprocals — a safety net; the author wires
both ends now.
