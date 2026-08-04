---
trdd-id: LFSWY0C6
title: CLAUDE.md excess narrative is migrated out automatically by a scheduled chore
column: todo
created: 2026-08-04T18:18:52+0200
updated: 2026-08-04T18:18:52+0200
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
