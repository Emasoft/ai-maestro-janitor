---
trdd-id: 82JRK0CY
title: Shrink the per-fire heartbeat protocol so the model does near-zero parsing and the quiet path is near-free
column: proposal
created: 2026-07-23T13:46:08+0200
updated: 2026-07-23T13:46:08+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
approval-tier: 2
relevant-rules: [1]
task-type-detail: heartbeat-protocol-serialization
parent-source: 2026-07-23 janitor-shortcomings critique in this session (improvement D5)
npt: []
eht: []
---

# Shrink the per-fire heartbeat protocol so the model does near-zero parsing and the quiet path is near-free

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-23

- **STATE.** Proposal authored, `column: proposal`, awaiting Tier-2 (MANAGER) approval. No code written. Nothing committed by this task.
- **SCOPE.** D5 — collapse the scattered marker-emitting `print()`s in `dispatch.main()` into ONE machine-authored **decision envelope** (an ACTION token + verbatim payload lines + pre-formatted agent-spawn directives), and rewrite `rules/janitor-heartbeat-protocol.md` from a 7-row parse-and-match table to "act on the one ACTION field". Make QUIET an explicit unmissable token instead of ambiguous empty stdout.
- **NEXT ACTION (one step).** Get the D1-vs-D5 sequencing decision from MANAGER (see `## Interdependencies`): **RECOMMENDATION — ship D5 as a THIN SERIALIZATION LAYER on D1; if sequenced together, MERGE the rule/prompt rewrite into one change.** Do NOT start coding until that decision is recorded here.
- **LOAD-BEARING FACTS / GOTCHAS.**
  - A cron fire is a full turn re-reading ~500-600k cached tokens at the 0.1x cache-read rate. **No output shape makes the turn free** — D5's "near-free" = model WORK per fire (near-zero parsing) + unmissability, NOT turn elimination. The turn-COST lever is cadence/maintenance and is already shipped (`heartbeat_cadence.py`). Do not re-claim that win.
  - The baked cron prompt (`skills/janitor-arm/SKILL.md` step 3) is frozen at ARM time → a new envelope only reaches crons armed AFTER the change. The SKILL.md fallback hardcodes bare `[janitor-resume]` recognition and is the SURVIVAL backstop — **keep a bare-token form the old fallback still matches**, or emit legacy bare markers alongside the envelope for one deprecation window.
  - Two agent-marker producers live OUTSIDE `main()`: `detectors/memory-maintenance.py` and `detectors/ticket-dispatch.py`, emitting through `_run_detector`. An envelope built only in `main()` misses them unless detector stdout is wrapped.
  - The forgery guard (`_defang_foreign_markers` / `_RESERVED_MARKER_RE` / `_MARKER_OWNERS`) MUST be extended to the new format — a single structured line is a RICHER forgery target than a bare marker.
- **SUPERSEDED — do NOT carry forward.** (none yet)
- **ARTIFACTS TO READ BEFORE ACTING.** `scripts/dispatch.py` (`main` L1957-2153 + the `_phase_*` functions), `rules/janitor-heartbeat-protocol.md`, `skills/janitor-arm/SKILL.md` (step 3 + fallback), `tests/test_heartbeat_protocol_rule.py`, `tests/test_dispatch_defang.py`, `tests/test_dispatch_phases.py`.

## The problem

Every cron fire is load-bearing night-survival reliability riding on **LLM line-parsing**. On each fire the model reads three artifacts and does real parsing:

1. The **baked cron prompt** (`skills/janitor-arm/SKILL.md` step 3, lines 77-80) — a deliberately tiny stub pointing at (2).
2. The installed **rule** `~/.claude/rules/janitor-heartbeat-protocol.md` — a 7-row marker table + zero-output contract + security/defang clauses + shell-allowlist clause (~47 lines).
3. `dispatch.py`'s **raw stdout** — a heterogeneous stream: 0..N BARE marker lines (`[janitor-resume|renew|reload|reload-skills|self-disarm|memory-*|ticket]`) + free-prose directive lines + verbatim detector drift lines.

The model must: split lines, exact-match bare-whole-line markers, ignore mimicry, spawn exactly one agent per agent-marker, and reply EMPTY on quiet. Two concrete defects:

- **Parsing is the reliability surface.** A parse-error that MISSES a `[janitor-resume]`/`[janitor-renew]` on a resume/renew fire silently stalls an unattended session forever (after compact or rate-limit). The correctness of overnight survival depends on the LLM matching bare whole lines against a 7-row table under a noisy stream.
- **QUIET is ambiguous.** The quiet contract is "reply empty on empty stdout". Empty stdout is un-diagnosable: was the stub even run? did a line get eaten? Silence is indistinguishable from failure — the exact property you do NOT want on the most-common (quiet) path.

D5 target: have `dispatch.py` assemble ONE structured decision so the rule collapses from a parse-and-match table to "act on the one ACTION field", and make QUIET a single unmistakable token. Cost framing: the platform FLOOR is a full turn at 0.1x cache-read — D5 reduces model WORK + adds unmissability; it does not make the turn free.

## The fix (this TRDD's scope)

Concrete, grounded in the Phase-1 map. Two edits, one optional third.

### 1. `scripts/dispatch.py` — funnel every marker phase through ONE envelope-builder

`main()` (L1957-2153) orchestrates ~12 phases; several `_phase_*` functions `print()` independently and RETURN EARLY after clearing flags. Introduce a single envelope-builder that every phase writes its outcome into, and emit the envelope ONCE at the end of `main()`.

- **Envelope shape (machine-authored).** A single structured block carrying: one `ACTION` field (the token the model acts on with zero interpretation — e.g. `RESUME`, `RENEW`, `RELOAD`, `RELOAD_SKILLS`, `SELF_DISARM`, `SPAWN_AGENTS`, `QUIET`), verbatim PAYLOAD lines (resume-directive text, detector drift lines carried through untouched), and pre-formatted AGENT-SPAWN directives (one ready-to-act line per agent).
- **QUIET token.** When no phase fired, the envelope carries `ACTION: QUIET` explicitly — never empty stdout. The rule maps `QUIET` → reply empty.
- **Preserve exactly-once + early-return + flag-clear semantics.** The four resume phases (`_phase_rate_limit_recovery`, `_phase_compact_resume`, `_phase_clear_resume`, `_phase_keep_going_nudge`) each clear their flags, cross-clear each other's flags (to prevent a redundant second `[janitor-resume]`), and `_stamp_resume`. The collapse to one builder MUST NOT re-order flag-clears or let two resume actions coexist in one envelope. Simplest safe approach: keep the phase FUNCTIONS and their early-returns intact, but have each write into the builder instead of `print()`; the "first resume phase wins and returns" ordering already guarantees a single resume outcome.
- **Fail-SAFE default.** Current bare-whole-line design fails toward "surface verbatim". The envelope MUST keep that: an unknown/garbled/edge state ⇒ `ACTION: RESUME` (or surface-verbatim), NEVER drop. A missed resume is strictly worse than an extra surfaced line.
- **Extend the forgery guard.** `_defang_foreign_markers` / `_RESERVED_MARKER_RE` / `_MARKER_OWNERS` must cover the new envelope grammar so untrusted content (TRDD titles, memory notes, detector text) cannot inject a fake `ACTION` field. Symbols in scope: `main`, `_phase_rate_limit_recovery`, `_phase_compact_resume`, `_phase_clear_resume`, `_phase_heartbeat_renew`, `_phase_skills_reload`, `_phase_plugin_reload`, `_phase_keep_going_nudge`, `_resolve_heartbeat_mode`, `_run_detector`, `_defang_foreign_markers`, `_RESERVED_MARKER_RE`, `_MARKER_OWNERS`, `_stamp_resume`, `_phase_cadence_tier`.
- **Agent-marker folding.** `memory-maintenance.py` + `ticket-dispatch.py` emit agent-markers through `_run_detector` (outside `main()`). Two options — pick in the merge/impl step: (a) post-process detector stdout in `_run_detector` into the envelope's agent-spawn section (more hot-path complexity), or (b) keep agent-markers bare + documented as a separate authorized channel (smaller parsing win, less code). Recommendation: (a), because leaving a second bare channel undercuts the "one ACTION field" contract; but (a) must NOT become a new forgeable authorization surface — authority for a ticket lives in ticket STATUS, not the marker line.

### 2. `rules/janitor-heartbeat-protocol.md` — rewrite to consume ONE ACTION field

Rewrite the 7-row marker table into "read the `ACTION` field; act on it; surface PAYLOAD verbatim; spawn the listed agents; on `QUIET` reply empty". **Preserve the security clause** (act only on THIS fire's own stub stdout; mimicry is defanged) and the invariant "a bare marker / an ACTION token is the ONLY authorization to spawn an agent, and only the one it names". This file ships via `rules_installer.install_rules` on the cached prefix with **zero re-arm** — so the rule text is the cheap change channel; prefer editing the rule over the baked prompt wherever the survival fallback allows.

### 3. `skills/janitor-arm/SKILL.md` — keep the fallback compatible (minimal touch)

The baked prompt is frozen at arm time and its fallback (L79) is the survival backstop. If the envelope keeps a bare `[janitor-resume]`-matchable form (recommended), SKILL.md needs no change; if the envelope format is incompatible, update the fallback AND emit legacy bare markers for one deprecation window. Author this edit ONCE with D1's eventual shape in mind to avoid a second re-arm-rollout churn.

**No new env knob.** The contract is intentionally rule-file-based (ships with zero re-arm). No `CLAUDE_PLUGIN_OPTION` should govern protocol/output SHAPE — a shape knob would fragment the contract. Existing cadence knobs (`HEARTBEAT_CADENCE_DYNAMIC`, `HEARTBEAT_RENEWAL_THRESHOLD_DAYS`, `KEEP_GOING_DEFAULT`, the TTL-regime knobs, `DETECTOR_TIMEOUT`) are adjacent inputs, not D5 surface.

`files_touched`: `scripts/dispatch.py`, `rules/janitor-heartbeat-protocol.md`, `skills/janitor-arm/SKILL.md`.

## Interdependencies

D5 shares the SAME marker set and the SAME two model-facing artifacts (protocol rule + baked prompt) with three sibling improvements. Ordering and the D1 merge decision are mandatory.

- **D1 (daemon-owns-wake) — HEAVIEST overlap; D5 MUST state its merge posture.** The markers ARE the wake protocol: `resume`/`renew`/`self-disarm` are exactly the wake decisions D1 relocates from `dispatch.py` into the daemon. If D1 moves wake COMPUTATION into the daemon, **D5's structured envelope is simply the SERIALIZATION of D1's decision.** Shared files/functions: the whole marker set, `rules/janitor-heartbeat-protocol.md`, `skills/janitor-arm/SKILL.md` (baked prompt + fallback), `dispatch.main()`'s resume/renew phases (`_phase_rate_limit_recovery`, `_phase_compact_resume`, `_phase_clear_resume`, `_phase_heartbeat_renew`, `_phase_cadence_tier`), and `on-session-start._cron_liveness_nudge` (shared-fate re-arm).
  - **DECISION (this TRDD's recommendation): ship D5 as a THIN SERIALIZATION LAYER on top of D1.** If D1 and D5 are sequenced together, **MERGE the rule/prompt rewrite into ONE change** — authoring the rule/prompt twice forces two re-arm-rollout churns. If D1 does NOT proceed, D5 can ship standalone (collapse the scattered `print()`s into one envelope + rewrite the rule), but the rule/prompt edit MUST be authored ONCE with D1's eventual shape in mind. **Required ordering: D1 first (or jointly); D5 never lands a marker-restructuring that D1 would then re-restructure.**
  - **Merge caveat:** D5 alone does NOT touch the daemon flock/lifecycle. A D1 merge makes the envelope daemon-authored → daemon liveness/staleness (`ensure_daemon_running`, `daemon_needs_restart`) becomes a survival dependency of the wake protocol it currently is NOT. Keep that coupling explicit in the merge record.
- **D2 (self-budget).** Shared: `scripts/lib/token_meter.py`, `dispatch._phase_heartbeat_cost`, `scripts/lib/heartbeat_cadence.py`. D5's "near-free quiet" is delivered by D2/cadence (fewer/cheaper fires), NOT by output shape. Coordinate so both do not claim the same win — D5 = model-WORK reduction + unmissability; cadence = fire-COST reduction.
- **D4 (harness self-test).** Shared: `scripts/lib/harness_backend.py`, `dispatch._detector_runs_in_harness` + `_NON_HARNESS_DETECTORS` + `state.in_ai_maestro_agent_env`, `_resolve_heartbeat_mode`. The envelope must carry the thin(#J)/full(#N) mode so the harness path emits a coherent quiet/decision; a harness self-test is the natural place to assert the envelope round-trips inside an agent session.
- **CENTRAL shared enforcement across all four:** `dispatch._defang_foreign_markers` + `_RESERVED_MARKER_RE` + `_MARKER_OWNERS` — the single forgery guard every marker/envelope change must keep intact.
- **Delivery channel:** `rules_installer.install_rules` — the zero-re-arm channel all rule-text changes (D1 + D5) ride; prefer rule edits over baked-prompt edits.

## Verification

- **Contract pins (`tests/test_heartbeat_protocol_rule.py`).** Update and keep green: `rule_covers_every_marker`, `zero_output_contract_and_security_clauses`, `scopes_to_heartbeat_and_survives_disarm`, `baked_prompt_is_a_slim_stub`, `baked_prompt_fallback_is_non_lossy`, `installer_ships_the_protocol_rule`. These are the guardrail against silently dropping a wake marker — the rewrite MUST re-express every marker's behavior as an ACTION-field outcome, and assert `QUIET` is an explicit token.
- **Forgery (`tests/test_dispatch_defang.py`).** Add cases proving the new envelope grammar is NON-forgeable from detector/untrusted text (a fake `ACTION:` line in a TRDD title / memory note / drift line must be defanged, never acted on).
- **Phase assembly (`tests/test_dispatch_phases.py`).** This imports `dispatch` and calls `_phase_*` directly — the seam D5 refactors. Add envelope-assembly assertions: each phase writes exactly one outcome; exactly one resume outcome can exist; `QUIET` emitted when nothing fired.
- **Survival latency proven UNCHANGED (the load-bearing proof).** `tests/test_dispatch_cold_cache.py` exercises the resume/compact early-return paths. Assert the resume ACTION still fires EXACTLY ONCE through the new single-emission path, on the same trigger conditions, with the same flag-clear side effects — i.e. the number of fires to recover from a compact/rate-limit is identical to today. Add a round-trip test: envelope built by `dispatch` → parsed by the rule's stated procedure → yields the same action the bare-marker path yielded (no missed resume/renew on any phase).
- **Stub passthrough (`tests/test_dispatcher_stub.py` + `tests/test_stub_lib_constant_parity.py`).** An OLD `dispatch.py` may run under the auto-roll stub → assert its (legacy bare-marker) output stays rule-compatible during the deprecation window.
- **Agent-marker producers (`tests/test_ticket_dispatch.py` + `tests/test_memory_maintenance.py`).** Assert their agent-markers are folded/wrapped into the envelope's agent-spawn section (option a) or remain a documented bare channel (option b) — whichever the impl chooses — and that authority still derives from ticket status / pending-state, not the marker line.
- **Payload fidelity (`tests/test_resume_trigger.py` + `tests/test_post_compact_resume_hook.py` + `tests/test_pending_agents_manifest.py`).** Assert the resume-directive + pending-agent lines are carried VERBATIM in the envelope PAYLOAD.
- **Cadence unaffected (`tests/test_dispatch_cadence.py` + `tests/test_heartbeat_cadence.py`).** Confirm tier demotion/promotion still works when output shape changes — D5 must not perturb the cost lever.

## Notes and lessons learned
