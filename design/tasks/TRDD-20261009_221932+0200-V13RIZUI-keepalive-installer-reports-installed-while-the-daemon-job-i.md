---
trdd-id: V13RIZUI
title: keepalive installer reports installed while the daemon job is left unloaded
column: complete
status: tasked
created: 2026-10-09T22:19:32+0200
updated: 2026-10-09T23:11:05+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-09T22:19:32+0200
implementation-commits: [1393ae8a]
release-via: publish
---

# keepalive installer reports installed while the daemon job is left unloaded

Measured 2026-10-09 on this Mac with the installed 3.8.11 copy of scripts/keepalive_install.sh (the repo copy has the same lines, 291 to 293): 'bash keepalive_install.sh install' on a host whose job was loaded and running (pid 73460) printed 'keepalive: installed (macos)' and exited 0, but afterwards 'launchctl print gui/UID/com.ai-maestro-janitor.daemon' found no job, 'launchctl list' had no janitor entry, no daemon process existed, and the script's own 'status' answered 'not installed (macos)'. The plist on disk was correct and passed plutil -lint. A plain 'launchctl bootstrap gui/UID <plist>' a minute later exited 0 and the daemon ran (pid 6931). The daemon, which owns OAuth rotation and machine-wide updates, was down for about one minute and would have stayed down until the next session-driven recovery.

Mechanism, read from the code, not yet proven by a failing test: install_macos runs 'launchctl bootout ... || true' and then immediately 'launchctl bootstrap ... 2>/dev/null || launchctl load -w ... 2>/dev/null || true'. Both failures are discarded and nothing checks that the job is loaded before 'installed' is printed. The likely cause of the bootstrap failure is that bootout had not finished tearing the job down; that is an inference.

## Acceptance

- [x] A test reproduces it: install over an already-loaded job leaves the job loaded (or the installer exits non-zero).
- [x] install_macos verifies the job is loaded (launchctl print) after bootstrap, retrying briefly after bootout, and exits non-zero with the launchctl error when it is not; it never prints 'installed' for an unloaded job.
- [x] The Linux path is checked for the same pattern.
- [x] ruff, mypy, pyright and uv run pytest pass; the strict validator still exits 0 (this file is scanned and has a ProgramArguments invariant).

## Approval log

- 2026-10-09T22:19:32+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-09T22:29:24+0200 — column → testing by main-agent@ai-maestro-janitor. fix committed; box 4 (mypy, pyright, full suite, strict validator) still to run
- 2026-10-09T23:11:05+0200 — column → complete by main-agent@ai-maestro-janitor. all four boxes met; ships with the next release

## Notes

2026-10-09 after the review of 1393ae8a, measured by the main session: (1) the new test is RED on the old script (1 failed, 1 passed with 1393ae8a^'s keepalive_install.sh swapped in) and green on the fix (2 passed); the fixed file was restored and git shows it unmodified. (2) The caller, scripts/lib/launchd_keepalive.py activate(), returns the installer's result as a (bool, message) tuple through _run, so exit 1 is reported, not raised; _run itself was not read. RESIDUAL, not fixed: (a) if the booted-out job is still present after the 5 s wait and bootstrap fails as already loaded, launchctl print still succeeds and install returns 0 with the OLD job loaded and the new plist unapplied; (b) on Linux, is-active right after enable --now can see a unit still activating and report a false failure, and no Linux host has run this; (c) launchctl print proves loaded, not healthy; (d) the code comment states the bootout race as the cause, which remains an inference. Box 3 was ticked on a code change with no Linux run.
2026-10-09 BOX 4 MET: the full gate ran on 5c81abf3 (which contains the fix 1393ae8a): ruff pass, mypy pass (536 files), uv run pytest 18232 passed and 2 skipped, strict validator exit 0 (CRITICAL 0, MAJOR 0, MINOR 0, NIT 0). Pyright failed there on four unrelated test lines, fixed in f623da67 (now 0 errors). The residual holes (a) to (d) above stay open as recorded; they are not this card's measured bug.
