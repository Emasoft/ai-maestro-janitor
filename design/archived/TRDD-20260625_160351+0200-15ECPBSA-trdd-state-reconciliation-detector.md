---
trdd-id: 15ECPBSA
title: TRDD state-reconciliation detector — flag shipped-but-open board drift, surface-only
column: published
created: 2026-06-25T16:03:51+0200
updated: 2026-06-25T16:57:13+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 2
severity: MEDIUM
effort: M
labels: [trdd, kanban, detector, board-drift, reconciliation, heartbeat]
task-type: feature
parent-trdd: null
npt: []
eht: []
blocked-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
test-requirements: [unit]
audit-requirements: []
review-requirements: []
impacts: []
implementation-commits: [bf95575, 708d198, 5602d92]
published-version: 0.24.9
published-at: 2026-06-25T16:57:13+0200
---

# TRDD state-reconciliation detector — catch shipped-but-open board drift

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-25

- **WHY (the incident that motivated this):** TRDD-3b9b2040 sat at `column: dev`
  for weeks after its work shipped (atom engine, Phase g, in released tags). A
  backlog-assessment agent then summarised it as "shipped, close" while its own
  STATE prose still said "publish BLOCKED on GROUP B" — and a later read showed
  the block was stale (GROUP C had landed). The board claimed a state that
  ground truth contradicted, and nobody reconciled them. Worse, on 2026-06-25 a
  read-only audit agent — explicitly told to verify against git — STILL
  over-claimed 8 TRDDs as CLOSE-PUBLISHED; the orchestrator's independent
  cross-check (commit-in-tag AND NEXT-ACTION/column) caught that at least 2 were
  plainly wrong (one `blocked` with remaining phases, one today's active work).
- **THE LESSON the design encodes:** one machine check is not enough. The
  "keystone" (a TRDD's commits are in a released tag) is NECESSARY but NOT
  SUFFICIENT — it over-includes partially-shipped TRDDs that still have in-scope
  work. So the detector pairs the keystone with a remaining-work signal, and it
  SURFACES candidates for a human/agent to confirm — it NEVER mutates a TRDD's
  `column:` itself (surface-not-mutate, like the memory-librarian).
- **✅ SHIPPED + CLOSED — 2026-06-25 (column: published, v0.24.9):** built TDD,
  shipped across THREE releases. The build (`bf95575`): new SSOT
  `scripts/lib/trdd_common.py` (the 4 pure checks — keystone commit-in-tag PAIRED
  with a remaining-work gate so partially-shipped ≠ closeable; prose↔frontmatter
  mismatch; stale blocker), the surface-only detector
  `scripts/detectors/trdd-state-reconciliation.py`, registered in dispatch at
  86400s — shipped **v0.24.7**. It ALSO fixed a real pre-existing bug it surfaced:
  the `[0-9a-f]{8}` TRDD-id matcher silently dropped every modern UPPERCASE base36
  id, so trdd-drift/reminder never flagged a stale v2 TRDD — consolidated to one
  `extract_uid` matcher (the old test that cemented the bug was replaced).
- **✅ Precision-tuned on the REAL board (unit fixtures could not catch these):**
  the live smoke test surfaced two genuine bugs the fixtures missed.
  **v0.24.8** (`708d198`) — Check 2 scoped the done-marker to the NEXT-ACTION LINE
  (a ✅ on a finished sub-part no longer masks a pending action): closeable 16→3.
  **v0.24.9** (`5602d92`) — Check 3 now excludes TERMINAL TRDDs (a closed TRDD's
  historical "blocked" prose is not live drift; mirrors Check 4's guard):
  prose-mismatch 15→0. Net 36 noisy candidates → 21 high-signal (3 closeable, 18
  partially-shipped-review, 0 noise). The detector ran LIVE in the heartbeat.
- **Surface-only validated (the detector NARROWS, the verifier CONFIRMS):** hand-
  verifying the 3 "closeable" candidates showed 2 (TRDD-aebedbff #230 pending,
  TRDD-T198DT1W GROUP C mid-phase) still have remaining work Check 2's NEXT-ACTION
  heuristic did not parse — the design WORKING (never auto-close; a conscious pass
  confirms). Board reconciliation of the ~21 surfaced candidates continues
  incrementally; the detector re-surfaces them each heartbeat until closed.
- **Load-bearing facts / gotchas:**
  - Detectors are PROJECT-scoped, `--one-shot`, surface-only; they emit drift
    lines + a report, never mutate project files. This one must obey that.
  - `git tag --contains <commit>` is the keystone primitive (verified by hand on
    2026-06-25 — it correctly placed every shipped TRDD's commits in v0.21.0+).
  - Commit-discipline puts `TRDD-<id8>` in commit subjects, so a TRDD's commits
    are greppable even when `implementation-commits:` is unpopulated.
  - Markdownlint MD004 trap (see janitor-publish-pipeline memory [^2]): never
    start a hard-wrapped line in a TRDD/markdown with `+ ` / `* ` / `- `.

## Background

The janitor already ships `trdd-drift`, `trdd-reminder`, and `report-to-trdd-drift`
detectors. None of them cross-check a TRDD's CLAIMED column against the GROUND
TRUTH of whether its code is in a released tag. That gap is the board drift this
TRDD closes: a TRDD whose work shipped but whose column never advanced past `dev`
(or that sits in `blocked` behind a now-resolved blocker) is invisible to the
existing detectors, accumulates silently, and misleads every later reader.

## Design — the four checks (each SURFACED, never auto-applied)

Each check is a PURE function over parsed inputs (frontmatter dict, STATE text, a
`commit -> {tags}` map), so it is unit-testable in isolation.

- **Check 1 — shipped-but-open (the keystone).** A non-terminal TRDD (column not
  in {published, complete, live, failed, superseded, cancelled, refused}) whose
  commits — from `implementation-commits:` OR `TRDD-<id8>` grepped in commit
  subjects — are contained in a released git tag. Signal: "work shipped; column
  still <X>." High precision, but see Check 2.
- **Check 2 — remaining-work gate (suppresses Check-1 false positives).** Does the
  TRDD still encode unfinished in-scope work? Signals: `column: blocked`; an
  unchecked `- [ ]` task; a NEXT-ACTION line whose latest STATE status marker is
  NOT a DONE/SHIPPED/COMPLETE (✅) note. Check-1 AND no-remaining-work → strong
  "closeable candidate"; Check-1 AND remaining-work → weaker "partially shipped,
  review" (the ab232dbd case — do not over-claim closeable).
- **Check 3 — prose↔frontmatter mismatch.** STATE prose contains
  "blocked"/"BLOCKED"/"hostage to"/"blocked on" but frontmatter `column != blocked`
  AND `blocked-by: []`. The human prose claims a block the machine fields do not
  encode — reconcile one to the other.
- **Check 4 — stale blocker.** A `blocked-by:` entry (or a STATE-named blocker
  TRDD) that is ITSELF now terminal (`column` in {published, complete, live,
  superseded}). Signal: "blocker cleared; re-evaluate / unblock."

## Output + safety contract

- SURFACE-ONLY: write candidates to `reports/trdd-reconciliation/<ts>-board.md`
  (one row per flagged TRDD: id, title, column, which checks fired, the evidence
  tag/commit) + emit ONE heartbeat drift line summarising counts and ids. NEVER
  edit a TRDD's `column:` — a conscious pass (a session/agent) does the close
  after reading the full STATE, exactly as was done by hand for 3b9b2040.
- BOUNDED: low cadence (≈ daily); per-TRDD seen-file dedupe so a still-open
  candidate is not re-nagged every heartbeat; honors the standard detector gates.
- READ-ONLY on the repo except its own report + drift line; no network beyond the
  local `git tag --contains` / `git log` it already needs.

## Test plan (TDD — real fixtures, no mocks)

- Unit-test each of the 4 checks against fixture TRDDs + a synthetic
  `commit -> {tags}` map: a shipped-and-clean TRDD (Check 1 fires, Check 2 clear)
  → closeable; a shipped-but-blocked TRDD (Check 1 + Check 2 remaining) → review,
  NOT closeable (the regression that proves we don't repeat the audit over-claim);
  a prose-says-blocked / frontmatter-says-dev TRDD (Check 3); a TRDD blocked by a
  now-published TRDD (Check 4); a genuinely in-progress unshipped TRDD (NOTHING
  fires).
- Verify the detector is surface-only: after a run on a fixture board, every
  fixture TRDD's `column:` is byte-identical (it mutated nothing).

## Acceptance

- The 4 checks have passing unit tests including the "shipped-but-blocked →
  review, not closeable" regression.
- The detector emits a correct candidate report + a single drift line on a
  fixture board, and mutates ZERO TRDD files.
- Registered in `dispatch.py` at a low cadence with seen-file dedupe.
- `publish.py` dry-run green (tests + lint + CPV --strict) before ship.

## Companion (NOT part of this detector's code; noted for completeness)

The discipline layer — "never close/act on a TRDD from a summary; verify the full
STATE + git first; evidence-tag every verdict" — is behavioural, already applied
this session (the audit agent was required to cite git/tag evidence, and the
orchestrator independently cross-checked). It belongs in the assessment-agent
prompt template + the project's TRDD conventions, NOT in this detector. The
detector is the AUTOMATIC backstop for when the discipline is skipped.
