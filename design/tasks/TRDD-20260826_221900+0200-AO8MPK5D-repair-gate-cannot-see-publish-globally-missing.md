---
trdd-id: AO8MPK5D
title: The repair chore is told to fix publish-globally-missing but its gate cannot see it
column: todo
created: 2026-08-26T22:19:00+0200
updated: 2026-08-26T22:19:00+0200
current-owner: janitor-main-session
task-type: bugfix
priority: normal
scope: project
project-id: ai-maestro-janitor
severity: minor
min-approval-requirement: none
labels: [wikimem, memory-maintenance, repair, lint]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# The repair chore is told to fix `publish-globally-missing` but its gate cannot see it

## ⏵ STATE — READ THIS FIRST ON RESUME

**The obvious fix reintroduces the exact bug the code it touches exists to prevent. Read the
"why it cannot be closed the obvious way" section before writing anything.**

## The gap, measured 2026-08-26 22:15

`memgrep lint` over all three scope roots: **67 findings, none at ERROR**, of which **29 are
`publish-globally-missing`, every one a PROJECT page** (0 in USER, 0 in LOCAL).

The repair skill explicitly owns this defect — `skills/janitor-memory-repair/SKILL.md:91`:

> **PROJECT page missing `publish-globally`** → add it as `false` (the default — publishing
> beyond this project must be opt-in, never assumed on a page's behalf).

But `memory_content_precheck.repair_defect` — the SINGLE-SOURCE candidacy predicate feeding
BOTH the scheduler's `repair_has_work` gate AND the candidate-listing CLI — returns no slug for
it. Its checks are `no-frontmatter`, `missing-key:<key>`, `illegal-tier`, `no-notes-heading`,
`nested-only-dates`, `inverted-tier-shape`, `atom-desc`, `superseded-misplaced`,
`atom-after-footer`. Nothing about `publish-globally`.

**So a PROJECT page whose ONLY defect is the missing field is invisible to the chore end to
end:** it never makes the gate fire, and on a dispatch triggered by some other page it never
appears in the candidate list either. The skill's instruction is unreachable. 29 pages.

This is the janitor#227 shape (gate and arbiter disagreeing, so the chore cannot converge),
one layer up: here they do not disagree about a page, they disagree about which *rules exist*.

## ⚠ Why it CANNOT be closed the obvious way

Adding a `publish-globally` check to `repair_defect` keyed on `metadata.type == project` **would
recreate janitor#227**, because that is not what memgrep keys on. `memory.rs:4878`
`publish_globally_state` decides scope from the PATH:

```rust
let page_abs = page_path.canonicalize().ok()?;
if scope_layer(&page_abs) != Some(SCOPE_PROJECT) { return None; }
```

`metadata.type` is the CONTENT class (`user|feedback|project|reference`) and is independent of
which memory ROOT a page lives in — a page under `.claude/project/memory/` may legitimately carry
`type: reference`. Keying the Python predicate on `type` would flag pages memgrep never flags and
skip pages it does, which is precisely the "gate and arbiter must be identical" invariant
`repair_defect`'s own docstring was written to protect.

**And `repair_defect(text: str)` structurally cannot mirror a PATH rule — it never receives the
path.** That is the real blocker, and it is why this is a card rather than a one-line commit.

## Two honest options (pick at implementation time, not now)

1. **Widen the signature** — `repair_defect(text, path=None)` and add the check only when a path
   is supplied, mirroring `scope_layer`'s PROJECT test. Callers that have a path (both real ones
   do) pass it; the text-only contract stays valid for tests. Risk: two behaviours from one
   predicate, which is a smell in a function whose whole point is single-sourcing.
2. **Do nothing here and let normalization drain it.** `memgrep::normalize_page_until_clean`
   ALREADY fixes this per page, on every write through any verb, idempotently and with no mtime
   churn when clean. The 29 are simply pages nothing has written since the field was introduced;
   each self-heals the next time it is edited. The lint count only stops shrinking if those pages
   are never touched again.

Option 2 is why the severity is `minor` and why **no hand-edit of the 29 should happen**: editing
them outside the transaction core to satisfy a linter would be doing the chore's job in the one
way the chore's design forbids, for a WARN whose runtime behaviour is already identical
(normalization defaults the field to `false` anyway).

## Verified before filing, so the next reader does not redo it

- All 29 are PROJECT-root pages; USER and LOCAL have none.
- **`false` is provably the correct value for all 29**: 6 symlinks exist in the USER root, and
  they reconcile exactly — 4 point at this project's 4 pages that already declare
  `publish-globally: true`, 2 point at another project entirely. No page with publish intent is
  missing the field, so the lint message's "no symlink exists, so there is no evidence of intent"
  holds for every one of the 29.
- `memgrep lint` has no `--fix`; there is no one-command drain.
- There is no no-op write verb that would trigger normalization without a content change.

## Acceptance

- [ ] A PROJECT page whose only defect is a missing `publish-globally:` is named by
      `memory_candidates_cli.py` and makes `repair_has_work` return True
- [ ] The PROJECT test mirrors `memgrep`'s `scope_layer` PATH rule, NOT `metadata.type` — with a
      test that a `type: reference` page in the PROJECT root is still flagged, and a `type:
      project` page in the USER root is NOT
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`

## Notes and lessons learned

The other 38 findings, recorded so this card is not mistaken for covering them: 25
`atom-after-footer` (WARN — `repair_defect` DOES detect this one, so their persistence has a
different cause and is worth its own look), 8 `lesson-uncited` (INFO), 5 `atom-oversized` (INFO,
owned by the split chore).
