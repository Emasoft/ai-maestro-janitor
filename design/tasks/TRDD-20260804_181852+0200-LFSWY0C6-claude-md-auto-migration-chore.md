---
trdd-id: LFSWY0C6
title: CLAUDE.md excess narrative is migrated out automatically by a scheduled chore
column: todo
created: 2026-08-04T18:18:52+0200
updated: 2026-08-13T07:15:09+0200
implementation-commits: [d82dc15a, 20f226ba, 7b7b37ea]
current-owner: ai-maestro-janitor
task-type: feature
relevant-rules: [7.1, 8.1, 9.1, 10.1]
parent-trdd: H12K9JYX
npt: []
eht: []
---

# CLAUDE.md excess narrative is migrated out automatically by a scheduled chore

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-04

**NOT STARTED.** The shape is fully specified; nothing is implemented.

- **Already shipped** (TRDD-H12K9JYX, `column: complete`): the canonical form itself, the
  fence surgery, the index renderer, the slim-contract `check`, the preservation oracle
  (`verify`), the `janitor-project-cld-md-optimizer` skill (renamed from
  `janitor-claude-md-slim` on 2026-08-04 — CPV rejects `claude` as a reserved word in a skill
  name), and a **nudge** on `project-map-drift`.
  This repo's `CLAUDE.md` conforms today — verified `claudemd-slim: conforming and fresh`,
  1,029 narrative bytes, 0 violations.
- **The gap**: `PRRD G8.1` requires migration to be **automatic**. What exists is an
  advisory nudge, which G8.1 explicitly rules out.
- **NEXT ACTION**: implement the chore per §2 as a new intervention in the
  memory-maintenance scheduler (`scripts/detectors/memory-maintenance.py` + a
  `[janitor-memory-claudemd]` marker routed to `janitor-memory-subconscious-agent`), reusing
  the EXISTING `claudemd_slim` primitives rather than writing new ones.

## ⏵ 2026-08-13 — PRE-CHECK BEFORE BUILDING: the chore has ZERO work today. Build it in two halves.

**Measured now, not assumed:** `claudemd_slim check` → `conforming and fresh`, exit 0. So on this
repo, today, the chore would migrate nothing. That is not a reason to skip it — G8.1 is GOLDEN and
narrative WILL accumulate — but it changes two things, and both are the kind of detail that
silently makes a build worthless:

1. **Acceptance cannot be taken against the live file.** Every box in §4 must run against a
   SYNTHETIC violation planted in a fixture. A run against today's `CLAUDE.md` passes every box
   while doing nothing at all — the "green because there was no work" failure this project has hit
   twice this week (TRDD-4ZSYW21E's rung named 0 cards; TRDD-XFPOAF2I's acceptance was computed by
   a cruder query than its own spec).
2. **The end-to-end cannot be observed on real input**, so the preservation oracle is not merely
   *a* gate — it is the ONLY evidence the chore is safe. It must be falsified explicitly: plant
   content, break the oracle, and prove the chore REFUSES to remove. An oracle that has never been
   seen to say no is decoration.

### Build the DECISION half first; the DELIVERY half is separately risky

Applying the `acceptance-criteria-expire` lesson `^decompose-a-blocked-manual-confirmation` — the
two halves fail for different reasons and are worth separating anyway:

- **DECISION half (safe, build first):** given a `CLAUDE.md`, compute what WOULD migrate — the
  offending lines, the wikimem page that owns each subject (via recall), and whether a new page
  is needed. Output a plan. **Removes nothing, writes nothing.** This is independently useful: it
  is the dry-run a human can read before ever trusting the automatic path, and it is where the
  hard part actually lives (subject ownership, the §3 exemption boundary).
- **DELIVERY half (build only once the decision half is trustworthy):** apply the plan through
  `memory_txn`, gated on the preservation oracle, and remove the lines.

**Why this order and not the reverse:** step 4 deletes from a file the USER also hand-edits. If
the decision half is wrong — it misjudges the §3 exemption, or picks the wrong owning page — the
delivery half executes that mistake unattended and the only thing standing between it and lost
knowledge is an oracle proving *some* text landed *somewhere*, not that it landed in the RIGHT
place. Preservation and correctness are different properties; the oracle only checks the first.

**Not a blocker, and G8.1 is not in question:** automatic migration is a GOLDEN rule the owner
set, so the destination is settled. This is sequencing, not a request to reconsider.

## ⏵ 2026-08-13 — DECISION HALF SHIPPED (`d82dc15a`) AND IT IS WRONG ON REAL INPUT. Do not build delivery.

The planner exists (`scripts/lib/claudemd_migration_plan.py` + `claudemd_slim.py plan`), 13 tests
green, full suite 15038 passed, mypy + ruff clean. **And running it once on the live `CLAUDE.md`
— which it is safe to do, because it writes nothing — showed it is wrong.**

### The defect, diagnosed and verified (not inferred)

| predicate | value on the live `CLAUDE.md` |
|---|---|
| `slim_violations(text)` | **0** — the file CONFORMS (`claudemd_slim check` agrees: "conforming and fresh") |
| `narrative_outside_fences(text)` | **1029 bytes** — and the planner treats ALL of it as migration candidates |

Those two are not the same set, and that is the whole bug. `narrative_outside_fences` returns
everything outside the two janitor fences, which **by design includes the five PERMITTED
elements** — the H1 title, the one-paragraph description, `## Links`, `## Commands`. So on a
fully-conforming file the planner proposes 8 migrations. Measured output:

```
[1] MIGRATABLE -> FOLD into 'fleet-third-party-plugin-dep-fork-pin-pattern'   <- the description
[2] MIGRATABLE -> FOLD into 'ai-maestro-fleet-hub-what-and-roster'            <- "- Repo: <url>"
[3] MIGRATABLE -> FOLD into 'ai-maestro-amp-down-coordinate-via-github-issues' <- "- Marketplace: <url>"
[4] MIGRATABLE -> FOLD into 'ai-maestro-amp-down-coordinate-via-github-issues' <- "- Connected harness: <url>"
[5] EXEMPT (matched enumeration word: 'testing')                              <- correct
```

The §3 exemption works correctly (5 is right). The **candidate selection** is what is wrong, and
the destinations it picks for a bare URL line are nonsense — recall will always return *some*
page, so a wrong candidate silently acquires a confident-looking home.

### Why this is the vindication of splitting the card, not a setback

Had the DELIVERY half been built in the same pass, its first unattended run would have deleted
this project's title, description and entire `## Links` section from `CLAUDE.md` and scattered
four URLs into three unrelated wiki pages. **The preservation oracle would very likely have
PASSED**, because the text did land somewhere — which is exactly the distinction recorded above
this block: *preservation and correctness are different properties, and the oracle only checks
the first.* That was written as an argument; it is now an observation.

**Note what did NOT catch this: 13 passing tests.** They use synthetic fixtures, and the fixtures
did not reproduce a conforming file's permitted-element structure. The suite is green and the
planner is wrong — the same shape as everything else on this board tonight. The ONE thing that
caught it was running it on real input, which was only safe *because* the delivery half does not
exist.

### ⏵ 06:50 UPDATE — the fix attempt (`20f226ba`) is PARTIAL. The defect survives, measured.

`20f226ba` gates `plan_migration` on `slim_violations(text) == []`. That is a correct NECESSARY
condition and the conforming case is now safe (live file: 8 blocks → 0). **It is not sufficient**,
and the tests do not show it because all three new tests exercise only the conforming path.

Measured on the real `CLAUDE.md` plus enough narrative to cross the 8192-byte cap (narrative 9932
bytes, `slim_violations` = 1) — i.e. the ONLY case the chore exists for:

```
total blocks planned: 48
[0] new_page | 'A Claude Code plugin that keeps the dev environme…'   <- the description
[1] new_page | '- Repo: https://github.com/Emasoft/ai-maestro-jan…'   <- ## Links
[2] new_page | '- Marketplace (`ai-maestro-plugins`): https://git…'
[3] new_page | '- Connected ai-maestro harness: https://github.co…'
```

### THE REAL BLOCKER: the primitive this needs does not exist

Neither existing function can answer "is THIS block excess?":

| function | what it actually is | why it cannot be the candidate set |
|---|---|---|
| `narrative_outside_fences` | everything outside the two fences | INCLUDES the five permitted elements by design |
| `slim_violations` | 4 whole-file checks: both fences present, a github url present, and total narrative bytes ≤ `narrative_max_bytes()` (8192) | coarse by construction — it can say the narrative is TOO BIG, never WHICH blocks are excess |

So the missing piece is a **per-block permitted-element classifier**: given a narrative block, is it
the H1 title / the one-paragraph description / a `## Links` entry / a `## Commands` line (all
PERMITTED), or is it excess? That is the function the planner should select on, and it is also what
would let `check` report violations per-block instead of one whole-file byte count.

**Write that classifier first, as its own unit with its own tests, then re-point the planner at it.**
Do not try to derive it from `slim_violations` — that function is structurally the wrong shape.

### ⚠ How BOTH previous attempts passed while wrong — read before writing the next acceptance test

1. The first planner: 13 green tests, all fixtures PLANTED a violation, so none exercised a
   conforming file.
2. The fix: 3 new green tests, all exercised the CONFORMING file, so none exercised an over-cap one.

Each round tested exactly the case the previous round got wrong, and missed the next. **The
acceptance test for the classifier must assert on a file that is BOTH over-cap AND contains the
permitted elements** — that is the only shape where the two failure modes cannot hide behind each
other. Concretely: `plan_migration(over_cap_text)` must contain the excess blocks and MUST NOT
contain the title, the description, any `## Links` entry, or any `## Commands` line.

My own criterion caused the second miss: I specified "empty `slim_violations` ⇒ empty plan", which
a top-level early return satisfies exactly. It was necessary, not sufficient, and a spec that a
symptom patch can satisfy will get one.

### FIX BEFORE ANY DELIVERY WORK

1. Candidate selection must key on what actually VIOLATES the slim contract, not on
   `narrative_outside_fences`. A file where `slim_violations` is empty MUST yield an empty plan —
   that is the single strongest acceptance test available and it runs against the live file for
   free.
2. Add that as a regression test using a CONFORMING fixture (the current fixtures all plant
   violations, so none of them can catch this class).
3. Only then revisit delivery.

## ⏵ 2026-08-13 07:15 — CLASSIFIER SHIPPED (`7b7b37ea`). The DECISION half is now correct.

`scripts/lib/claudemd_migration_plan.py::classify_permitted` is the primitive §"THE REAL BLOCKER"
asked for, built as its own unit with its own tests, with the planner re-pointed at it — not derived
from `slim_violations`.

Three structural rules, one per narrative-visible §CM-1 element (4 and 5 are fenced and already
stripped before a block reaches the planner, so only 1–3 can appear):

| element | rule | shape, not meaning |
|---|---|---|
| 1 description | first content block, and only while `in_preamble` | `split_narrative_blocks` now tracks preamble: a leading `# Title` is the document title and keeps it open; any deeper heading (or a second H1) closes it. "One-paragraph" is the spec's word, so exactly one block can hold the role |
| 2 urls | `is_project_url_line` | one line, optional list marker, optional `<label>: ` prefix ≤60 chars carrying no URL of its own, then ONE URL token — bare, `<angled>`, or `[md](link)` |
| 3 devops | `classify_exemption` — **unchanged** | the closed §CM-3 enumeration, untouched |

**Bias is deliberate and asymmetric.** Where a rule is uncertain it errs toward PERMITTED: keeping
one block too many leaves the file over budget and the next run still reports it; migrating a
permitted element deletes content the canonical form requires and no later run restores it. Named
consequence: `- Note: see https://x.example` reads as a URL line. Accepted.

`exempt` and `permitted` were ONE concept under TWO names — which is precisely how elements 1 and 2
went unhandled while 3 was covered. Verdict is now `permitted` + `permitted_element`; `render_plan`
reports migratable-vs-permitted instead of miscounting every block as excess.

### The acceptance test is the shape §"How BOTH previous attempts passed" demanded

Over cap AND carrying all three permitted elements — the intersection both earlier rounds left
empty. It asserts BOTH halves, because either alone is passable by a wrong fix: planning nothing
satisfies "no permitted element migrates" (that is exactly what `20f226ba` did), and migrating
everything satisfies "the excess is found" (the original defect).

**Falsified, not merely green** — each recognizer was removed in-process and the acceptance test
observed to go red: pre-fix devops-only ✗, description recognizer removed ✗, urls recognizer removed
✗, permit-everything symptom patch ✗, real classifier ✓.

**Verified on REAL input** (the check that caught both previous misses, run again rather than
trusted): the live `CLAUDE.md` pushed over cap yields 8 permitted (1 description, 3 urls, 4 devops)
and 8 migratable, zero leaks. The same file previously gave the description and all of `## Links` as
`new_page`.

Gates: 15045 passed / 1 skipped, ruff clean, mypy clean (474 files).

### One test was DELETED because it asserted the defect

`test_conforming_gate_actually_gates_a_would_be_migratable_block` required the DESCRIPTION to become
migratable once a fence was stripped. A guard whose expected result IS the bug cannot fail while the
bug is present — a fifth variant of this card's recurring theme, and the reason a green suite kept
certifying broken behavior. Replaced with the orphan paragraph, which is excess whether or not the
file is over cap, so the only thing varying is the gate under test.

### The `slim_violations` gate STAYS, and it is a scope choice — not a correctness crutch

With the classifier in place the gate no longer hides anything: permitted elements are correctly
recognized with or without it. What it still does is suppress an under-cap non-permitted block,
which §CM-1 ("these five and nothing else") does call a defect. That is deliberate: editing
CLAUDE.md busts the prompt-cache prefix of every live session (TRDD-e247a349 §5), so churning a file
`check` calls conforming costs more than the stray block does. Both gates are now documented in
`plan_migration`'s docstring as the two separate questions they answer — WHETHER to plan, and WHICH
blocks — because conflating them is what shipped broken twice.

### NEXT ACTION — the DELIVERY half, still unbuilt and still separately risky

Nothing in this commit writes anything. Delivery is CM-2 steps 3–5: write the atom (or fold + `[^N]`
lesson), remove the migrated lines, and prove preservation with `claudemd_slim verify --old` BEFORE
committing. Its acceptance bar is the same one that caught this: run it on real input, not only on
fixtures.

## 1. Why (the cost argument, measured)

`CLAUDE.md` is injected into every session's context on every turn, and a turn re-reads that
context once per tool call. Measured 2026-08-04 via `agentlenspro heartbeat-cost`: ONE
heartbeat fire re-read its context **6 times** — 3,239,112 tokens, $1.72. A paragraph parked
in `CLAUDE.md` is therefore paid per turn, per tool call, per agent, forever, including by
every agent for whom it is irrelevant. Wikimem inverts that: the knowledge costs nothing
until a symptom query asks for it.

## 2. The chore

Per `design/specs/claude-md-canonical-form.md` §CM-2:

1. Detect narrative beyond the five permitted elements (`claudemd_slim` already computes
   `narrative_outside_fences` and `slim_violations`).
2. **RECALL** the wikimem page owning the subject — never mint a duplicate page.
3. Write a new atom, **or** fold into the owning atom **plus** a `[^N]` lesson learned.
4. Remove the migrated lines from `CLAUDE.md`.
5. **Prove preservation before commit**: `claudemd_slim verify --old <pre-migration>`, the
   map fence byte-identical when only narrative moved, `memgrep validate` + `lint` clean.
6. Refresh the index fence (`G10.1`: every root topic listed) and the map fence.

Runs through `memory_txn` like every other editorial chore, so a crash rolls forward.

## 3. The exemption is a closed list (`G9.1`)

Exempt: git, commit, branching, merging, linting, building, testing, tagging, pushing, CI,
publishing, installing, deploying. The test is "is this a command an agent runs to operate
the repo?". Architecture, gotchas, incident history, design rationale and conventions are
NOT exempt however short. The chore MUST NOT extend the list by analogy — encode it as a
literal enumeration so a future model cannot reason its way to a wider one.

## 4. Acceptance

- [ ] A line added to `CLAUDE.md` outside the five elements is migrated by the next chore
      run, without any agent being prompted.
- [ ] The migrated content is recallable by a symptom query that uses none of its own jargon.
- [ ] A dev-ops command line added to §Commands is left ALONE (the exemption holds).
- [ ] Preservation oracle passes; refuses to commit and reports if it does not.
- [ ] Index fence lists every root topic after the migration.
- [ ] `claudemd_slim check` exits 0 afterwards.
- [ ] A chore that cannot find an owning page creates one at the right tier rather than
      dumping the text into an unrelated page.

## 5. Risks

- **Knowledge shredding** — the chore removes lines it failed to write anywhere. Mitigated
  by step 5 being a hard gate: no removal without a passing preservation proof.
- **Page sprawl** — a chore that creates a page per migrated paragraph. Mitigated by step 2
  (recall-first) and by the wikimem rule "one element = one page".
- **Over-broad exemption** — a future model reasons that "deployment architecture" is
  dev-ops. Mitigated by §3's literal enumeration.
