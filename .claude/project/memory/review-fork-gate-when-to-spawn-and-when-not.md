---
name: review-fork-gate-when-to-spawn-and-when-not
description: "the review-fork gate fires on every turn / should I spawn a fork for a docs-only commit / the adversarial review loop is eating the session / forks keep finding smaller and smaller things / when is a review fork worth it / prose-only turn still triggered the gate / how do I stop reviewing my own prose / the gate blocks my turn and I have nothing to review / review-supervisor says N changes unreviewed / diminishing returns on adversarial review / should I fork after every commit / stopping criterion for review forks / the fork found a defect in the fix for the last fork's defect / agentlenspro review-gate keeps firing / is a card closure worth a review fork"
ocd: 2026-09-05
lmd: 2026-09-05
publish-globally: true
metadata:
  node_type: memory
  type: feedback
  tier: component
---

# review-fork-gate-when-to-spawn-and-when-not


^ATOM-0GLJ-EK3A [desc: "Fork when the turn changed EXECUTABLE BEHAVIOUR, asserted a VERDICT, or CHARACTERISED WHAT EVIDENCE ESTABLISHES — that third clause is load-bearing: without it the rule suppresses review of exactly th", keywords: should_I_spawn_a_fork_for_a_docs-only_commit review-fork_gate_fires_on_every_turn prose-only_turn_triggered_the_gate when_is_a_review_fork_worth_it stopping_criterion_for_review_forks the_adversarial_review_loop_is_eating_the_session forks_finding_smaller_and_smaller_things diminishing_returns_on_adversarial_review is_a_card_closure_worth_a_fork gate_blocks_the_turn_with_nothing_to_review how_to_decline_the_review_gate_honestly review-supervisor_says_changes_unreviewed, ocd: 2026-09-05, lmd: 2026-09-05]
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


^ATOM-D8ML-JZ6R [desc: "The corrected rule reduces to 'fork unless the turn is MECHANICAL or purely SUBTRACTIVE' — the exemption is small by construction, and its value is a checkable reason to decline, not a large saving", keywords: does_the_criterion_exempt_anything_at_all is_clause_c_too_broad what_turn_correctly_gets_no_fork fork_unless_mechanical_or_subtractive how_much_does_the_rule_actually_suppress can_I_decline_the_gate_honestly using_the_rule_as_a_rationalisation if_you_cannot_name_which_clause_fires examples_of_turns_needing_no_review the_criterion's_real_yield, ocd: 2026-09-05, lmd: 2026-09-05]
**BE HONEST ABOUT HOW MUCH THIS EXEMPTS: not much.** With clause (c) in place the rule reduces
to **"fork unless the turn is MECHANICAL or purely SUBTRACTIVE"** — because TRDD and memory prose
is *mostly* evidence characterisation. **The exemption is small by construction.**

*(An earlier version claimed "roughly FOUR forks correctly suppressed" on the originating
session. STRUCK — never enumerated, and the count would have conflated three different reasons
for not spawning: the criterion firing, a RESCOPE rather than a decline, and one decline driven
by context pressure. Only the first is the rule's yield. A number that reads as counted and was
not, inside the page that warns against exactly that.)*

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

## Notes and lessons learned
