---
name: review-fork-gate-which-turns-need-a-fork
description: "should I spawn a review fork for this turn / which turns need a review fork / which turns get no review fork / can I decline the review fork gate / the gate fires on a turn that changed nothing executable / does a docs-only commit need a review fork / does a timestamp or frontmatter bump need a review fork / is a prose-only turn exempt from review / what counts as characterising what evidence establishes / clause (c) of the fork rule / how small is the exemption from the review fork rule / I cannot name which of a b or c fires / commit after the review fork re-arms the gate / a fork that says STOP is scoped to its subject / findings shrink in scope not materiality / fork rule first version was unsound / checkable reason to decline a review fork / the review-fork gate fires on every turn / should I spawn a fork for a docs-only commit / when is a review fork worth it / prose-only turn still triggered the gate / how do I stop reviewing my own prose / the gate blocks my turn and I have nothing to review / should I fork after every commit / is a card closure worth a review fork / the rule as first written was unsafe and is corrected"
ocd: 2026-11-16
lmd: 2026-11-16
metadata:
  node_type: memory
  type: feedback
  tier: component
publish-globally: true
---

# review-fork-gate-which-turns-need-a-fork


^ATOM-0GLJ-EK3A [desc: "Fork when the turn changed EXECUTABLE BEHAVIOUR, asserted a VERDICT, or CHARACTERISED WHAT EVIDENCE ESTABLISHES — clause (c) is load-bearing; the first version omitted it and the rule was unsound.", keywords: should_I_spawn_a_fork_for_a_docs-only_commit when_is_a_review_fork_worth_it prose-only_turn_triggered_the_gate review-fork_gate_fires_on_every_turn is_a_card_closure_worth_a_fork how_to_decline_the_review_gate_honestly what_counts_as_executable_behaviour what_counts_as_a_verdict what_counts_as_evidence_characterisation clause_c_load_bearing_evidence_claims spawn_criterion_three_clauses review_fork_spawn_rule, ocd: 2026-09-05, lmd: 2026-09-28]

**SPAWN a review fork when the turn (a) changed EXECUTABLE BEHAVIOUR — code, a test, a script, a
config the machine reads; (b) asserted a VERDICT — closing a card, claiming a fix works, a rules
interpretation, a memory write; or (c) CHARACTERISED WHAT EVIDENCE ESTABLISHES — "this shows X",
"this bounds Y", "this was measured", a withdrawal, a restatement of what a result means.**
Only a turn that is none of those gets a re-read instead.

**⚠ CLAUSE (c) IS LOAD-BEARING AND THE FIRST VERSION OF THIS ATOM OMITTED IT — the rule was
unsound, and its own session refutes it.** Written with (a)+(b) only, it would have suppressed the
two forks that caught the worst late errors of the session that produced it. Both commits changed
no code, closed no card and interpreted no rule; both were things I had re-read and was satisfied
with:
- a "negative result" from 30 green runs that **tested nothing** — the hypothesis predicts
  leftover state from a FAILING run, and every run passed;
- a **polarity inversion** (leakage confounds a RED result, not a green one) plus the wrong
  statistical assumption named (independence, when the failure is identical-distribution).
A third caught a memory atom citing **another agent's measurement of a different operation** as
evidence for mine. **A claim about what evidence shows is not a "verdict" by the (b) definition,
and it is exactly where the errors were.** The rule caught decisions and missed inferences.


^ATOM-J2L0-SMXK [desc: "Operating the spawn rule in practice: findings shrink in scope not materiality; the gate fires even on exempt turns — decline in one line; a fork's STOP is scoped; commit first, fork last.", keywords: stopping_criterion_for_review_forks the_adversarial_review_loop_is_eating_the_session forks_finding_smaller_and_smaller_things diminishing_returns_on_adversarial_review gate_blocks_the_turn_with_nothing_to_review review-supervisor_says_changes_unreviewed review_gate_fires_again_after_commit commit_then_review_order gate_fires_on_genuinely_exempt_turns fork_says_stop_is_a_finding rescope_after_a_stop_finding git_diff_check_for_executable_changes, ocd: 2026-09-28, lmd: 2026-09-28]


**The honest cost curve:** findings shrank in SCOPE but not reliably in MATERIALITY, and the ones
that stayed material were about evidence claims. That is the shape to prune by — not "early forks
good, late forks prose".

**The gate keeps firing on turns that are genuinely none of (a)-(c);** it is a Stop hook and
cannot tell. Say so in one line and do not spawn. Checkable start:
`git diff --name-only HEAD~1 HEAD | grep -v '\.md$'` — non-empty ⇒ (a). It does not decide (b)
or (c); read the diff for those.

**A fork that says STOP is a finding — act on it, SCOPED TO WHAT THAT FORK WAS REVIEWING.** "Stop
reviewing this card's prose" is not "stop reviewing". Do the fixes it names, then stop on that
subject regardless of what a further review would say; rescoping to a different subject is
legitimate and is not defiance.

**A commit after the review fork re-arms the gate — commit first, then spawn the fork last.** [^1] (overstated; corrected by [^2]) [^2]


^ATOM-D8ML-JZ6R [desc: "The corrected rule reduces to 'fork unless the turn is MECHANICAL or purely SUBTRACTIVE' — the exemption is small by construction; an earlier 'four forks suppressed' claim was struck as uncounted", keywords: does_the_criterion_exempt_anything_at_all is_clause_c_too_broad fork_unless_mechanical_or_subtractive how_much_does_the_rule_actually_suppress the_exemption_is_small_by_construction how_many_forks_were_correctly_suppressed why_was_the_four_forks_suppressed_claim_struck a_number_that_reads_as_counted_and_was_not trdd_and_memory_prose_is_mostly_evidence_characterisation clause_c_in_place_what_does_the_rule_reduce_to, ocd: 2026-09-05, lmd: 2026-10-17]

**BE HONEST ABOUT HOW MUCH THIS EXEMPTS: not much.** With clause (c) in place the rule reduces
to **"fork unless the turn is MECHANICAL or purely SUBTRACTIVE"** — because TRDD and memory prose
is *mostly* evidence characterisation. **The exemption is small by construction.**

*(An earlier version claimed "roughly FOUR forks correctly suppressed" on the originating
session. STRUCK — never enumerated, and the count would have conflated three different reasons
for not spawning: the criterion firing, a RESCOPE rather than a decline, and one decline driven
by context pressure. Only the first is the rule's yield. A number that reads as counted and was
not, inside the page that warns against exactly that.)*


^ATOM-F1CG-2AFB [desc: "Which turns genuinely get no review fork (timestamp/frontmatter bump, pure formatting or link repair, correcting a false commit-message sentence); the rule's value is a checkable reason to decline", keywords: what_turn_correctly_gets_no_fork examples_of_turns_needing_no_review can_I_decline_the_gate_honestly using_the_rule_as_a_rationalisation if_you_cannot_name_which_clause_fires the_value_is_a_checkable_reason_to_decline declining_the_fork_out_of_fatigue timestamp_or_frontmatter_bump_needs_no_fork formatting_or_link_repair_needs_no_fork relaying_another_agents_report_without_endorsing correcting_a_false_commit_message_removes_a_claim spawn_when_unsure_which_clause_fires, ocd: 2026-10-17, lmd: 2026-10-17]


**What genuinely gets no fork** — turns making no claim about evidence at all: a timestamp or
frontmatter bump; a pure formatting or link repair; correcting a false sentence in an earlier
commit message (that REMOVES a claim rather than making one). *Untested, listed for completeness:
relaying another agent's report without endorsing it — every relay on the originating session
carried the relayer's own assessment, so this case was never exercised.*

**The value is not the exemption — it is having a CHECKABLE REASON to decline**, so declining is
a judgment you can defend rather than fatigue wearing a rule as a costume. That distinction is
the whole point, given this rule was first written by the agent it exempts, at the end of a long
session, and had to be corrected for exactly that bias.

**⇒ IF YOU CANNOT NAME WHICH OF (a), (b) OR (c) FIRES, THAT IS THE ANSWER: SPAWN.** A rule you
have to squint at is being used as a rationalisation.


## See also

- [[review-fork-gate-when-to-spawn-and-when-not]]

## Notes and lessons learned

[^1]: [id: ATOM-4YHQ-4RO2, status: valid, keywords: "review_gate_fires_again_after_commit second_review_fork_for_the_same_change NO_REVIEW_POSSIBLE_exit_rejected commit_after_review_re-arms_the_gate positional_exit_review_gate write_after_the_last_review review_fork_costs_500k_tokens commit_then_review_order Stop_hook_review-gate_loop agentlenspro_review-gate", ocd: 2026-09-23, lmd: 2026-09-23] DO NOT commit (or run any write-shaped command) AFTER spawning the review fork for that same change, BECAUSE the Stop-hook gate is positional: a write after the last review re-arms it, and the `REVIEW-GATE: NO REVIEW POSSIBLE` exit is rejected whenever a spawn was possible, so a verified one-line edit costs a second ~500k-token review (measured 2026-09-24, commits 3bcea8ac and 0e5d02a1). DO commit first, then spawn the review fork as the last tool call of the turn.
[^2]: [id: ATOM-D4IP-N3SM, status: valid, keywords: "review_gate_fires_again_after_commit second_review_fork_for_the_same_change NO_REVIEW_POSSIBLE_exit_rejected commit_after_review_re-arms_the_gate positional_exit_review_gate write_after_the_last_review review_fork_costs_500k_tokens commit_then_review_order Stop_hook_review-gate_loop agentlenspro_review-gate", ocd: 2026-09-23, lmd: 2026-09-23] DO NOT commit (or run any write-shaped command) AFTER spawning the review fork for that same change, BECAUSE the Stop-hook gate is positional: a write after the last review re-arms it, and the `REVIEW-GATE: NO REVIEW POSSIBLE` exit was rejected three times out of five on 2026-09-24 (acceptance rule unknown), so a verified edit can cost a second ~500k-token review. DO commit first, then spawn the review fork as the last tool call of the turn.
