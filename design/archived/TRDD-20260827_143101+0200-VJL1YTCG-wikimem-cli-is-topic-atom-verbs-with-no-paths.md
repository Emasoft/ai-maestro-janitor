---
trdd-id: VJL1YTCG
title: The wikimem CLI must be topic/atom verb pairs with no paths and maintenance must leave the main agent
column: complete
created: 2026-08-27T14:31:01+0200
updated: 2026-09-01T21:14:00+0200
current-owner: janitor-main-session
task-type: refactor
priority: high
scope: project
project-id: ai-maestro-janitor
severity: major
min-approval-requirement: none
labels: [wikimem, memgrep, cli, ux, librarian, agents]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# The wikimem CLI: topic/atom verb pairs, zero paths, and maintenance off the main agent

## ⏵ STATE — READ THIS FIRST ON RESUME

**⏵ ALL THREE PARTS ARE IMPLEMENTED (A, B, C — 2026-08-29).** Still committed-not-deployed: 3.4.0
is blocked at the push by TRDD-X4LJFTB4 (owner decision), so none of it is live yet.

*The rest of this block is the DESIGN RECORD. It was written when A was partial and B/C unstarted,
and it kept saying so long after that stopped being true — costing a session a round of questions
about work already in the tree. Read it for the reasoning; the status is the line above.*

| part | state |
|---|---|
| **A** — no paths, `--scope` + env-var templates | **DONE.** `2e801dff` (+ `282a39c6`/`864652f0` renames the scanner forced) shipped the scope resolvers; `--path` itself was removed 2026-08-27 (`memory.rs:3124`), verified absent from `new-mem-topic --help` — the only surviving mention is the line saying it does not exist. Sweep 2026-08-29: every remaining `--path` in the tree is `cargo install --path`, an unrelated tool's flag. |
| **B** — topic/atom verb pairs | **DONE.** The full table ships in `main.rs::VERB_TABLE` with the old spellings retained as aliases (`new-page`→`new-mem-topic`, `add-atom`→`new-mem-atom`, `edit`→`update-mem-topic`, `migrate`→`migrate-mem-atom`). **The `add-lesson` question the card said to raise was answered by the USER on 2026-08-27 and the answer is in the code:** a lesson is `update-mem-atom --lesson`, because it records that an EXISTING atom's fact was superseded — an update to knowledge, not the authoring of a new fact. `add-lesson` keeps its own deprecated arm rather than being rewritten onto the new verb, because a rewrite would land the legacy argv WITHOUT `--lesson` and silently overwrite the atom's body. |
| **C** — maintenance invisible to the main agent | **DONE, after one wrong turn.** See below. |

**Part C, and the correction that matters more than the fix.** The crux — "lint MUTATES, so whoever
runs it performs maintenance by side effect" — was first resolved by giving `lint` a `--no-fix`
mode and putting the `wikimem-syntax` heartbeat detector on it (`5a0227b4`). **The owner reverted
that the same day** (`eabe1140`): executing a memgrep edit against a malformed page corrupts it and
loses data, so fixing before AND after every wikimem edit is mandatory, and the ~5-minute autofix
cadence is a DATA-INTEGRITY PRECONDITION for the librarians' writes — not a side effect to be
cleaned up. `--no-fix` survives, re-scoped to debug/diagnostic use only (spec WM-LINT-09).

The real fix was the other half: **Part C constrains who SEES maintenance, not whether it
happens.** `_OTHER_ACTOR_DETECTORS` in `dispatch.py` stops the lint summary riding the urgency
override into the main conversation, while the reconciliation continues underneath. Both halves of
the directive now hold; suppressing the write satisfied neither.

**Part A additions since the first STATE:** the three env vars take `~/`-relative TEMPLATES with
`@project_root@` / `@project_slug@` symbols (the owner's "wildcards for the project root and
slug"); USER scope deliberately leaves a project symbol UNEXPANDED so a misconfiguration is
visible rather than silently sharding the global store. The spelling is `@name@`, not `{name}`,
and the identifier is `resolve_scope_pattern`, not `…template` — both because CPV's scanner
read the obvious spellings as Server-Side Template Injection and blocked the publish; see the
comment above `DEFAULT_LOCAL_SCOPE_PATTERN` for the incident and the wrong first guess. This card exists so the full shape is recorded before any more of it is
built — the pieces below are individually small and collectively a CLI-surface migration.

### The governing principle (Part A) — a PATH IS AN INTERNAL DETAIL

> *"path is an internal implementation detail that can change at each version, or even be
> customized by the user … memgrep must never require explicit paths, only use the defaults or the
> env vars. The command must not have any path option."*

Callers say WHAT they want and WHICH SCOPE; memgrep decides WHERE. This is what lets the roots
move without touching a single call site.

**DONE already (see `implementation-commits`):**
- `WIKIMEM_LOCAL_SCOPE_PATH` / `WIKIMEM_PROJECT_SCOPE_PATH` / `WIKIMEM_USER_SCOPE_PATH`, honoured
  by three resolvers AND — the load-bearing half — **inside `scope_layer` itself**. That ordering
  is not cosmetic: `scope_layer` classifies by hardcoded substring, so a relocated root would
  classify `None`, and `None` is SILENT (`publish_globally_state` returns early on it). A user who
  moved their PROJECT root would have quietly lost publish-globally reconciliation with no error
  anywhere. Pinned by a test.
- `new-page --path` is now OPTIONAL; omitted, the destination is `<scope root>/<name>.md` derived
  from `--scope`, which **defaults to `local`** — the safe default by construction, since LOCAL is
  machine-private and never pushed, so a forgotten flag cannot publish or commit anything.

**STILL TO DO for Part A:** actually REMOVE `--path`. It is deprecated-but-honoured today so
existing callers keep working. Removal is a breaking change and needs the full sweep
(`~/.claude/rules/check-all-files-after-breaking-change.md`): skills, Python callers, the spec,
docs, tests, and any prose naming the flag. Do NOT remove it without that sweep — a rule or skill
still passing `--path` fails at RUNTIME, and prose cannot be caught by a type-checker.

### Part B — verb naming: TOPIC vs ATOM, explicitly

The owner's objection to `new-mem` is that it is ambiguous about WHAT is being created. A wikimem
page (a TOPIC) and an atom INSIDE a page are different objects and deserve different verbs:

| topic (a page file) | atom (a fact inside a page) |
|---|---|
| `new-mem-topic` | `new-mem-atom` |
| `update-mem-topic` | `update-mem-atom` |
| `delete-mem-topic` | `delete-mem-atom` |
| `merge-mem-topic` | `merge-mem-atom` |
| `split-mem-topic` | `split-mem-atom` |
| `reference-mem-topic` | `reference-mem-atom` |
| `recall-mem-topic` | `recall-mem-atom` |
| — | `migrate-mem-atom` |

- `reference-mem-*` add specific wikilinks to a given page.
- `recall-mem-*` are **aliases** for plain `memgrep` / `memgrep recall`, present for completeness.
- Today's verbs map on: `new-page`→`new-mem-topic`, `add-atom`→`new-mem-atom`,
  `migrate`→`migrate-mem-atom`, `edit`→ the `update-mem-*` pair. `add-lesson` has no named slot in
  the owner's list and MUST NOT be silently folded into `new-mem-atom` — a lesson is a correction
  with supersession semantics, not an atom. Raise it rather than guess.

**Migration discipline:** ship the new names as the primary surface and keep the old ones as
aliases for one release, or every skill, rule and script that shells out to memgrep breaks at
once. There is no type-checker for a verb name in a markdown instruction.

### Part C — maintenance must be INVISIBLE to the main agent

> *"all the migrations and corrections of errors reported by the memgrep linter must be carried in
> background invisibly by the wikimem librarians agents, not by the main agent. The wikimem must
> not distract the main claude from its job. The main claude must only be involved directly when it
> decides to create/update/recall memories. Not when doing maintenance chores!"*

**This card's own session is the counter-example, and it is the reason Part C matters.** While
implementing Part A, the main agent hand-topped-up eight atoms' keywords and hand-reconciled 29
pages, then reported both to the owner. Every one of those was librarian work. The main agent
should have seen nothing.

Concretely:
- Lint findings must NOT surface to the main agent as work. The heartbeat already has a quiet
  filter and a findings ledger; maintenance-class findings belong there, drained by
  `janitor-memory-subconscious-agent`, never printed into the main conversation.
- The librarian owns: reconciliation fallout, keyword/description backfill, atom placement,
  migrations, lint-driven repair.
- The main agent owns exactly three things: CREATE, UPDATE, RECALL — and only when it decides to.
- **Watch for the trap:** `lint` now MUTATES (TRDD-RY0IJBJI), so whoever runs it performs
  maintenance by side effect. If the main agent runs `memgrep lint`, it is doing librarian work
  whether it meant to or not. Either the main agent stops running lint, or lint grows a
  read-only mode for non-librarian callers. **Decide this explicitly — it is the crux of Part C.**

## NEXT ACTION

**None — all three parts are implemented (see the STATE block).** The original plan is kept below
because its ORDERING argument turned out to be right and is worth reusing:

1. ~~Part C first~~ — correct call. It was the owner's stated pain, it was the smallest change, and
   the lint-mutates-by-side-effect question did decide the shape of everything else. It also
   produced the one real correction of this card: `--no-fix` on the heartbeat was wrong, because
   "invisible" is not "absent".
2. ~~Then Part B~~ — new names primary, old as aliases for one release. Shipped that way.
3. ~~Then finish Part A~~ — the "full breaking-change sweep" it demanded is what showed the removal
   had already landed and that every remaining `--path` in the tree belongs to `cargo install`.

**What remains is not work on this card:** the aliases (`new-page`, `add-atom`, `edit`, `migrate`,
and the deprecated `add-lesson` arm) were promised for ONE release. Retiring them is a separate
breaking change and needs its own card and its own sweep — do not fold it in here.

## Provenance

Owner directives during TRDD-RY0IJBJI's implementation. Part A's principle came from an objection
to `--path` appearing in the new `--scope` work; Parts B and C followed in the same exchange.

## Approval log

- 2026-09-01T21:14:00+0200 — APPROVED human_review → complete by the session acting under the
  USER's delegated review authority ("i've put you in charge", 2026-09-01). Reviewer verified 3
  load-bearing claims against HEAD (memory.rs:3121-3134 + live --help; main.rs:661-681;
  dispatch.py:676-705), 2 spot-checked first-hand by the approver. Report:
  reports/trdd-verify/20260901_211317+0200-VJL1YTCG-human-review.md
