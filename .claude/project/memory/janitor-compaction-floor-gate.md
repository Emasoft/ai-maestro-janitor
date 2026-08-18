---
name: janitor-compaction-floor-gate
description: "the janitor compacted my context over and over / it keeps compacting every 10 minutes forever / why is the context still huge right after a compaction / what should the auto-compact threshold be / compacting barely shrank anything"
ocd: 2026-07-17
lmd: 2026-08-18
metadata:
  node_type: memory
  type: project
  tier: component
publish-globally: false
---

The janitor's PROACTIVE-idle auto-compact trigger (`cold_cache_compact` +
`on-stop-proactive-compact.py` + `dispatch._phase_proactive_idle_compact`) and the one gate that
makes it terminate. Shipped in **v0.49.0** (2026-07-17; TRDD-D3PROACT; the loop fix is `1a69ec6`,
release-bump `b5c298a`). The buggy loop-prone form was NEVER published — it was caught in the
pre-publish batch, so no release ever shipped the size-only gate.


^ATOM-QF32-QZW4 [desc:"The first turn after a compaction has no fresh usage line, so a transcript-based context reading is the PRE-compaction one — omit it, never soften it", keywords: context_reading_is_wrong_right_after_a_compaction hook_says_compact_but_I_just_compacted prepare_for_auto-compact_with_0k_headroom_is_false resolve_context_transcript_fallback context_percent_disagrees_with_reality first_turn_after_compaction_reads_the_old_context, ocd: 2026-08-12, lmd: 2026-08-12]

**The first turn after a compaction cannot measure its own context from the transcript.**
`token_meter.latest_context_size` returns the newest usage-bearing assistant entry — and on that
first turn the newest one is the PRE-compaction turn, because this turn has not written a usage
line yet. Any reading taken then describes a context that no longer exists.

Measured live 2026-08-13 on this repo: the `pre-tool-context-usage` hook injected *"~65% used,
⚠ PREPARE for auto-compact: ~0k until the auto-compact point (~660k)"* when the truth was
**273,670 tokens with 386,330 of headroom** — it was reporting the pre-compaction 661,367. Acting
on it would have discarded a context compacted seconds earlier and paid a full re-cache.

Fixed in TRDD-G043V3V0 (commit 2ec63fec): `resolve_context` takes an injected `last_compact_ts`
(the `last-compact.ts` high-water stamp the PostCompact hook writes) and OMITS the reading —
returns `(None, None, None, False)` — when the entry predates it. Omission, not the `stale` flag:
`_format_line` only appends *"(snapshot may lag)"*, which softens a number that is not soft.

**Diagnose it by asking which BRANCH ran.** `resolve_context` prefers the statusline snapshot at
`<project>/.claude/janitor/context-usage.<session_id>.json` and only falls back to the transcript
when that file is ABSENT — the fallback was the branch that could not report staleness. Check for
that file before theorising; a session with a snapshot never had this bug.




^ATOM-L03E-L31N [desc: "the cold-resume shrink refused on 'cache state unknown' — a gate fed only by an OPTIONAL tool is unreachable; fixed by measuring elapsed time instead", keywords: cache_state_unknown_not_clearing cold_resume_did_not_shrink every_session_paid_a_full_cache_write_on_its_first_turn agentlensPro_absent_so_the_clear_never_fires, type: reference, ocd: 2026-08-18, lmd: 2026-08-18]

Two defects made the cold-resume shrink LOOK implemented while doing nothing useful (TRDD-CEWVQ8DG, fixed in `904ddef4`); both were found in `.janitor/logs/`, not by reading code.

**A gate whose only input is an OPTIONAL tool is unreachable.** `should_clear_on_resume` requires `cache_expired is True`, and its only source was a probe of the agentlensPro CLI. Where that tool is absent the probe abstains, so the verdict was `why=cache state unknown — not clearing` and a whole fleet of cold resumes each paid a full cache-creation write on its first turn. The fix is not to relax the veto — `/clear` is unrecoverable — but to ANSWER THE SAME QUESTION with a measurement that needs no third party: elapsed time. Past `max(ttl, 60min)` no prompt cache survives, so the age IS the verdict. `cache_expired_by_age` returns **True or None, never False**: "not yet certainly dead" is not "alive", and a False would override a probe that said expired, re-creating the refusal being fixed. `resolve_cache_expired` consults the probe FIRST, so a warm probe still beats an ancient mtime and a live cache is never thrown away.


^ATOM-PKZU-XTVT [desc: "why next_fire_misses_cache and this floor gate use opposite TTL asymmetries despite reading the same elapsed time", keywords: next_fire_misses_cache_vs_this_gate opposite_TTL_asymmetries_same_elapsed_time why_5_min_vs_60_min_TTL, type: reference, ocd: 2026-08-18, lmd: 2026-08-18]

The two clocks read the SAME elapsed time with OPPOSITE asymmetries, which is why the floor is its own constant: `next_fire_misses_cache` predicts a COST and uses the SHORT TTL (5 min) to err toward acting; this gate authorizes a DESTRUCTIVE act and uses the LONG one (60 min) to act only where certainty is real.


^ATOM-F9K2-BPPQ [desc: "a CLI in a plugin-cache bin dir is invisible to shutil.which in a hook child — verify a PATH-dependent fix under the environment that failed, not your shell", keywords: llm-ext_is_not_on_PATH handoff_degraded_to_the_template summary_permanent_not_retrying which_llm-ext_fails_in_a_hook verify_PATH_dependent_fix_under_env_-i, type: reference, ocd: 2026-08-18, lmd: 2026-08-18]

**A CLI that ships inside another plugin is invisible to `shutil.which` in a hook child.** llm-ext lives at `~/.claude/plugins/cache/<marketplace>/llm-externalizer/<version>/bin/llm-ext` — a dir the user's interactive PROFILE puts on PATH, which a hook-spawned detached child never inherits. So `summary: permanent — llm-ext is not on PATH; not retrying` fired on every cold resume and each handoff silently degraded to the link-only template. Resolve by the install's OWN layout (the convention `llm_ext_data_dir` already reads in reverse), PATH first so an operator keeps control, and order versions by PARSED NUMERIC TUPLE — as strings `"9.0.0"` sorts above `"13.5.1"` and would pin the oldest install forever.

**Verify a PATH-dependent fix under the environment that FAILED, not your shell**: `env -i HOME=$HOME PATH=/usr/bin:/bin <interpreter> -c '...'` reproduces the hook child. An interactive shell finds the binary and proves nothing.


^ATOM-V42V-4CJO [desc: "on 2026-08-18 the externalized compaction cleared a live session and left a REFUSAL in its handoff — the whole validation was 'out or None'", keywords: handoff_was_a_refusal compaction_cleared_my_session_and_the_handoff_was_useless model_refused_the_compaction exit_0_but_wrong_output llm-ext_returned_a_refusal, type: project, ocd: 2026-08-18, lmd: 2026-08-18]

On 2026-08-18 the externalized compaction cleared a live session and left a REFUSAL in its
handoff. Every mechanical step was correct — cold-cache gate opened, the hook BLOCKED on the
watcher, the chain typed `/clear` — and the log said `summary: ok on attempt 1`. The model had
not summarised: it declined the compaction as a prompt injection and lectured about this plugin,
on exit 0 with non-empty stdout. The whole validation of the artifact that authorises destroying
a context was `out or None`.


^ATOM-3LYT-GMKT [desc: "the fix classifies a refusal as UNKNOWN with a constant detail and degrades to a link-only handoff; the match is anchored to the first line, not anywhere in the text", keywords: summary_ok_but_the_summary_was_garbage agent-handoff.md_contains_a_lecture looks_like_refusal_fix blockquote_not_stripped, type: project, ocd: 2026-08-18, lmd: 2026-08-18]

**A zero exit says the CLI ran. It says nothing about whether the text is a summary.** The fix
(3.3.13, `_looks_like_refusal`) classifies a refusal as UNKNOWN with a CONSTANT detail — the
retry bound counts identical details, so prose in the detail would silently make it unbounded —
and the pre-existing degrade-to-template path then writes an honest link-only handoff and still
clears. The clear is never held hostage to summary quality; that was always the design.

The match is ANCHORED to the first line, NOT "anywhere in the first N chars": a legitimate
summary OF this incident opens by QUOTING the refusal. Blockquote `>` is deliberately not
stripped — a leading `>` is evidence of quoting, the opposite of refusing.


^ATOM-1EV0-XCON [desc: "3.3.14 added evidence capture on every failed attempt; blast radius measured 1/19 poisoned handoffs, upstream cause is llm-externalizer's driver.ts prompt wording", keywords: compaction_failed_could_not_be_answered_without_a_repro evidence_transcript_path_bytes_rc_elapsed blast_radius_poisoned_handoffs driver.ts_prompt_reads_as_injection, type: project, ocd: 2026-08-18, lmd: 2026-08-18]

3.3.14 added the other half: until then stderr was read into a local and DROPPED on every
zero-exit path, and stdout was dropped on every non-OK path, so "the compaction failed" could
not be answered without a repro. Each attempt now carries `evidence` (transcript path + bytes,
rc, elapsed, both-ends excerpts of both streams), logged the moment it fails.

Blast radius measured across 19 project handoffs on this host: 1 poisoned. Full record:
TRDD-IFZQ98BA. The upstream half is llm-externalizer's `driver.ts:996-997` prompt, whose
"Your output REPLACES the transcript ... it is a handoff, not a report" reads as injection-shaped
to a safety-tuned model; that reword is theirs, and they have it.

## Governed by

- [[debugging-methodology]] — the general discipline this incident fed back into (a claim asserted
  in three places, measured in none; a gate reused at a new trigger point without re-deriving
  termination).

^compaction-does-not-shrink-the-base [desc: a_compaction_only_removes_the_transcript_never_the_base_that_reloads_after_it, keywords: compacting_barely_shrank_anything context_still_huge_right_after_compacting why_is_my_context_300k_on_a_fresh_compact compaction_only_freed_10_percent, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**A compaction cannot shrink the BASE — only the transcript above it.** After every compaction the
harness reloads CLAUDE.md, every enabled plugin's skills/agents/hooks, `~/.claude/rules/*`, the MCP
tool schemas, and the freshly-written summary. That floor is a property of the INSTALL, not of the
conversation, so it is identical after every compaction.

Measured on this repo 2026-07-17 (~10 plugins + several MCP servers): a real compaction went
**343,007 → 308,644** — a 10% shrink. The often-quoted "compaction takes ~600k → ~50k" is FALSE on
a heavy install; TRDD-EUWIHP0G's cold-burn savings estimate was written against that wrong premise.

The floor is per-machine and GROWS as plugins/MCP servers are added — so any threshold expressed
relative to it must be re-measured, never assumed. Read it live with
`token_meter.latest_context_size` on the first turn after a compaction.

^size-only-gate-cannot-terminate [desc: a_repeating_compact_trigger_gated_on_size_alone_loops_forever_because_the_floor_exceeds_the_threshold, keywords: janitor_compacted_my_context_over_and_over compacts_every_10_minutes_forever infinite_compact_loop auto_compact_fires_again_and_again cooldown_did_not_stop_it, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**A REPEATING auto-compact trigger gated on context size alone CANNOT terminate when the
post-compaction floor sits above the threshold.** With floor 308,644 > threshold 270,000: compact →
land at the floor → still over → cooldown expires → compact again → forever, destroying context
each cycle. No threshold value fixes this in general, because the floor is set by the install, not
chosen by us.

**A cooldown DEFERS a loop; it never ends one.** It was the only thing standing between this design
and a 10-minute context-destruction cycle, and it was mistaken for a stop. [^1]

The bug entered by REUSE: the size-only gate was safe for the two ORIGINAL triggers because they
are RARE — SessionStart fires once per session, the rate-limit path once per limit. It became a
loop the instant it was reused at Stop, which fires every turn. Nothing about the gate changed; its
trigger frequency did. See [[debugging-methodology]] `^debug-re-derive-termination-on-reuse`.

^floor-gate-is-the-stop [desc: gate_on_reclaimable_tokens_above_the_learned_floor_not_on_context_size, keywords: how_do_I_stop_the_compact_loop what_gate_makes_auto_compact_terminate exclude_the_compaction_case min_gain_tokens, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**Gate on RECLAIMABLE tokens, not on size:** fire only when `ctx − floor ≥ min_gain` (default
150k, `..._PROACTIVE_IDLE_COMPACT_MIN_GAIN_TOKENS`). This asks the only question that matters —
*would compacting actually free anything?* At the floor the answer is 0, so the trigger goes silent
until real work accumulates above it. It is NOT a permanent latch: a session that grows large again
still gets its compaction.

^ATOM-CMPF-LEAR [desc: the_floor_is_learned_not_assumed_stop_hook_stamps_it, keywords: when_is_the_floor_measured how_is_the_learned_floor_recorded stop_hook_earliest_observable_point post_compact_resume_stamps_last_compact_ts, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
The floor is LEARNED, never assumed: `post-compact-resume.py` stamps `last-compact.ts`, and the
next **Stop** records the context it observes as the floor (`cold_cache_compact.refresh_floor`).
**Stop is the earliest point at which the post-compaction size is observable at all** — PostCompact
itself is too early, because the compacted size does not exist until a turn has run against it. [^2]
Measuring at a turn's end can only OVER-state the floor, which under-states the gain and biases
toward NOT firing: a missed optimization, never a destroyed context.

^ATOM-CMPF-PRIO [desc: measurement_must_run_before_the_action_gates_that_veto_it, keywords: TRDD-28XF77X6 measurement_behind_cooldown_gate_never_ran floor_needs_learning_check_first record_floor_before_cooldown_check, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**The measurement runs BEFORE the action gates** (TRDD-28XF77X6, fixed same day v0.49.0 shipped):
both call sites check `cold_cache_compact.floor_needs_learning` (cheap: `last_compact > floor_ts`)
and record the floor FIRST, then apply cooldown / user-present / active-waiting to the compact
decision only. The compaction stamps all three gates itself (`mark_fired` → 600s cooldown; its
auto-resume → `last-resume.ts`, 30-min recency; keep-going → active forever), so a measurement
placed behind them never ran in exactly the unattended sessions the trigger targets — v0.49.0
shipped with the floor gate inert, saved only by the 350k threshold sitting above the ~308k floor. [^3]

^ATOM-CMPF-HWTS [desc: last_compact_ts_is_a_high_water_timestamp_never_consume_once, keywords: is_last_compact_ts_a_flag_or_a_timestamp why_not_clear_last_compact_ts_after_reading high_water_mark_vs_consume_once_flag, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
`last-compact.ts` is a high-water TIMESTAMP, never a consume-once flag — a flag some reader clears
could let a compaction go unobserved, and an unobserved compaction is one whose floor is never
learned, which silently re-opens the loop.

^threshold-must-exceed-the-floor [desc: the_min_context_threshold_is_floor_relative_and_is_the_reactive_paths_only_protection, keywords: what_should_the_auto_compact_threshold_be why_350k_not_270k cold_cache_compact_min_context_tokens lower_the_threshold_to_save_more, type: project, ocd: 2026-07-17, lmd: 2026-07-17]
**`cold_cache_compact_min_context_tokens` (350k since 2026-07-17, was 270k) MUST sit ABOVE this
install's post-compaction floor.** It is not a round fraction of the window — it is floor-relative.

This matters most for the paths that have NO floor gate: the REACTIVE ones (SessionStart,
rate-limit resume). They fire once per rare event so they cannot loop, but at 270k each would burn
a lossy compaction on a context already sitting at its floor — reclaiming nothing. The threshold is
their only protection.

Pinned by `test_default_threshold_sits_above_the_measured_post_compaction_floor`, so a future
"lower it to 200k for more savings" fails loudly instead of quietly restoring the loop. If the
floor grows past 350k (more plugins/MCP), that test is the alarm — re-measure, don't just bump it.

## See also

- [[janitor-tool-call-cost-law]] — why context size is the cost driver at all, and why shrinking an
  idle context is worth a lossy operation.
- [[janitor-hooks-two-import-conventions]] — the `from lib import state` vs bare `import state`
  trap; both the Stop hook and its tests live on that fault line.


^ATOM-34JJ-8P4R [desc:"the cold-cache compact trigger is last-turn AGE only, never context size, and its repeat guard must stay longer than its trigger", keywords: the_janitor_did_not_compact_my_big_context_on_restart resumed_session_paid_a_full_cache_write_on_the_first_turn compact_threshold_never_fires cold_cache_compact_dead_code why_is_my_600k_session_not_compacted changing_the_auto_compact_window_changed_janitor_behaviour compact_fired_over_and_over_on_an_idle_session, ocd: 2026-08-04, lmd: 2026-08-04]

The CACHE-EXPIRED compact trigger (`should_compact_on_resume` + `should_compact_after_idle`) fires on ONE thing: the last turn is older than the prompt-cache TTL — 55 min, `DEFAULT_MIN_IDLE_SECONDS=3300`. It consults NO context size (USER directive 2026-08-04). It used to also require `context_tokens >= min_context_tokens()`, and that clause made the whole feature DEAD CODE: `min_context_tokens()` is harness-relative (`CLAUDE_CODE_AUTO_COMPACT_WINDOW - summary_overhead + backstop_margin`), so with the window at 700000 it resolved to 716,000 while Claude Code's own auto-compaction fires at 666,000 — a bar no context can reach, because the harness compacts first. Measured live: the gate returned False at 300k/500k/600k/700k, and resumed 500-600k sessions each paid a full cache WRITE on their first turn. The deeper error was one function serving two different economic events: OVERFLOW compaction (prevent running out of window — correctly defers to the harness) and CACHE-WRITE compaction (the harness has no such feature at all, so there is nothing to defer to). `min_context_tokens()` still exists and still gates the PROACTIVE warm-idle path, which really is asking "did the harness's compaction fail?". [^5]


^ATOM-MQ3R-WT50 [desc:"the compact repeat-guard window must stay LONGER than the expiry trigger, or an idle session compacts on a loop forever", keywords: compact_fired_over_and_over_on_an_idle_session repeat_guard_window did_a_compact_already_happen_recently last-compact.ts_stamp does_the_guard_cover_a_manual_compact_or_auto-compact compact_loop_on_an_abandoned_session, ocd: 2026-08-04, lmd: 2026-08-04]

Two invariants hold the cache-expired compact path together. (1) The TRIGGER (55 min) is deliberately UNDER the 1h prompt-cache TTL, because the last-turn age is measured at CHECK time while the compact turn runs later. (2) The REPEAT guard (`recently_compacted`, 65 min) reads TWO stamps: `last-compact.ts`, which the PostCompact hook writes unconditionally — so it covers a `/compact` the user ran by hand, one a janitor cron fired, AND Claude Code's native auto-compact, none of which the janitor would otherwise know happened — plus our own `cold-compact-fired.ts` for a fire that may not have landed yet. **GUARD (65) > TRIGGER (55) is load-bearing**: reverse them and a permanently idle session clears the guard while still satisfying the trigger, and compacts on a cycle forever. What none of this fixes: a `/compact` is ITSELF a turn, so the FIRST cold read of a resumed context is unavoidable — the win is paying it once instead of carrying the context through every later turn of the window. Getting under that first read needs `/clear`-with-handoff, which is a separate lever (`clear_enabled()`).


^ATOM-69ST-CS4K [desc:"the clear and the re-arm after it are ONE atomic act — clear_trigger checks presence once up front, never per phase", keywords: session_was_cleared_but_the_janitor_never_re-armed heartbeat_died_after_a_clear why_does_clear_trigger_ignore_user_presence stranded_session_unarmed clear_then_bootstrap_two_phases, ocd: 2026-08-04, lmd: 2026-08-04]

`/janitor-handoff-and-clear` fires TWO keystroke phases — phase A `/clear`, phase B the bootstrap that re-arms the heartbeat (`clear_trigger.plan_clear`). The load-bearing detail is that presence is checked EXACTLY ONCE, in `main()`, and each phase is then fired with `respect_user_presence=False`. That looks like a safety gate being bypassed and is the opposite: a per-phase check can pass for A and fail for B if the user appears in the settle window between them, which CLEARS the session and then REFUSES the re-arm — stranding it with no heartbeat and no memory of why. The two phases are one indivisible act, so the decision to act must be taken once, before either. GENERAL SHAPE: when a sequence is irreversible after step 1, every precondition belongs BEFORE step 1; re-evaluating it between steps converts "we declined to act" into "we half-acted". Related: the SHIPPED DEFAULT clear is a SELF-trigger, but not because it has to be — a handoff no longer needs a model turn to author (see ^ATOM-1661-HAO6, and [^7] for the clause this corrects). See [[claude-code-esc-input-semantics]] for the injector rules and why this is never routed through fleet_inject. [^7]


^ATOM-1KAU-ALIB [desc:"the janitor CAN compact itself — compact_trigger.py is an agent-invoked lever independent of the automatic gates, and ships in the cached plugin", keywords: can_the_janitor_compact_itself can_I_compact_my_own_context only_the_user_can_run_/compact compact_trigger.py session_too_expensive_and_I_am_waiting_for_the_user self_compaction_lever agent_invoked_compact, ocd: 2026-08-05, lmd: 2026-08-05]

The janitor ships a MANUAL, agent-invoked compaction lever independent of every automatic gate on
this page: `scripts/compact_trigger.py` (+ `scripts/lib/terminal_trigger.py`) resolves THIS
session's own terminal pane and types `/compact` into it. It ships in the CACHED plugin, so it
works even when the working tree is hundreds of commits ahead of the installed version and the
daemon/detector commits are inert. Verified 2026-08-05: a dry run resolved the live iTerm session
id, a real run returned `COMPACT_FIRED` / exit 0, and the compaction landed. So "only the USER can
lower per-turn context" is FALSE — when context cost is the acute problem, the agent can fire it.
This does NOT loosen the backstop-only rule: that rule governs the AUTOMATIC path (the cold-cache
and proactive-idle gates, which stay harness-relative), and firing the manual lever while the
harness is about to auto-compact anyway re-creates the same BUG-2 competition. [^6]


^ATOM-1661-HAO6 [desc:"the EXTERNAL zero-model-turn clear exists (default OFF) — and its typist needs CLAUDE_PROJECT_DIR set or it strands the session it cleared", keywords: clear_a_session_without_a_model_turn external_handoff_and_clear zero_token_handoff who_writes_agent-handoff.md idle_session_clears_itself_from_outside cleared_session_never_resumed resume_marker_written_to_the_wrong_tree, ocd: 2026-08-06, lmd: 2026-08-06]

The in-model clear (`dispatch._phase_idle_clear_nudge` → `/janitor-handoff-and-clear`) costs the thing it saves: the handoff is authored BY THE MODEL, so an abandoned session pays a full turn on its huge context to write the note that lets it shrink. `scripts/external_handoff_clear.py` + `lib/external_clear.py` (TRDD-PXP08ZQC) do all three steps outside the model — decide, compose, type — and ship DEFAULT OFF (`CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED`).

THE TYPIST NEEDED NO CHANGES: `clear_trigger._spawn_chain`'s `--__chain` child already takes pane + state-dir + directive as DATA, so an out-of-session caller reuses the ratified injection chain verbatim. It only requires `CLAUDE_PROJECT_DIR` be set FOR THE CHILD — its fallbacks are git-toplevel then cwd, which from a daemon resolve to the DAEMON's cwd, writing the resume marker into another tree while the cleared session waits for one that never arrives. The handoff itself only POINTS: `compose_template_handoff` satisfies `check_handoff_concise` by construction (unconditional memgrep pointer, never a fence, trims whole tail ITEMS since a mid-line cut leaves a half-written TRDD id that resolves to nothing). See [[reference_llm_ext_returns_an_ensemble_report]] for why an LLM does not write it.


^ATOM-1661-TRIG [desc:"'has the cache expired' is the wrong predicate when the heartbeat is faster than the TTL — ask whether the NEXT fire will miss", keywords: cache_expired_trigger_never_fires TTL_longer_than_the_heartbeat_cadence gate_that_can_never_be_true threshold_never_met idle_clear_never_fires measure_the_cadence_against_the_TTL, ocd: 2026-08-06, lmd: 2026-08-06]

Measuring beats reasoning on this one. With a probed 60-min cache TTL and a `*/5` cadence (measured 2026-08-06 from `ttl-regime.json` + `armed-cadence.cron`) a fire every 5 minutes keeps the prompt cache permanently WARM, so a literal `cache_expired` predicate is NEVER true and any lever gated on it does not exist. The question that costs money is not "is the cache cold" but "will the NEXT fire pay the miss": `age_since_last_turn + seconds_until_next_fire >= ttl`, which fires in the idle gap BEFORE the expensive fire. It is OR'd with the long-idle rule because neither subsumes the other — the miss trigger is silent on a warm fleet, and a warm fire on a 460k context still re-reads ~10M weighted tokens. GENERAL SHAPE: before shipping a threshold, plug in this machine's real numbers and check the gate can ever close; `cold_cache_compact` shipped this bug twice before (see the CLEAR section's own "a threshold high enough to never be met is a feature that does not exist"). [^5]


^ATOM-1661-SHAP [desc:"terminal identity has TWO dict shapes and mixing them is a SILENT no-op, not an error — terminal_from_record is the adapter", keywords: terminal_identity_dict_has_two_shapes kind_pane_vs_iterm_session_id recorded_terminal_returns_the_wrong_shape injection_did_nothing_and_reported_nothing keystrokes_never_arrived osascript_refused_to_build ITERM_SESSION_ID_has_a_tty_prefix, ocd: 2026-08-06, lmd: 2026-08-06]

`session_liveness.capture_terminal_identity` and `fleet_restart.recorded_terminal` emit the FLEET shape `{iterm_session_id, tmux_pane}`. `terminal_trigger` and `clear_trigger._this_terminal` consume a DIFFERENT shape, `{kind, pane|session_id}`. Passing the former straight to the latter yields `kind=""`, and every builder treats an unknown kind as "unsupported channel" — so the injection SILENTLY does nothing and reports success. `external_clear.terminal_from_record` is the adapter (tmux preferred, because its pane can be read back, which is what lets the chain VERIFY a command before submitting it). Second trap in the same conversion: `ITERM_SESSION_ID` is recorded VERBATIM as `<tty>:<UUID>`, so the UUID must be split off or `clear_trigger._UUID_RE` rejects the whole string and refuses to build the osascript at all.


## Superseded


^ATOM-MK02-SA6C [desc: "the handoff that authorised a destructive clear was never validated — 'summary: ok' only ever meant the process printed something", keywords: handoff_was_a_refusal compaction_cleared_my_session_and_the_handoff_was_useless summary_ok_but_the_summary_was_garbage model_refused_the_compaction agent-handoff.md_contains_a_lecture externalized_compaction_lost_my_work exit_0_but_wrong_output llm-ext_returned_a_refusal, type: project, ocd: 2026-08-18, lmd: 2026-08-18, status: superseded, superseded-by: ATOM-V42V-4CJO]

On 2026-08-18 the externalized compaction cleared a live session and left a REFUSAL in its
handoff. Every mechanical step was correct — cold-cache gate opened, the hook BLOCKED on the
watcher, the chain typed `/clear` — and the log said `summary: ok on attempt 1`. The model had
not summarised: it declined the compaction as a prompt injection and lectured about this plugin,
on exit 0 with non-empty stdout. The whole validation of the artifact that authorises destroying
a context was `out or None`.

**A zero exit says the CLI ran. It says nothing about whether the text is a summary.** The fix
(3.3.13, `_looks_like_refusal`) classifies a refusal as UNKNOWN with a CONSTANT detail — the
retry bound counts identical details, so prose in the detail would silently make it unbounded —
and the pre-existing degrade-to-template path then writes an honest link-only handoff and still
clears. The clear is never held hostage to summary quality; that was always the design.

The match is ANCHORED to the first line, NOT "anywhere in the first N chars": a legitimate
summary OF this incident opens by QUOTING the refusal. Blockquote `>` is deliberately not
stripped — a leading `>` is evidence of quoting, the opposite of refusing.

3.3.14 added the other half: until then stderr was read into a local and DROPPED on every
zero-exit path, and stdout was dropped on every non-OK path, so "the compaction failed" could
not be answered without a repro. Each attempt now carries `evidence` (transcript path + bytes,
rc, elapsed, both-ends excerpts of both streams), logged the moment it fails.

Blast radius measured across 19 project handoffs on this host: 1 poisoned. Full record:
TRDD-IFZQ98BA. The upstream half is llm-externalizer's `driver.ts:996-997` prompt, whose
"Your output REPLACES the transcript ... it is a handoff, not a report" reads as injection-shaped
to a safety-tuned model; that reword is theirs, and they have it.

^ATOM-KBU2-58YM [desc:"the cold-resume shrink refused on 'cache state unknown' and its handoff had no summary — a gate fed only by an OPTIONAL tool is unreachable, and a CLI in a plugin-cache bin dir is invisible to a hook ", keywords: cache_state_unknown_not_clearing cold_resume_did_not_shrink every_session_paid_a_full_cache_write_on_its_first_turn llm-ext_is_not_on_PATH handoff_degraded_to_the_template summary_permanent_not_retrying agentlensPro_absent_so_the_clear_never_fires which_llm-ext_fails_in_a_hook, type: reference, ocd: 2026-08-15, lmd: 2026-08-15, status: superseded, superseded-by: ATOM-L03E-L31N]

Two defects made the cold-resume shrink LOOK implemented while doing nothing useful (TRDD-CEWVQ8DG, fixed in `904ddef4`); both were found in `.janitor/logs/`, not by reading code.

**A gate whose only input is an OPTIONAL tool is unreachable.** `should_clear_on_resume` requires `cache_expired is True`, and its only source was a probe of the agentlensPro CLI. Where that tool is absent the probe abstains, so the verdict was `why=cache state unknown — not clearing` and a whole fleet of cold resumes each paid a full cache-creation write on its first turn. The fix is not to relax the veto — `/clear` is unrecoverable — but to ANSWER THE SAME QUESTION with a measurement that needs no third party: elapsed time. Past `max(ttl, 60min)` no prompt cache survives, so the age IS the verdict. `cache_expired_by_age` returns **True or None, never False**: "not yet certainly dead" is not "alive", and a False would override a probe that said expired, re-creating the refusal being fixed. `resolve_cache_expired` consults the probe FIRST, so a warm probe still beats an ancient mtime and a live cache is never thrown away.

The two clocks read the SAME elapsed time with OPPOSITE asymmetries, which is why the floor is its own constant: `next_fire_misses_cache` predicts a COST and uses the SHORT TTL (5 min) to err toward acting; this gate authorizes a DESTRUCTIVE act and uses the LONG one (60 min) to act only where certainty is real.

**A CLI that ships inside another plugin is invisible to `shutil.which` in a hook child.** llm-ext lives at `~/.claude/plugins/cache/<marketplace>/llm-externalizer/<version>/bin/llm-ext` — a dir the user's interactive PROFILE puts on PATH, which a hook-spawned detached child never inherits. So `summary: permanent — llm-ext is not on PATH; not retrying` fired on every cold resume and each handoff silently degraded to the link-only template. Resolve by the install's OWN layout (the convention `llm_ext_data_dir` already reads in reverse), PATH first so an operator keeps control, and order versions by PARSED NUMERIC TUPLE — as strings `"9.0.0"` sorts above `"13.5.1"` and would pin the oldest install forever.

**Verify a PATH-dependent fix under the environment that FAILED, not your shell**: `env -i HOME=$HOME PATH=/usr/bin:/bin <interpreter> -c '...'` reproduces the hook child. An interactive shell finds the binary and proves nothing.
## Notes and lessons learned

[^1]: [id:ATOM-CMPF-LOOP, status:valid, keywords:"self_limiting_claim_was_false claimed_it_stops_without_measuring termination_claim_in_docstring", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT write "self-limiting" or any termination claim into a docstring, config description, or
  TRDD without a measurement or test behind it, BECAUSE the claim then propagates as established
  fact — here "after the compact the context is small, so the size gate fails next fire" was
  asserted in all three places, was false in all three, and only the USER's question ("*are you
  sure it actually stops after the compaction ended?*") caught it before it shipped. DO pin every
  termination claim with a regression test carrying the REAL measured numbers.

[^2]: [id:ATOM-CMPF-CRON, status:valid, keywords:"compact_should_run_first cron_fire_burned_tokens_before_compacting cache_creation_burn_at_turn_start", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT expect a heartbeat/cron `/compact` to prevent ITS OWN fire's cold burn, BECAUSE a cron
  fire IS a turn: it re-reads the whole transcript (the cache-creation write) BEFORE `dispatch.py`
  runs as a tool call, so the burn is already paid. DO prevent it upstream — keep an idle context
  small while the cache is WARM (Stop, which fires at the end of every turn, is the event that can;
  crons cannot fire mid-query, so a >1h working turn has no heartbeat inside it).

[^3]: [id:ATOM-OBSV-GATE, status:valid, keywords:"floor_never_learned observation_behind_action_gates compact_floor_json_absent measurement_blocked_by_cooldown gate_inert_in_production", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT place a passive MEASUREMENT behind the gates that veto the ACTION it informs, BECAUSE
  the action's own side effects can hold every gate closed in exactly the target population —
  the compaction stamped the cooldown AND the resume recency, keep-going holds active-waiting
  forever, so `refresh_floor` never ran and v0.49.0's floor gate was inert (verified live: three
  fires after a real compaction, `compact-floor.json` never written). DO gate observations only
  on "is there something unobserved?" (`floor_needs_learning`) and record before any early-return.

[^4]: [id:ATOM-TEST-IMPS, status:valid, keywords:"test_passed_on_impossible_state fixture_missing_side_effects mark_compacted_without_mark_fired regression_test_wrong_state", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT hand-build a test fixture from the ONE stamp the assertion needs, BECAUSE the production
  event writes SEVERAL stamps and the omitted ones may be exactly what blocks the code under test
  — the loop test stamped `mark_compacted` alone (no `mark_fired`, no `last-resume.ts`), a state
  production can never reach, so it proved the floor gate worked in a configuration that does not
  exist. DO reproduce the event's FULL side-effect set, and prove the test FAILS on the pre-fix
  code (stash the fix, run, restore).
[^5]: [id:ATOM-SLM9-5K1D, status:valid, keywords:"a_feature_never_fires_but_its_tests_are_green threshold_derived_from_an_unrelated_setting gate_sits_above_the_point_another_system_already_acts dead_code_that_looks_configured", ocd:2026-08-04, lmd:2026-08-04] DO NOT derive a feature's threshold from a setting that belongs to a DIFFERENT mechanism, BECAUSE the two move independently and the gate can silently drift past the point where that other mechanism already acts — here the cold-compact bar (716,000) sat above Claude Code's own auto-compact point (666,000), so the feature could never fire, every unit test stayed green, and the burn it existed to prevent ran for weeks unnoticed. DO gate on the quantity the feature is actually about (cache expiry is a TIME fact, so trigger on last-turn AGE), and when a threshold must exist, prove it is REACHABLE by evaluating it against the live environment rather than reading the formula.
[^6]: [id:ATOM-FF72-T3KF, status:valid, desc:"told the user /compact was their lever alone while holding a working self-compact trigger", keywords:"waiting_for_the_user_to_compact only_the_user_can_compact I_am_blocked_on_context_cost session_too_expensive_nothing_I_can_do", ocd:2026-08-05, lmd:2026-08-05] DO NOT tell the user that `/compact` is their lever alone while a session burns context, BECAUSE `compact_trigger.py` ships in every cached version and a two-command check disproves it — I stayed blocked across several heartbeat fires reporting a cost problem whose fix I was holding. DO run `uv run --quiet scripts/compact_trigger.py` (dry-run first if unsure), and defer to the user only when the harness's own auto-compact is imminent.
[^7]: [id:ATOM-MM04-SFP4, status:valid, supersedes:ATOM-69ST-CS4K, desc:"the clear's self-trigger rationale outlived its premise once a template could author the handoff", keywords:"only_the_model_can_author_the_handoff the_clear_must_be_a_self-trigger can_a_handoff_be_written_without_a_model_turn why_is_the_clear_not_fired_from_outside reason_outlived_its_premise", ocd:2026-08-06, lmd:2026-08-06] DO NOT carry forward "the clear must be a SELF-trigger because only the MODEL can author the handoff `/clear` will destroy", BECAUSE that was a statement about the tooling of the day, not a law: `external_clear.compose_template_handoff` now builds a conforming link-only handoff from on-disk facts (TRDD STATE blocks, git log, the findings ledger) with zero model tokens, so an out-of-session watcher can author it and fire the same ratified chain — and anyone still reading the old clause would conclude the external lever is impossible and stop. DO keep the atom's ACTUAL invariant, which is untouched and is the reason it exists: the clear and its re-arm are ONE indivisible act, so every precondition is evaluated ONCE before phase A. SUPERSEDED BODY: `/janitor-handoff-and-clear` fires TWO keystroke phases — phase A `/clear`, phase B the bootstrap that re-arms the heartbeat (`clear_trigger.plan_clear`). The load-bearing detail is that presence is checked EXACTLY ONCE, in `main()`, and each phase is then fired with `respect_user_presence=False`. That looks like a safety gate being bypassed and is the opposite: a per-phase check can pass for A and fail for B if the user appears in the settle window between them, which CLEARS the session and then REFUSES the re-arm — stranding it with no heartbeat and no memory of why. The two phases are one indivisible act, so the decision to act must be taken once, before either. GENERAL SHAPE: when a sequence is irreversible after step 1, every precondition belongs BEFORE step 1; re-evaluating it between steps converts "we declined to act" into "we half-acted". Related: the clear is a SELF-trigger because only the model can author the handoff `/clear` will destroy — see [[claude-code-esc-input-semantics]] for the injector rules and why this is never routed through fleet_inject.
