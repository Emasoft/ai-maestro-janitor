---
trdd-id: 3K8SVX2H
title: memgrep lint reports content-shape findings on superseded atom bodies, which the protocol forbids editing
column: todo
created: 2026-08-16T02:17:12+0200
updated: 2026-08-16T02:17:12+0200
current-owner: unassigned
task-type: bugfix
project-id: ai-maestro-janitor
approval-tier: 0
severity: low
scope: project
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-3PWQK8NM]
implementation-commits: []
---

# A finding nobody is allowed to fix

## Observed, not reported

Decomposing an oversized atom on `janitor-tool-call-cost-law` with `add-atom --supersedes` (the
sanctioned lesson-free path from TRDD-3PWQK8NM) left the page with exactly one lint finding — and
it is on the **superseded copy**, not on either live atom:

```text
INFO …/janitor-tool-call-cost-law.md:107 [atom-oversized] — atom body is 1876 chars (> 1500)
## Superseded  ← line 104
^ATOM-Q6AN-1PDO ← line 107, the historical body the supersession preserved verbatim
```

The two replacement atoms are both within the limit. The flagged text is the immutable record of
what the atom used to say.

## Why it is a defect rather than a nit

The memory protocol's central rule is **supersede, never overwrite — nothing is deleted, only
relocated**. A superseded body is history; editing it to satisfy a linter would destroy the exact
thing supersession exists to keep. So this finding is **unsatisfiable by construction**: the only
compliant response is to ignore it, forever, on every page that has ever corrected an atom.

That is the failure class this repo keeps meeting from the other side — a check that cannot fail
where it matters. This one is its mirror: a check that fires where it cannot be obeyed. Both erode
the same thing, which is whether a clean run means anything. Every superseded oversized atom in the
corpus adds one permanent INFO that a reader must learn to skip, and a reader who learns to skip
findings is the actual cost.

It is `INFO`, and `atom-oversized` was already demoted from a higher level (`6b57a04a`, janitor#200)
precisely because no chore gate can act on it — so part of this was known. Demotion made it quiet;
it did not make it correct.

## The shape of the fix — and the scope question to settle first

The narrow fix is to skip `atom-oversized` inside `## Superseded`. The better question, and the
reason this is a card rather than a one-liner: **which lint rules should apply to superseded
content at all?** A superseded body is frozen, so every CONTENT-SHAPE rule (size, structure,
formatting) is equally unactionable there. Rules about the page's INTEGRITY (a superseded atom
whose id is malformed, a broken link out of it) may still be worth reporting, because those are
repairable without rewriting the historical claim.

Decide that boundary once and apply it as a section-scope, rather than adding rule-by-rule
exemptions — a per-rule exemption list is how the next rule gets forgotten.

## Acceptance

- [ ] Content-shape findings are not reported against bodies under `## Superseded`; the boundary
      between "content shape" and "integrity" is stated in the code, not implied by which rules
      happened to be exempted.
- [ ] A live atom of the same size still reports — falsify by shrinking the live one and growing
      the superseded one, and check the count moves the right way.
- [ ] `janitor-tool-call-cost-law.md` lints clean (it is the natural fixture: one superseded
      oversized atom, two compliant live ones).
- [ ] `cargo test` in `scripts/memgrep` green.

## Notes and lessons learned

Found while decomposing an atom I had just written oversized — so the sequence was: violate the
corpus's own one-fact-per-atom guidance, fix it the sanctioned way, and discover the fix produces
a permanent finding. Worth stating because the temptation at that moment is to leave the oversized
atom alone and avoid the noise, which would make the linter's false positive quietly discourage the
correct behaviour.
