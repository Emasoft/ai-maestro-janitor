---
trdd-id: 0SU2C2IM
title: Automatic re-login of a dead account slot is always on
column: todo
status: tasked
created: 2026-10-04T09:49:52+0200
updated: 2026-10-04T09:49:52+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-04T09:49:52+0200
---

# Automatic re-login of a dead account slot is always on

OWNER DECISION 2026-10-04, verbatim: "never stop the automatic relogin". Asked in the same conversation: "do you want the background service to open Chrome and re-capture a dead login on its own?"

Context. On the night of 2026-10-04 two spare account slots were credential-dead (refresh refused) while each account's claude.ai web session cookie was valid until 2026-10-22. The rotator logged `cascade: renew-cookie=...` on every tick and did nothing: `_bootstrap_seeded_slots` in scripts/oauth_rotator/rotator.py only launches `slot_capture_browser.py` when the daemon environment has CLAUDE_ROTATOR_AUTO_BOOTSTRAP truthy, and it defaults to OFF (card 5OJX3SCF, "surprise headful Chrome"). The owner rotated by hand. Evidence: reports/oauth-rotator/20261004_094111+0200-cookie-leg-recon.md and reports/oauth-rotator/20261004_092844+0200-rotation-failure-1004-recon.md.

Requirement. The automatic re-login (cookie leg) runs by default in the daemon tick whenever a slot is eligible. It must not depend on an environment variable being set by hand.

Open points to settle in design, not decided by the owner's sentence: (1) whether an explicit CLAUDE_ROTATOR_AUTO_BOOTSTRAP=0 stays as an emergency off switch; (2) the per-slot launch cap ROTATOR_MAX_BOOTSTRAP_LAUNCHES (3) also stops re-login after three tries, so decide whether it resets on a time basis; (3) a headful Chrome opening unattended (locked screen, Cloudflare) is unverified; (4) capturing the LIVE account mints a new grant and may evict the running session's own grant, so the live account stays excluded; (5) skills/janitor-refresh-cc-logins/SKILL.md step 4 and memory atom ATOM-LTOX-A05P say auto-bootstrap is opt-in and must be updated.

Verify. With a credential-dead spare slot and a valid web session cookie, one daemon tick with NO environment variable set logs an `auto-bootstrap:` launch line and the slot is re-filed; a test asserts the default.

Related: supersedes the default chosen in TRDD-5OJX3SCF; parent umbrella TRDD-JSQSJ3PZ.

## Approval log

- 2026-10-04T09:49:52+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
