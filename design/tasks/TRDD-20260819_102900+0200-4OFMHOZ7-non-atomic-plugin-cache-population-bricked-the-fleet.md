---
trdd-id: 4OFMHOZ7
title: Non-atomic plugin-cache population bricked every session's tools for 20 minutes — post-mortem + staging-dir guard
column: todo
created: 2026-08-19T10:29:00+0200
updated: 2026-08-19T10:29:00+0200
current-owner: janitor-main-session
task-type: security
priority: high
approval-tier: 0
scope: project
external-refs: [janitor#232, TRDD-ZM5LZ24Y, ai-maestro PE54D95Q]
npt: []
eht: []
---

# Non-atomic cache population — the 2026-08-19 09:35 fleet-bricking incident

## What happened (measured, two observers)

09:35–09:55: `~/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/3.3.16/` went
PARTIAL (hub measured 120 files vs 1758 in 3.3.15; this session measured `scripts/` reduced
to 6 entries — `lib/`, `detectors/`, `hooks/`, `daemon.py`, `dispatch.py` gone) and was
CHURNING. Every session's PreToolUse hooks then failed Errno-2 on the missing hook scripts —
**bricking ALL tools machine-wide** (this session included: Bash, Read, everything) until the
USER manually ran `/reload-plugins`. Host memory pressure was live in the window (daemon
memory-guard: free 614–659MB < 1024MB floor at 09:03/09:19/09:54) — the janitor#232 signature
(an extraction/copy killed partway loads without complaint).

Recovery (this session, per the plugin-cache-install-integrity page's remedy order): moved the
broken dir aside → CLI re-extraction → **tag-diff v3.3.16 = 0 missing**, byte-identical sample
on daemon.py/dispatch.py/on-session-start.py/plugin.json/agents. The hub also completed the
cache additively from the repo checkout in the same window (both observers converge on 2749
files). Quarantined copy: `~/.claude/.broken-cache-quarantine/` (keep until this card closes).
SECOND bug found during recovery: the quarantine `mv` initially parked the broken copy INSIDE
the marketplace cache dir, where the scanner tried to load it as a plugin (7 load errors,
janitor surface missing) — a quarantine location must be OUTSIDE every scanned tree.

**Published source verified NOT at fault:** the marketplace serves this plugin by git URL
(`Emasoft/ai-maestro-janitor.git`); the v3.3.16 tag is complete (1656 files). Only LOCAL cache
population is non-atomic. No emergency republish required.

## What

1. **Post-mortem:** identify the actor whose extraction was interrupted (harness
   `claude plugin update` from a peer session / fleet-plugins-update child / other) from the
   window's logs, and whether the churn was one interrupted write or repeated rewrites.
2. **Named requirement for the server-absorption design (hub asked):** cache population MUST be
   staging-dir + atomic rename — a version dir either exists complete or not at all. The
   extraction is HARNESS behavior, so the durable fix may be an upstream ask; the janitor side
   can still (a) verify-after-update (tag-diff, already proven) and (b) alarm on a version dir
   that loses files while installed (the self-integrity detector's domain — check whether C2
   covers the INSTALLED root or only the pinned one).
3. Fold the quarantine-location lesson into the recovery procedure (memory page update).

## Acceptance

- [ ] interrupted actor identified (or explicitly unattributable with the evidence listed)
- [ ] staging-dir+rename requirement recorded in the server-absorption design (hub §) + upstream
      ask filed if the extraction is harness-owned
- [ ] detector coverage decided: installed-root file-loss alarm exists or a measured refusal
- [ ] plugin-cache-install-integrity memory page updated (quarantine location + this incident)

## Approval log
