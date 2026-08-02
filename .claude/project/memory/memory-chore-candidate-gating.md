---
name: memory-chore-candidate-gating
description: "the consolidate chore spawned an agent that abstained / a memory chore burned 295k tokens to reject one candidate / should I add a similarity threshold to the librarian's aggregation clusters / the librarian keeps surfacing notes that only share keywords / is the consolidate false-positive rate worth fixing upstream / why is there a Jaccard gate on conflict but not consolidate / will the same rejected candidate be dispatched again"
ocd: 2026-08-02
lmd: 2026-08-02
metadata:
  node_type: memory
  type: project
  tier: component
---

# memory-chore-candidate-gating


^ATOM-BAJX-BGNF [desc:"MEASURED: a keyword-similarity gate cannot work for consolidate — the true and false classes overlap, so no threshold separates them", keywords: should_I_add_a_similarity_threshold_to_aggregation_clusters jaccard_gate_on_conflict_but_not_consolidate librarian_surfaces_notes_that_only_share_keywords tried_to_reuse_the_conflict_gate_for_consolidate, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

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


^ATOM-TZAW-LB9U [desc:"the abstention cost is already bounded by the corpus-fingerprint gate, not by the refusal ledger — verify the gate before proposing any fix", keywords: a_memory_chore_burned_hundreds_of_k_tokens_to_abstain will_the_same_rejected_candidate_be_dispatched_again is_the_consolidate_false_positive_rate_worth_fixing consolidate_has_work_returned_false which_gate_stops_re_dispatch, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

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


^ATOM-035X-O02P [desc:"why the same Jaccard statistic separates conflict PAIRS but not aggregation FAMILIES — same statistic, different population", keywords: why_does_the_jaccard_gate_work_on_conflict_but_not_consolidate pair_versus_cluster_similarity a_topic_family_has_low_internal_similarity_by_nature reusing_a_threshold_across_a_different_population, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

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

## Notes and lessons learned
