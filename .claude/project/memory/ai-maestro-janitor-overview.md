---
name: ai-maestro-janitor-overview
description: "how does ai-maestro-janitor work — the overall story + where the deeper pages are / what is ai-maestro-janitor / why did a hook fail silently / session stranded after a compaction / credential window burning twice as fast as its budget / difference between the heartbeat and the daemon / why does the cron stub re-resolve the newest plugin version / avoid N sessions racing claude plugin update stampede / where does the markdown memory wiki live / what is memgrep used for / how does the support-ticket system turn a finding into repair work / where is the architecture hub page / what runs on the per-session heartbeat cadence / janitor fleet control plane mode flags and locks / how does the janitor publish pipeline work / why does the auto-compact loop terminate / project-scoped versus global-scoped work invariant"
ocd: 2026-07-28
lmd: 2026-09-24
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: ai-maestro-janitor-overview
  globs: ["scripts/**", "skills/**", "agents/**", "hooks/**", "rules/**"]
publish-globally: false
---
^1Y80JMO4 [desc: "ai-maestro-janitor is a Claude Code plugin that makes SILENT dev-machine failures audible instead of trying to prevent every one", keywords: what_is_ai-maestro-janitor silent_failures_on_a_dev_machine hook_that_dies_at_import_silently index_quietly_loses_rows session_stranded_after_a_compaction credential_window_burning_twice_as_fast_as_budget janitor_makes_silence_audible organising_idea_of_the_janitor nothing_errors_things_simply_stop_happening why_did_a_hook_fail_silently, ocd: 2026-07-28, lmd: 2026-09-23]
**ai-maestro-janitor** is a Claude Code plugin that keeps a developer machine tidy and
secure without being asked. Its organising idea is that the expensive failures on a dev
box are the SILENT ones — a hook that dies at import, an index that quietly loses rows, a
session stranded after a compaction, a credential window burning twice as fast as its
budget. Nothing errors; things simply stop happening, and nobody notices for weeks. So the
janitor's job is less "fix problems" than **make silence audible**.

^2PDTOOPU [desc: "the janitor runs a per-session heartbeat for project-scoped drift detection and one machine-wide daemon for every user/global-scope mutation, never the reverse", keywords: difference_between_the_heartbeat_and_the_daemon per_session_heartbeat_cron_stub why_does_the_cron_stub_re-resolve_the_newest_plugin_version avoid_n_sessions_racing_claude_plugin_update_stampede single_machine-wide_daemon_owns_global_scope project-scoped_versus_global-scoped_work_invariant what_runs_on_the_per-session_heartbeat_cadence heartbeat_runs_39_project-scoped_drift_detectors silent_when_nothing_drifted hardest_invariant_project_scope_in_sessions_global_scope_in_daemon, ocd: 2026-07-28, lmd: 2026-09-23]
It runs on two clocks. A per-session **heartbeat** (a cron firing a stub that re-resolves
the newest cached plugin version, so updates roll forward without re-arming) runs ~39
project-scoped drift detectors and emits one-line findings — silent when nothing drifted.
A single machine-wide **daemon** owns every user/global-scope mutation, because N sessions
racing the same `claude plugin update` is a stampede. That split is the plugin's hardest
invariant: project-scoped work in sessions, global-scoped work in the daemon, never the
reverse.

^A0FMMMTO [desc: "the janitor's markdown memory wiki (LOCAL/PROJECT/USER, searched by symptom via memgrep) and its support-ticket system are used more than its hygiene detectors", keywords: where_does_the_markdown_memory_wiki_live what_is_memgrep_used_for three_scope_memory_wiki_local_project_user searched_by_symptom_through_memgrep how_does_the_support-ticket_system_turn_a_finding_into_repair_work support_ticket_system_vs_a_nag_that_recurs_forever memory_wiki_and_support-tickets_used_more_than_hygiene scheduled_repair_work_instead_of_a_recurring_nag janitor_features_beyond_drift_detection recurring_finding_becomes_scheduled_work, ocd: 2026-07-28, lmd: 2026-09-23]
Two things it provides are used far more than the hygiene: the three-scope **markdown
memory wiki** (LOCAL / PROJECT / USER, searched by symptom through `memgrep`) and the
**support-ticket system** that turns a recurring finding into scheduled repair work
instead of a nag that recurs forever.

## Parts map

- `[[janitor-architecture]]` — the architecture hub: the two tiers, the scope invariant,
  the detector roster, the resilience and immortality layers, where state lives.
- `[[janitor-beat-tasks-and-limitations]]` — cadences: what runs how often, and what the
  platform will not let it do.
- `[[janitor-fleet-control-plane]]` — the machine-wide mode flags and locks, and the
  one-daemon-per-host rule the ai-maestro server also plays by.
- `[[janitor-publish-pipeline]]` — how a release actually ships, and the gates that block
  one.
- `[[janitor-compaction-floor-gate]]` — why the auto-compact loop terminates (gate on
  reclaimable tokens above the learned floor, never on raw context size).
- `[[jev-compaction]]` — the post-clear pipeline: extract, score via the OpenRouter Jev model,
  compose a full copy plus a small injected one, run synchronously by a SessionStart hook.

## Applies to

- (radiates down to the component/aspect pages of this functionality — wire the reciprocal
  `## Governed by` on each as they are written)

## See also

- `[[debugging-methodology]]` (USER scope) — the general investigation methods this
  project keeps generating: prove SLOW vs STUCK before touching a timeout, a green check
  that scanned nothing is not green, the installed copy is not the source.
- [[jev-compaction]] — already listed in the Parts map above (backtick-wrapped there,
  which the link-law checker does not parse as a link); this unwrapped form is the formal
  reciprocal edge.

## Notes and lessons learned
