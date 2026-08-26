---
trdd-id: AO8MPK5D
title: The repair chore is told to fix publish-globally-missing but its gate cannot see it
column: todo
created: 2026-08-26T22:19:00+0200
updated: 2026-08-26T22:34:30+0200
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

### ⛔ CORRECTION 2026-08-26 22:20 — I NAMED A REAL CAUSE THAT IS NOT THE OPERATIVE ONE

**Doing every acceptance box below would change NOTHING observable.** The reason these 29 never
drain is not (only) that `repair_defect` cannot see them — it is that **the memory-maintenance
scheduler never dispatches ANY chore for PROJECT scope at all.**

`memory-maintenance._scopes_in_play` (`:135`) drops PROJECT unless `edit_project_scope` is on;
`memory_settings.py:61` defaults it `False`, and it is `False` on this host (measured). The
rationale is sound and is not a bug: *"PROJECT memory is in-repo and unpushable outside
`publish.py`"* — an agent editing it would create commits nothing can push.

So the gate order is: **scope gate first, candidacy predicate second.** Widening `repair_defect`
would make the predicate correct while the pages remain unreachable, and the implementer would
ship it, re-lint, see 29 findings unchanged, and have to find this out the hard way.

**This also explains the OTHER class on this page's Notes.** 25 `atom-after-footer` findings sit
on 10 pages and `repair_defect` DOES detect that one — so its persistence had to have a different
cause, and it is the same cause. **54 of the 67 lint findings (81%) are PROJECT-scope and
structurally out of every chore's reach by design.**

**What this card is now really about, and it is smaller:** `repair_defect`'s blind spot is still
a genuine latent gap — the day `edit_project_scope` is turned on, 29 pages would still be
invisible while 25 others got fixed. Fix it as latent-correctness, not as a way to drain
anything. **Do NOT turn `edit_project_scope` on to make this card's boxes observable** — that is
a USER decision about what agents may write into a git-tracked, pushed store, and it is not this
card's to make.

**Reporting-fidelity residue, separate from the fix:** the heartbeat's `memgrep lint: 67
finding(s)` line counts findings the janitor cannot act on, which reads as accumulating debt when
it is out-of-scope-by-design. **Do NOT file this as a card** — janitor#276 already litigated that
line and fixed the real half (a severity regex matching `ERROR` inside the clause that NEGATES
it, promoting the most routine line in the system on every fire). The line prints unconditionally
by design: a linter silent on success cannot be told apart from one that never ran (janitor#191).

### ⛔ SECOND CORRECTION 2026-08-26 22:34 — the PROJECT-gate finding is NOT new

**TRDD-LFSWY0C6 recorded it on 2026-08-13**, thirteen days earlier: same file, same two line
numbers, same conclusion that a chore hosted there would be *"silently disabled on every default
install — wired, reachable, documented, and inert"*. It goes further than the correction above
does, naming a second defect (an axis mismatch: the scheduler's subject is a memory scope ROOT,
while that chore's subject is a FILE) and leaving the host choice as an open design decision.

I re-derived the whole thing from source tonight and wrote it up as a discovery. **The reason is
worth more than the embarrassment:** `memgrep recall` indexes MEMORY pages, and nothing indexes
`design/tasks/*.md` — so a fact that lives only in a card body is invisible to the retrieval path
every session actually uses. Recall found nothing because there was nothing in the corpus to
find, and the card that held it was never going to surface for the symptom I searched with.

Migrated to `[[memory-system]]` (`ATOM-HO67-QC61`) citing LFSWY0C6, with the transferable half as
`ATOM-LATA-4NGJ`: grep `design/tasks/` for the symbol or setting name alongside the memory recall
before claiming a mechanism is unrecorded — and when the grep hits, migrate the fact rather than
leaving it where recall cannot reach it.

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
- [ ] The card's own doc states the SCOPE GATE runs first, so nobody measures success by
      re-linting: with `edit_project_scope` off, a correct predicate still drains nothing
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`

## Notes and lessons learned

The other 38 findings, recorded so this card is not mistaken for covering them: 25
`atom-after-footer` (WARN, 10 pages — `repair_defect` DOES detect this one; **its persistence has
the same cause as the 29**, the PROJECT scope gate, see the correction in the STATE block), 8
`lesson-uncited` (INFO), 5 `atom-oversized` (INFO, owned by the split chore).

[^1]: [id:ATOM-AO8M-PK01, status:valid, keywords:"a linter reports defects that never get fixed, the chore owns this defect but nothing ever repairs it, my fix is correct and the finding count did not move, findings persist across every run of a working chore, which gate runs first the scope gate or the candidacy check", ocd:2026-08-26, lmd:2026-08-26]
    DO NOT diagnose "why does this chore never fix X" by studying the chore's CANDIDACY predicate
    first, BECAUSE a scope/eligibility gate runs EARLIER and can exclude the whole root, making a
    perfectly correct predicate unobservable — here `_scopes_in_play` drops PROJECT unless
    `edit_project_scope` is on (default off), so 54 of 67 lint findings were unreachable no matter
    what the predicate said, and I filed a card naming a real-but-secondary cause whose fix would
    have changed nothing measurable. DO walk the gates in EXECUTION ORDER, outermost first, and
    confirm the target is even in the eligible set before reading the predicate that judges it.
