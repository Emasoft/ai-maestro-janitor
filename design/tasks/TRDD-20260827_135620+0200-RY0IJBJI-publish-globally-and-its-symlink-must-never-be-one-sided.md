---
trdd-id: RY0IJBJI
title: publish-globally and its USER-root symlink must never be one-sided and the linter must reconcile them
column: blocked
pre-block-column: complete
blocked-by: [X4LJFTB4]
created: 2026-08-27T13:56:20+0200
updated: 2026-08-27T16:09:03+0200
current-owner: janitor-main-session
task-type: bugfix
priority: normal
scope: project
project-id: ai-maestro-janitor
severity: major
min-approval-requirement: none
labels: [wikimem, memgrep, publish-globally, symlink, lint]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# `publish-globally` and its symlink must never be one-sided

## ⏵ STATE — READ THIS FIRST ON RESUME

## ⏸ 2026-08-27 16:10 — CODE-COMPLETE, NOT YET DEPLOYED: publish 3.4.0 blocked at the push

Everything below is committed locally and passed every gate on publish attempt 5 (CPV `--strict`
0/0/0/0, lint, typecheck, full suite). GitHub refused the push on push-protection over two
SYNTHETIC test fixtures — an owner decision, filed as **TRDD-X4LJFTB4**. No instance on this
machine runs the new memgrep or the `edit_project_scope` flip until 3.4.0 lands. Nothing more to
do on THIS card; it completes the moment X4LJFTB4 is resolved and the same publish re-runs.

**On leaving `complete`:** terminal columns are frozen, and this card had been marked `complete`
before the push failed. The reading taken: `complete` here meant "deployed", and it was not —
the mark was premature, not a finished card being reopened. So this is a correction of an untrue
column, the case the kanban rule explicitly prefers over a lying one, and `pre-block-column:
complete` records where it returns.

## ✅ IMPLEMENTED 2026-08-27 — all four rules enforced, plus the create-time guarantee

Owner directive escalated mid-card ("implement the code immediately … autofix this always, no
exceptions"), which also SETTLED the open question below — see the ruling note there.

| rule | before | now |
|---|---|---|
| `true` + no symlink → create link | write path only | write path **and lint** |
| symlink + no field → set `true` | write path only | write path **and lint** |
| `false` + symlink (conflict) | **terminal, never auto-resolved** | **autofixed — flag flips to `true`** |
| stray symlink → delete | **did not exist** | `reconcile_user_symlink_root()` |
| create at `public-project` | no such flag | `new-page --scope`, flag + link in ONE write |

**The direction chosen for the conflict, and why it is not arbitrary:** the symlink WINS and the
flag follows it. That is the direction the owner's own other rule already points — a symlink is
evidence of publish intent, which is exactly why `MissingSymlinkImpliesTrue` writes `true`. It is
also the non-destructive branch: flipping a flag cannot break another project, whereas deleting a
link that another project already resolves through can. The cost was stated before it shipped and
the owner reaffirmed: a page whose author explicitly wrote `false` gets flipped if a symlink
exists — reachable only when something already created a link for a `false` page, i.e. converging
an already-corrupt state, not overriding a healthy preference.

**`lint` is no longer a pure reporter — this is the load-bearing change.** Reconciliation used to
be reachable ONLY from the write path, so a page nobody wrote kept a one-sided state indefinitely
while lint re-named it every sweep; the invariant was maintained by TRAFFIC, not enforced. Lint is
the only verb that visits unwritten pages. It now reconciles first and reports what REMAINS (never
what it just fixed — a linter naming findings it had already repaired trains the reader to ignore
it). Three Rust tests that asserted the old pure-reporter contract were rewritten to assert the
new one, and are named for what they now prove.

**Create-time guarantee is STRUCTURAL, not ordering luck.** `new-page --scope public-project`
emits `publish-globally: true` into the frontmatter BEFORE handing bytes to `atomic_write_page`,
whose reconciliation then creates the link inside that same call. There is no window in which the
page exists published-but-unlinked. `--scope` is deliberately NOT `--type`: the new test creates a
`public-project` page with `type: reference` precisely to pin that they are independent axes.

**⚠ EXPECTED SIDE EFFECT ON FIRST RUN AFTER INSTALL:** the 29 PROJECT pages currently missing the
field will be written with `publish-globally: false` by the next `memgrep lint` — including the
janitor heartbeat's. `.claude/project/memory/` is git-TRACKED, so that surfaces as ~29 modified
files needing a commit. This is the directive working as asked, not a bug; it happens once.

Verified: memgrep 219 + 145 tests pass (0 failed), clippy warning count unchanged at 13 (none in
the new code — the collapsible-`if` pair is pre-existing in `build.rs`), and an end-to-end run of
the real binary produced both the flag and a correctly-resolving symlink in one command.

---

*Original analysis below.*

**OWNER REQUIREMENT (stated 2026-08-27, verbatim intent):** a PROJECT wikimem page's
`publish-globally: true` and its USER-root symlink are TWO HALVES OF ONE FACT. There must never
exist a state where only one is present.

- `true` + no symlink ⇒ **grave bug**; the linter must create the symlink.
- symlink + no `publish-globally: true` ⇒ the linter must repair the missing half.
- Symlinks in the USER root pointing at LOCAL- or USER-scoped pages ⇒ **delete immediately.**
- The reconciliation is the LINTER'S job and must be **immediate**, not deferred.

## Measured state of the world, 2026-08-27 (before any change)

**The invariant currently HOLDS on this machine — zero violations.** This card is not a bug
report; it is a request to make a property that is currently true by luck into one that is
enforced.

- 4 PROJECT pages in this repo carry `publish-globally: true`; all 4 have a USER-root symlink.
- 6 symlinks exist in the USER root; all 6 resolve to PROJECT pages carrying `true`. (Two belong
  to OTHER projects — correct: the USER root aggregates published pages fleet-wide.)
- 0 stray symlinks to LOCAL/USER-scoped pages.
- 29 PROJECT pages are missing the field entirely; **0** of them have a symlink, so every one is
  the unambiguous `MissingDefaultFalse` case.

## The actual gap — reconciliation is WRITE-triggered, not LINT-triggered

memgrep already implements all four repairs, in `apply_publish_globally_fix` (`memory.rs:4901`):

| variant | fix | matches the owner rule? |
|---|---|---|
| `MissingDefaultFalse` | insert `false` | n/a (neither half present) |
| `MissingSymlinkImpliesTrue` | insert `true` | YES — symlink + no field |
| `TrueNoSymlink` | `create_user_symlink` (best-effort) | YES — `true` + no symlink |
| `ConflictFalseWithSymlink` | **never auto-resolved** | **NO — see the open question** |

But the ONLY thing that runs them is `normalize_page_until_clean`, and its only non-test caller
is `atomic_write_page` (`:2527`, `:2529`). **`lint` reports and returns; it never fixes.** So a
page nobody writes keeps a one-sided state indefinitely, and lint merely names it every sweep.
That is exactly the mechanism behind the 29 unwritten pages, and it is why the invariant is today
maintained by traffic rather than enforced.

Rule 4 (**delete stray symlinks to LOCAL/USER pages**) has **no implementation at all** — grep
finds no symlink removal anywhere in the crate; the only `remove_file` calls are tmp-file cleanup.

## ⚠ ~~OPEN QUESTION~~ — RULED ON 2026-08-27: autofix it, no exceptions

**Resolved by the owner before implementation, after the trade-off below was put to them
explicitly.** The ruling is "autofix always, no exceptions"; the flag flips to `true` (the symlink
is evidence of intent) and the link is never deleted. The original framing is kept verbatim below
because it records what was weighed — the decision was made with the un-publish risk on the table,
not in ignorance of it.

`ConflictFalseWithSymlink` is `publish-globally: false` **and** a symlink exists. memgrep
**deliberately refuses** to auto-resolve it; its doc comment reads:

> Two defensible fixes (drop the symlink vs flip the flag) means a human decides; NEVER
> auto-resolved.

That is a genuine contradiction, not a missing half, so the owner's rule as stated does not
strictly cover it — but "never leave the two out of agreement" would override the refusal. The
two resolutions are NOT equivalent and neither is safe by default:

- **drop the symlink** — silently UN-publishes a page some other project may already link to;
- **flip the flag to `true`** — silently PUBLISHES a page whose author explicitly wrote `false`.

Do not pick one to make the linter tidy. Get the ruling first.

## NEXT ACTION — none; all four items below were resolved or superseded

1. ~~Get the owner's ruling on `ConflictFalseWithSymlink`.~~ RULED: autofix, flag follows symlink.
2. ~~Decide the surface — lint itself, a `--fix` flag, or a new verb.~~ RULED by "no exceptions":
   lint itself reconciles unconditionally. A `--fix` flag was the conservative option and was
   NOT taken, deliberately — an opt-in flag reproduces the exact defect (an unwritten page stays
   one-sided until somebody remembers to pass it).
3. ~~Implement stray-symlink deletion.~~ DONE — `reconcile_user_symlink_root()`, covering all
   three junk shapes (dangling, mis-scoped, self-referential), link-only, best-effort.
4. ~~Add a lint rule that FAILS on a one-sided state.~~ **SUPERSEDED, and would now be dead code:**
   lint reconciles BEFORE it collects violations, so a one-sided state cannot survive long enough
   to be reported. A failing rule downstream of the fix could never fire. What replaces it is the
   Rust tests, which assert the repair happened AND that the finding is consequently absent — a
   stronger claim than "we noticed it".

**If the invariant needs re-auditing later**, the check is the shell loop in the measured-state
section above; it should be read as a diagnostic, not re-added as a lint rule.

## Provenance

Surfaced while closing TRDD-AO8MPK5D, when the owner challenged that card's claim that the
symlink split makes the missing-field case undecidable from text. The challenge was correct (see
that card's correction and lesson `ATOM-BLQS-A2XW` on `memory-system`), and it exposed this
larger, real requirement underneath: the two halves are one fact, and nothing currently enforces
that outside the write path.
