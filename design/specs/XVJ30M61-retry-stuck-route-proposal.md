# XVJ30M61 retry_stuck route proposal
Status: REVIEWED 2026-11-13. Decision: build ONLY the countdown logging (`retry_wedge@<attempt>[<retry_in>]`, section 4) now, as its own commit. The retry_stuck route is DEFERRED until a real `retry_wedge@N[0s]` line with a static attempt appears in daemon.log on the running Claude Code build (the only static-0s frame on record is from 2.1.258). Advisor corrections, applied to any later build of the route: (a) decouple the hold from the scope bar: the hold only proves the countdown elapsed with the attempt unchanged (hold >= countdown + 2 beats); transcript_stale supplies the 15-minute bar; time-to-ESC for 0s becomes roughly 15-17 min (recompute when built); sections 1, 2 and test 3 below use hold >= W and the 30-34 min arithmetic and are SUPERSEDED by (a); (b) logging first; (c) the "second-scale banner whose 3 s recheck keeps failing" clause never matures and is dropped; (d) read pane_policy._flush_wedge and detectors/peer-freeze-recovery.py before building.
## Original draft (read-only design; nothing changed)

Everything below traced in source unless marked UNVERIFIED. Paths under scripts/.

## 0. Shape
New diagnosis `retry_stuck`, NOT an override at the decline site. Decline site (daemon.py:2338-2349) would need 4 overrides (action_for 2127, trailing_enqueues 2294, build_injection esc_first 2357, act esc_first 2484) and audit/give-up would say cron_dead ("re-arm typed N times", _GIVE_UP_TEXT 188). A diagnosis flows through `injection_is_hard` to all four. Decline stays for hour walls, not-in-flight, shared roots, not-yet-matured.

## 1. Stuck timestamp
- Field `stuck_since` (epoch int) in retry-wedge-episode.json (fleet_scan._RETRY_WEDGE_STATE_FILE; _read/_write_retry_wedge_state 1304/1317). Do NOT reuse `first_seen` (cleared to None for non-second-scale, session_liveness.py ~345-361).
- Pair = (attempt, retry_in). Set in `retry_wedge_state_update` (session_liveness.py:245-368): first sighting, attempt decrease, attempt advance -> now. Tie branch -> carry iff `current_retry_in is not None and prev_retry_in == current_retry_in and prev stuck_since is int`, else now. `current_retry_in` None -> None (reset). `now` None -> None.
- Why None resets: diagnose_root takes attempt via `retry_wedge_attempt` (anywhere in frame, fleet_scan:1537) but retry_in via the at-tail anchor (1538). A quoted/old banner gives attempt with retry_in None; resetting means such a frame can never mature.
- Existing 3 s recheck revert branch (fleet_scan ~1569-1580, parsed-different recheck): add `new_state["stuck_since"] = now`.
- Open point A, window start: ANY lane (natural, no extra code). Stale-lane-only start needs a `stale` arg threaded into the update. Time-to-ESC is the SAME either way, measured by arithmetic: W=900 (stale_threshold_for, */5). Fast-lane first read b1 in [60,180); first stale beat t_s in [900,1020) always precedes stuck_since+900 (n=ceil((900-b1)/120)=7 -> 840<900). So that beat is cron_dead -> `_decline("retry_wedge_on_screen")` stamps last_ts -> COOLDOWN_S=900 (fleet_recovery.py) -> ESC at ~t_s+900 = 30-34 min after the banner (46+ min if armed */15, W=2700). Cooldown dominates for W<=900. Other gather_fleet callers hit the else branch (fleet_scan:1583) and wipe the file pre-stale; harmless (falls back to the same ~30 min). Faster only by skipping the cooldown stamp for a not-yet-matured stuck pair: not proposed.
- Open point B, unreadable read: PRESERVE. pane_text None (1521-1531) never calls update, file untouched. Recheck unreadable (`new_state = prev`, ~1563) preserves. Frame without wedge (attempt None) ends the episode (cleared). Matches the blind-read contract.

## 2. Countdown -> seconds, scope
- New pure `session_liveness.retry_in_seconds(text) -> int|None`: fullmatch of `(\d+)\s*([hms])` tokens, sum. `0s`->0, `2m 50s`->170, `5h`->18000, `4h 59m 30s`->17970, junk->None (out of scope, fail closed). Not _SECOND_SCALE_RE (187).
- New pure `retry_wedge_stuck(state, *, now, window_s) -> bool`: stuck_since int, `now - stuck_since >= window_s`, secs not None, `secs <= window_s`.
- window_s = `effective_stale_s` already computed in diagnose_root (`stale_threshold_for(armed, stale_s)`, fleet_scan:~1478; STALE_S=900 at :46). One value serves hold-time and scope. Soundness: same attempt held >= W and countdown <= W means the wait elapsed even if the display froze; a live monotonic countdown cannot alias. No new recheck/sleep needed.

## 3. Branch change
- diagnose_root (fleet_scan:1442), after the existing recheck block, before diagnose_instance (1584):
  `retry_stuck = fast_lane and transcript_stale and not retry_wedged and transcript_turn_in_flight(root) and retry_wedge_stuck(new_state, now=now, window_s=effective_stale_s)`
  - `transcript_turn_in_flight` (1145, fail-closed): the stale lane has NO in-flight gate, and an idle cron-dead session may still show an old banner (docstring 1152-1155). Without it we ESC + type `resume` into an idle session.
  - `fast_lane` = liveness beat AND single-instance root (daemon.py:1879; gather_fleet withholds it from shared roots). Other callers keep cron_dead as today. Flag name is now a misnomer; rename is a proposal, not in scope.
  - `not retry_wedged`: attempt-advance route (WKTD5JTC) and frozen-countdown route (07f34be0) win; unchanged.
- diagnose_instance (session_liveness.py:565): kwarg `retry_stuck=False`; final line `return "retry_stuck" if retry_stuck else "cron_dead"` (after rate_limited->frozen, version_stale). unarmed/server_owned/dead/healthy gates untouched.
- fleet_recovery.py: add to DIAGNOSES (before cron_dead), `_DIAGNOSIS_RECOVERY["retry_stuck"]="esc_retry"` (session_liveness ~548 marker), `action_for`: `if diagnosis in ("retry_wedged","retry_stuck")` -> wedge_action (esc_nudge_resume, esc_nudge once resume_sent), `injection_is_hard` += "retry_stuck".
- daemon.py: `_GIVE_UP_TEXT` (187) entry. After `pane = pane_state.read` (2338) insert freshness guard: if diagnosis == retry_stuck and not (pane.status.kind RETRY_WEDGE and (pane.status.attempt, pane.status.retry_in) == persisted pair [new public `fleet_scan.read_retry_wedge_episode(root)`]) -> `_decline("retry_stuck_pane_changed", action, None)`; add `_DECLINE_REMEDY` row (143). The scan's 120 s old verdict is thus re-proven on a fresh status-row-anchored read before any key.
- ESC-confirmed-before-resume: already implemented, reuse. `pane_actuate.act` (RECOVERY_RUNG, command=None) -> pane_policy._at_wedge (306-321) -> _rung -> _flush_wedge, final_expect=Expect.WEDGE_GONE (satisfied() 149) = act re-reads until RETRY_WEDGE is gone, else FAILED. Then `resume_after_esc` (pane_actuate.py:342-481): first read status must be in _RESUME_TYPABLE_KINDS={IDLE,API_ERROR} (328) else NOT_TYPABLE; empty composer; type `resume` no Enter; read back EXACT; Enter; final read. Failure -> `_after_esc_resume` (daemon.py:2605) writes resume-pending marker, `_resume_pending_pass` (2659) retries resume only. No new actuation code.
- Budget: fire path stamps attempts+1/last_ts; gate COOLDOWN_S=900, MAX_ATTEMPTS=4 -> FLEET-GIVE-UP with the new text. Declines stamp last_ts only. ESC ends wedge -> next scan wipes episode; a recurrence needs a fresh W hold.
- Audit (`_audit`, daemon.py:1893): outcome `fired`/`fire_failed`, rung `esc_nudge_resume`, diagnosis column `retry_stuck`; new decline outcome `retry_stuck_pane_changed`. Not-yet-matured beats keep the existing `retry_wedge_on_screen`.
- 2448 block (write_rate_limited_flag + request_rotator_tick): NOT extended. A hung request is not a limit; flag would trigger rotation + resume-wake. OPEN for owner: the 0s fixture text is "429 Rate limited". Continuity is carried by esc_nudge_resume's own resume.
- Other diagnosis consumers: fleet_stop.py:136 and fleet_restart.py:165 key on "frozen" only (untouched); fleet_status.py maps (114, 672-676, 842-847) lack retry_wedged too, so it prints the raw string (149); `_resume_wake_pass` is healthy-only. UNVERIFIED: detectors/peer-freeze-recovery.py consumption.

## 4. Countdown logging `retry_wedge@<attempt>[<retry_in>]`
- Format already exists: pane_policy._read_detail (~562-575). Add `session_liveness.retry_wedge_token(attempt, retry_in)` and make `_read_detail` call it (one format).
- NOT in diagnose_root: gather_fleet has 6 callers (daemon.py:1082, 1879, 3143; cold_cache_clear_task.py:77; fleet_status.py:663; peer-freeze-recovery.py:128) = duplicate lines. Emit once per beat from the liveness beat, new helper called right after gather (1879), BEFORE the typing-gate return (~1925) so deferred beats log: for each instance with an episode file, `state.log_line("daemon", f"session-liveness: {name} {token} stuck={now-stuck_since}s")`. Caveat: reflects the last read by ANY caller; a blind beat repeats the previous value.

## 5. Tests (mutation = change that must turn it red)
session_liveness tests (tests/test_session_liveness.py):
1. test_retry_in_seconds_whole_countdown: values in 2. M: parse only the s token -> 17970 becomes 30.
2. test_stuck_since_carried_on_identical_pair_reset_on_change: attempt change, countdown change, countdown None each reset; identical carries. M: reset every poll / never reset / carry across None.
3. test_retry_wedge_stuck_hold_and_scope_boundaries: 0s held W True, W-1 False; 15m00s True; 15m01s False; 5h False. M: `>=`->`>`, `<=`->`<`.
4. test_diagnose_instance_retry_stuck_ranking: stale+retry_stuck -> retry_stuck; with rate_limited -> frozen; not stale -> healthy; server_owned/unarmed win; retry_wedged wins. M: rank above frozen/server_owned.
tests/test_fleet_recovery.py: 5. test_retry_stuck_action_and_hardness: esc_nudge_resume, esc_nudge when resume_sent, injection_is_hard True. M: drop it from injection_is_hard (resume typed into wedge).
tests/test_fleet_scan.py (helpers _fl_root, _retry_frame, _PaneSpy, _IN_FLIGHT_ROWS; fixtures real-wedged-rate-limit-429.txt, real-wedged-session-limit.txt, real-wedged-fable-limit.txt):
6. test_static_0s_attempt_held_for_window_is_retry_stuck: 0s/5 at 120 s beats, transcript stale, in flight, fast_lane=True: cron_dead before W, retry_stuck at >=W. M: reuse first_seen / drop stuck_since carry.
7. test_frozen_2m50s_held_is_the_existing_route_not_retry_stuck: diagnosis retry_wedged, proof frozen-countdown. M: new route ranked above retry_wedged.
8. test_5h_wall_never_retry_stuck: fable fixture held 3W stays cron_dead. M: drop `secs <= window_s`.
9. test_single_frame_never_fires: first stale read -> cron_dead, one capture.
10. test_advancing_attempt_resets_stuck_since: assert on episode file stuck_since == last poll (diagnosis is retry_wedged, WKTD5JTC may ESC). M: no reset on advance.
11. test_idle_session_with_old_banner_never_retry_stuck: transcript ends on assistant end_turn, stale, static pair held 3W -> cron_dead. M: drop transcript_turn_in_flight.
12. test_non_liveness_callers_never_yield_retry_stuck: fast_lane=False -> cron_dead. M: drop `fast_lane`.
13. test_unreadable_read_preserves_stuck_since: capture None mid-hold, hold still counted from the original. M: reset on None.
14. test_moved_recheck_resets_stuck_since: second-scale pair, recheck parsed-different -> stuck_since==now, no retry_stuck. M: omit the new line in the revert branch.
15. test_fast_lane_unchanged_never_retry_stuck: fast lane, transcript not stale, held 2W -> healthy. M: drop `transcript_stale`. Existing test_fast_lane_* stay green.
tests/test_daemon_session_liveness.py (LivePane from tests/pane_sim.py, pattern of the test at :158; episode file seeded):
16. test_retry_stuck_escs_then_types_resume_only_after_wedge_gone: ESC, composer read, `resume` read back, submitted==["resume"]; audit diagnosis retry_stuck / fired / esc_nudge_resume. M: type before the re-read.
17. test_retry_stuck_wedge_survives_esc_types_nothing_marker_written: pane stays wedged -> no `resume`, resume-pending marker. M: skip the status check.
18. test_retry_stuck_pane_changed_declines_without_spending_attempt: fresh pane pair differs -> audit `retry_stuck_pane_changed`, attempts unchanged, no key. M: remove guard.
19. test_cron_dead_with_hour_wall_still_declines_retry_wedge_on_screen: audit outcome asserted, no ESC.
20. test_retry_stuck_writes_no_rate_limited_flag_no_rotator_tick (cf. :848 retry_wedged test). M: extend the 2448 condition.
21. test_countdown_logged_once_per_beat: daemon.log has exactly one `retry_wedge@5[0s]` per beat, also on a healthy fast-lane instance and a typing-deferred beat. M: log inside diagnose_root.

## 6. Files / size / risk
Prod ~125 lines: session_liveness.py ~55 (parse, stuck fn, state field, rank, token), fleet_scan.py ~30 (verdict, revert line, accessor), fleet_recovery.py ~8, daemon.py ~30 (guard, texts, log helper), pane_policy.py ~2. Tests ~280 across 4 files.
Strongest reason it ESCs a healthy session: a legitimately long in-flight request (a retry whose response streams or runs > 30 min with no transcript write) shows a static `Retrying in 0s attempt N`; ESC cancels it and `resume` reissues. Cost = one request. Root premises UNVERIFIED: no captured frame shows a live 0s loop advancing the attempt (ARCHITECTURE.md:392 is prose), and no frame proves CC's request timeout aborts and bumps the attempt; API_TIMEOUT_MS here is 19000000 ms. Mitigations: in-flight gate, fresh-pair guard, 4-attempt budget, give-up alert.
Tension to resolve (do not pick silently): STATE says the route also covers "a second-scale banner whose 3 s recheck keeps failing". A recheck that is parsed-and-different means a MOVING countdown, which STATE also forbids escaping (this design resets and excludes it). Only an UNREADABLE recheck can stay in scope, and it never matures either. Effective coverage: static 0s and any static countdown without a seconds token (e.g. `3m`). Confirm the STATE wording.
Also for the owner: ESC arrives ~30-34 min after the banner (cooldown-bound), not ~16.

## Review findings to resolve before building the route (2026-11-13)
- Freshness guard compares pane_state.read's (attempt, retry_in) with the persisted pair from session_liveness.retry_wedge_retry_in: two parsers; add a test feeding each real fixture through both and asserting equality (session-limit frame has a `(2:10pm)` suffix).
- retry_in_seconds must be tested on the retry_in extracted from all three real fixtures, not hand-typed strings.
- stuck_since faces the same wipe by non-liveness gather_fleet callers as the fast-lane episode; test the interleaving.
- State whether the restored-prompt clearing ESCs (RJJGXPIK round 3) are part of the reused resume_after_esc path.
- Weak tests: #9, #15, #19 are true by construction or today's behaviour (keep only with their mutations); #21 must seed an episode file.
- Shared roots (2+ instances) never get this route; MAX_RETRIES=100 vs /300 on screen unresolved; no natural capture exists.
