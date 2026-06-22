---
trdd-id: fe45babc-6567-4622-862b-de19db908ad5
title: Autonomous overnight session — OAuth survival + memory-system + immortality GROUP C + issue coordination
column: dev
created: 2026-06-22T02:20:07+0200
updated: 2026-06-22T02:20:07+0200
current-owner: claude-janitor-dev
assignee: claude-janitor-dev
task-type: infra
release-via: none
relevant-rules: []
test-requirements: [unit]
impacts: []
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues"]
---

# Autonomous overnight session — the night brain (read on every wake)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; the task queue + next action) — 2026-06-22

USER directive (verbatim, 2026-06-22 ~02:15): *"i will go to sleep. You must work all
night to fix all the issues and complete the immortality and the memory system. be sure
to keep reading and writing to issues on github and coordinating with the other claudes.
… use any means necessary to continue. … the current window of the current oauth is soon
going to finish. so you must switch oauth token soon."* Then `/go-on-yourself`.

### STANDING CONSTRAINTS (never violate)
- **This IS a plugin project → PUSH + PUBLISH are AUTHORIZED via `scripts/publish.py`.**
  (Updated `/go-on-yourself` 2026-06-22: *"Do not push unless you are working on a plugin
  project. … If it is a plugin, publish using the publish.py script. It has strict quality
  and security gates."*) Publish COHERENT, TESTED milestones only — never half-done work.
  Do NOT hand-`git push` / `gh release`; `publish.py` OWNS the version bump + tag + release
  + all gates (validate --strict, lint, tests). After a publish: daemon auto-updates →
  `/reload-plugins` → `/janitor-arm` (activates new hooks/skills/the subconscious agent).
- **GitHub issue WRITES are ALLOWED** (the user explicitly asked to read+write issues and
  coordinate). Comment + close issues as their fix ships.
- No changes outside the project dir + `/tmp`. TRDD per change. TDD where possible.
  Commit often, stage by name (never `git add -A`). Never relax security/quality gates.
- Per PRRD G1.1: every GitHub post starts with a one-line self-identification.

### OAUTH SURVIVAL (check FIRST on every wake — this is the lifeline)
- Rotator opted-in; daemon alive (manages 60s ticks). Two accounts:
  `emanuele.sabetta@gmail.com` + `fmuaddib@gmail.com`. BOTH near 7d limits (~90-93%).
- **At 02:20 force-rotated LIVE → `fmuaddib` (5h=0% fresh); `emanuele` 5h≈95% recovering.**
- Rule each wake: `ROT=…/0.15.0/scripts/oauth_rotator/rotator.py`;
  `uv run --script --quiet "$ROT" usage`. If the LIVE account is **>88% on 5h OR 7d**,
  `… "$ROT" switch <other-email>`. The built-in auto-rotate NEAR threshold is too lax
  (said "within limits" at 92%) — manage manually until that's fixed (queue item M0).
- Budget is TIGHT (both ~90%+ on 7d). Prioritize high-value work; commit often so a
  mid-night stall loses nothing.

### CONTINUATION MECHANISM
- Heartbeat cron (`*/5`, session-only) = janitor dispatch (silent).
- **Work-driver cron** (separate, ~15 min) fires `[night-work]` turns that re-read THIS
  TRDD's STATE and do the next queue item. Fresh context each wake — so this STATE block
  is the ONLY memory; keep it current (update the done-log + NEXT ACTION every commit).

### NEXT ACTION
Start queue item **M1** (memory detector false-positive fixes) — spawn parallel spark
agents (one per bug) to diagnose+fix+test #53/#54/#55/#56/#59. They are independent,
well-scoped, cheap, high-ROI. Commit each separately; comment on each issue.

### TASK QUEUE (priority order — budget-aware: cheap+certain first)
- **M0** — Make the rotator auto-rotate NEAR threshold configurable + lower the default
  (it said "within limits" at 92% → overnight stall risk). TRDD + test. (HIGH value for
  survival, but careful — don't break the rotator; do AFTER M1 once on fresh token.)
- **M1** — Memory detector/serializer FALSE-POSITIVE fixes (independent, parallelizable):
  - #53 memory-scope-leak: `machine-host` FP on GitHub `action@sha` pin syntax.
  - #54 memory-librarian: flags sibling `*-proposed.md` detector outputs as malformed notes.
  - #55 memory-librarian: MEMORY.md-sync flags every note "missing from MEMORY.md" but
    MEMORY.md is the deprecated stub.
  - #56 memory repair serializer nests ocd/lmd under `metadata:` — diverges from the
    write-skill top-level shape (two frontmatter shapes coexist).
  - #59 trdd-reminder: reports `backburner` proto-TRDDs as "active"; age is
    days-since-updated not true age.
- **M2** — #60 (background-dispatch wikimem passes): ALREADY built (commit 619cedd, the
  janitor-memory-subconscious-agent). Comment on #60 that it's addressed + publish-pending.
- **M3** — Granular memory skills (the subconscious-agent toolkit), on DEFAULTS since the
  user is asleep: keep `merge` inside `consolidate`, keep `conflict` (not rename to
  harmonize). AUTHOR new txn-gated skills + their verify_* + tests: `create-expander`,
  `create-reducer`, `verifier`, `deduplicate`, `check-references`, `scope-validation`.
  Inject each into `agents/janitor-memory-subconscious-agent.md` `skills:` as it lands.
  (LARGE — do in batches, TDD, commit per skill.)
- **M4** — #57/#58 un-splittable convergence: a type:reference archive with no `##` seams
  over split_max_bytes abstains every cycle. Build the seam-synthesizing auto-split.
- **C** — Immortality GROUP C (self-integrity, #228): ship `.integrity/manifest-sha256.json`,
  flip self-integrity ENFORCING, verify-before-exec gate in dispatcher-stub, pin-good/
  quarantine-bad rollback. (LARGE — careful; don't brick the janitor.)
- **COORD** — As each item lands: comment on its issue (self-identify per G1.1), close
  when fully fixed+committed (note "committed not pushed; ships in next publish").

### DONE LOG (append; most recent last)
- 02:20 — OAuth force-rotated → fmuaddib (fresh 5h). Night infra set up (this TRDD).
- (next: M1 fixes …)

### SUPERSEDED — do NOT carry forward
- The earlier idea of waiting for the user's naming calls on the granular skills — the
  user is asleep + said "complete the memory system"; proceed on the M3 defaults above.

## Durable artifacts to read before acting
- `design/tasks/TRDD-…-aebedbff-…md` — the 3-tier memory architecture (subconscious agent).
- `design/tasks/TRDD-…-324223a6` + the immortality plan — GROUPS A/B done, C pending.
- The 3 OAuth memory notes (rotator 3-layer architecture + design directives + renew transport).
- Open issues: `gh issue list --repo Emasoft/ai-maestro-janitor --state open`.
