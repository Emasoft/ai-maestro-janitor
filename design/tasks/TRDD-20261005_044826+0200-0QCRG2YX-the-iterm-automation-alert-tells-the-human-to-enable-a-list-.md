---
trdd-id: 0QCRG2YX
title: The iTerm Automation alert tells the human to enable a list entry that macOS may never have created and repeats on every heartbeat
column: dev
status: tasked
created: 2026-10-05T04:48:26+0200
updated: 2026-10-05T05:56:42+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T04:48:26+0200
implementation-commits: [47f2abe6]
---

# The iTerm Automation alert tells the human to enable a list entry that macOS may never have created and repeats on every heartbeat

## Report (2026-10-05, relayed by another Claude session on this machine as the owner's words; not verified as typed by the owner in this session)

The heartbeat prints on every fire, for hours, the HUMAN-ONLY alert that the global daemon sees iTerm running but enumerated zero iTerm sessions via osascript, with the second view reporting probe-failed exit 1. Its remedy says to open System Settings, Privacy and Security, Automation and allow the Python runtime that made the call to control iTerm.

Relayed quote: "unfortunately there is no way to add binaries manually. macos only add those permissions if detect an attempt and open a dialog asking the user to allow or not. only then it adds the program to the list."

So the Automation pane has no add control. An entry exists only after macOS itself showed its consent dialog for that exact binary. If the dialog never appeared for the daemon's runtime there is nothing to switch on, and the alert repeats with no action the human can take.

## Observed in this project's own session on 2026-10-05

The same alert text was printed by the dispatcher on more than twenty consecutive heartbeat fires of one session between about 02:20 and 04:30, first in the form naming a cron_dead instance and "5 of 6 scanned instance(s) have NO channel", later in the form "enumerated ZERO iTerm sessions". The remedy sentence is built in scripts/dispatch.py near line 2603.

## Earlier cards that this report contradicts or reopens (all terminal, so this is a new card)

- TRDD-VQ4LX7ND (complete): already noted that the consent prompt cannot be surfaced by a headless agent and must be solicited from a foreground context, and left open whether a login agent can raise the prompt at all.
- TRDD-EZ3PMQYX (complete): the alarm must branch on the daemon's launch context; launchd-spawned means the grant remedy cannot succeed.
- TRDD-KU3ERYFX (complete): a human-only alarm must say so and emit once.
- TRDD-DB1P25S4 (published): run the daemon under the signed python.org 3.12 so the existing grant applies.
- TRDD-9PDH8G0W (complete): the unconditional-negative discriminator.

## Not verified (do not treat as fact)

- Whether the cause on this machine is a denied grant, a grant never requested, or a hung osascript; the alert itself says more than one fits.
- How the daemon was launched when the alert fired, and whether a consent dialog was ever shown for that binary.
- Whether the EZ3PMQYX branch and the KU3ERYFX emit-once rule are present in the installed plugin version and simply did not apply to this form of the alert, or have regressed.
- From the relaying session, untested: a background process that is not the responsible app of a desktop session usually gets a silent refusal instead of a dialog; a call made from a terminal is attributed to the terminal app; resetting the Apple Events decisions re-arms the prompt at the cost of every app's Automation choices. No such reset was run.

## What the report asks for

1. Reword the remedy: say that the entry appears only after macOS prompts, say how to make the prompt appear for the daemon's runtime or state plainly that it cannot be made to appear from a detached daemon if that is what is found, and give tmux as the working alternative.
2. If it can be told apart, name one cause: no entry was ever created, versus an entry that exists and is off.
3. Do not repeat the full alert on every fire while nothing changed.

## First step

Read the alert builder in scripts/dispatch.py and the launch-context branch added for TRDD-EZ3PMQYX, and establish from the dispatcher's own state why an emit-once human-only alert printed on every fire. No fix is proposed yet.

## Approval log

- 2026-10-05T04:48:26+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-05: The owner confirmed in the project session: decide yourself, go on, and solve the iTerm control problem by investigating the Apple documentation. So this card is assigned and in progress.
2026-10-05 CORRECTIONS to the body: (a) the claim that the Automation list has no add control was affirmed on the relayed text, not checked on this machine; (b) the "contradiction" with earlier cards is not established, because only fifteen lines of TRDD-VQ4LX7ND and the titles of the other four were read; in particular what "emit once" means in TRDD-KU3ERYFX is unread; (c) the alert was seen on 25 consecutive heartbeat fires of one session (7 in the cron_dead form, then 18 in the zero-sessions form), starting with the second fire; the time range in the body is an estimate; (d) the session-start findings ledger already showed the same finding seven times in the previous thirty minutes with identical evidence, so the repeat predates that session; (e) the alert already offers tmux and already says it cannot tell its two causes apart; (f) the alert says "check the evidence age below" and prints no evidence age.
2026-10-05 APPLE DOCUMENTATION (CoreServices, AE framework header AppleEvents.h, macOS 10.14 and later; function AEDeterminePermissionToAutomateTarget): a process can ask whether it may send Apple events to a RUNNING target application without sending one. With askUserIfNeeded false it returns noErr when permitted, errAEEventNotPermitted (-1743) when the user refused, errAEEventWouldRequireUserConsent (-1744) when the user was never asked, and procNotFound (-600) when the target is not running. With askUserIfNeeded true the system asks the user itself. The header says not to call it on the main thread because it can block while the user is prompted. Passing the wildcard class and id asks about every event. This gives the one-named-cause the report asks for, and the supported way to raise the consent dialog for the exact binary.
2026-10-05 MEASURED on the machine where the alert fired, with a ctypes call to that function and askUserIfNeeded false: the daemon's Python (the python.org framework 3.12, signed, identifier org.python.python) is PERMITTED to automate iTerm, both from a session shell and from a temporary launchd job started the way the daemon's launch agent starts it. So a missing or refused Automation grant is NOT the cause there, and the alert's remedy points at a setting that is already correct.
2026-10-05 MEASURED: the daemon's own session-listing AppleScript (fleet_scan._ITERM_TTY_OSASCRIPT) returned exit 0 and 30 sessions in under two seconds from a session shell and from a temporary launchd job. The installed plugin's fleet_scan.py is byte-identical to the repository's.
2026-10-05 MEASURED: the flag file said probe_outcome "error (after 3 attempts)" and second_view "probe-failed:exit-1". Two daemon processes were running, both about sixteen hours old: the launchd keepalive entry, and a daemon.py from the plugin cache that had been spawned by a session and reparented to launchd. That second process's working directory no longer exists (it was under the user's Trash). Which of the two runs the fleet scan was NOT established.
2026-10-05 MEASURED, explains the second view: from a process whose working directory was deleted, `claude agents --json` exits 1 at once with "The current working directory was deleted"; from a valid directory it exits 0.
2026-10-05 NOT EXPLAINED: why the daemon's osascript attempts report "error". From a deleted working directory under the system temp folder, osascript still returned exit 0 and the full listing. In the unified log the daemon's three attempts (two and four seconds apart, matching the retry backoff) are indistinguishable from a successful run. The probe (_run_probe_outcome in scripts/lib/fleet_scan.py) discards the exit code detail and all error text and turns any exception into "error", so the daemon cannot say what failed.
2026-10-05 CANDIDATE mechanisms not yet separated: a nonzero exit from the AppleScript for a reason the log does not show; an exception in subprocess.run such as a text decoding error under the daemon's locale; the scan being run by the other daemon process; a deleted working directory under a privacy-protected folder behaving differently from one under the temp folder; the long-running process holding older code than is on disk.
2026-10-05 INTENDED FIX, to be put forward for review before any code changes: (1) the probe records the real exit code, the first line of error text and the exception type, and the alert prints them; (2) every probe subprocess runs with an explicit working directory that always exists, and the daemon changes to such a directory at start; (3) when iTerm is running and the listing comes back empty, the daemon calls AEDeterminePermissionToAutomateTarget with askUserIfNeeded false and the alert states permitted, refused, or never asked, offering the grant remedy only for refused and the prompt-raising step only for never asked; (4) the alert is reworded and, if TRDD-KU3ERYFX means once per unchanged evidence, it stops repeating on every fire.
2026-10-05 NOT DONE on the host: no reset of Automation decisions, no settings change, the stale daemon was not restarted. Two temporary launchd jobs were loaded and removed, and the system privacy log was read.
2026-10-05 NEXT ACTION: read what the background watcher caught of the daemon's next scan (parent and working directory of its osascript child); read TRDD-KU3ERYFX and TRDD-EZ3PMQYX whole; then put the four-part fix forward for review.
2026-10-05 MEASURED by watching the next scan: the process that runs the fleet scan is the session-spawned daemon.py from the plugin cache, not the launchd keepalive entry. Its osascript children were caught twice with that daemon as parent, and each child's working directory was the daemon's own one under the user's Trash, which a shell cannot see (deleted, or not readable without Full Disk Access; not separated). So "which of the two runs the scan" is now established, and a working directory that is gone or unreadable is the leading candidate for the osascript error; it differs from the temp-folder reproduction only in being under a privacy-protected folder.
2026-10-05 05:15 MEASURED 2026-10-05 05:04-05:10 (a local measurement report (gitignored)): the session-spawned daemon (plugin cache 3.7.0 scripts/daemon.py, about 16.5 h old) holds the singleton lock and is the only live worker; the launchd standby (daemon_keepalive_entry.py --keepalive under the launchd agent, working directory /) is a standby blocked on the same lock.
2026-10-05 05:15 The working directory of the session-spawned daemon was under the user's Trash and is deleted: ls on its parent returns "No such file or directory", not "Operation not permitted".
2026-10-05 05:15 CORRECTION of the earlier reading: the deleted working directory explains only the second view. `claude agents --json` exits 1 with "The current working directory was deleted" from a deleted directory, and exits 0 from an existing one. It does NOT explain the osascript failure: the same probe script returned 30 sessions with exit 0 and empty stderr from a normal directory, from a directory inside the Trash, and from a deleted directory inside the Trash. The reproduction ran from a shell inside an iTerm session, not from a detached process.
2026-10-05 05:15 The cause of the osascript error inside the session-spawned daemon is NOT ESTABLISHED. A 20-minute unified log extract (37555 lines) holds no Apple-event denial and none of the errors -1743, -1744, -600, -10810 for osascript. The daemon code discards the child's exit code and stderr, so the running process cannot tell us more. The log check was partial: a keyword search of the extract found only unrelated App Store receipt messages for osascript.
2026-10-05 05:15 The privacy database holds an allowed Apple-events row for the Python binary the standby runs (auth_value 2, target iTerm). No evidence either way that a launchd-started Python has sent Apple events to iTerm. Qualifiers: only the first 20 rows were read, no row names the Python.app bundle path, and how macOS attributes a launchd-started instance was not measured, so a consent dialog or a silent refusal after a restart is possible.
2026-10-05 05:15 fleet_scan.py and daemon.py are byte-identical (shasum) in the plugin data scripts folder, the 3.7.0 cache and the repository, so a restart changes no code. The scan runs in the daemon task session-liveness every 120 s and is not in the list of chores yielded to the ai-maestro server. The flag is rewritten on every blocked scan and removed on a healthy one; it is not latched. Not verified: that the standby's in-memory copy matches the file on disk, which was written seconds after the standby started.
2026-10-05 05:15 daemon.py has no chdir, no getcwd and no check that its own directory still exists; SIGTERM is handled and releases the lock and the pid file; there is no dedicated stop command.
2026-10-05 05:15 A plain terminate signal to the session-spawned daemon, so the launchd standby would take over, was attempted at 05:15 and refused by the Claude Code permission classifier; no signal was sent.
2026-10-05 05:15 Review of the restart proposal (adversarial fork, 05:10): the restart changes working directory and responsible process together, so its result must be read from the new daemon's flag content (probe_outcome and second_view), not from the alert's presence; no forced kill.
2026-10-05 05:25 — review of the attempted restart: a restart is expected to cure only the second view, would destroy the only live reproduction of the osascript failure, and cannot be undone; it is NOT recommended until the probe records its real error. Fix order decided: first and alone, the probe records exit code, error text and exception type; then an explicit working directory for the second view, at daemon start and at spawn, described as fixing the second view only; alert wording states the measured outcome and drops the Automation remedy; the repetition is a separate defect with a cause read from the code (the flag is rewritten on every scan because the change comparison ignores only the evidence-age field while three other fields are patched in afterwards, and the heartbeat hashes the whole file) and gets its own change. The earlier idea that the daemon exits when its directory has gone is dropped: a start-time change of directory makes it unnecessary.
2026-10-05 — first code change: the iTerm probe now writes its real failure to the daemon log (exit code, trailing AppleScript error number, cleaned error text, exception type, resolved osascript path; also the timeout and the exit-0-with-no-output cases). Return shapes, the flag file and the alert are unchanged. It takes effect in a daemon only after a publish and a daemon restart. Next: the second view discards its error text in the same way and runs without an explicit working directory.
