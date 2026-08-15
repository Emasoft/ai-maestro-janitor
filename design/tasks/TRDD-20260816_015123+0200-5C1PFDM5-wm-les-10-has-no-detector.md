---
trdd-id: 5C1PFDM5
title: WM-LES-10 is a MUST with no detector — a substantive in-place atom edit is invisible
column: backburner
created: 2026-08-16T01:51:23+0200
updated: 2026-08-16T01:51:23+0200
current-owner: unassigned
task-type: feature
project-id: ai-maestro-janitor
approval-tier: 0
severity: medium
scope: project
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-3PWQK8NM]
implementation-commits: []
---

# The spec's strongest memory rule is the one nothing checks

`design/specs/wikimem-memgrep-spec.md:395` states `WM-LES-10` **every-substantive-change-supersedes**
as a `MUST`: every change to an atom's *meaning* creates a superseded version, and the only
edit-in-place exception is a typo that changes no fact. Its rationale is the sharpest in the spec —
*"a reader who acted on the old assertion has no way to see it ever differed"*.

**Nothing enforces it.** TRDD-3PWQK8NM closed the AUTHORING half — `add-atom --supersedes`
(WM-CLI-13) makes the correct move cheap and lesson-free, and the spec records that gap as closed.
The DETECTION half was explicitly carved out of that card's scope and is still open: an agent that
edits an atom's body in place, changing what it asserts, produces a page that `memgrep validate` and
`memgrep lint` both call clean. The history the rule exists to preserve is simply gone, silently.

This is the repo's recurring failure class stated in one line: **the rule is written, the correct
path is paved, and the wrong path is unlit.**

## Why it was deferred rather than built

Detecting it needs something the memgrep crate does not have anywhere: **git history**. The check is
"diff this atom's current body against its last committed body, and flag a change that is not a pure
formatting slip" — which means shelling to `git show HEAD:<path>`, parsing the prior version's atoms,
and matching them by id. `build.rs` shells to git, but no runtime code path does, so this introduces
git as a *runtime* dependency of `lint` for the first time and has to degrade cleanly where there is
no repo (LOCAL and USER memory roots are not in one — that is most of the corpus).

## Shape when picked up — decide, do not treat as settled

- **WARN, never ERROR.** TRDD-3PWQK8NM §3 already ruled this deliberately non-blocking. A false
  positive that fails a chore is worse than the defect: it would push agents toward not editing.
- **The hard part is "substantive", not the diff.** A whitespace reflow, a markdown escape, a
  renamed link target — none change what the atom asserts. Reuse the spec's own WM-LES-06 typo
  exception as the predicate rather than inventing a second definition of "substantive"; two
  definitions of the same word in one system is its own defect.
- **Scope-aware by construction.** Outside a git repo the check must report *"not checkable here"*
  and never *"clean"* — silence that cannot distinguish "looked and found nothing" from "could not
  look" has already produced wrong conclusions in this project (`ATOM-ZFUE-H8IZ`).
- Consider whether this belongs in `lint` at all versus a janitor detector that sweeps committed
  history periodically. `lint` is per-page and synchronous; the question is inherently historical.

## Acceptance

- [ ] A substantive in-place atom edit with no supersession is REPORTED (warn-level).
- [ ] A pure formatting/typo edit is NOT reported — same predicate as WM-LES-06, not a second one.
- [ ] Outside a git repo the result is an explicit "not checkable", never a clean verdict.
- [ ] Falsified: the check goes red on a real edited-in-place fixture and green after the same edit
      is redone through `add-atom --supersedes`.
- [ ] `cargo test` green; the spec's `WM-LES-10` entry records the gap as closed, like WM-CLI-13's.

## Notes and lessons learned

Filed while closing TRDD-3PWQK8NM, whose own NEXT ACTION said to scope this as its own card. Parked
at `backburner` deliberately and not at `todo`: `backburner` is a resting state the drain rule
accepts, and claiming `todo` for work that needs a runtime dependency nobody has decided to take on
would be the untrue-column failure in the other direction.
