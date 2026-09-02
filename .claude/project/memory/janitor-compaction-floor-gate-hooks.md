---
name: janitor-compaction-floor-gate-hooks
description: "the hook says compact but I just compacted / context reading is wrong right after a compaction / cache state unknown not clearing / cold resume did not shrink / every session paid a full cache write on its first turn / llm-ext is not on PATH / handoff degraded to the template / summary permanent not retrying / the janitor did not compact my big context on restart / the compaction cleared a live session and left a refusal in its handoff / summary ok but the summary was garbage / agent-handoff.md contains a lecture / exit 0 but wrong output / model refused the compaction / compaction failed could not be answered without a repro / blast radius of poisoned handoffs / why does the hook report stale usage right after compact / what does resolve_context prefer over the transcript / why is a gate fed only by an optional tool unreachable / why is a CLI in a plugin-cache bin dir invisible to a hook child"
ocd: 2026-08-12
lmd: 2026-09-02
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: proactive-compaction
  globs: ["scripts/hooks/*compact*.py"]
publish-globally: false
split-lineage: 279f387b68144a63a5744f521e53338f
---

The compaction hooks' own correctness bugs — the first turn after a compaction reading stale
context, the cold-resume "cache state unknown" refusal, the `llm-ext` PATH-visibility trap, and
the 2026-08-18 incident where a model's refusal was accepted as a completed summary. Split out of
[[janitor-compaction-floor-gate]] (the hub overview) 2026-09-02 — every fact below is unchanged
from that page.

^ATOM-QF32-QZW4 [desc:"The first turn after a compaction has no fresh usage line, so a transcript-based context reading is the PRE-compaction one — omit it, never soften it", keywords: context_reading_is_wrong_right_after_a_compaction hook_says_compact_but_I_just_compacted prepare_for_auto-compact_with_0k_headroom_is_false resolve_context_transcript_fallback context_percent_disagrees_with_reality first_turn_after_compaction_reads_the_old_context why_does_the_hook_report_stale_usage_right_after_compact what_is_last_compact_ts_used_for what_file_does_resolve_context_prefer_over_the_transcript snapshot_may_lag, ocd: 2026-08-12, lmd: 2026-08-12]

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




^ATOM-L03E-L31N [desc: "the cold-resume shrink refused on 'cache state unknown' — a gate fed only by an OPTIONAL tool is unreachable; fixed by measuring elapsed time instead", keywords: cache_state_unknown_not_clearing cold_resume_did_not_shrink every_session_paid_a_full_cache_write_on_its_first_turn agentlensPro_absent_so_the_clear_never_fires why_is_a_gate_fed_only_by_an_optional_tool_unreachable what_is_cache_expired_by_age why_does_it_return_true_or_none_never_false what_does_resolve_cache_expired_consult_first max_ttl_60_min_no_prompt_cache_survives why_is_the_veto_never_relaxed, type: reference, ocd: 2026-08-18, lmd: 2026-08-18]

Two defects made the cold-resume shrink LOOK implemented while doing nothing useful (TRDD-CEWVQ8DG, fixed in `904ddef4`); both were found in `.janitor/logs/`, not by reading code.

**A gate whose only input is an OPTIONAL tool is unreachable.** `should_clear_on_resume` requires `cache_expired is True`, and its only source was a probe of the agentlensPro CLI. Where that tool is absent the probe abstains, so the verdict was `why=cache state unknown — not clearing` and a whole fleet of cold resumes each paid a full cache-creation write on its first turn. The fix is not to relax the veto — `/clear` is unrecoverable — but to ANSWER THE SAME QUESTION with a measurement that needs no third party: elapsed time. Past `max(ttl, 60min)` no prompt cache survives, so the age IS the verdict. `cache_expired_by_age` returns **True or None, never False**: "not yet certainly dead" is not "alive", and a False would override a probe that said expired, re-creating the refusal being fixed. `resolve_cache_expired` consults the probe FIRST, so a warm probe still beats an ancient mtime and a live cache is never thrown away.


^ATOM-PKZU-XTVT [desc: "why next_fire_misses_cache and this floor gate use opposite TTL asymmetries despite reading the same elapsed time", keywords: next_fire_misses_cache_vs_this_gate opposite_TTL_asymmetries_same_elapsed_time why_5_min_vs_60_min_TTL why_does_a_cost_predictor_use_a_short_TTL why_does_a_destructive_gate_use_a_long_TTL two_clocks_reading_the_same_elapsed_time act_only_where_certainty_is_real err_toward_acting_vs_err_toward_certainty why_is_the_floor_its_own_constant why_are_the_two_asymmetries_opposite, type: reference, ocd: 2026-08-18, lmd: 2026-08-18]

The two clocks read the SAME elapsed time with OPPOSITE asymmetries, which is why the floor is its own constant: `next_fire_misses_cache` predicts a COST and uses the SHORT TTL (5 min) to err toward acting; this gate authorizes a DESTRUCTIVE act and uses the LONG one (60 min) to act only where certainty is real.


^ATOM-F9K2-BPPQ [desc: "a CLI in a plugin-cache bin dir is invisible to shutil.which in a hook child — verify a PATH-dependent fix under the environment that failed, not your shell", keywords: llm-ext_is_not_on_PATH handoff_degraded_to_the_template summary_permanent_not_retrying which_llm-ext_fails_in_a_hook verify_PATH_dependent_fix_under_env_-i why_is_a_plugin-bundled_CLI_invisible_to_shutil_which does_a_hook_child_inherit_the_interactive_profile_PATH how_do_I_reproduce_the_hook_child_environment string_sort_pins_the_oldest_install_forever what_does_llm_ext_data_dir_read, type: reference, ocd: 2026-08-18, lmd: 2026-08-18]

**A CLI that ships inside another plugin is invisible to `shutil.which` in a hook child.** llm-ext lives at `~/.claude/plugins/cache/<marketplace>/llm-externalizer/<version>/bin/llm-ext` — a dir the user's interactive PROFILE puts on PATH, which a hook-spawned detached child never inherits. So `summary: permanent — llm-ext is not on PATH; not retrying` fired on every cold resume and each handoff silently degraded to the link-only template. Resolve by the install's OWN layout (the convention `llm_ext_data_dir` already reads in reverse), PATH first so an operator keeps control, and order versions by PARSED NUMERIC TUPLE — as strings `"9.0.0"` sorts above `"13.5.1"` and would pin the oldest install forever.

**Verify a PATH-dependent fix under the environment that FAILED, not your shell**: `env -i HOME=$HOME PATH=/usr/bin:/bin <interpreter> -c '...'` reproduces the hook child. An interactive shell finds the binary and proves nothing.


^ATOM-V42V-4CJO [desc: "on 2026-08-18 the externalized compaction cleared a live session and left a REFUSAL in its handoff — the whole validation was 'out or None'", keywords: handoff_was_a_refusal compaction_cleared_my_session_and_the_handoff_was_useless model_refused_the_compaction exit_0_but_wrong_output llm-ext_returned_a_refusal the_model_declined_the_compaction_as_a_prompt_injection why_was_a_zero_exit_treated_as_success what_does_out_or_none_mean the_cold-cache_gate_opened_and_still_lost_the_session why_did_the_model_lecture_about_a_prompt_injection, type: project, ocd: 2026-08-18, lmd: 2026-08-18]

On 2026-08-18 the externalized compaction cleared a live session and left a REFUSAL in its
handoff. Every mechanical step was correct — cold-cache gate opened, the hook BLOCKED on the
watcher, the chain typed `/clear` — and the log said `summary: ok on attempt 1`. The model had
not summarised: it declined the compaction as a prompt injection and lectured about this plugin,
on exit 0 with non-empty stdout. The whole validation of the artifact that authorises destroying
a context was `out or None`.


^ATOM-3LYT-GMKT [desc: "the fix classifies a refusal as UNKNOWN with a constant detail and degrades to a link-only handoff; the match is anchored to the first line, not anywhere in the text", keywords: summary_ok_but_the_summary_was_garbage agent-handoff.md_contains_a_lecture looks_like_refusal_fix blockquote_not_stripped why_is_the_refusal_match_anchored_to_the_first_line does_a_leading_blockquote_count_as_a_refusal why_is_the_retry_detail_a_constant_string is_the_clear_ever_held_hostage_to_summary_quality what_does__looks_like_refusal_classify_as why_is_a_leading_blockquote_evidence_of_quoting, type: project, ocd: 2026-08-18, lmd: 2026-08-18]

**A zero exit says the CLI ran. It says nothing about whether the text is a summary.** The fix
(3.3.13, `_looks_like_refusal`) classifies a refusal as UNKNOWN with a CONSTANT detail — the
retry bound counts identical details, so prose in the detail would silently make it unbounded —
and the pre-existing degrade-to-template path then writes an honest link-only handoff and still
clears. The clear is never held hostage to summary quality; that was always the design.

The match is ANCHORED to the first line, NOT "anywhere in the first N chars": a legitimate
summary OF this incident opens by QUOTING the refusal. Blockquote `>` is deliberately not
stripped — a leading `>` is evidence of quoting, the opposite of refusing.


^ATOM-1EV0-XCON [desc: "3.3.14 added evidence capture on every failed attempt; blast radius measured 1/19 poisoned handoffs, upstream cause is llm-externalizer's driver.ts prompt wording", keywords: compaction_failed_could_not_be_answered_without_a_repro evidence_transcript_path_bytes_rc_elapsed blast_radius_poisoned_handoffs driver.ts_prompt_reads_as_injection why_was_stderr_dropped_on_every_zero_exit_path how_many_handoffs_were_poisoned_across_this_host what_evidence_does_each_compact_attempt_now_carry why_does_the_prompt_wording_read_as_a_prompt_injection how_do_I_repro_a_failed_compaction what_TRDD_records_the_blast_radius, type: project, ocd: 2026-08-18, lmd: 2026-08-18]

3.3.14 added the other half: until then stderr was read into a local and DROPPED on every
zero-exit path, and stdout was dropped on every non-OK path, so "the compaction failed" could
not be answered without a repro. Each attempt now carries `evidence` (transcript path + bytes,
rc, elapsed, both-ends excerpts of both streams), logged the moment it fails.

Blast radius measured across 19 project handoffs on this host: 1 poisoned. Full record:
TRDD-IFZQ98BA. The upstream half is llm-externalizer's `driver.ts:996-997` prompt, whose
"Your output REPLACES the transcript ... it is a handoff, not a report" reads as injection-shaped
to a safety-tuned model; that reword is theirs, and they have it.

## Superseded


^ATOM-MK02-SA6C [desc: "the handoff that authorised a destructive clear was never validated — 'summary: ok' only ever meant the process printed something", keywords: handoff_was_a_refusal compaction_cleared_my_session_and_the_handoff_was_useless summary_ok_but_the_summary_was_garbage model_refused_the_compaction agent-handoff.md_contains_a_lecture externalized_compaction_lost_my_work exit_0_but_wrong_output llm-ext_returned_a_refusal was_the_handoff_that_authorised_a_clear_ever_validated what_did_summary_ok_actually_mean, type: project, ocd: 2026-08-18, lmd: 2026-08-18, status: superseded, superseded-by: ATOM-V42V-4CJO]

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

^ATOM-KBU2-58YM [desc:"the cold-resume shrink refused on 'cache state unknown' and its handoff had no summary — a gate fed only by an OPTIONAL tool is unreachable, and a CLI in a plugin-cache bin dir is invisible to a hook ", keywords: cache_state_unknown_not_clearing cold_resume_did_not_shrink every_session_paid_a_full_cache_write_on_its_first_turn llm-ext_is_not_on_PATH handoff_degraded_to_the_template summary_permanent_not_retrying agentlensPro_absent_so_the_clear_never_fires which_llm-ext_fails_in_a_hook two_defects_found_in_janitor_logs_not_by_reading_code what_TRDD_fixed_the_cold-resume_shrink, type: reference, ocd: 2026-08-15, lmd: 2026-08-15, status: superseded, superseded-by: ATOM-L03E-L31N]

Two defects made the cold-resume shrink LOOK implemented while doing nothing useful (TRDD-CEWVQ8DG, fixed in `904ddef4`); both were found in `.janitor/logs/`, not by reading code.

**A gate whose only input is an OPTIONAL tool is unreachable.** `should_clear_on_resume` requires `cache_expired is True`, and its only source was a probe of the agentlensPro CLI. Where that tool is absent the probe abstains, so the verdict was `why=cache state unknown — not clearing` and a whole fleet of cold resumes each paid a full cache-creation write on its first turn. The fix is not to relax the veto — `/clear` is unrecoverable — but to ANSWER THE SAME QUESTION with a measurement that needs no third party: elapsed time. Past `max(ttl, 60min)` no prompt cache survives, so the age IS the verdict. `cache_expired_by_age` returns **True or None, never False**: "not yet certainly dead" is not "alive", and a False would override a probe that said expired, re-creating the refusal being fixed. `resolve_cache_expired` consults the probe FIRST, so a warm probe still beats an ancient mtime and a live cache is never thrown away.

The two clocks read the SAME elapsed time with OPPOSITE asymmetries, which is why the floor is its own constant: `next_fire_misses_cache` predicts a COST and uses the SHORT TTL (5 min) to err toward acting; this gate authorizes a DESTRUCTIVE act and uses the LONG one (60 min) to act only where certainty is real.

**A CLI that ships inside another plugin is invisible to `shutil.which` in a hook child.** llm-ext lives at `~/.claude/plugins/cache/<marketplace>/llm-externalizer/<version>/bin/llm-ext` — a dir the user's interactive PROFILE puts on PATH, which a hook-spawned detached child never inherits. So `summary: permanent — llm-ext is not on PATH; not retrying` fired on every cold resume and each handoff silently degraded to the link-only template. Resolve by the install's OWN layout (the convention `llm_ext_data_dir` already reads in reverse), PATH first so an operator keeps control, and order versions by PARSED NUMERIC TUPLE — as strings `"9.0.0"` sorts above `"13.5.1"` and would pin the oldest install forever.

**Verify a PATH-dependent fix under the environment that FAILED, not your shell**: `env -i HOME=$HOME PATH=/usr/bin:/bin <interpreter> -c '...'` reproduces the hook child. An interactive shell finds the binary and proves nothing.

## Governed by

- [[janitor-compaction-floor-gate]] — the hub overview this page is a detail sub-page of.

## Notes and lessons learned
