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


^ATOM-0GLJ-EK3A [desc: "Spawn a review fork when the turn changed EXECUTABLE BEHAVIOUR or asserted a VERIFIABLE VERDICT; a turn whose whole diff is prose gets a re-read instead — checkable with git diff --name-only | grep -v", keywords: should_I_spawn_a_fork_for_a_docs-only_commit review-fork_gate_fires_on_every_turn prose-only_turn_triggered_the_gate when_is_a_review_fork_worth_it stopping_criterion_for_review_forks the_adversarial_review_loop_is_eating_the_session forks_finding_smaller_and_smaller_things diminishing_returns_on_adversarial_review is_a_card_closure_worth_a_fork gate_blocks_the_turn_with_nothing_to_review how_to_decline_the_review_gate_honestly review-supervisor_says_changes_unreviewed, ocd: 2026-09-05, lmd: 2026-09-05]

**SPAWN a review fork when the turn changed EXECUTABLE BEHAVIOUR** (code, a test, a script, a
config the machine reads) **or asserted a VERIFIABLE VERDICT** (closing a card, claiming a fix
works, a rules interpretation others will act on, a memory write). **A turn whose entire diff is
prose gets a re-read before commit and no fork.**

Checkable in one command: `git diff --name-only HEAD~1 HEAD | grep -v '\.md$'` — non-empty ⇒
fork. No judgment about severity required.

**The gate will keep firing on prose turns; it is a Stop hook and cannot tell the difference.**
Say so in one line and do not spawn. That is not defying it — the gate's own purpose is "the
check that catches what tests and types cannot", and there is no test that could catch a
paragraph being too long, nor any defect when it is.

**WHY, measured 2026-09-05 over ~20 forks in one session.** The first five caught real
instrument defects that would have produced false data — a survivor census blind to the process
it counted, a loop stop-condition tied to a rendering detail, a missing per-run cap, an
overclaimed `--kill-after`. Then the findings moved from the EVIDENCE to how the PROSE
characterises the evidence, and kept shrinking: a stale STATE block, then a column contradicting
it, then the justification for the column, then the wording of the justification. **Prose about
prose has unbounded surface area** — there is always another imprecision, so the loop does not
converge on its own. Five consecutive rounds touched the same two paragraphs while the operative
content had been stable for three.

**A fork that says STOP is a finding — act on it.** When one recommends ending the review of
something, that instruction survives the next round: do the fixes it names, then stop *regardless
of what a further review would say*. Otherwise the gate re-opens what the previous fork closed.

## Notes and lessons learned
