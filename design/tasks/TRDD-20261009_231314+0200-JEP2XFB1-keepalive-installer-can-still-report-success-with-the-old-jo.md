---
trdd-id: JEP2XFB1
title: keepalive installer can still report success with the old job loaded, and its Linux check can fail falsely
column: testing
status: tasked
created: 2026-10-09T23:13:14+0200
updated: 2026-10-11T00:36:23+0200
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

- [x] install_macos distinguishes the new job from an old one that never left (for example by failing when the pre-bootstrap wait times out, or by comparing the loaded job's plist path or start time), with a test that fails on 1393ae8a.
- [x] install_linux retries is-active briefly before failing, with a test in the style of the existing ones.
- [x] The code comment says the bootout race is the likely cause, not the established one.
- [ ] ruff, mypy, pyright, uv run pytest and the strict validator pass on the commit.

## Approval log

- 2026-10-09T23:13:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-11T00:24:19+0200 — column → testing. built and gated; waits on the strict validator (box 4) and a release

## STATE

2026-10-11 00:24 (clock) BUILT, one commit with this line (TRDD-S6GX1DHN wave 23 card 3). (a) install_macos: when the job is still loaded after the 5 s wait that follows bootout, it prints that the previous job did not unload and the new plist was NOT applied, and returns 1 without calling bootstrap. (b) install_linux: after a successful enable it polls is-active up to 10 times 0.5 s apart; a failing enable still fails at once. (c) the comment calls the bootout race the likely cause. TESTS, 4 new in tests/test_keepalive_install.py with stand-in launchctl, systemctl and uname first on PATH: old job never unloads (red before the change), unit still activating (red before), never active and enable fails (both green before, so guards only). The ordinary macOS install is covered by the existing test_install_over_loaded_job_never_claims_installed_while_unloaded. That the two were red first is the worker report, not re-run by the main session. GATE on the uncommitted diff, read whole by the main session: ruff, mypy, pyright exit 0; 18379 passed, 2 skipped (reports/board/gate-jep2xfb1.txt). Box 4 stays open: the strict validator was NOT run and cannot pass on this host until the owner decides the validator item. LIMITS, from the reviews of the brief and of the diff, accepted and not cured: after a failed macOS install the old job keeps running with the new plist on disk, and how soon the caller retries was not traced (the caller, scripts/lib/launchd_keepalive.py, treats a failure as best-effort, captures the error line and allows 30 s); an unload slower than 5 s is now a failure where it was a false success; a loaded but crash-looping job still reads as installed; the uninstall path bootout is untouched; no test has a job that unloads late within the 5 s; the never-active test allows 8 s, tight on a loaded host; the new variable ok is global like the others in these two functions. FIELD CASE UNOBSERVED: both defects were read from code, and no Linux host has run this installer.
2026-10-11 00:36 (clock) CORRECTIONS from the review of 00cca2b0, accepted. Box 1 asks for a test that fails on 1393ae8a; the red run was on the working tree before this change, as reported by the worker, and was not run on that commit. Box 2: of the three Linux tests only the still-activating one was red first. Read whole holds for the script diff; the test diff was read as its added lines, cut at 170 characters. The commit subject is broader than the fix, since a loaded but crash-looping job still reports success. The never-unloads test adds about 5 s to the suite.
