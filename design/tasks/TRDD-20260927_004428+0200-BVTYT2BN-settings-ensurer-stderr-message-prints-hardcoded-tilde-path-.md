---
trdd-id: BVTYT2BN
title: settings-ensurer stderr message prints hardcoded tilde path even when HOME is redirected
column: backburner
status: tasked
created: 2026-09-27T00:44:28+0200
updated: 2026-09-27T00:44:28+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-09-27T00:44:28+0200
---

# settings-ensurer stderr message prints hardcoded tilde path even when HOME is redirected

Verified 2026-09-27 during the V12 matrix run: scripts/hooks/on-session-start.py:1093 prints '[ai-maestro-janitor] Updated N recommended setting(s) in ~/.claude/settings.json' with the tilde path HARDCODED in the message string, while the actual write target resolves at call time via settings_ensurer._settings_path (settings_ensurer.py:79, Path(home) if home else Path.home()) honoring a redirected HOME. Measured: in a V12 isolated run (fake HOME), stderr printed the '~/' message but the write landed in the fake home's .claude/settings.json (9 keys verified inside the scratch box) and the REAL ~/.claude/settings.json was untouched (mtime unchanged, zero key delta). Impact: wording-only - an operator or test reading stderr in any HOME-redirected context (tests, sandboxes, CI with HOME override) is told the wrong file was modified and may trust a false claim about their real config. The ensurer's safety design (verify-before-swap atomic write, lock-serialized, invariant-checked) is correct and untouched. FIX: one line - resolve the display path from the same source the writer uses (pass the resolved path into the message, or print the resolved absolute path) in on-session-start.py plus a one-test assertion that a redirected HOME produces a stderr naming the redirected path. Worker task: implement via fastedit, run the settings-ensurer test file plus ruff/mypy/pyright on scripts/, report path back. Related: TRDD-EQ792YPX (the ensurer's origin card).

## Approval log

- 2026-09-27T00:44:28+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
