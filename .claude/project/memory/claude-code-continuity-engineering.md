---
name: claude-code-continuity-engineering
description: "claude stalled overnight / fleet stopped working in my absence / session stuck in a retry loop after a 429 / janitor kept injecting commands or compacting at random / how do we keep unattended Claude Code sessions ALWAYS working — the continuity-engineering topic HUB linking every layer of the never-stall stack / how does account rotation prevent 429 stalls / window-asymmetric rotation thresholds 7d vs 5h / how to unstick a frozen retrying session / why does typing text into a blocked session flood the input buffer / janitor backstop versus harness auto-compact competing / nudging an idle armed session to keep working / keep-going-off sentinel to mute nudges / stale-hook ghosts mimic an unfixed bug after a shipped fix / does a shipped fix apply without reloading hooks / per-project channeling so a burn alarm reaches only its own project / ai-maestro server chore must match janitor chore outcome parity / prevention versus recovery two-layer stall fix / TRDD-P7WU40G9 overnight stall incident record"
ocd: 2026-07-18
lmd: 2026-09-24
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: continuity
publish-globally: true
---

^0SYALO3G [desc:"Claude Code continuity engineering: the discipline of keeping an unattended Claude Code fleet working indefinitely overnight (TRDD-P7WU40G9); owner directive: they must never stop.", keywords:"claude_stalled_overnight fleet_stopped_working_in_my_absence how_do_we_keep_unattended_claude_code_sessions_always_working trdd_p7wu40g9_overnight_stall_incident_record they_must_never_stop shipped_v0_53_0_v0_54_0"]
**Claude Code continuity engineering** — the discipline of keeping an UNATTENDED fleet of
Claude Code sessions working indefinitely (overnight, in the user's absence), distilled from
the 2026-07-17/18 overnight-stall incident (TRDD-P7WU40G9, shipped v0.53.0+v0.54.0) and the
CC docs verified 2026-07-18. The owner's standing directive: *"they must never stop."*

## The stack — six layers, each owned by its own page

^4ESPVFB8 [desc:"The six-layer never-stall stack: settings substrate, account rotation (prevention), freeze recovery (ESC-only unstick), compaction discipline, nudging idle-armed sessions, rollout observability.", keywords:"how_does_account_rotation_prevent_429_stalls window_asymmetric_rotation_thresholds_7d_vs_5h how_to_unstick_a_frozen_retrying_session why_does_typing_text_into_a_blocked_session_flood_the_input_buffer janitor_backstop_versus_harness_auto_compact_competing nudging_an_idle_armed_session_to_keep_working keep_going_off_sentinel_to_mute_nudges stale_hook_ghosts_mimic_an_unfixed_bug_after_a_shipped_fix does_a_shipped_fix_apply_without_reloading_hooks session_stuck_in_a_retry_loop_after_a_429 fleet_reachability_which_pane_can_be_injected", lmd: 2026-09-24]
1. **Settings substrate** — the harness must retry instead of stopping, and questions must
   auto-continue: [[claude-code-continuity-settings]] (watchdog + AFK chain, ensured by BOTH
   the janitor and the ai-maestro server in lockstep).
2. **Account rotation (PREVENTION — the load-bearing layer)** — a 429 only stalls a session
   for hours when every retry re-hits the same exhausted account. Window-ASYMMETRIC rotation
   thresholds (7d rejected only at 99, 5h at 97) guarantee a live rotation target:
   [[oauth-rotation-renew-reauth-cascade]]; record: TRDD-P7WU40G9 §BUG 1.
3. **Freeze recovery (UNSTICK)** — a session in the retry-watchdog "Retrying in Xm" wait is
   freed with ESC-ONLY injection (2 raw ESCs, zero text, zero Enter — anything typed BUFFERS
   and floods). Semantics: [[claude-code-esc-input-semantics]]; record: TRDD-P7WU40G9 §BUG 3.

^ATOM-DSGY-OJ87 [desc: "The last three layers of the never-stall stack: compaction discipline (janitor backstops harness auto-compact, never competes), nudging idle-armed sessions to keep going, and rollout observability (a ", keywords: janitor_backstop_versus_harness_auto_compact_competing nudging_an_idle_armed_session_to_keep_working keep_going_off_sentinel_to_mute_nudges stale_hook_ghosts_mimic_an_unfixed_bug_after_a_shipped_fix does_a_shipped_fix_apply_without_reloading_hooks fleet_reachability_which_pane_can_be_injected compaction_discipline_backstop_not_compete rollout_observability_hook_reload when_does_the_janitor_backstop_auto_compact why_is_a_fix_not_live_after_shipping, ocd: 2026-09-24, lmd: 2026-09-24]

4. **Compaction discipline** — the janitor only BACKSTOPS a failed harness auto-compact,
   never competes with it: fire only above `CLAUDE_CODE_AUTO_COMPACT_WINDOW − overhead +
   margin` (`cold_cache_compact.min_context_tokens()`); record: TRDD-P7WU40G9 §BUG 2. The
   exact-prediction formula lives in the USER-scope page
   `feedback-auto-compact-window-prediction-and-prepare-alert` (machine-global wikimem,
   recall by symptom — not wikilinked from this PUSHED page).
5. **Nudging** — an idle-but-armed session is told to continue its pending work on every
   heartbeat (default-ON via `_phase_keep_going_nudge`; muted only by an explicit per-project
   `keep-going-off` sentinel). USER-scope page:
   `feedback-agents-must-never-stop-maintenance-nudges-continue`.
6. **Rollout observability** — a shipped fix is not live in a session until that session
   reloads its hooks; stale-hook "ghosts" mimic unfixed bugs:
   [[claude-code-plugin-rollout-staleness]].

Fleet reachability (which pane can be injected, via which channel): USER-scope page
`janitor-fleet-guardian-reachability`.

## Design laws (cross-layer, all owner-ratified)

^M96S3JQO [desc:"Four cross-layer, owner-ratified design laws: prevention beats recovery, never type text+Enter into a blocked session, per-project alert channeling, ai-maestro/janitor outcome parity.", keywords:"prevention_versus_recovery_two_layer_stall_fix janitor_kept_injecting_commands_or_compacting_at_random per_project_channeling_so_a_burn_alarm_reaches_only_its_own_project ai_maestro_server_chore_must_match_janitor_chore_outcome_parity never_type_text_enter_into_a_blocked_session rate_limited_flag_janitor_resume_machinery"]
- **Prevention beats recovery**: fix rotation first; recovery (ESC) then only accelerates a
  retry that would already succeed. [^1]
- **Never type text+Enter into a blocked session** — ESC-only; the session's own
  `rate-limited.flag → [janitor-resume]` machinery does the continuation.
- **Per-project channeling**: every automatic surface (findings, alerts, token/burn warnings)
  reaches ONLY the project it concerns; the culprit project alone sees its burn alarm
  (TRDD-X92VBFNF, ARCHITECTURE.md §3).
- **Outcome parity**: any ai-maestro server function replicating a janitor chore must be
  identical in outcome (owner 2026-07-18); parity deltas are posted on janitor#100.

## Notes and lessons learned

[^1]: [id:ATOM-CONT-2LAYER, status:valid, keywords:"claude stuck retry loop 429 hours overnight stall two layer fix rotation prevents esc unsticks", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT treat "stuck in a retry loop" as one bug, BECAUSE it is two: the retry re-hitting a
  dead account (rotation failure — the hours-long part) and the session sleeping out the wait
  (recovery gap — the minutes part). DO fix rotation first, then unstick with ESC-only; either
  alone leaves stalls.
