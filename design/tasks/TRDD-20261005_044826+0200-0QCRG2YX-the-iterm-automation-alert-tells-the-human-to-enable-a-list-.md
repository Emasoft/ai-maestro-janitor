---
trdd-id: 0QCRG2YX
title: The iTerm Automation alert tells the human to enable a list entry that macOS may never have created and repeats on every heartbeat
column: todo
status: tasked
created: 2026-10-05T04:48:26+0200
updated: 2026-10-05T04:48:26+0200
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
