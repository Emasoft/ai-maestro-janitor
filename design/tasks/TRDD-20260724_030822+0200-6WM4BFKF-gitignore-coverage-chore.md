---
trdd-id: 6WM4BFKF
title: gitignore-coverage chore — prove the ignore file covers every private class BEFORE a secret can be tracked
column: testing
created: 2026-07-24T03:08:22+0200
updated: 2026-09-02T13:48:03+0200
current-owner: main-session
task-type: security
scope: project
severity: high
relevant-rules: []
implementation-commits: [e607e95a]
npt: []
eht: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-02 13:48

- **⏵ REOPENED 13:48 → `testing` — criterion 2 was NOT met by the shipped code; fixed, awaiting
  the next publish.** The second review fork caught it: the 13:36 close asserted criterion 2 on
  the CODE's definition of contamination (`tracked ∧ is_ignored`, i.e. a rule must already
  exist), while the criterion and D2 say "a `.env` ALREADY tracked" with no rule mentioned —
  `git ls-files` against the CLASS matcher. The first seeded run WAS that scenario and printed
  no contamination line; adding the rule until the line appeared changed the scenario, not the
  evidence. Fleet-wide effect: a secret tracked in an UNCOVERED class was invisible to the
  contamination line, and the coverage line's "the NEXT such file is published" was false for
  a file already shipping.
  **Fix (this commit):** `gitignore_coverage.matches_private_class` matches tracked paths
  against the table's own thirteen canonical patterns (three fixed shapes: bare glob → basename
  at any depth, `dir/` → any directory component, inner slash → anchored), OR-ed with git's
  `is_ignored`; and the detector now asks git ONCE (`check-ignore -v -n -z --stdin` over the
  probes + all tracked paths, instead of one `-q` call per file — 1,802 here, hourly), which is
  also what makes a `!` NEGATION visible: `-q` says "not ignored" for both a path no rule
  mentions and one deliberately re-included, and `tracked_offenders` now yields to the latter
  (`is_negated`). Without that the matcher flagged this repo's own `/.trashcan/*` +
  `!/.trashcan/.gitkeep` markers for `git rm --cached` — the exact false positive D3 warns
  about. `state.run_subprocess` gained `input=` for the `--stdin` form.
  **Verified:** 9 focused tests (the criterion-2 scenario verbatim on a real seeded repo,
  asserting on the marker not on silence; a negated marker beside a tracked `.env`; the
  matcher's three shapes with their nearest non-matches) + `test_tracked_ignored` = 15 passed;
  ruff + mypy clean; this repo silent again on a live run (criterion 4 control holds); the
  fork's settling command prints `CRITERION-2 MET`.
  **NEXT ACTION:** `uv run scripts/publish.py --patch`; on green CI + install, add the fix SHA
  to `implementation-commits:` and move to `complete`. Nothing else is open on this card.
- **(superseded by the reopen above) ✅ CLOSED 2026-09-02 13:36 — done-but-unclosed since `e607e95a`.** The card sat at `planned`
  for six weeks after its detector shipped (`scripts/detectors/gitignore-coverage.py`,
  `scripts/lib/gitignore_coverage.py`, `tests/test_gitignore_coverage.py`, wired in
  `dispatch.py` at a 3600 s cadence, in the roster page). Re-verified against the six
  acceptance criteria today, not inferred from the commit: 1–3 by the shipped tests (uncovered
  class reported with its canonical pattern; an existing rule does not clear an already-tracked
  file; protected prefixes recognised); 4 by a live run on this repo — zero findings, exit 0 —
  **made meaningful by a control**, because the detector fails OPEN to silence and an empty
  run alone cannot tell CLEAN from DID-NOT-RUN (review-fork finding): the identical invocation
  (`CLAUDE_PROJECT_DIR=<root> uv run --script --quiet scripts/detectors/gitignore-coverage.py`)
  on a seeded repo with a tracked `.env` and no `.gitignore` printed the coverage line naming
  `dotenv (add .env)` among 12 uncovered classes; adding the `.env` rule and re-running printed
  the separate contamination line `1 file(s) are ignored by a rule yet still TRACKED: .env …
  remedy is git rm --cached` — which is also criterion 2 observed live (contamination means
  "ignored by a rule AND still tracked"; a tracked file in an UNCOVERED class surfaces through
  the coverage line first, then as contamination once the rule exists). 5 by `git status`
  byte-identical after the run on this repo; 6 by the 3.4.9 publish gate (ruff + mypy + the
  full suite, green, with this code in the range). Fleet census the same day: ten projects carry
  LOW `ADVISORY-GITIGNORE-COVER` findings, so dispatch's run path reaches real repos too.
- **D5 (the `/janitor-gitignore-fix` remedy command) was NOT built and is NOT required by the
  criteria above** — spun out as its own card, **TRDD-VMXAF9IY** (`todo`), because the fleet
  findings are being re-recorded hourly with nobody remedying them by hand.
- The 2026-07-24 entries below are kept as the design record; their NEXT ACTION is superseded.

### 2026-07-24 (design-time state, superseded by the close above)

- **WHY THIS EXISTS:** on Claude Code a plugin ships its **whole tracked repo** — there is no
  packaging-exclusion field in `plugin.json` and none in the plugin spec. Verified empirically:
  the installed cache of this plugin carries `design/` (191 files) and `.claude/project/memory/`
  (33 files). Therefore **TRACKED == SHIPPED == PUBLIC**, and a single missing `.gitignore`
  pattern is not untidiness — it is a publication of private data to every installer.
- **THE GAP (verified by survey, not assumed):** the janitor already ships three adjacent
  detectors, and **all three presuppose a correct `.gitignore` already exists**:
  - `tracked-ignored` — fires only when a rule EXISTS and a file is tracked against it (the
    "rule added after the commit" case). A **missing** rule fires nothing.
  - `memory-scope-leak` — content-level scan INSIDE the memory corpus only.
  - `project-memory-tracked` — guards the opposite direction (keeps PROJECT memory tracked via
    a negation line).
  No detector asks the prior question: **does `.gitignore` cover the private classes at all?**
- **CURRENT AUDIT OF THIS REPO (2026-07-24) — CLEAN, zero tracked in every class:**
  `.env` 0 · `*_dev/` 0 · `.venv/` 0 · `node_modules/` 0 · `.DS_Store` 0 · `reports/` 0 ·
  `*.log` 0 · `settings.local.json` 0 · `*.pem` 0 · `*.key` 0 · nested `.git/` 0 ·
  `.trashcan/` exactly `.gitkeep` + `README.txt`. This chore is PREVENTIVE, not remedial.
- **NEXT ACTION:** implement the detector per the design below, starting with the pure
  classifier + its table-driven class list, then wire the heartbeat entry.
- **LOAD-BEARING FACTS:** a `.gitignore` rule does NOT untrack an already-tracked file (git
  keeps existing index entries by design) — so detection must check BOTH "is the class
  covered" AND "is anything in the class already tracked", and the remedy for the latter is
  `git rm --cached` (never a working-tree delete). PROJECT-scope paths that MUST stay tracked
  (`design/**`, `.claude/project/memory/**`) are protected by negation lines and must never be
  proposed for ignoring — a false positive here would destroy the shared kanban and the shared
  memory corpus.
- **SUPERSEDED — do NOT carry forward:** an earlier reading of this session that `.venv` /
  `.DS_Store` / `.in_use` / `.orphaned_at` were being SHIPPED. They are `tracked=0`; they are
  runtime debris created inside the plugin CACHE dir by `uv run` and the cache system. Nothing
  leaked.
- **ARTIFACTS TO READ BEFORE ACTING:** `scripts/detectors/tracked-ignored.py`,
  `scripts/detectors/memory-scope-leak.py`, `scripts/detectors/project-memory-tracked.py`,
  `scripts/lib/project_memory_tracked.py`, this repo's `.gitignore` (its negation block for
  `.claude/project/memory/**` is the reference pattern).

## Problem

A missing `.gitignore` pattern is silent. Git does not warn, the commit succeeds, the push
succeeds, and — because Claude Code publishes the tracked tree verbatim — the file is then
downloaded by every user who installs the plugin. The existing detectors cannot catch this
because each of them starts from the assumption that the ignore file is already right.

The blast radius is not limited to this repo: the janitor runs in every project on the machine,
so the same missing-pattern class applies to every repo it watches.

## Design

**D1 — a table-driven class list, not a regex pile.** One table of PRIVATE CLASSES, each with
its canonical ignore pattern, a matcher, and a short WHY. Initial classes:

- secrets and credentials — `.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa*`, `credentials`,
  `secrets.{json,yaml,yml,txt}`
- local scope — `.claude/settings.local.json`, LOCAL-scope artifacts
- dev-only trees — `*_dev/` (`docs_dev`, `scripts_dev`, `reports_dev`, …) and `reports/`
- build and dependency output — `.venv/`, `node_modules/`, `__pycache__/`, `dist/`, `build/`,
  `target/`, `*.pyc`
- OS and editor debris — `.DS_Store`, `Thumbs.db`, `*.swp`, `*~`, `*.bak`, `*.tmp`, `*.log`
- janitor runtime state — `.janitor/state/`, `.janitor/logs/`, `.trashcan/` (minus its two
  tracked markers)
- nested VCS — a nested `.git/` inside the tree

**D2 — two independent checks per class, because they fail differently.**

- COVERAGE: does `.gitignore` (or an ancestor ignore file) actually cover the class? Ask git
  itself with `git check-ignore` against a synthetic probe path — never by parsing the ignore
  file, whose precedence and negation semantics are subtle and would be re-implemented wrong.
- CONTAMINATION: is anything in the class ALREADY tracked? `git ls-files` against the class
  matcher. This is the case a coverage-only check misses, since adding a rule later does not
  untrack.

**D3 — the protected-path allowlist is load-bearing.** `design/**` and
`.claude/project/memory/**` are DELIBERATELY tracked and pushed. They must be exempt from every
contamination check and must never be proposed for ignoring. Encode them as an explicit
allowlist with the reason attached, so a future contributor cannot "tidy" them away.

**D4 — SURFACE, never mutate.** The detector reports; it does not edit `.gitignore` and does
not run `git rm --cached`. Remedy belongs to a user-invoked command (see D5) because untracking
a file changes what every other clone receives.

**D5 — a `/janitor-gitignore-fix` command** that shows the proposed diff, requires
confirmation, appends only the MISSING patterns (never reorders or rewrites existing lines,
never touches a negation line), and for contamination emits the exact `git rm --cached`
invocations for the user to approve.

**D6 — cadence and noise budget.** Cheap (a handful of git calls), so a slow cadence with
seen-file dedupe. A finding on a secrets class is HIGH severity and routes to the findings
ledger; a debris class is informational.

## Acceptance criteria

1. On a repo whose `.gitignore` lacks `.env`, the detector reports the missing class with its
   canonical pattern — verified on a seeded temp repo, not on a live one.
2. On a repo where a `.env` is ALREADY tracked, the detector reports contamination separately
   from coverage, and names `git rm --cached` as the remedy.
3. `design/**` and `.claude/project/memory/**` are never flagged and never proposed for
   ignoring, even though they would match a naive "internal docs" heuristic.
4. Running against THIS repo today reports zero findings (it is currently clean — criterion 3
   plus a clean run is the regression guard).
5. The detector only reads; a run leaves `.gitignore` and the git index byte-identical.
6. pyright 0 new errors, ruff clean, full `pytest tests/` green.

## Approval log

- 2026-09-02T13:48:03+0200 — REOPENED complete → testing by janitor-main-session. Review fork:
  criterion 2 closed on the code's contamination predicate, not the card's; the shipped code
  never reported a tracked file in an uncovered class. Fixed in this commit; complete after the
  next publish installs it.
- 2026-09-02T13:36:41+0200 — COMPLETED by janitor-main-session (Tier 0, own scope). All six
  acceptance criteria verified live today (see STATE); implementation `e607e95a`, shipped since
  3.4.x and part of the 3.4.9 green range. D5 spun out to TRDD-VMXAF9IY.

## Notes and lessons learned

[^1]: [id:ATOM-6WM4-BF01, status:valid, keywords:"tracked_equals_shipped plugin_ships_whole_repo gitignore_missing_pattern private_file_published", ocd:2026-07-24, lmd:2026-07-24]
  DO NOT assume a Claude Code plugin ships only its declared component dirs, BECAUSE
  `plugin.json` has no files/exclude field and the installed cache was verified to carry the
  entire tracked tree — so TRACKED == SHIPPED and one missing ignore pattern publishes a
  private file to every installer. DO treat `.gitignore` coverage as a publication gate.

[^2]: [id:ATOM-6WM4-BF02, status:valid, keywords:"gitignore_rule_does_not_untrack already_tracked_file git_rm_cached", ocd:2026-07-24, lmd:2026-07-24]
  DO NOT believe that adding a `.gitignore` rule removes an already-committed file, BECAUSE git
  keeps existing index entries by design and the file keeps shipping. DO check coverage AND
  contamination as two separate conditions, and remedy contamination with `git rm --cached`
  (which preserves the working-tree copy) instead of a delete.

[^3]: [id:ATOM-6WM4-BF03, status:valid, keywords:"detector printed nothing exit 0 is it clean fail-open silence proves nothing seeded must-fire control check-ignore -q cannot see negation contamination requires class matcher tracked secret uncovered class invisible", ocd:2026-09-02, lmd:2026-09-02]
  DO NOT close an acceptance criterion on a detector that printed nothing, BECAUSE a fail-open
  detector prints nothing for "clean" AND for "could not run" — and DO NOT settle a criterion by
  adjusting the scenario until the expected line appears (the first seeded run with no rule WAS
  criterion 2, and its silence was the defect). DO run the identical invocation on a seeded repo
  that MUST fire and assert on the marker; and when a class matcher joins git's answer, ask git
  with `check-ignore -v -n` so a `!` re-include is distinguishable from "no rule" — `-q` merges
  them and the matcher then proposes untracking what the user deliberately kept.
