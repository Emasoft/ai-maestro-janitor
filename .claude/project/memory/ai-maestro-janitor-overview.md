---
name: ai-maestro-janitor-overview
description: "how does ai-maestro-janitor work — the overall story + where the deeper pages are"
ocd: 2026-07-28
lmd: 2026-07-28
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: ai-maestro-janitor-overview
  globs: ["scripts/**", "skills/**", "agents/**", "hooks/**", "rules/**"]
---
**ai-maestro-janitor** is a Claude Code plugin that keeps a developer machine tidy and
secure without being asked. Its organising idea is that the expensive failures on a dev
box are the SILENT ones — a hook that dies at import, an index that quietly loses rows, a
session stranded after a compaction, a credential window burning twice as fast as its
budget. Nothing errors; things simply stop happening, and nobody notices for weeks. So the
janitor's job is less "fix problems" than **make silence audible**.

It runs on two clocks. A per-session **heartbeat** (a cron firing a stub that re-resolves
the newest cached plugin version, so updates roll forward without re-arming) runs ~39
project-scoped drift detectors and emits one-line findings — silent when nothing drifted.
A single machine-wide **daemon** owns every user/global-scope mutation, because N sessions
racing the same `claude plugin update` is a stampede. That split is the plugin's hardest
invariant: project-scoped work in sessions, global-scoped work in the daemon, never the
reverse.

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

## Applies to

- (radiates down to the component/aspect pages of this functionality — wire the reciprocal
  `## Governed by` on each as they are written)

## See also

- `[[debugging-methodology]]` (USER scope) — the general investigation methods this
  project keeps generating: prove SLOW vs STUCK before touching a timeout, a green check
  that scanned nothing is not green, the installed copy is not the source.

## Notes and lessons learned
