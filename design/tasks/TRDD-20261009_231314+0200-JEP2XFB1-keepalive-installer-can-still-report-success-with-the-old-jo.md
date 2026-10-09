---
trdd-id: JEP2XFB1
title: keepalive installer can still report success with the old job loaded, and its Linux check can fail falsely
column: todo
status: tasked
created: 2026-10-09T23:13:14+0200
updated: 2026-10-09T23:13:14+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-09T23:13:14+0200
---

# keepalive installer can still report success with the old job loaded, and its Linux check can fail falsely

Residue of TRDD-V13RIZUI (fix 1393ae8a), recorded there as notes and moved here so it outlives that card's archiving. Both items are read from the code, not observed.

(a) macOS false success: install_macos waits up to 5 s for the booted-out job to vanish. If the job is STILL present after the wait, bootstrap fails as already loaded, the load -w fallback fails too, and the following launchctl print succeeds because the OLD job is loaded, so the function returns 0. The new plist on disk is not applied and the installer prints installed. Same class as the bug V13RIZUI fixed: success claimed for a state that was not checked.

(b) Linux false failure: install_linux runs systemctl --user enable --now and then is-active --quiet at once. A unit still in activating reads as not active, so a healthy install can exit 1. No Linux host has run this code.

Also: launchctl print proves loaded, not healthy (a crash-looping job still prints); and the code comment states the bootout race as the cause of the original failure, which was an inference.

## Acceptance

- [ ] install_macos distinguishes the new job from an old one that never left (for example by failing when the pre-bootstrap wait times out, or by comparing the loaded job's plist path or start time), with a test that fails on 1393ae8a.
- [ ] install_linux retries is-active briefly before failing, with a test in the style of the existing ones.
- [ ] The code comment says the bootout race is the likely cause, not the established one.
- [ ] ruff, mypy, pyright, uv run pytest and the strict validator pass on the commit.

## Approval log

- 2026-10-09T23:13:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
