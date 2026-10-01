---
name: janitor-detector-and-hook-roster
description: "the janitor detector and hook roster split into parts / how many janitor detectors are there / full list of the janitor detectors by group / what are the 16 janitor hooks / where do detector coverage and false-positive measurements live / how good is a security detector really / does agent-context-integrity actually catch poisoning / which detectors cover supply-chain security / which detectors watch for scope drift / the cleanup and observability detector groups / what does the github-issues-watch detector do / what does gh-reply-watch do / boundedness invariants for self-healing loops"
ocd: 2026-08-02
lmd: 2026-10-01
metadata:
  node_type: memory
  type: reference
  tier: hub
  functionality: detector-and-hook-roster
publish-globally: false
split-lineage: c4529390a94648e49f74f86799cd937b
---

# janitor-detector-and-hook-roster

^DZT4L6QZ [desc:"The janitor detector-and-hook roster hub: the single-page roster outgrew the split cap, so it is split into a grouped listing page and a measured-effectiveness findings page.", keywords:"the_janitor_detector_and_hook_roster_split_into_parts how_many_janitor_detectors_are_there where_is_the_full_list_of_janitor_detectors what_are_the_16_janitor_hooks why_was_the_detector_roster_split_into_two_pages where_do_detector_coverage_measurements_live janitor_detector_hook_inventory single_page_roster_outgrew_split_cap detector_roster_hub_overview which_page_holds_the_detector_list", type: reference, ocd: 2026-08-02, lmd: 2026-10-01]
The janitor's full detector-and-hook inventory, split across two pages once the
single-page roster outgrew the split cap: the grouped detector/hook/pattern-library
listing itself, and the measured effectiveness findings (coverage, false-positive
rate, and specific detector bugs) discovered while auditing that listing.

## Parts

^WI3G8WWJ [desc:"The -list part page holds the full grouped detector roster, the boundedness invariants, the pattern-library conventions, and all 16 janitor hooks.", keywords:"full_list_of_the_janitor_detectors_by_group what_are_the_16_janitor_hooks the_cleanup_and_observability_detector_groups which_detectors_cover_supply_chain_security which_detectors_watch_for_scope_drift boundedness_invariants_for_self_healing_loops what_does_the_github_issues_watch_detector_do what_does_gh_reply_watch_do pattern_library_conventions git_workflow_hygiene_detectors_group trdd_task_detectors_group memory_and_updates_detector_groups", type: reference, ocd: 2026-08-02, lmd: 2026-10-01]
- [[janitor-detector-and-hook-roster-list]] — the full grouped detector roster
  (git/workflow hygiene, TRDD/task, cleanup, observability, scope drift, memory,
  supply-chain/security, updates groups), the boundedness invariants, the
  pattern-library conventions, and all 16 janitor hooks.
^JWSJ97UF [desc: "The -findings part page holds measured coverage and false-positive rates for agent-context-integrity, regex failure shapes, two detector bug write-ups, and the CLAUDE.md poisoning analysis.", keywords: how_good_is_a_security_detector_really does_agent_context_integrity_actually_catch_poisoning where_do_detector_coverage_and_false_positive_measurements_live regex_matching_mechanics_failure_shapes gitignore_coverage_detector_bug project_map_drift_detector_bug claude_md_poisoning_vector_analysis detector_false_positive_rate_measured recurring_regex_failure_shapes scan_text_rule_effectiveness detector_effectiveness_findings, type: reference, ocd: 2026-08-02, lmd: 2026-10-01]
- [[janitor-detector-and-hook-roster-findings]] — measured coverage/false-positive
  rates for `agent-context-integrity`, the recurring regex-matching-mechanics
  failure shapes behind them, the `gitignore-coverage` and `project-map-drift`
  bug write-ups, and the CLAUDE.md poisoning-vector analysis.

## Applies to

- [[janitor-detector-and-hook-roster-list]]
- [[janitor-detector-and-hook-roster-findings]]

## Governed by

- [[janitor-architecture]] — the architecture hub; this page is the detailed roster
  behind its abbreviated detector/pattern-library/hooks summaries.

## Notes and lessons learned
