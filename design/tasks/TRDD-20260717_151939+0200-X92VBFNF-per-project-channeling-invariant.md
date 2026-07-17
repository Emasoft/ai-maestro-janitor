---
trdd-id: X92VBFNF
title: Per-project channeling invariant — no automatic surface carries another project's findings
column: published
created: 2026-07-17T15:19:39+0200
updated: 2026-07-17T17:05:00+0200
implementation-commits: [41eecae]
current-owner: claude-ai-maestro-janitor
task-type: security
scope: project
severity: high
related-trdd: [157OH2D7, 4649ZLE0, PZLVT2RN]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-17

**USER DIRECTIVE (2026-07-17, verbatim):** *"you cannot mix projects! not only they have not
the skills to manage the specific elements of another projects, but they are prevented to act
on the other agents workdirs, gits or github repos! and more importantly, such disturbance
will break the division of tasks and responsabilities, making some agents wasting tokens in
things that were not in their budget, and ending for making those agents unable to complete
their own job instead! Absolutely not, all communications must be channeled strictly to the
project they are relative to. no other project must receive them. a big issue of data
exfiltration will also be created by this, since each project have different degrees of
sensible data protections, some simple projects have zero. this could end in a big security
breach. be sure to fix this immediately! notify the ai-maestro claude too!"*

**THE INVARIANT:** an AUTOMATIC surface (heartbeat drift line, detector output, injected
nudge, proposal TRDD, notification) may carry information about EXACTLY the project it fires
in — never another project's findings, names, or even aggregate counts that include them. The
four reasons, each sufficient alone: wrong skills; forbidden cross-actuation (other agents'
workdirs/gits/repos); token-budget contamination breaking the division of responsibilities;
data exfiltration into projects with weaker (possibly zero) data protections. EXPLICIT HUMAN
commands (`/janitor-show-global-status`, `/janitor-github-config-fix --all`) remain
machine-wide — the human's authority, invoked on demand, is not an automatic channel.

**FIXED THIS SESSION (the one violator found):** the `fleet-github-config` per-session
detector surfaced the daemon's FLEET-aggregate github-audit line into every session (counts
across all repos + a fleet-wide fix pointer), deduped on the fleet digest. Now:
`summarize_for_slug` replaces `summarize` (fleet-aggregate wording DELETED, no legacy);
`payload_for_slug` filters strictly; the detector resolves its own slug first (no slug ⇒
SILENT, never fleet data), emits only own-repo findings with a `--slug`-scoped fix pointer,
and dedupes on the own-repo digest (another repo's change can neither re-alert nor silence
us). Slug is shape-validated (`_SLUG_RE.fullmatch`) before reaching a drift line. Proposal
isolation was ALREADY correct (`_propose_for_this_repo`). Tests: isolation both ways,
unsafe-slug refusal, per-repo dedupe (`test_github_config_audit.py`,
`test_fleet_github_config_detector.py` — the old "other repo is still NOTIFIED" contract test
rewritten to assert INVISIBILITY).

**Audited, judged compliant:** memory surfaces (per-scope by construction); daemon watchdog
lines (janitor-internal infra, no project data); `/janitor-token-attribution`, `fleet_status`
(human-invoked). **BORDERLINE — USER TO DECIDE:** `window-burn-rate`'s culprit clause names
the top-consuming OTHER project's slug in whatever session trips the alarm (TRDD-OY0W6LX5,
user-driven design: the machine-wide token budget is genuinely shared). Left unchanged;
flag if it should be redacted to "another project (see /janitor-token-attribution)".

**Consequences wired into siblings:** TRDD-4649ZLE0's escalation rule is now PER-PROJECT
(a finding pushes to the HUMAN when ITS project has no live session; never routed through
another session). ai-maestro notified on janitor#100 — the invariant binds the server's
daemon-function equally (route findings only to the affected agent; no broadcast).

**SHIPPED: v0.50.0 published 2026-07-17** (commit `41eecae`, release `103c84a`). The
window-burn-rate borderline stays scheduled for the plan's Phase 4 (token-quietness rework).

## Notes and lessons learned

[^1]: [id:ATOM-XPRJ-CHN1, status:valid, keywords:"cross project findings leak fleet summary line other repo data exfiltration wrong budget", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT let an automatic per-session surface carry another project's findings — not even
  aggregate counts, BECAUSE it burns the wrong agent's budget, invites forbidden cross-repo
  action, and exfiltrates into projects with weaker protections. DO route strictly
  per-project; unattended projects reach the HUMAN via the daemon channel.
