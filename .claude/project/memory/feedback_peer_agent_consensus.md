---
name: feedback_peer_agent_consensus
description: "Coordinating with the peer Claude agents (maintainer/manager plugins) on GitHub — seek consensus, never give directives / how should I talk to the maintainer or manager plugin agent on GitHub / is it ok to tell a peer agent what to do / who owns iTerm automation / a peer filed an issue instead of a PR / why did five similar issues appear the same morning / should I patch or work around a janitor automation / what is the self-identification convention for GitHub replies / how do I coordinate on the baseline-ruleset sync issue / peers lamenting janitor automations / directive framing toward an equal peer breeds friction / propose don't assign tasks to a peer / does the janitor own iTerm automation fleet-wide / how do I coordinate with the ai-maestro maintainer plugin / two agents investigated the same incident the same morning / duplicate work with a peer agent / I messaged then had to correct myself / message churn in a peer context / what is the contract between two daemons / shared state schema between two implementations / coordination left nothing durable / a chat message is not a contract / which side owns the shared file format"
ocd: 2026-06-02
lmd: 2026-08-26
metadata:
  node_type: memory
  type: feedback
  tier: component
  functionality: fleet-coordination
publish-globally: false
---

When coordinating with the OTHER AI Maestro plugin Claudes (ai-maestro-maintainer-agent, the manager) via GitHub issues, each one owns its own plugin, repo, and issues and is an **autonomous peer with its own agency**. Seek CONSENSUS — frame everything as a proposal or a question, acknowledge their ownership, and converge on a shared decision together.

**Why:** they have their own issues and judgment; directive framing ("X is yours, do Y", "go ahead with Z", assigning tasks to a peer) is presumptuous toward an equal and breeds friction. The user explicitly corrected this.

**How to apply:** in GitHub replies — propose + ask "does this split look right to you?"; accept their framing when reasonable; offer to take the slice *I* own without telling them what to do with theirs; let each peer claim/confirm its own work. Always self-identify (the user's mandated first-line GitHub self-identification — see `feedback_github_comment_self_identification` in USER scope, and PRRD baseline rule G1.1: all agents share the single owner gh identity). Standing duty: poll janitor issue #14 ↔ maintainer issue #7 (baseline-ruleset sync) every heartbeat and reply on sight.


^ATOM-JTBG-TQWT [desc:"iTerm automation is JANITOR-OWNED fleet-wide (owner directive 2026-08-08): peer plugin agents must NOT patch or work around janitor automations — they file issues on the janitor repo instead; expect i", keywords: peers_lamenting_janitor_automations who_owns_iterm_automation peer_filed_issue_instead_of_PR fleet_coordination_protocol issue_cluster_same_morning should_a_peer_patch_around_a_janitor_automation why_did_five_iterm_issues_appear_in_9_minutes triage_a_cluster_of_issues_together convergence_of_independent_vantage_points_is_a_diagnostic_signal do_peers_align_with_the_ai-maestro_claude's_instructions, ocd: 2026-08-08, lmd: 2026-08-08]

Owner directive to ALL plugin agents (2026-08-08, verbatim intent): leave iTerm automation to
the janitor plugin — do not interfere; report problems by opening new issues on the janitor
repo. For everything else, peers implement/push/publish freely but align with the ai-maestro
Claude's instructions (accept its PRs, follow its SendMessage directives, proactively ask it
for specs and TRDDs). Consequence for janitor sessions: after any fleet-visible alarm, expect
a same-morning CLUSTER of peer issues describing one underlying cause from several vantage
points (2026-08-08: five iTerm issues #233-#237 in 9 minutes, all one launch-context root
cause) — triage them TOGETHER before replying to any, because the convergence of independent
vantage points is itself the strongest diagnostic signal. [^1]

## Notes and lessons learned

(none yet)
[^1]: [id: ATOM-M03S-DMHO, status: valid, desc: "co-owned subsystem: read the peer's board first, and put the contract where the shared DATA lives", keywords: "two_agents_investigated_the_same_incident_the_same_morning duplicate_work_with_a_peer_agent peer_already_had_a_TRDD_open_for_this I_messaged_then_had_to_correct_myself message_churn_in_a_peer's_context what_is_the_contract_between_two_daemons shared_state_schema_between_two_implementations should_I_check_the_peer's_board_before_starting coordination_left_nothing_durable a_chat_message_is_not_a_contract the_peer_reimplemented_it_in_another_language which_side_owns_the_shared_file_format", ocd: 2026-08-26, lmd: 2026-08-26] DO NOT start work on a subsystem a peer agent co-owns without first reading THEIR board, and do not coordinate by chat message alone, BECAUSE parallel blind work is the default outcome and messages leave nothing a later session can read: on 2026-08-26 the peer filed a TRDD on the dead OAuth slots at 04:47 and I independently root-caused the same incident at 09:40, each unaware, then I sent a mis-framed message plus a correction — three sends into their context for a contract that still existed nowhere on disk. DO grep the peer's `design/tasks/` for the symptom BEFORE the first measurement, and when two implementations share state, pin the schema next to the SHARED DATA rather than in either repo — the CODE may legitimately differ per language (a TS port inside the server is the intended design), so the state format is the actual contract.
