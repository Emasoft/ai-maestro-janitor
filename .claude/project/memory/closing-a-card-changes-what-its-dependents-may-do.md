---
name: closing-a-card-changes-what-its-dependents-may-do
description: "closing a TRDD broke another card's task / a chore that edits card X became forbidden when X went complete / terminal freeze blocks a cleanup I had planned / I closed a card and only then found the dependent / which cards break if I mark this one complete / what to check before closing a card / is it safe to close this TRDD / pre-close dependency check / undeclared dependency on a card's column / a card whose task is edit card X declares nothing / blocked-by and eht are not the only dependencies / rule 12 forbids the collapse I wanted to do / can I revert a close to unblock a chore / is a readability collapse a body edit / grep for dependents before a terminal transition / who references this TRDD / closing a card is not a local act"
ocd: 2026-09-05
lmd: 2026-09-05
publish-globally: true
metadata:
  node_type: memory
  type: user
  tier: component
---

# closing-a-card-changes-what-its-dependents-may-do


^ATOM-UWNX-7VH9 [desc: "Closing a TRDD changes the PERMISSION SET of every card naming it: rule 12 freezes the body, so a chore whose task is 'edit card X' is FORECLOSED once X goes terminal. Grep for dependents first.", keywords: closing_a_card_broke_another_card's_task chore_that_edits_card_X_forbidden_after_X_went_complete terminal_freeze_blocks_a_planned_cleanup closed_a_card_then_found_the_dependent which_cards_break_if_I_close_this_one what_to_check_before_closing_a_card is_it_safe_to_close_this_TRDD pre-close_dependency_check undeclared_dependency_on_a_column a_card_whose_task_is_edit_card_X_declares_nothing blocked-by_and_eht_are_not_the_only_dependencies grep_for_dependents_before_a_terminal_transition who_references_this_TRDD should_I_delay_a_close_for_a_dependent_chore, trdd: TRDD-34GB6XUI, ocd: 2026-09-05, lmd: 2026-09-05]
**Closing a card is not a local act — it changes what every card that NAMES it may do.**
`blocked-by:` (a HOLD `trdd-drift` re-evaluates) and `eht:` (a GATE checked at the terminal
transition — different code, different moment) are the DECLARED dependencies. A card whose task
is "edit card X" depends on X's `column:` just as hard and **declares nothing**: nothing warned
me, and I know of no check that would. Rule 12 freezes a terminal card's body with only four
narrow exceptions — the closing edit, an `## Approval log` append, archival as itself, and
removing a body line that FALSELY and machine-verifiably contradicts the column. A readability
collapse or a restructure is none of those.

**THE CHECK, before any terminal transition:** `grep -rl "<id8>" design/tasks/*.md`, and read
what comes back. One command. *(Verified 2026-09-05: that grep does list the dependent.)*

**⚠ WHAT TO DO ABOUT A HIT IS A JUDGMENT — "do it first, then close" is the WRONG default.**
Either do the dependent's work first or accept that closing forecloses it, and which is right
depends on whether that work is worth delaying the close. **Foreclosing is sometimes exactly
right:** in the incident below the USER had already de-coupled the dependent so a finished fix
would not wait on a readability chore, so "do it first" would have re-imposed by habit the
coupling a human removed by decision.


^ATOM-FRF1-8340 [desc: "Incident 2026-09-05: closing ZQ02QG1L (mechanically correct) FORECLOSED 34GB6XUI's task as written — the card is not dead, it has four paths, and the consequence was deductive not measured", keywords: the_incident_that_produced_this_page ZQ02QG1L_close_foreclosed_34GB6XUI closing_a_card_with_an_undeclared_dependent_worked_example pre-block-column_restore_was_mechanical the_card_is_not_dead_only_its_task_as_written four_options_after_a_task_is_foreclosed cancel_re-scope_exception_or_evaporated was_the_close_premature_because_work_remained chore_about_the_card_versus_work_of_the_card deduction_is_not_a_measurement, trdd: TRDD-34GB6XUI, ocd: 2026-09-05, lmd: 2026-09-05]

**THE INCIDENT, 2026-09-05.** I closed TRDD-ZQ02QG1L `blocked` → `complete`: its blocker had
gone terminal, so `pre-block-column: complete` was restored MECHANICALLY — replaying a
completeness judgment made a day earlier, before the dependent was a live consideration. That
**FORECLOSED TRDD-34GB6XUI's TASK AS WRITTEN**, whose whole job was collapsing ZQ02QG1L's 404
lines into its surviving facts.

**"Foreclosed", not "killed": the card is not dead.** Four paths remain — cancel it; re-scope so
the surviving facts land in a NEW card; seek a USER-level freeze exception; or recognise the task
simply EVAPORATED, because nobody must work FROM a terminal card and its correction layers are
exactly the audit trail rule 12 preserves.

**This consequence was DEDUCED, not measured** — a rule applied to a state change. Saying so
matters on a corpus whose discipline is separating the two: the only thing actually measured was
that `grep -rl ZQ02QG1L design/tasks/` lists 34GB6XUI.

**The objection a reader will raise, answered:** *"`complete` means done; the chore was
outstanding work; so the close was premature."* It fails because the chore is ABOUT the card, not
work OF it — the card's own text calls it "an UNGATED chore" and says "Nothing waits on this".


^ATOM-6ES3-OVTV [desc: "Two traps after a close breaks a dependent: reverting the close falsifies board state, and rule 7's mechanical-repair carve-out does NOT license a body edit on a frozen card", keywords: can_I_revert_a_close_to_unblock_a_chore un-closing_a_card_to_make_a_chore_executable is_a_readability_collapse_a_mechanical_repair rule_7_mechanical_repair_on_a_terminal_card fact-preserving_edit_on_a_frozen_card new_work_equals_new_TRDD_remedy leave_the_old_card_pointing_at_the_new_one superseded-by_versus_external-refs the_pointer_is_itself_a_body_edit why_are_rule_12_exceptions_enumerated does_preserving_facts_make_an_edit_allowed re-coupling_work_a_human_de-coupled, trdd: TRDD-34GB6XUI, ocd: 2026-09-05, lmd: 2026-09-05]

**Two traps once a close has broken a dependent.**

**1. Do NOT revert the close.** Un-closing a card to make a chore ABOUT that card executable
falsifies board state for convenience, and it re-couples work a human may have deliberately
de-coupled. A `pre-block-column:` restore is MECHANICAL — it replays a completeness judgment
already made, often before the chore was a live consideration. Rule 12's own remedy is
"new work = new TRDD". Note the obvious form of that is itself illegal: "leave X frozen and
POINTING at the new card" requires a body edit to X. Instead the NEW card carries
`external-refs: [X]`, or use `superseded-by:` — permitted on a terminal card — but only if X
really was superseded rather than merely distilled.

**2. Rule 7 does NOT rescue a fact-preserving edit.** The tempting argument: rule 7 exempts
"MECHANICAL repair (format/syntax only, no fact change)", so a collapse that keeps every claim
should be allowed. It is not. Rule 12's exceptions are ENUMERATED and every one of them is
itself fact-preserving — which would make all four redundant if "preserves facts" were the
test. Rule 7 answers *"do I bump `updated:`?"*; rule 12 answers *"may I edit?"* and names
`updated:` among the only things that may change, so it already constrains rule 7's mechanism.


## See also

- [[trdd-state-block-staleness-vs-implementation-commits]]

## Notes and lessons learned
