---
trdd-id: W8KDPT2M
title: Adopt the AI Maestro control-monitor-task CLI layer for all fleet operations
column: backburner
created: 2026-07-16T03:16:02+0200
updated: 2026-07-16T03:16:02+0200
current-owner: janitor-session
task-type: infra
scope: project
severity: major
effort: XL
labels: [fleet, ai-maestro, cli-adoption, epic]
relevant-rules: []
---

# Adopt the AI Maestro control/monitor/task CLI layer (epic)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-16

**Origin:** GitHub issue **#76** (ai-maestro TRDD-SCLSRS6E deliverable). AI Maestro now exposes a
complete control + monitor + task surface through a permanent CLI script layer, and the governing
Plugin Abstraction Principle mandates: **no plugin may call the AI Maestro HTTP API directly** —
the CLI scripts are the immutable interface shielding plugins from a constantly-changing API.

**Scope of the epic (from the issue — re-read `gh issue view 76` before starting; it carries the
full command reference):** replace/extend the janitor's fleet-facing surfaces (fleet_scan /
fleet_inject session targeting, session liveness, the kanban/task mirror, any direct AMP/API
touchpoint) with the ai-maestro CLI verbs where they exist, keeping the janitor's own native
fallbacks for machines with no AI Maestro server (the janitor MUST keep working standalone —
that is its IND design point).

**Why backburner:** cross-project integration epic — needs the CLI layer verified deployed +
stable on this machine, an inventory of janitor call-sites, and a per-call-site mapping table
BEFORE any code. Not blocking anything the janitor does today.

## NEXT ACTION
1. Inventory: grep the janitor for every fleet/AMP/server touchpoint; produce the call-site →
   CLI-verb mapping table (verbs from the issue's command reference; verify each verb EXISTS on
   the deployed CLI with a distinguishing observation — never trust `--help` exit 0 alone, per
   `memgrep-subcommand-existence-probe.md`).
2. Design the standalone-fallback split (server present → CLI; absent → current native paths).
3. Implement per subsystem as child TRDDs (depth-1), each test-gated.

## Verification
- No direct AI Maestro HTTP call remains in the janitor; CLI verbs used where the server exists;
  full standalone behavior preserved with the server absent (tests cover both).

## Notes and lessons learned
