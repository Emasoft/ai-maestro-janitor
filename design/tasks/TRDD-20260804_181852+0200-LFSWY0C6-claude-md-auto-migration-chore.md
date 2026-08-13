---
trdd-id: LFSWY0C6
title: CLAUDE.md excess narrative is migrated out automatically by a scheduled chore
column: todo
created: 2026-08-04T18:18:52+0200
updated: 2026-08-13T06:31:40+0200
implementation-commits: [d82dc15a]
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

### FIX BEFORE ANY DELIVERY WORK

1. Candidate selection must key on what actually VIOLATES the slim contract, not on
   `narrative_outside_fences`. A file where `slim_violations` is empty MUST yield an empty plan —
   that is the single strongest acceptance test available and it runs against the live file for
   free.
2. Add that as a regression test using a CONFORMING fixture (the current fixtures all plant
   violations, so none of them can catch this class).
3. Only then revisit delivery.

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
