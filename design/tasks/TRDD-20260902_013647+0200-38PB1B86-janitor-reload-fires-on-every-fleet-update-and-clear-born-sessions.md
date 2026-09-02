---
trdd-id: 38PB1B86
title: janitor-reload fires on every fleet-update epoch and on every clear-born session — gate it on relevance and seed the ack for clear
column: dev
created: 2026-09-02T01:36:47+0200
updated: 2026-09-02T01:36:47+0200
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
implementation-commits: []
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
- [ ] item 2: `_phase_plugin_reload` compares the CHANGED plugin set against this session's
      enabled plugins and stays silent when they do not intersect; the marker line carries the
      changed plugin(s) and versions; a test pins both the silent and the firing case
- [ ] item 3 recorded as resolved on #290
- [ ] `ruff check scripts tests` + `mypy scripts/ --ignore-missing-imports` + the touched tests green
- [ ] #290 answered with this card id, then closed when items 1–2 ship

## Notes and lessons learned

- A peer's measured issue sat unanswered for five days while the board said the pipeline was
  draining. The nudge now carries the open-issue count; the count is only useful if someone
  reads the threads.
