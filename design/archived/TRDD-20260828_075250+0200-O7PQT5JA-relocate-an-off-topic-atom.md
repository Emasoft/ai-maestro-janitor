---
trdd-id: O7PQT5JA
title: Duty 14 — relocate an atom that belongs on a different page
column: complete
created: 2026-08-28T07:52:50+0200
updated: 2026-08-28T10:55:00+0200
current-owner: janitor-session
task-type: feature
project-id: ai-maestro-janitor
parent-trdd: 87RKBYJ8
npt: []
eht: []
min-approval-requirement: none
---

# Duty 14 — relocate an off-topic atom

Split out of **TRDD-87RKBYJ8** per its own rule.

## What is missing

The MOVE rule is specified — a fact belongs on the page that OWNS its subject, and a transferable
methodology lesson belongs in the methodology page rather than a case page. **No executor exists.**
The rule is enforced today only by whoever happens to read the page.

## Why relocation and not deletion

The memory protocol is explicit that knowledge is never deleted, only relocated, and that a moved
lesson leaves a `[[link]]` rather than a hole. So this duty's success condition is not "the atom is
gone from page A" but "the atom is on page B AND page A still points at it".

## The transaction shape this forces

A relocation touches TWO pages and must be atomic across both: an atom that leaves A before it
lands on B is lost knowledge, and one that lands on B without A's link is orphaned. `memgrep`
already has the two-scope lock primitive for exactly this class (`write_gate::acquire_two`, used by
`migrate-mem-atom` / `merge` / `split`) — reuse it rather than inventing a second ordering.

## Acceptance

- [x] Executor moves an atom between pages under a two-page lock, id preserved
- [x] Source page keeps a `[[link]]` to the destination — never a hole
- [x] Lessons anchored to the atom travel with it
- [x] A crash between the two writes leaves a recoverable state, proven by a test
- [x] `uv run pytest -q`, ruff, mypy

## What shipped (2026-08-28) — mostly a WIRING job, not a build

Spec: **WM-MIG-01a**. `pytest` 15899 passed / 0 failed; ruff + mypy clean; memgrep 400 tests.

**Three of the four boxes were ALREADY satisfied** by `migrate-mem-atom`, and this card did not
know it. Read first-hand in `memory.rs::cmd_migrate_cli` before writing anything:
`write_gate::acquire_two` for the two-page lock (box 1), `migrate_compute` moving the atom's
`[^N]` lessons and renumbering on collision (box 3), and destination-written-BEFORE-source so a
crash between the two leaves a recoverable DUPLICATE rather than a loss (box 4, WM-MIG-05).
The card's framing — "**No executor exists**" — was wrong: the executor existed, unconnected to
this duty. **Always check for the verb before building one.**

**The genuine gap was box 2, and only box 2**: the source page was left with a HOLE. Shipped
`migrate-mem-atom --leave-link`, which wires `## See also` on BOTH pages in the same write (THE
LINK LAW — one end alone is a `link-one-sided` violation). OFF by default, because the same verb
also serves plain scope moves where no link is wanted.

**The refusal that had to come with it.** A `--leave-link` whose direction runs DOWN the
LOCAL → PROJECT → USER order is refused BEFORE any lock or read, naming both scopes and quoting
`downward_reason`. Without that guard the flag would cheerfully author the exact edge
`link-downward-cross-scope` exists to forbid — a USER page pointing at a PROJECT page that may
not exist in the next project at all. Unrecognised scope on either side fails OPEN.

**Box 4 needed no failure injection.** The ordering contract is provable on the PURE
`migrate_compute`: the destination text carries the atom and the source text no longer does, so
applying only the destination write (the crash-after-B state) leaves the atom on BOTH pages —
a duplicate, never a loss. Asserting that is stronger than mocking a crash, and it cannot rot.

Verified end-to-end on the installed binary, not `cargo run`: atom moved with its id, `[^1]`
travelled with it, `a.md` gained `- [[b]]` and `b.md` gained `- [[a]]`.

**Argument shape to remember:** the atom is POSITIONAL (`migrate-mem-atom --from A --to B <ATOM>`),
not `--atom` — the one verb in the family that differs. Cost a failed invocation while verifying.

## Notes and lessons learned
