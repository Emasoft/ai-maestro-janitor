---
name: janitor-detector-and-hook-roster-findings
description: "how good are the scan_text rules / does agent-context-integrity actually catch poisoning / measuring a security detector's coverage / detector recall unknown / why did this rule score zero on its own class / detector flagged my security policy / false positive on prohibition text / widening a security regex without false positives / gitignore-coverage named a tracked templates dir as contamination / why does project-map-drift do nothing in this repo / the CLAUDE.md slim-contract nudge never fires / a detector emitted nothing and I read that as clean / an opt-in flag silently disabled an unrelated check / can a poisoned CLAUDE.md attack me without running anything / snake_case defeats word boundary / nested paren defeats negated character class / how to widen a detector regex safely / do not tune a pattern against the samples that exposed it"
ocd: 2026-08-02
lmd: 2026-09-05
metadata:
  node_type: memory
  type: reference
  tier: hub
  functionality: detector-and-hook-roster
publish-globally: false
split-lineage: c4529390a94648e49f74f86799cd937b
---

# janitor-detector-and-hook-roster-findings

Measured detector-effectiveness findings — coverage/false-positive rates,
recurring rule-matching failure shapes, and specific detector bug write-ups —
gathered while auditing the roster on [[janitor-detector-and-hook-roster-list]].


^ATOM-NARU-DPF4 [desc: "agent-context-integrity's scan_text rules measured at ~28% recall on 87 blind-authored samples across 10 of 21 claimed classes", keywords: does_agent-context-integrity_actually_catch_poisoning detector_recall_unknown how_good_are_the_scan_text_rules 28_percent_recall_measured_2026-08-12 87_blind-authored_samples_10_of_21_classes seven_in_ten_poisoned_files_produce_no_finding best_single_class_reaches_56_percent scripts_agent_context_bench.py janitor#226_measured_coverage poisoned_CLAUDE.md_not_detected commit_c06a44b9 how_good_is_agent-context-integrity_really is_the_poisoning_detector_actually_effective, type: project, ocd: 2026-08-18, lmd: 2026-08-18]

The `agent_config_patterns.scan_text` rules that guard auto-loaded context files were never
measured until 2026-08-12; the answer is **~28% recall** (any rule firing) on 87 blind-authored
samples across 10 of the 21 claimed classes — so roughly seven in ten realistic poisoned files
produce NO finding, and the best single class reaches 56%. Bench: `scripts/agent_context_bench.py`,
corpus + baseline under `tests/agent_context_bench/` (janitor#226, commit `c06a44b9`).


^ATOM-7B1B-RX8T [desc: "the corpus was authored BLIND so the measurement is meaningful; two recurring failure shapes are closed verb enumeration and rigid literal adjacency", keywords: measuring_a_security_detector's_coverage blind_corpus_red_team closed_verb_enumeration rigid_adjacency_to_a_literal domain_blocklist_cannot_catch_a_novel_domain corpus_authored_blind_by_intent_only a_corpus_derived_from_the_patterns_scores_near_100_percent concealment-directive_misses_report_omit_suppress verb_next_to_the_user_evaded_by_ordinary_prose exfil-webhook-sink_cannot_catch_a_novel_domain why_is_the_bench_measurement_meaningful two_recurring_failure_shapes_in_the_rules a_scope_limit_no_tuning_fixes, type: project, ocd: 2026-08-18, lmd: 2026-08-18]

The measurement is only meaningful because the corpus was authored BLIND — an external model got
the attack classes BY INTENT ONLY and never saw the regexes; a corpus derived from the patterns
measures the author's consistency with themselves and scores near 100%. Two failure shapes are
concrete and recurring in these rules: a CLOSED VERB ENUMERATION (`concealment-directive` knows
`tell/inform/notify/mention/show` but not `report`/`omit`/`suppress`), and RIGID ADJACENCY to a
literal (it wants the verb next to `the user`, so "do not mention this in any output visible to
the user" evades it by ~45 characters of ordinary prose). A domain BLOCKLIST like
`exfil-webhook-sink` cannot catch a novel domain at all, which is a scope limit no tuning fixes —
say so in the docs rather than shipping a rule that gestures at the broader class.


^ATOM-PRUF-Y44L [desc: "never tune a pattern against the samples that exposed it — use the dev/holdout split; see janitor-findings-pipeline for where findings land", keywords: do_not_tune_against_the_samples_that_exposed_it split_of_dev_holdout never_tune_a_pattern_against_the_samples_that_exposed_it converts_recall_from_generalisation_into_fit split_of()_splits_the_corpus_dev_holdout where_do_these_findings_land see_janitor-findings-pipeline_for_the_findings_route dev_holdout_split_prevents_overfitting_a_regex a_pattern_that_passes_its_own_exposure_sample_is_not_fixed do_not_tune_a_pattern_against_the_samples_that_exposed_it how_to_validate_a_security_pattern_fix generalisation_vs_fit_when_tuning_a_regex, type: project, ocd: 2026-08-18, lmd: 2026-08-18]

Do NOT tune a pattern against the samples that exposed it: that converts recall from
generalisation into fit. `split_of()` splits the corpus dev/holdout for exactly this.
See [[janitor-findings-pipeline]] for where these findings land.


^ATOM-TV6I-CCIO [desc: "agent-context-integrity false-positives at 19% — all three cases are a doc describing an attack in order to prohibit, narrate, or fixture it", keywords: detector_flagged_my_security_policy false_positive_on_prohibition_text agent-context-integrity_fires_on_a_doc_describing_an_attack post-mortem_flagged_as_injection test_fixture_flagged_as_poisoning 19_percent_false_positive_rate_measured_2026-08-12 3_of_16_blind-authored_benign_controls prompt-injection-multilingual_fired_on_a_security_policy sensitive-secret-ref_fired_on_an_incident_post-mortem janitor#167_FP_hardening_did_not_cover_prose_about_the_attack janitor#254_tracks_the_FP_half why_did_the_security_scanner_flag_my_document, type: project, ocd: 2026-08-18, lmd: 2026-08-18]

Measured 2026-08-12 alongside the recall figure: `scan_text`'s false-positive rate is **19%**
(3 of 16 blind-authored benign controls), and all three are the SAME shape — a file that
describes an attack in order to prohibit, narrate, or fixture it. Concretely: a security policy
documenting prompt injection fired `prompt-injection-multilingual`; an incident post-mortem
fired `sensitive-secret-ref`; a clearly-labelled test fixture fired
`prompt-injection-multilingual`. janitor#167 landed FP hardening for prohibition text and
negation context, so whatever that covers, it does NOT cover prose ABOUT the attack, past-tense
narrative, or a file that declares itself a fixture. Tracked in janitor#254 (FP half) — kept out
of janitor#226 by that issue's own scope rule (coverage only).


^ATOM-4SNY-SOW4 [desc: "paired with ~28% recall, the FP channel flags the docs that warn about attacks; gate on whether the string is an object of discussion, not an imperative", keywords: why_this_matters_more_than_ordinary_noise self_referential_security_docs discriminating_feature_object_of_discussion_vs_imperative low_recall_paired_with_flagging_the_docs_that_warn_about_attacks reader_learns_to_dismiss_the_one_guarding_channel this_repos_own_security_docs_trip_the_detector gate_on_object_of_discussion_not_imperative document-level_frame_cheaper_than_per-line_negation this_document_describes_we_observed_example_fixture why_does_low_recall_matter_more_than_ordinary_noise a_channel_that_flags_the_docs_warning_about_it own_security_docs_trip_the_own_detector, type: project, ocd: 2026-08-18, lmd: 2026-08-18]

**Why this matters more than ordinary noise:** paired with ~28% recall it means the channel
misses most real attacks while flagging the documentation that warns about them, which is how a
reader learns to dismiss the one channel guarding auto-loaded context. It is self-referential —
THIS repo's own security docs trip it, as would any project that documents these attack classes.
The discriminating feature to gate on is that the attack string appears as the OBJECT OF
DISCUSSION ("this document describes", "we observed", "example", "fixture"), not as an imperative
addressed to the agent; a document-level frame is a cheaper signal than per-line negation.


^ATOM-Z18Y-WQ7U [desc: "do not tune against the three FP samples alone — that fixes the samples, not the class; use the bench's dev/holdout split", keywords: do_not_tune_against_those_three_samples_alone use_the_bench_dev_holdout_split fixing_the_samples_is_not_fixing_the_class tuning_a_false-positive_fix_to_three_examples_only overfitting_a_detector_to_its_own_test_cases regression_test_the_FP_samples_but_generalise_the_fix bench's_dev_holdout_split_for_FP_hardening_too narrow_fix_that_only_covers_the_reported_cases should_I_fix_only_the_three_reported_samples generalise_a_false-positive_fix_beyond_its_report avoid_overfitting_a_detector_patch when_narrowing_a_security_regex_use_the_holdout_split, type: project, ocd: 2026-08-18, lmd: 2026-08-18]

Do NOT tune against those three samples alone — that fixes the samples, not the class; use the
bench's dev/holdout split.


^ATOM-9E4P-KYW5 [desc: "5 claimed rules scored 0 out-of-sample for ONE reason — each enumerated its attack's CANONICAL PHRASING and the corpus used a variant", keywords: detector_rule_scores_zero_on_its_own_class claimed_rule_reads_as_coverage closed_canonical_phrasing_enumeration eleven_languages_of_one_sentence rule_searched_the_wrong_field five_claimed_rules_scored_zero_out-of-sample concealment-directive_missed_concealment_from_the_record mcp-annotation-lying_searched_the_innocuous_field two-step-code-injection_missed_the_shell_pipeline_form silent-FN_asymmetry_a_bench_exists_to_expose why_did_this_rule_score_zero_on_its_own_class check_the_rules_object_and_field_not_just_its_technique, ocd: 2026-08-21, lmd: 2026-08-21]

Measured 2026-08-21 (TRDD-VAWIKRK2) on a second blind corpus: five rules the coverage report
showed as claimed matched ZERO of their own class. Same root cause each time — the rule
enumerated the CANONICAL PHRASING of its attack, and real attacks vary the OBJECT, the FIELD, or
the SYNTAX. Not one was missing a language, a host, or a technique.

`concealment-directive` matched concealment from "the user"; every attack concealed from the
RECORD (audit trail, logs, changelog, commit message). `prompt-injection-multilingual` covered
the canonical disregard-the-prior-prompt opener in ELEVEN languages; every attack kept the verb
and swapped the object for a security control — eleven languages of ONE sentence is far
narrower than it reads on a report. `mcp-annotation-lying` searched `name` for the destructive verb the attacker had
deliberately put in `handler`, i.e. it searched the innocuous half by construction.
`two-step-code-injection` knew `atob`/`Buffer.from` → `eval` while every sample used the shell
pipeline that pipes `base64 -d` straight into `bash`, which is also the commoner form in the wild.

This is the silent-FN asymmetry a bench exists to expose: a declared blind spot is honest, while
a claimed rule scoring 0 reads as coverage on every report. Check what a rule's OBJECT and FIELD
are, not just whether its technique is listed.


^ATOM-PJ03-3B29 [desc: "Across ~10 detector changes every false positive came from adding VOCABULARY; not one came from fixing a BOUNDARY, FIELD or POSITION", keywords: widening_a_security_regex_without_false_positives vocabulary_costs_FP_structure_does_not measured_refusal_pin_it_as_a_test secret_interpolation_in_docs_is_not_exfiltration every_false_positive_came_from_adding_vocabulary reach_for_boundary_field_position_first env_vars_widening_caused_FP_on_changelogs token_interpolation_widening_caused_FP_on_official_docs pin_every_refusal_as_a_negative_test how_to_widen_a_detector_regex_safely a_refusal_nobody_pinned_gets_re-proposed structural_fixes_measured_zero_new_firings, ocd: 2026-08-21, lmd: 2026-08-21]

The reusable design rule from TRDD-VAWIKRK2's widening pass. Across ~10 changes to
`agent_config_patterns`, EVERY false positive came from adding VOCABULARY; not one came from
fixing a BOUNDARY, a FIELD, or a POSITION. Four vocabulary widenings were implemented, measured
against ~12.6k real agent-context files, and reverted: `env_vars` (+5 FP on ordinary
CHANGELOGs), a `${…TOKEN}` interpolation (+18 FP on OFFICIAL plugin docs — a secret
interpolation is what correct documentation SHOWS you), a prose read-only claim fed to an
existing 800-char window (+33), and an unbounded self-contradiction span (+33 — two words in one
long paragraph are not a contradiction). Every structural fix measured 0 new firings.

So: reach for boundary/field/position first, and treat a proposed new WORD as the expensive
option that must be measured before it ships. PIN every refusal as a negative test — a refusal
nobody pinned gets re-proposed by the next reader who has the same idea. See [[ATOM-9E4P-KYW5]]
for why the rules were narrow in the first place.


^ATOM-5DFW-DLSZ [desc: "Two detector misses were MATCHING MECHANICS, not vocabulary — a word boundary cannot see inside snake_case, and a negated-paren class stops at a NESTED paren", keywords: snake_case_defeats_word_boundary nested_paren_defeats_negated_character_class regex_misses_the_shape_it_was_written_for mis-filed_as_a_threshold_problem word_boundary_b_cannot_see_inside_snake_case user_credentials_never_matches_bcredentialsb bracket_class_stops_at_the_first_nested_paren shell_true_never_reached_because_of_a_nested_paren fix_with_a_lazy_same-line_bound_not_balanced_paren mis-filed_as_a_base64_length_threshold_problem why_did_the_regex_miss_a_shape_it_was_written_for balanced_paren_constructs_backtrack_badly, ocd: 2026-08-21, lmd: 2026-08-21]

Two `agent_config_patterns` misses (TRDD-VAWIKRK2) were matching mechanics rather than
vocabulary, and both are worth recognising by shape because each was mis-filed as something
else and the mis-filing pointed at a more dangerous fix.

`\b` CANNOT see inside a snake_case compound: `_` is a word character, so `\bcredentials\b`
never matches `user_credentials` and `\bsession_token\b` never matches `session_tokens`. A rule
that reads agent CONFIG has to be able to read config SPELLING — snake_case is the convention an
attacker writing a config file will use, so requiring the bare word requires the one spelling
they will not write. Fix with `(?<![A-Za-z])` / `(?![A-Za-z])`, which lets `_` and `-` separate
while still refusing a letter-glued substring.

`[^)]*` stops at the FIRST `)`. In `subprocess.run(base64.b64decode('c2g=').decode(),
shell=True)` that is the NESTED one, so `shell=True` was never reached and the most dangerous
form in the class was precisely the one that escaped. It had been filed as "base64 literal under
the 40-char floor", which would have sent the next reader at an unmeasured threshold knob that
was never the cause. Fix with a lazy same-line bound, NOT a balanced-paren construct — those
backtrack badly on adversarial input. [^5]


^ATOM-4O7Z-D790 [desc: "project-map-drift serves TWO independent contracts and only ONE of them is behind the repo-map opt-in — the slim-contract nudge must run first, unconditionally", keywords: the_CLAUDE.md_slim-contract_nudge_never_fires project-map-drift_does_nothing_in_this_repo wikimem_index_check_skipped no_repo_map_so_no_CLAUDE.md_check_at_all repomap-opt-in_flag_gates_more_than_the_map a_detector_emitted_nothing_and_I_read_that_as_clean an_opt-in_flag_silently_disabled_an_unrelated_check two_independent_contracts_share_one_early-return slim-contract_nudge_must_run_unconditionally_first read_fence_header_only_ever_reads_the_map_fence why_does_project-map-drift_do_nothing_here two_different_fence_markers_map_vs_wikimem-index, ocd: 2026-08-22, lmd: 2026-08-22]

`project-map-drift.py` carries TWO unrelated duties against CLAUDE.md, and confusing them made the second one dead code for every map-less project. (1) The REPO-MAP digest check — genuinely opt-in, gated on `$PROJECT/.janitor/state/repomap-opt-in.flag`, reading the `JANITOR-REPO-MAP-*` fence via `repomap.markers.read_fence_header`. (2) The SLIM-CONTRACT nudge (`_slim_contract_nudge`) — which polices CLAUDE.md's canonical shape and the wikimem index, and is owed to EVERY project whether or not it opted into a map. Until 2026-08-22 (TRDD-LFSWY0C6) duty 2 sat below duty 1's early-return, so a repo with a wikimem-index fence, zero map fences and no opt-in flag — this one — received no check at all, silently. The nudge now runs at the top of `main`, before both the flag test and `read_fence_header`. The two fences are DIFFERENT markers: `read_fence_header` only ever reads the map fence, so a wikimem-index fence can never satisfy it. [^6]


^ATOM-HM4C-18YQ [desc: "gitignore-coverage named a tracked templates/reports/ dir as contamination — why the class matcher anchors reports/ *_dev/ .trashcan/ at the root, and how to measure a matcher change on the fleet", keywords: detector_names_tracked-on-purpose_files templates/reports_flagged_as_contamination git_rm_--cached_advised_for_a_template gitignore-coverage_false_positive class_matcher_precision nested_reports_dir root-anchored_pattern_leading_slash fleet_sweep_before_shipping_a_detector still_TRACKED_wrong_file scripts_dev_tracked, trdd: TRDD-6WM4BFKF, ocd: 2026-09-02, lmd: 2026-09-02]
gitignore-coverage's class matcher (lib/gitignore_coverage.matches_private_class) root-anchors /reports/, /*_dev/ and /.trashcan/ — a leading slash has git's meaning, only the FIRST directory component may match — while .venv/ and node_modules/ match at any depth. Before 10faea1e an unanchored reports/ named a skill's tracked skills/<x>/templates/reports/*.md in another fleet repo as contamination every hour with git rm --cached as the remedy. The precision of a matcher widening is measured, never argued: run the detector read-only over every janitor-managed repo (CLAUDE_PROJECT_DIR=<repo> uv run --script --quiet scripts/detectors/gitignore-coverage.py) and attribute each offender to class-match vs ignore-rule before shipping. The 2026-09-02 sweep: 85 offenders — 34 real class hits, 4 false, 47 from the rule branch that duplicate tracked-ignored (TRDD-IEAZQ9MK).



^ATOM-NBGE-HWP7 [desc:"a CLAUDE.md that arrives already poisoned needs no execution at all — three deliberate convention breaks in agent-context-integrity follow from that", keywords: can_a_poisoned_CLAUDE.md_attack_me_without_running_anything is_a_gitignored_CLAUDE.md_safe why_does_this_detector_report_on_the_very_first_run injection_arrived_via_a_merged_PR_or_a_clone agent_context_poisoning_vector three_ways_agent_context_gets_poisoned no_silent_first-fire_baseline_for_this_detector no_gitignore_filter_the_documented_exception_to_janitor#99 what_does_the_agent_LOAD_vs_what_does_the_repo_SHIP every_emitted_byte_is_sanitized_before_stdout can_a_context_file_attack_without_any_execution what_covers_a_CLAUDE.md_that_arrives_already_poisoned, ocd: 2026-08-04, lmd: 2026-08-04]

Agent context is poisoned three ways: a dependency postinstall WRITES `CLAUDE.md` (caught by `ai-context-poisoning`), an MCP response carries a hostile payload (caught by `post-mcp-response-sanitizer`), or the context file ARRIVES ALREADY POISONED via a clone, a pull, or a merged PR. The third was the unwatched one and is the cheapest: it needs NO EXECUTION — no install script, no server, no command — because `CLAUDE.md` is read into every session automatically, so the hostile line is ACTED ON before any detector could report it. `agent-context-integrity` (janitor#167) covers it. Three deliberate convention breaks follow from that vector, each of which looks like a bug until you see why: (1) NO silent first-fire baseline, unlike every other watcher here — a file poisoned BEFORE the janitor arrived is still poisoned, so adopting current state as clean is the silent-disable shape; content-hash dedupe stops the nagging instead. (2) NO gitignore filter, the documented exception to janitor#99 — that rule asks "what does the repo SHIP?", this one asks "what does the agent LOAD?", and a gitignored `CLAUDE.md` is still auto-loaded. (3) EVERY emitted byte is sanitized, because this detector quotes attacker-controlled text into heartbeat stdout, where the model reads lines as instructions — a poisoned file containing a bare marker must arrive defanged. See [[janitor-findings-pipeline]] for where its findings land.



## Superseded


^ATOM-T1UU-0DNF [desc:"agent-context-integrity false-positives at 19% and every case is a doc DESCRIBING an attack to prohibit it — measured 2026-08-12, tracked in janitor#254", keywords: detector_flagged_my_security_policy false_positive_on_prohibition_text agent-context-integrity_fires_on_a_doc_describing_an_attack post-mortem_flagged_as_injection test_fixture_flagged_as_poisoning superseded_by_the_2026-08-18_atom old_measurement_of_the_19_percent_FP_rate stale_snapshot_kept_for_the_supersession_chain do_not_treat_this_as_the_current_figure see_the_non-superseded_atom_for_the_live_number archived_snapshot_not_the_current_FP_rate historical_record_of_the_first_FP_measurement, type: project, ocd: 2026-08-12, lmd: 2026-08-12, status: superseded, superseded-by: ATOM-TV6I-CCIO]

Measured 2026-08-12 alongside the recall figure: `scan_text`'s false-positive rate is **19%**
(3 of 16 blind-authored benign controls), and all three are the SAME shape — a file that
describes an attack in order to prohibit, narrate, or fixture it. Concretely: a security policy
documenting prompt injection fired `prompt-injection-multilingual`; an incident post-mortem
fired `sensitive-secret-ref`; a clearly-labelled test fixture fired
`prompt-injection-multilingual`. janitor#167 landed FP hardening for prohibition text and
negation context, so whatever that covers, it does NOT cover prose ABOUT the attack, past-tense
narrative, or a file that declares itself a fixture. Tracked in janitor#254 (FP half) — kept out
of janitor#226 by that issue's own scope rule (coverage only).
**Why this matters more than ordinary noise:** paired with ~28% recall it means the channel
misses most real attacks while flagging the documentation that warns about them, which is how a
reader learns to dismiss the one channel guarding auto-loaded context. It is self-referential —
THIS repo's own security docs trip it, as would any project that documents these attack classes.
The discriminating feature to gate on is that the attack string appears as the OBJECT OF
DISCUSSION ("this document describes", "we observed", "example", "fixture"), not as an imperative
addressed to the agent; a document-level frame is a cheaper signal than per-line negation.
Do NOT tune against those three samples alone — that fixes the samples, not the class; use the
bench's dev/holdout split.

^ATOM-8ANO-T80F [desc:"agent-context-integrity's 21 rules catch ~28% of realistic poisoned context files — measured 2026-08-12 against a blind corpus, not assumed", keywords: does_agent-context-integrity_actually_catch_poisoning detector_recall_unknown how_good_are_the_scan_text_rules measuring_a_security_detector's_coverage blind_corpus_red_team poisoned_CLAUDE.md_not_detected superseded_by_the_2026-08-18_recall_atom old_21-rules_recall_measurement stale_snapshot_kept_for_the_supersession_chain do_not_treat_this_as_the_current_figure see_the_non-superseded_atom_for_the_live_number archived_snapshot_not_the_current_recall_figure, type: project, ocd: 2026-08-12, lmd: 2026-08-12, status: superseded, superseded-by: ATOM-NARU-DPF4]

The `agent_config_patterns.scan_text` rules that guard auto-loaded context files were never
measured until 2026-08-12; the answer is **~28% recall** (any rule firing) on 87 blind-authored
samples across 10 of the 21 claimed classes — so roughly seven in ten realistic poisoned files
produce NO finding, and the best single class reaches 56%. Bench: `scripts/agent_context_bench.py`,
corpus + baseline under `tests/agent_context_bench/` (janitor#226, commit `c06a44b9`).
The measurement is only meaningful because the corpus was authored BLIND — an external model got
the attack classes BY INTENT ONLY and never saw the regexes; a corpus derived from the patterns
measures the author's consistency with themselves and scores near 100%. Two failure shapes are
concrete and recurring in these rules: a CLOSED VERB ENUMERATION (`concealment-directive` knows
`tell/inform/notify/mention/show` but not `report`/`omit`/`suppress`), and RIGID ADJACENCY to a
literal (it wants the verb next to `the user`, so "do not mention this in any output visible to
the user" evades it by ~45 characters of ordinary prose). A domain BLOCKLIST like
`exfil-webhook-sink` cannot catch a novel domain at all, which is a scope limit no tuning fixes —
say so in the docs rather than shipping a rule that gestures at the broader class.
Do NOT tune a pattern against the samples that exposed it: that converts recall from
generalisation into fit. `split_of()` splits the corpus dev/holdout for exactly this.
See [[janitor-findings-pipeline]] for where these findings land.

## Governed by

- [[janitor-detector-and-hook-roster]] — the overview this page is a part of.

## Notes and lessons learned

[^5]: [id: ATOM-QLN0-QZPS, status: valid, keywords: "memgrep_lint_footnote-dangling-ref regex_fragment_in_a_memory_description caret_bracket_reads_as_a_footnote", ocd: 2026-08-21, lmd: 2026-08-21] DO NOT put a bare regex fragment containing `[^...]` in an atom's `desc:` or in any prose outside a code span, BECAUSE markdown reads `[^)]` as a FOOTNOTE REFERENCE and `memgrep lint` correctly reports `footnote-dangling-ref` at ERROR — which blocks the page on a rule that is doing its job. The body is safe only because the fragments there are inside backticks; the `desc:` field is not a place where backticks help. DO describe the construct in words in the desc ("a negated-paren class stops at a nested paren") and keep the literal regex in the backticked body instead.
[^6]: [id: ATOM-58SL-OBUT, status: valid, keywords: "a_detector_produced_no_findings_and_I_assumed_the_project_was_clean an_opt-in_flag_silently_disabled_an_unrelated_check a_check_that_serves_two_features_sat_behind_one_feature's_flag feature_flag_suppressed_more_than_its_own_feature", ocd: 2026-08-22, lmd: 2026-08-22] DO NOT let one feature's opt-in flag stand above a check that serves a DIFFERENT contract, BECAUSE the unrelated check then dies silently for every project that never opted into the first feature — and a detector emitting nothing is indistinguishable from a project with nothing wrong, so the gap survives until someone reads the control flow (measured 2026-08-22 on `project-map-drift.py`: the CLAUDE.md slim-contract nudge was unreachable in this very repo). DO order the unconditional duties FIRST, above every early-return, and when adding a flag ask which of the callees below it are actually part of the feature being gated.
