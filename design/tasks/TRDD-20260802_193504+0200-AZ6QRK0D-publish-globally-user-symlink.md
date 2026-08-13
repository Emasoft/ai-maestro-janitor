---
trdd-id: AZ6QRK0D
title: Publish-globally pages get a real USER-scope symlink mechanism
column: todo
created: 2026-08-02T19:35:04+0200
updated: 2026-08-13T05:17:19+0200
current-owner: janitor-session
task-type: feature
severity: medium
scope: project
release-via: publish
created-by: 87RKBYJ8
external-refs: [52, TRDD-JPL0JU86]
npt: []
eht: []
implementation-commits: []
---

## ⏵ 2026-08-13 — DIRECTION CONSTRAINT from TRDD-JPL0JU86. Read before implementing.

**This card and JPL0JU86 are about the same mechanism from opposite ends, and neither cited the
other.** JPL0JU86 diagnosed four pages that are PERMANENTLY unmaintainable because they are
symlinks: the memory transaction core's **M-10 symlink-escape guard refuses them — correctly** —
so no editorial chore can ever repair, split, atomize or consolidate them, and the refusal ledger
records a permanent tombstone instead of a transient de-dup. Its verdict on the approach was
blunt: *"Correct intent, wrong mechanism … MOVE them, do not link them."*

**So a symlink mechanism built naively here does not add a feature — it industrialises that
defect**, turning four unmaintainable pages into one per `published-globally` page, forever.

**The reconciliation is already in JPL0JU86 and it is about DIRECTION:** *"If the janitor's own
index still wants them, the link goes the other way."* Concretely, the invariant this card must
satisfy:

  - the CANONICAL file lives at USER scope and is a REAL FILE there — that is the copy every
    editorial chore opens, and it must never be reached through a link;
  - anything PROJECT-side is a pointer OUT to it, never a link that makes a USER page appear to
    live inside a project's scope root (that is precisely the escape M-10 refuses);
  - **verify against the guard, not against the filesystem** — "the symlink exists and resolves"
    is NOT the acceptance test; "a chore can still open and commit the page" is. The four broken
    pages resolve fine today.

Whichever card ships first must not leave the other one's fix impossible. If this mechanism
lands first, it must not re-create the four pages JPL0JU86 is trying to move.

# `published-globally` frontmatter value → a real USER-scope symlink

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-02

### 2026-08-13 — THE BLOCK BELOW IS SUPERSEDED BY A USER DIRECTIVE, AND MOST OF THIS SHIPPED

**Do not act on the 2026-08-02 block.** The USER directed this build explicitly on 2026-08-12
(*"make sure … the memgrep will always add the publish-globally field to project scoped wikimem
pages, and if true, ensure the symlink exist. if not it must create the symlink"*). The owner of
this repo is also the owner of `ai-maestro-plugin`, so that directive is the authority the older
block was deferring TO — it does not conflict with `how-to-fix-issues-of-other-projects.md`, it
answers it.

**What actually shipped** (verified in the tree 2026-08-13, `scripts/memgrep/src/memory.rs`):
  - `classify_publish_globally` + `apply_publish_globally_fix` + `normalize_page_until_clean`
    — the field is normalized and the USER-root symlink created/refreshed, **always**, bracketed
    around every `atomic_write_page` (before AND after each change, iterating to a fixed point).
    There is deliberately no `--fix` flag: a write that skipped normalization would persist a
    malformed page.
  - `memgrep lint` renders every inconsistent state.
  - `ConflictFalseWithSymlink` (flag `false` but a symlink exists) is **never auto-resolved** —
    two defensible fixes means a human decides. That is the decision-margin discipline, correct.
  - ~70 references/tests in the engine.

**WHAT IS STILL MISSING — the privacy gate.** This card's own Verification says *"A page with an
absolute `$HOME` path refuses to publish"*, and no such refusal exists: `apply_publish_globally_fix`
consults no privacy scan. The exposure is smaller than the 2026-08-02 card assumed (a USER-scope
symlink is not a git push, and the page is already committed at PROJECT scope, which IS pushed),
so this is not urgent — but publishing is still the moment to run `memory-scope-leak`'s check, and
today it is not run.

**NEXT ACTION — corrected 2026-08-13, ~1h after it was first written. My earlier wording,
*"wire the privacy scan into the publish path"*, was wrong in a way that would have cost the
next session real work:** it reads as mechanical, and it is not. The publish path is **Rust**
(`memory.rs::apply_publish_globally_fix`); the privacy scan is **Python**
(`lib/memory_migrate.py::privacy_scan`), and it is not a regex — it composes FOUR pattern
catalogues plus an entropy gate, sharing them with the `memory-scope-leak` detector. Verified:
the engine has no privacy predicate at all (`grep -n "fn .*leak\|fn .*privacy" src/*.rs` finds
only a test name).

So "wire it in" means choosing where the check LIVES, and the options are genuinely different:

  1. **Port the catalogues to Rust** — fastest at publish time, but forks the detection logic
     into two languages. The classes would then drift silently, and a privacy scanner that is
     accurate in one language and stale in the other is worse than one scanner, because both
     look authoritative.
  2. **Engine shells out to the Python scan** — one source of truth, at the cost of a process
     spawn inside a page write, and a new failure mode (what does a write do when the scanner
     is missing? refusing breaks writes; proceeding defeats the gate).
  3. **Keep the gate in the Python layer** — the linter/detector already scans PROJECT pages;
     make an unpublishable page fail there, and let the engine keep doing the mechanical part.
     Weakest coupling, but the symlink exists for a while before anything objects.

**This is a design decision with more than one defensible answer, so it escalates rather than
being picked here** (the decision-margin rule). The exposure is small — a USER-scope symlink is
not a git push, and PROJECT scope, which IS pushed, already holds the page — so there is no
urgency forcing a rushed pick.

---

**SUPERSEDED 2026-08-13 — historical, do NOT act on:** ~~BLOCKED — do NOT build (the #52
coordination the card mandated was done 2026-08-02 and it FORBIDS building this here).~~ The publishing verbs (`publish-sync` / `link`)
belong to the UPSTREAM memgrep engine roadmap — ai-maestro-plugin **TRDD-202ccfa2**,
tracked as **ai-maestro-plugin#18** — and the engine owner has not shipped them
(re-verified in #52's thread: memgrep 0.1.0, verbs absent; design-text-only upstream).
The janitor VENDORS `scripts/memgrep/`; a prior session's recorded ownership decision on
janitor#52 (correct, per `how-to-fix-issues-of-other-projects.md`) is that building
these verbs in the vendored copy would FORK the engine and pre-empt the owner's design.
The janitor's standing OFFER to implement them as a branch→PR on ai-maestro-plugin sits
on #18 awaiting the owner's go.

**Unblock condition:** ai-maestro-plugin#18 lands a released memgrep with the verbs (or
the owner accepts the PR offer) → re-sync the vendored copy → then wire this card's
janitor half (symlink lint + privacy-gate + skills/heartbeat wiring) in one pass.
**NEXT ACTION on unblock:** re-read janitor#52's last two comments (the held asks
1/2/4/5 land together with the wiring), then implement per the audit steps below.

**SUPERSEDED — do NOT carry forward:** "Not started. … Coordinate with issue #52 …
before building" (the coordination happened; its outcome is the block above).

---

Child 2 of 4 split out of TRDD-87RKBYJ8 (duty 21, second in the parent's own
priority order).

## The ask (parent duty 21 — the publishing half is MISSING)

A page whose frontmatter carries the `published-globally` value must be **symlinked at
USER scope** so every project's recall sees it. Scope classification + privacy direction
already exist (`memory.rs::scope_layer`, cross-scope lint, `memory-scope-leak` detector);
what does NOT exist is the publishing executor.

## Verified facts (2026-08-02 audit, spot-checked)

- The symlink appears ONLY as a test fixture
  (`memory.rs:7027-7051`, `lint_does_not_report_one_file_twice_when_reached_by_two_paths` —
  proves the linter TOLERATES a symlink; nothing CREATES one).
- No `publish` subcommand exists in `main.rs` (grep: zero hits).

## Smallest shippable step (audit recommendation)

A `memgrep publish-globally <page>` subcommand that creates/refreshes the USER-root symlink,
plus the inverse (unpublish), plus lint enforcement that a `published-globally` page without
its symlink (or an orphaned symlink) is flagged. Respect the memory-scope-leak direction:
publishing must run the privacy scan first — a page with machine-private content REFUSES.

## Verification

- Round-trip: mark a page `published-globally` → publish → visible in USER-scope recall from a
  different project root → unpublish → gone; lint flags the inconsistent states.
- A page with an absolute `$HOME` path refuses to publish (privacy gate).

## Notes and lessons learned
