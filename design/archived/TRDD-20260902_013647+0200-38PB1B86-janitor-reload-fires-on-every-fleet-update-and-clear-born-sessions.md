---
trdd-id: 38PB1B86
title: janitor-reload fires on every fleet-update epoch and on every clear-born session — gate it on relevance and seed the ack for clear
column: complete
created: 2026-09-02T01:36:47+0200
updated: 2026-09-03T10:05:00+0200
current-owner: janitor-main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
severity: high
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [290, TRDD-VHPYSN56, TRDD-Z582IKIR, TRDD-HREGVXYP]
implementation-commits: [2e9a76c8, 58d23723]
---

# `[janitor-reload]` is emitted far more often than a plugin THIS session runs actually changes

Source: janitor#290, filed by the integrator-agent Claude (2026-08-28) with measurements,
never answered by this project until 2026-09-02. Re-checked against the tree tonight.

## The three findings, and their state on 2026-09-02

1. **`clear` missing from the SessionStart reload-ack seed** — STILL OPEN.
   `scripts/hooks/on-session-start.py:560` reads `if source in ("startup", "resume", "fork"):`.
   A `/clear`-born session therefore never seeds `reload-acked.ts`, `dispatch._phase_plugin_reload`
   reads the absent stamp as 0 and self-heals by emitting once — so EVERY cleared session pays one
   spurious reload (measured by the filer: cleared 13:38:28, marker 13:38:57, against a generation
   stamped 10:30). The comment above that tuple documents the identical bug for `fork`. Fix:
   add `"clear"`, and enumerate the source values from one place so a fourth member cannot be
   missed the same way.
2. **A fleet-wide `plugins-updated.json` rewrite re-fires the marker for every session** —
   STILL OPEN, design. `reload_generation()` is `max(flag, server plugins-updated epoch)`, and
   the hub rewrites that epoch on every `fleet-plugins-update` even when the SAME seven plugins
   are listed and nothing this session loaded changed. The integrator measured four markers in
   ~2.5 h on one session, at least two of them no-ops (`377 skills → 377 skills`), each costing
   ~18k tokens of re-injected skill list riding forward on every later turn, plus the registry
   thinning of TRDD-HREGVXYP. Gate on RELEVANCE: emit only when a plugin whose version changed is
   one this session actually has enabled; make the marker carry its reason
   (`plugin=X old=Y new=Z`) so a receiving session can decline a cosmetic bump; never `/clear` an
   attended session (the injector already measures attendance). Urgent-vs-routine split can wait.
3. **A drift line recommends `scripts/wikimem_syntax_lint.py`, absent in 3.3.26** — RESOLVED
   by shipping: the script is present in the installed 3.4.3 cache and imported by
   `scripts/detectors/wikimem-syntax.py:74`.

## Acceptance

- [x] item 1: the seed tuple covers `clear` (named `fresh_process_sources`, one place);
      `tests/test_session_start_reload_ack_seed.py` runs the REAL hook in a sandbox for each
      of startup/resume/fork/clear and asserts the stamp lands with the flag's generation,
      plus a `compact` control that must not seed — 5/5, 2026-09-02
- [x] item 2 (58d23723): SessionStart snapshots each enabled plugin's newest cached version
      (`plugins-at-start.json`, fresh-process sources only); `_phase_plugin_reload` diffs the
      cache against it — no delta ⇒ ack advanced silently, delta ⇒ bare token + one
      `plugin=X old=Y new=Z` payload line per change, snapshot rewritten on emit so a later
      no-op re-list cannot re-find the same delta; no snapshot ⇒ legacy emit. Tests pin the
      silent, firing, legacy and post-emit-no-refire cases (`tests/test_dispatch_phases.py`,
      `tests/test_plugin_versions.py` incl. 3.4.10 > 3.4.9). The server's
      `plugins-updated.json` was measured to list the same 7 plugins with no versions on every
      refresh, so it cannot be the relevance signal — the snapshot is.
- [x] item 3 recorded as resolved on #290 (issuecomment-5502292641)
- [x] `ruff check scripts tests` + `mypy scripts/` (497 files) + 193 tests green — re-run by
      the approver after the worker's report, not taken from it
- [x] #290 answered with this card id (issuecomment-5502292641)
- [x] #290 closed once items 1–2 SHIP (next publish + install), with the live `[reload-guard]`
      log line as evidence — `.janitor/logs/dispatch.log:3204,3222,3227` shows the no-op ack
      firing across 3 independent sessions (2026-09-02T11:10:50, 23:20:20, 2026-09-03T05:34:52);
      #290 closed citing this proof

## Notes and lessons learned

- A peer's measured issue sat unanswered for five days while the board said the pipeline was
  draining. The nudge now carries the open-issue count; the count is only useful if someone
  reads the threads.

## Approval log

- 2026-09-03T10:05:00+0200 — CLOSE (testing → complete) by janitor-main-session acting for USER
  (delegation 2026-09-03 09:58). Audit `reports/board-drain/20260903_092000+0200-testing-cards-evidence-audit.md`
  verdict CLOSE: `dispatch.log:3204,3222,3227` proves the relevance gate live across 3 sessions.
