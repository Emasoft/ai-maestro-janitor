---
trdd-id: KM0XVVV8
title: Resolve the auto-compact window from settings in one shared place
column: backburner
created: 2026-09-18T06:25:16+0200
updated: 2026-09-18T06:36:25+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: refactor
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-18T06:25:16+0200
---

# Resolve the auto-compact window from settings in one shared place

The settings.json env merge exists only inside harness_will_autocompact; min_context_tokens's other callers read os.environ only, so off-session (e.g. launchd) callers can compute a different floor than guard 2. Move the merge into token_meter.predict_auto_compact or a shared helper.

## Approval log

- 2026-09-18T06:25:16+0200 — MANDATE issued by Emasoft (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-18T06:36:21+0200 — correction: minted by a janitor-main-session worker under the user's general go-ahead, not a mandate for this specific card; the 06:25:16 MANDATE line was the tool's default attribution.
