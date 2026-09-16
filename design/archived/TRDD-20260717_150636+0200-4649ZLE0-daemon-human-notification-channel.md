---
trdd-id: 4649ZLE0
title: Human-notification channel for daemon findings when no session is alive
column: published
created: 2026-07-17T15:06:36+0200
updated: 2026-07-17T19:55:00+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
severity: high
related-trdd: [PZLVT2RN, 157OH2D7, FENWWB4E, H7NVKSAX]
implementation-commits: [fe864d5]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-17

**USER DIRECTIVE (2026-07-17, verbatim):** *"if the claude instance of that project is not
executed for weeks, any error will remain undetected and unchecked, with the serious risk of
compromising the repo. You should at least report any error and any output of the sevurity
scanners to the human, maybe via some notification or email/telegram/slack/etc. so the human
will start the claude code instance interested by the iseue and tell the claude to fix it."*

**The gap, precisely:** the daemon's machine-wide chores (fleet github-config audit, its own
task failures/quarantines, security-relevant findings) surface ONLY through per-session
heartbeat detectors — and (SECOND user directive, same day, PER-PROJECT CHANNELING —
TRDD-X92VBFNF) each session may receive ONLY its own project's findings. So a finding about a
repo with no live session reaches NOBODY: it sits unread in the findings JSON + `daemon.log`
indefinitely. The one process guaranteed alive (the daemon) has no path to a human — and the
human channel is now the ONLY legitimate route for unattended projects (cross-surfacing into
other projects' sessions is banned: wrong skills, wrong budget, forbidden cross-repo action,
data exfiltration into weaker-protected projects).

**IMPLEMENTED (plan Phase 5, 2026-07-17, commit `fe864d5` — 8 tests green):**
`scripts/lib/notify.py` (Tier 1 osascript/notify-send default-on; Tier 2 opt-in webhook
`CLAUDE_PLUGIN_OPTION_NOTIFY_WEBHOOK_URL`; gates: sev ≥ HIGH tunable, content-hash
dedupe, 24 h cap default 3 with a one-per-day digest fold; injectable runner/opener).
Daemon wirings: supervisor alert findings; the F4 primary-keychain-UNREADABLE
degradation (derived case d); task-quarantine entry (case a, fired exactly at the
threshold); the fleet github-config digest (re-pushes only when `findings_digest`
changes). Case (b) holds by construction — a chore yielded to the server never runs,
so the janitor never pushes for it. Case (c) tests: dedupe / severity gate /
cap+digest / webhook-never-without-URL / sanitized single-line shape all pinned in
`tests/test_notify.py`.

**Residual (honest):** `findings_ledger.record()`'s `notify` SEAM remains available but
no caller passes it yet — today no daemon path writes ANOTHER project's ledger (the
fleet audit is slug-keyed, not workdir-keyed), so the per-project no-live-session push
via the seam activates when such a producer appears. The three machine-level wirings
above cover every finding the daemon currently produces.

**NEXT ACTION:** human review; ships in v0.51.0.

## Design (staged, zero-config first)

New `scripts/lib/notify.py` used ONLY by the daemon (single-writer — never per-session, or N
sessions would stampede the channel with duplicates):

1. **Tier 1 — native desktop notification (DEFAULT ON, zero config):** macOS
   `osascript -e 'display notification …'` (Linux: `notify-send` when present). Best-effort,
   no secrets, works the moment this ships.
2. **Tier 2 — user-configured webhook (OPT-IN):** one generic HTTPS POST
   (`CLAUDE_PLUGIN_OPTION_NOTIFY_WEBHOOK_URL` via userConfig) — a single primitive covers
   Slack, Telegram (bot sendMessage URL), Discord, ntfy.sh, etc. No per-service SDKs, no
   stored tokens beyond the URL the user supplies. Email deliberately NOT built (SMTP
   credential handling ≫ value when a webhook covers it; revisit only on explicit ask).

**What pushes (severity-gated, anti-spam — all three required):**
- severity ≥ HIGH (security findings, a repo-compromise-class config gap, a daemon task in
  quarantine after repeated failures); AND
- content-hash dedupe (same finding never pushes twice; rolling 24 h digest cap, e.g. ≤3
  pushes/day, remainder folded into one digest line); AND
- **the PER-PROJECT no-live-session escalation rule (revised by the channeling directive):**
  routing is strictly per project. While the AFFECTED project has a live session, that
  session's own heartbeat is the channel (push only CRITICAL); when the affected project has
  NO live session, any ≥HIGH finding about it pushes to the human — naming that project, so
  the human opens THAT project's Claude. Never routed through another project's session,
  whatever is or isn't open. The daemon's fleet scan already maps sessions→projects every
  liveness beat, so "does repo X have a live session" is a fact it holds for free.

**Message shape:** one line — `[janitor] <severity> <code> on <repo/project>: <summary> —
open a Claude session there and run /janitor-github-config-fix` (the notification's job is to
get the human to START the right Claude, per the directive — never to carry the full report).

**DERIVED tasks:** (a) daemon task errors: push when a Task enters quarantine (failcount
threshold), not on every failure; (b) the ai-maestro server coordination — when the server
owns the chores (PZLVT2RN B2), IT owns the notification for them too; janitor pushes only for
chores it actually ran (add to the #100 contract enumeration); (c) tests: dedupe, severity
gate, zero-session escalation, webhook never called without the opt-in URL; (d) **the
daemon-cannot-read-primary-keychain condition** (TRDD-H7NVKSAX F4): the rotator logged
"primary live credential UNREADABLE" every minute for hours into rotator.log where nobody
looks — a PERSISTENT security-degradation finding that must reach the human via this
channel (the ACL re-grant needs the user; only they can fix it).

## Notes and lessons learned

[^1]: [id:ATOM-NOTF-HMN1, status:valid, keywords:"findings unread no session open daemon silent error unattended repo compromise notification", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT let a background guardian's findings terminate in a file only live agent sessions
  read, BECAUSE with zero sessions open for weeks a security finding stays invisible until
  the damage is done. DO give the always-alive process a severity-gated human channel.
