---
trdd-id: UVPSQ1YC
title: Align the janitor with Claude Code 2.1.248 and take advantage of its new levers
column: complete
created: 2026-08-28T02:06:05+0200
updated: 2026-08-28T02:39:10+0200
current-owner: janitor-session
task-type: infra
project-id: ai-maestro-janitor
min-approval-requirement: none
---

# Align with Claude Code 2.1.248

USER directive 2026-08-28. Prior coverage: the ledger page
`project_janitor_cc_changelog_currency` triaged **2.1.234-2.1.247** on 2026-08-27
(ATOM-ZG19-ZDYA, no code break). **2.1.248 is new**, plus the leverage items that triage
flagged but did not implement.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-08-28

Five lean-workers dispatched in parallel, one work package each, all reporting into
`reports/cc-align-2148/`:

| # | package | the harness change it aligns to |
|---|---|---|
| A | `experimental.cacheTtl` per-agent TTL | 2.1.248 agent frontmatter; 2.1.243 made the 5m/1h split configurable |
| B | `--restricted` / `CLAUDE_CODE_RESTRICTED=1` | no Bash, no settings-file hooks ⇒ the janitor is INERT and must SAY so |
| C | cross-session messaging | now on Bedrock/Vertex/Foundry + telemetry-off; subagent replies land on the PARENT; invalid `crossSessionInbound` holds/refuses |
| D | hook stdout that looks like JSON | a `{…}` stdout that is not valid JSON is now a hook ERROR, not text |
| E | continuity + cache constants | hourly OAuth-refresh cache miss FIXED upstream; Sonnet 5 auto-compacts at ~967K not ~934K; Workflow tool description 5.7k → ~1k; `desktopSessionCleanupPeriodDays` |

**All five reported; every claim verified first-hand (grep/read, never the summary).** Result:
**one real gap, four already-aligned.**

- **B `--restricted` — GAP CLOSED.** `arm_prepare` now REFUSES (reusing the `scope=refused` STOP
  contract, so the skill needed no new branch) and `doctor` prints a `restricted-mode` FAIL row.
  **The worker's first cut had two defects I fixed:** it hand-rolled the env parse in BOTH files
  (the drift `state.is_truthy_env` exists to prevent — its docstring already records three
  detectors doing this), and its allow-list read `enabled` as NOT restricted, the wrong direction
  for a safety check. Now one home, `state.restricted_mode()`, erring toward refusing. It also
  shipped NO test; two were added.
- **A cacheTtl — no change.** All three agents are bounded single-pass workers with back-to-back
  turns; a 1h TTL only pays when turns are MINUTES apart. Prose already said "harness defaults".
- **C cross-session — no change.** No platform-conditional claim existed to go stale, and nothing
  waits on a reply that 2.1.248 now routes to the parent session.
- **D hook stdout — no change.** Every `{`-shaped stdout already goes through `json.dumps`; the
  `print(some_dict)` Python-repr trap is absent (checked independently).
- **E continuity/cache — no change.** No `934`/`967` constant and no Workflow-5.7k budget exists.
  It did find a stale ledger claim (TRDD-9DLBHWGV marked OPEN though `column: complete`).

**DONE 2026-08-28.** Full gate green: **15874 passed / 1 skipped / 0 failed** (24m44s — two more
than the 15872 baseline, which are the two restricted-mode tests added here), ruff clean, mypy
clean over 492 files. The Rust suite is untouched by this card (no `scripts/memgrep/` change).

**NEXT ACTION:** none for this card — it is complete. It remains UNCOMMITTED along with the other
three scopes; the owner authorizes commits in this repo, and publishing goes through
`scripts/publish.py` only.

**Gotchas that bind every worker:**
- `rules/` is at 53213 B against a **53700 B test cap** — workers are forbidden to add bytes
  there and must report a needed rule change instead.
- `.claude/project/memory/` is off-limits to hand edits; the ledger atom is updated through
  memgrep verbs once the findings are verified.
- Nothing in this repo is committed yet: the tree already holds TRDD-7EXBJB03,
  TRDD-VJL1YTCG/FDUOQFYS and TRDD-G5GY101S. This card's changes are a FOURTH scope.

## Acceptance

- [x] Each of the five packages reports, and each claimed fix is verified first-hand.
- [x] Full gate green: `uv run pytest -q`, `ruff`, `mypy`, Rust suite unaffected.
- [x] The changelog ledger atom records the 2.1.248 verdict through memgrep (never hand-edited).
- [x] Anything found but deliberately not fixed is filed as its own TRDD, not left in prose — nothing qualified: the four no-change packages found nothing to defer, and the one stale ledger claim was corrected in place rather than deferred.

## Notes and lessons learned

- 2026-08-28 — Ledger updated through memgrep verbs, never by hand: `ATOM-JOE9-C5MF` carries the
  2.1.248 verdict and the correction to the stale `TRDD-9DLBHWGV` OPEN line; its `[^2]` lesson
  records the duplicated-predicate defect. The page `description:` was extended in the same pass —
  recall ranks on description+title+tags and IGNORES the body, so an appended fact whose symptom
  the description lacks is unfindable. Page lints clean at ERROR level.
- The write verbs earned their keep twice here: `new-mem-atom` refused a 9-keyphrase lesson under
  the 10 minimum, and `lint` caught a literal `[^N]` placeholder I had left dangling in the atom
  body. Neither would have been visible in a hand-authored page.

