---
trdd-id: LRGZV19Z
title: the global daemon inherits the working directory of the session that spawned it
column: backburner
status: tasked
created: 2026-10-05T08:14:00+0200
updated: 2026-10-05T11:17:52+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T08:14:00+0200
parent-trdd: 0QCRG2YX
---

# the global daemon inherits the working directory of the session that spawned it

## Problem

A machine-wide daemon is started by whichever session first needs it, without an explicit working directory or environment, so it keeps that session's folder for its whole life. Measured on 2026-10-05: a daemon about 17 hours old had a working directory that had since been deleted. Its child `claude agents --json` then exited 1 on every scan (fixed for that one call under TRDD-0QCRG2YX by giving the call its own directory).

## What is exposed

About 70 child-process calls reachable from the daemon pass no working directory; only the agent-roster call was run from a deleted directory, the rest are untested. The project-root resolver runs git with no explicit directory and then falls back to the current directory, which raises in a deleted one; its results feed the findings ledger, the ticket store, the user-intent store and the requirements lookup. The launch agent sets no working directory either, so the launchd daemon runs from the filesystem root.
The agent-roster fix falls back to the root of the drive that holds the plugin when the home directory cannot be resolved; on a host where that is a removable drive this is the same class of fault, on its rarest path.

## Why not a plain change of directory at start

A session-spawned daemon works out its project from the folder it inherits. The resolvers for project root, janitor root, state directory and log directory are cached process-wide and the first call wins, so a change of directory before their first call silently moves the daemon's state directory, and one after it is safe only if all of them have already been called and nothing clears the cache at runtime.

## Candidate shape (NOT decided)

At daemon start, call the cached resolvers once so their answers are fixed, then change to the global-state directory. Separately pass an explicit working directory when a session spawns the daemon, which is the only fix for a daemon spawned from an already-deleted folder. To check first: any runtime call that clears those caches or resolves a project without them; whether any daemon task needs to run in a project folder; behaviour on each platform.

## Acceptance

A daemon whose spawning folder is deleted keeps scanning with no child failing for that reason, shown by a test that removes the folder under a running daemon; the daemon's state and log locations are unchanged for both launch paths.

## Approval log

- 2026-10-05T08:14:00+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-05 — premise to re-check: the daemon log shows an OS respawn on 2026-10-04 (exit for respawn when a newer version was staged, start a minute later). Two launch paths may exist (the launch agent, and a session starting the daemon when none runs); which produced a given process decides its working directory. Read the running daemon's parent process and working directory before building on this card.
