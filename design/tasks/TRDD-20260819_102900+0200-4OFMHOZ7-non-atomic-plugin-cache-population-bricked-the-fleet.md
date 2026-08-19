---
trdd-id: 4OFMHOZ7
title: Non-atomic plugin-cache population bricked every session's tools for 20 minutes — post-mortem + staging-dir guard
column: dev
created: 2026-08-19T10:29:00+0200
updated: 2026-08-19T20:52:00+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-19 19:52

**Box 1 — attribution: RESOLVED as far as this host's logs allow (daemon EXONERATED).**
`daemon.log` forensics, 2026-08-19 evening:
- The daemon's `user-plugins-update` sweep (child pid 29651, started 09:15:09, 77 plugins,
  alphabetical) processed the janitor slot ~09:15–09:19 SILENTLY — and silence means rc=0
  no-change, because every timeout in that sweep IS logged (`(15/77) claude-code-setup TIMED
  OUT` at 09:19:13, then 36,37,38,40,41,43,50,51). The workload-cap SIGKILL at 09:50:42
  landed on iteration ~52 (playwright zone), not the janitor.
- The daemon's requests-consumer path logged ZERO `plugin-update ai-maestro-janitor` lines
  on 08-19.
- `cold-cache-clear` verified from source (daemon.py:1907): it shrinks SESSION prompt-cache
  contexts, never touches plugin cache dirs — ruled out.
Remaining writer in the 09:35–09:55 churn window: the ai-maestro HUB-side updater (it owns
`user-plugins-update` per the 10:09:43 chore-coordination yield, and by its own account both
measured the partial dir AND additively completed it from the repo checkout) or a peer
session's manual `claude plugin update` — both outside this repo's logs. Memory pressure was
live throughout (memory-guard "pressure, no Tier-1 candidate" 09:03/09:19/09:54).

**Box 1 addendum — hub cross-check received (peer, 2026-08-19 ~20:50).** The hub lane's
`~/.aimaestro/auto-update-settings.json` lastRunSummary shows its
`claude plugin update ai-maestro-janitor@ai-maestro-plugins` ran **09:50:18–09:50:34, exit 0**
— inside the window, and the only CONFIRMED same-window writer. Timeline refinement: the
partial state was observed from ~09:35, BEFORE that run, and the hub tick was inside its
marketplace-refresh step from ~09:20:18 until killed at 09:50:18 — so the 09:50 extraction
most plausibly wrote OVER an already-partial dir (part of the observed churn / repair), and
the INITIAL truncation (09:15–09:35) remains unattributed: daemon exonerated, hub tick
occupied elsewhere, and any earlier hub fire is overwritten in a last-run-only trail. Peer
offered to add per-target start/end stamps + exit codes to the trail — ACCEPTED; that gives
the next post-mortem both ends. Attribution is now closed as: one confirmed overlapping
writer (hub, exit 0), initial truncator unattributable with existing trails.

**Box 3 — detector coverage: DECIDED (measured refusal + one gap named).** From
`scripts/detectors/janitor-self-integrity.py`: C2 manifest verification covers the .md
classes only (README/CLAUDE/skills/commands/rules) and is OPT-IN (default OFF); the stub's
C2-exec gate verifies scripts the STUB launches, not the hook scripts the HARNESS launches
(which is why the loss bricked tools with raw Errno-2 instead of a janitor finding). Mass
file-loss — this incident's class, 1758→120 files — inevitably takes hundreds of skills/*.md
with it, so the C2 manifest's missing-count WOULD flag it when armed. A dedicated
scripts/-loss alarm is REFUSED: the .md proxy covers the interrupted-extraction class, and a
targeted scripts-only tamper is C2-exec's domain at launch time. The real gap is the opt-in
default — surfacing that flag to the user is the actionable residue, not a new detector.

**Box 4 — memory page: DONE.** `plugin-cache-install-integrity` gained lesson
ATOM-X3NR-20M8 (quarantine must live OUTSIDE every scanned tree) and its `description:` now
carries the bricked-tools + quarantine-load-error symptoms.

**Box 2 — HALF-BLOCKED.** The staging-dir+atomic-rename requirement goes to the hub's
server-absorption design via peer message (sendable now). The UPSTREAM ask is harness-owned
(`claude plugin update` populates the cache non-atomically) ⇒ filing it means posting on a
repo NOT owned by this gh auth — forbidden without the USER's explicit word. NEXT ACTION:
ask the USER whether to file the upstream harness issue; on yes, file with the evidence
above (partial version dir observed live, 120/1758 files, loaded without complaint).

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

- [x] interrupted actor identified (daemon exonerated with evidence; remaining candidates —
      hub-side updater / peer session — named and outside this repo's logs; see STATE)
- [ ] staging-dir+rename requirement recorded in the server-absorption design (hub §) + upstream
      ask filed if the extraction is harness-owned — peer message sendable; upstream ask BLOCKED
      on USER approval (repo not owned by this gh auth)
- [x] detector coverage decided: measured refusal of a dedicated scripts/-loss alarm; the .md
      manifest proxy covers the class WHEN the opt-in flag is armed (see STATE)
- [x] plugin-cache-install-integrity memory page updated (lesson ATOM-X3NR-20M8 + description)

## Approval log
