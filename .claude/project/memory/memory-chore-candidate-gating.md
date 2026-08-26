---
name: memory-chore-candidate-gating
description: "the consolidate chore spawned an agent that abstained / a memory chore burned 295k tokens to reject one candidate / should I add a similarity threshold to the librarian's aggregation clusters / the librarian keeps surfacing notes that only share keywords / is the consolidate false-positive rate worth fixing upstream / why is there a Jaccard gate on conflict but not consolidate / will the same rejected candidate be dispatched again / a memory chore dispatches an agent that abstains repeatedly / harvest re-fires on an unchanged corpus every cadence / 200k tokens burned to discover nothing was due / a marker never self-clears for a curated wiki page / is_curated_wiki_page misparsed flow-style frontmatter / a guard exists but does not suppress the re-dispatch / why did the precheck not fire when it should have / two parsers for one metadata format disagree with each other / should the janitor add a suppression gate for aggregation / a keyword-similarity gate cannot separate true from false merges"
ocd: 2026-08-02
lmd: 2026-08-02
metadata:
  node_type: memory
  type: project
  tier: component
---

# memory-chore-candidate-gating


^ATOM-BAJX-BGNF [desc:"MEASURED: a keyword-similarity gate cannot work for consolidate — the true and false classes overlap, so no threshold separates them", keywords: should_I_add_a_similarity_threshold_to_aggregation_clusters jaccard_gate_on_conflict_but_not_consolidate librarian_surfaces_notes_that_only_share_keywords tried_to_reuse_the_conflict_gate_for_consolidate a_keyword-similarity_gate_cannot_work_for_consolidate true_and_false_classes_overlap_no_threshold_separates_them measured_2026-08-02_on_190_notes_across_three_scopes a_0.15_gate_keeps_only_1_of_4_true_families a_threshold_destroys_genuine_merge_candidates_silently see_the_sibling_atom_for_why_the_statistic_differs debugging-methodology_scored_below_two_noise_clusters even_a_0.10_gate_keeps_only_2_of_4_true_families, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

**Do NOT port the conflict path's Jaccard gate to aggregation/consolidate.** It looks like
the obvious reuse — the conflict path already carries `_MIN_TOKEN_JACCARD = 0.15` for the
same-domain-is-not-same-subject problem — and it is measurably wrong.

Measured 2026-08-02 on the live corpus (190 notes across LOCAL/PROJECT/USER), median
pairwise Jaccard over name+description tokens:

| class | clusters | median-J |
|---|---|---|
| NEGATIVE — the 3 surfaced aggregation clusters, all judged false | `oauth+renew+rotator`, `daemon+janitor`, `same+twice` | 0.060 / 0.075 / 0.081 |
| POSITIVE — split page families (same subject BY CONSTRUCTION) | 4 families | 0.070 / 0.089 / 0.139 / 0.239 |

**The classes overlap.** `debugging-methodology` — a genuine family — scores **0.070**, BELOW
two of the three noise clusters. A 0.15 gate keeps 1 of 4 true families; even 0.10 keeps only
2 of 4. Every threshold that clears the noise destroys most genuine merge candidates, and it
destroys them SILENTLY (an un-surfaced candidate leaves no trace).

See the sibling atom for WHY the same statistic works on conflict and cannot work here.


^ATOM-TZAW-LB9U [desc:"the abstention cost is already bounded by the corpus-fingerprint gate, not by the refusal ledger — verify the gate before proposing any fix", keywords: a_memory_chore_burned_hundreds_of_k_tokens_to_abstain will_the_same_rejected_candidate_be_dispatched_again is_the_consolidate_false_positive_rate_worth_fixing consolidate_has_work_returned_false which_gate_stops_re_dispatch an_abstention_is_expensive_but_not_recurring bounded_by_the_corpus-fingerprint_gate_not_the_refusal_ledger cost_is_one-time_per_corpus_state_and_self-limiting the_refusal_ledger_only_covers_repair_and_conflict check_which_gate_bounds_a_wasteful_chore_before_fixing_it consolidate_writes_refusals_but_nothing_reads_them_back the_7-day_recheck_window_before_the_same_candidate_returns, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

**An abstention is expensive (~295k subagent tokens, measured) but it is NOT recurring**, and
the mechanism that bounds it is `consolidate_has_work`'s **corpus-fingerprint** gate, not the
per-candidate refusal ledger.

Verified on the live LOCAL scope right after one such abstention: the fingerprint stamped at
dispatch equals the fingerprint now, so `consolidate_has_work(...)` returns **False** — the
same candidate cannot be re-dispatched until the corpus actually changes, or the 7-day
recheck window expires. Cost is therefore one-time per corpus state, and self-limiting.

The refusal ledger is a DIFFERENT mechanism with a narrower reach: `memory_content_precheck`
calls `memory_refusals.is_refused` for **repair** and **conflict** only. Consolidate writes
refusals (they are useful provenance and the agent records them) but nothing reads them back —
by design, because the fingerprint already covers the re-dispatch case at whole-corpus
granularity.

So before "fixing" a chore that looks wasteful: check which gate is supposed to bound it and
whether that gate is firing. Here the answer was "it already is", and the only correct action
was to change nothing.


^ATOM-035X-O02P [desc:"why the same Jaccard statistic separates conflict PAIRS but not aggregation FAMILIES — same statistic, different population", keywords: why_does_the_jaccard_gate_work_on_conflict_but_not_consolidate pair_versus_cluster_similarity a_topic_family_has_low_internal_similarity_by_nature reusing_a_threshold_across_a_different_population conflict_judges_a_pair_aggregation_judges_a_topic_family a_threshold_is_calibrated_against_a_population_not_a_metric two_same-subject_pages_may_share_no_words_at_all why_the_same_statistic_separates_pairs_but_not_families true_duplicate_scored_0.286_against_noise_0.108 aggregation_members_are_supposed_to_differ_from_each_other its_docstring_had_already_reached_this_conclusion the_measurement_confirms_it_empirically, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

**Why the same statistic works on conflict and cannot work here.** Conflict judges a PAIR:
on the calibration corpus a true duplicate scored **0.286** against noise **≤0.108** — a
genuine separation, which is what `_MIN_TOKEN_JACCARD = 0.15` sits in.

Aggregation judges a k-note TOPIC FAMILY, whose members are *supposed* to differ from each
other — that is what makes them separate notes rather than one. Its internal similarity is
LOW by nature, so the same number applied to a different population inherits none of the
separation it was calibrated on.

The general form, worth carrying beyond this detector: **a threshold is calibrated against a
population, not against a metric.** Reusing it wherever the metric appears silently assumes
the two populations have the same shape, and here they demonstrably do not.

`consolidate_has_work`'s own docstring had already reached this conclusion from the skill
contract ("two same-subject pages may share no words at all"). The measurement in the sibling
atom confirms it empirically, so the next reader does not re-derive it by shipping the gate
and discovering the loss only when a real merge never surfaces.


^ATOM-83MU-YJHL [desc:"the abstaining-chore burn was not a missing gate — is_curated_wiki_page misparsed FLOW-STYLE metadata, so harvest saw every curated overview stub as RAW forever", keywords: memory_chore_dispatches_an_agent_that_abstains harvest_re-fires_on_an_unchanged_corpus 200k_tokens_to_discover_nothing_is_due marker_never_self-clears flow-style_metadata_frontmatter is_curated_wiki_page_returns_False_on_a_curated_page the_gate_was_fine_its_input_was_wrong scans_frontmatter_line-by-line_and_misses_keys_inside_braces nothing_can_ever_mirror_an_already-curated_page blast_radius_is_every_project_not_one_file when_a_guard_does_not_suppress_suspect_its_input_first fixed_2026-08-07_commit_4bbe7b3e, type: project, ocd: 2026-08-07, lmd: 2026-08-07]

**The gate was fine; its INPUT was wrong.** `atomize_has_work`/`harvest_has_work` shipped
2026-07-08 and are present in every cached version — so "add a suppression gate" was the wrong
diagnosis (I reached it myself before measuring, janitor#212).

`memory_scopes.is_curated_wiki_page` scans frontmatter LINE-BY-LINE and takes each line's key as
the text before the first `:`. For the flow-style line
`metadata: {node_type: memory, type: overview, tier: hub}` that key is `metadata` — the
wikimem-only keys `node_type`/`tier` sit INSIDE the braces on the same line and are never seen.
The discriminator therefore calls an already-curated page RAW, `harvest_has_work` treats it as an
un-mirrored buffer note, and **nothing can ever "mirror" an already-curated page** — so the
marker never self-clears and re-dispatches a ~200k-token agent forever.

Blast radius is every project, not one file: that flow-style shape is exactly what SessionStart
writes for each freshly-bootstrapped scope's `*-overview.md` stub (confirmed on 5+ LOCAL scopes).

Fixed 2026-08-07 (`4bbe7b3e`) by also checking for a wikimem-only key inside a
`metadata: {...}` flow value. Verified both directions: `True` on the real reported file,
still `False` for `metadata: {type: feedback}`. [^1]

## Notes and lessons learned

[^1]: [id:ATOM-6RC1-5FNB, status:valid, desc:"when a guard does not suppress, suspect its INPUT before concluding the guard is missing", keywords:"the_gate_exists_but_does_not_suppress I_concluded_a_guard_was_missing two_parsers_for_one_format discriminator_returns_the_wrong_answer why_did_the_precheck_not_fire", ocd:2026-08-07, lmd:2026-08-07] DO NOT conclude that a guard is MISSING because it failed to suppress, BECAUSE a guard that runs correctly on a wrong ANSWER from its discriminator is indistinguishable from an absent guard at the symptom level — here the suppression gates had shipped a month earlier and the real fault was one line of frontmatter parsing upstream of them. DO establish what the guard's inputs actually evaluate to on the real data BEFORE proposing to add or widen the guard; had the fix followed the first diagnosis, a second redundant gate would have shipped on top of a still-broken discriminator. Corroborating signal for this class: `memory_edit_verify.parse_frontmatter` already parsed flow-style correctly, so TWO parsers for one format disagreed — when a format is parsed in more than one place, a bug in the smaller, dependency-free copy is the likelier fault than a missing feature in the caller.
