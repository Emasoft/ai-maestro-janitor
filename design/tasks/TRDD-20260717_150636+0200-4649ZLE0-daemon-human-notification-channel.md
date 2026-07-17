---
trdd-id: 4649ZLE0
title: Human-notification channel for daemon findings when no session is alive
column: todo
created: 2026-07-17T15:06:36+0200
updated: 2026-07-17T15:06:36+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
severity: high
related-trdd: [PZLVT2RN, 157OH2D7]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-17

**USER DIRECTIVE (2026-07-17, verbatim):** *"if the claude instance of that project is not
executed for weeks, any error will remain undetected and unchecked, with the serious risk of
compromising the repo. You should at least report any error and any output of the sevurity
scanners to the human, maybe via some notification or email/telegram/slack/etc. so the human
will start the claude code instance interested by the iseue and tell the claude to fix it."*

**The gap, precisely:** the daemon's machine-wide chores (fleet github-config audit, its own
task failures/quarantines, security-relevant findings) surface ONLY through per-session
heartbeat detectors. Any LIVE session surfaces the whole fleet's findings — so one open
session anywhere suffices — but with ZERO live sessions the findings sit unread in
`fleet-github-audit.json` + `daemon.log` indefinitely. The one process guaranteed alive (the
daemon) has no path to a human.

**NEXT ACTION:** implement after v0.50.0 ships (kept out of the architecture release
deliberately — this is its own feature with its own blast radius).

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
- **the no-live-session escalation rule:** while ≥1 janitor session is alive the heartbeat is
  the channel (push only CRITICAL); with ZERO live sessions ANY ≥HIGH finding pushes — that
  is exactly the user's "nobody is watching" scenario. The daemon already scans the fleet
  every liveness beat, so "zero sessions alive" is a fact it holds for free.

**Message shape:** one line — `[janitor] <severity> <code> on <repo/project>: <summary> —
open a Claude session there and run /janitor-github-config-fix` (the notification's job is to
get the human to START the right Claude, per the directive — never to carry the full report).

**DERIVED tasks:** (a) daemon task errors: push when a Task enters quarantine (failcount
threshold), not on every failure; (b) the ai-maestro server coordination — when the server
owns the chores (PZLVT2RN B2), IT owns the notification for them too; janitor pushes only for
chores it actually ran (add to the #100 contract enumeration); (c) tests: dedupe, severity
gate, zero-session escalation, webhook never called without the opt-in URL.

## Notes and lessons learned

[^1]: [id:ATOM-NOTF-HMN1, status:valid, keywords:"findings unread no session open daemon silent error unattended repo compromise notification", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT let a background guardian's findings terminate in a file only live agent sessions
  read, BECAUSE with zero sessions open for weeks a security finding stays invisible until
  the damage is done. DO give the always-alive process a severity-gated human channel.
