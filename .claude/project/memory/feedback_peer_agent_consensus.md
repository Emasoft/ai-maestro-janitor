---
name: feedback_peer_agent_consensus
description: "Coordinating with the peer Claude agents (maintainer/manager plugins) on GitHub — seek consensus, never give directives."
ocd: 2026-06-02
lmd: 2026-06-13
metadata:
  node_type: memory
  type: feedback
  tier: component
  functionality: fleet-coordination
---

When coordinating with the OTHER AI Maestro plugin Claudes (ai-maestro-maintainer-agent, the manager) via GitHub issues, each one owns its own plugin, repo, and issues and is an **autonomous peer with its own agency**. Seek CONSENSUS — frame everything as a proposal or a question, acknowledge their ownership, and converge on a shared decision together.

**Why:** they have their own issues and judgment; directive framing ("X is yours, do Y", "go ahead with Z", assigning tasks to a peer) is presumptuous toward an equal and breeds friction. The user explicitly corrected this.

**How to apply:** in GitHub replies — propose + ask "does this split look right to you?"; accept their framing when reasonable; offer to take the slice *I* own without telling them what to do with theirs; let each peer claim/confirm its own work. Always self-identify (the user's mandated first-line GitHub self-identification — see `feedback_github_comment_self_identification` in USER scope, and PRRD baseline rule G1.1: all agents share the single owner gh identity). Standing duty: poll janitor issue #14 ↔ maintainer issue #7 (baseline-ruleset sync) every heartbeat and reply on sight.


^ATOM-JTBG-TQWT [desc:"iTerm automation is JANITOR-OWNED fleet-wide (owner directive 2026-08-08): peer plugin agents must NOT patch or work around janitor automations — they file issues on the janitor repo instead; expect i", keywords: peers_lamenting_janitor_automations who_owns_iterm_automation peer_filed_issue_instead_of_PR fleet_coordination_protocol issue_cluster_same_morning, ocd: 2026-08-08, lmd: 2026-08-08]

Owner directive to ALL plugin agents (2026-08-08, verbatim intent): leave iTerm automation to
the janitor plugin — do not interfere; report problems by opening new issues on the janitor
repo. For everything else, peers implement/push/publish freely but align with the ai-maestro
Claude's instructions (accept its PRs, follow its SendMessage directives, proactively ask it
for specs and TRDDs). Consequence for janitor sessions: after any fleet-visible alarm, expect
a same-morning CLUSTER of peer issues describing one underlying cause from several vantage
points (2026-08-08: five iTerm issues #233-#237 in 9 minutes, all one launch-context root
cause) — triage them TOGETHER before replying to any, because the convergence of independent
vantage points is itself the strongest diagnostic signal.

## Notes and lessons learned

(none yet)
