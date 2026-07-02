---
trdd-id: TKNSTP82
title: Fix post-compact token-runaway false alarm + never-stop maintenance continue-nudge
column: dispatch
created: 2026-07-02T11:16:08+0200
updated: 2026-07-02T11:16:08+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: HIGH
effort: M
task-type: bugfix
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
impacts: []
attempts: 0
implementation-commits: []
---

# Fix post-compact token-runaway false alarm + never-stop maintenance continue-nudge

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-02

- **WHY (user, 2026-07-02):** (1) "all the other claudes from the other projects are alarmed" — the per-turn token guard screams `TOKEN RUNAWAY … cache-miss write NNNk … consider /compact` on EVERY turn right after a `/compact`, because re-caching the whole prefix legitimately spikes `cache_creation` past the HARD threshold. The wording implies a CONTEXT-SIZE problem and recommends `/compact` — counterproductive right after a compact. (2) "even in maintenance mode the janitor must nudge the agent to continue … they must never stop" — maintenance mode was over-optimized into full silence, so autonomous agents stall after a turn/compact/rate-limit.
- **v0.28.1 already fixed** the maintenance resume for compaction + rate-limit (the /code-review B2 fix ran the resume/renew/presence phases before the maintenance early-return). This TRDD adds the two remaining pieces.
- **NEXT ACTION:** two disjoint implementations (parallelizable) → verify (ruff+mypy+pytest) → publish v0.28.2. Evidence: `reports/token-estimation/20260702_110855+0200-fix-plan.md`.

## Part A — post-compact-aware token-budget guard + exact-data command

Root cause CONFIRMED (fix-plan report): `token_meter.evaluate_turn_budget` (scripts/lib/token_meter.py:316-353) scores `cache_creation_input_tokens` against a flat threshold with zero compaction awareness; `pre-tool-token-budget.py` never reads the post-compact signal; its hard/advisory text (L135-144) recommends `/compact` even when `/compact` caused the spike.

- **A1** — `token_meter.evaluate_turn_budget` (~316-323, 345-348): add an `ignore_cache_creation: bool = False` param; when set, the cache_creation signal does not contribute to the ok/advisory/hard classification (output-based classification is unchanged — genuine sustained runaway still trips).
- **A2** — `pre-tool-token-budget.py`: pass `ignore_cache_creation=True` when `.janitor/state/resume-after-compact.ts` is FRESH (written by post-compact-resume.py:192-193; cleared ~5 min later by dispatch.py) — i.e. suppress ONLY the expected one-time re-cache window.
- **A3** — `pre-tool-token-budget.py:135-144`: reword — a cache_creation-only trip is a per-turn cache-WRITE billing artifact (one-time after a compact/gap), NOT a context-size problem; DROP the `/compact` recommendation for cache_creation-only trips (keep it for output-only trips).
- **A4** — `/janitor-token-report --live`: print exact context used / 1M-window (%) + last-turn output/cache_creation/cache_read, clearly labeled. Move `resolve_context()` out of `pre-tool-context-usage.py` into `token_meter.py` and share it (single source). `pre-tool-context-usage.py` behavior itself is already correct — do NOT change its logic.
- Tests: tests/test_token_meter.py (ignore_cache_creation), tests/test_pre_tool_token_budget.py (fresh-vs-stale resume-ts gating + wording), new tests/test_token_report_live.py; regression-check tests/test_pre_tool_context_usage.py + test_context_size_guard.py.

## Part B — never-stop continue-nudge (maintenance + opt-in)

- **B1** — dispatch.py: add `_phase_keep_going_nudge(mode)` that emits `[janitor-resume]` + a short "continue your pending task; if nothing remains, say so briefly (and `/janitor-keep-going off` to stop the nudge)" line when EITHER `.janitor/state/keep-going` is present OR `mode == "maintenance"`. It emits (does NOT early-return). Place it AFTER `_phase_heartbeat_renew` and BEFORE the maintenance early-return, so: maintenance → nudge then cheap return (no detectors/daemon); full → nudge then detectors. If an earlier rate-limit/compact resume already fired+returned, this is naturally skipped.
- **B2** — new `/janitor-keep-going` skill (on/off) → atomically writes/removes `.janitor/state/keep-going` (mirror the maintenance-mode skill). `/janitor-keep-going off` removes it.
- **RUNAWAY GUARD:** the nudge fires ONLY under an explicit opt-in (the keep-going flag OR maintenance mode — both deliberate user choices). A plain full-mode session with neither → no nudge → idles normally. So no fleet-wide token runaway on default/interactive sessions.
- Tests: dispatch phase test — keep-going flag → nudge in full AND maintenance; maintenance (no flag) → nudge; full + no flag + no maintenance → NO nudge; a prior compact/rate-limit resume still short-circuits first.

## Delivery
Both parts touch DISJOINT files (A: token_meter.py, pre-tool-token-budget.py, token_report.py + tests; B: dispatch.py, new skill, dispatch tests) → implement in parallel. Verify ruff+mypy+pytest on touched files, then `publish.py --patch` → v0.28.2. Docs: CLAUDE.md hooks/skills list, README, the maintenance-mode skill (note it now nudges continue). Update this frontmatter (implementation-commits, column) on landing.
