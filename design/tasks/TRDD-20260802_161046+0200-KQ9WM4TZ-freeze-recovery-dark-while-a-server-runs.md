---
trdd-id: KQ9WM4TZ
title: Standalone sessions have no freeze recovery while an ai-maestro server runs
column: todo
created: 2026-08-02T16:10:46+0200
updated: 2026-08-02T16:10:46+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
parent-trdd: 5ZVS1DDP
blocked-by: []
relevant-rules: []
implementation-commits: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**Not started. This is an EHT of TRDD-5ZVS1DDP — it handles a CONSEQUENCE of that card's
shipped work, so 5ZVS1DDP cannot reach `complete` until this is terminal.**

**The gap is LIVE on this host as of 2026-08-02 16:10.** Not a hypothetical.

### What is dark, and why

TRDD-5ZVS1DDP made the janitor daemon EXIT while an ai-maestro server is running (one daemon
per host — the owner's unconditional ruling: two daemons "will conflict and write at the same
time in the same files, corrupting them"). That is correct and verified in production.

But the daemon owned **freeze recovery** (`session-liveness` / `fleet-stop`) — the ONE chore
that **structurally cannot** move to a per-repo cron, because a frozen session's own cron is
exactly what has stopped. A session cannot recover itself. So while a server runs:

- the daemon is gone (verified: **0 janitor daemons**, `daemon_pid()` → None, heartbeat 36.5 h
  stale), and
- standalone `#N` sessions have **no freeze recovery at all** — silently.

Measured now: server pid **95175** (`~/ai-maestro/node_modules/tsx`), up **3 days**, liveness
probe 24.8 s fresh. So this machine has been without standalone freeze recovery for ~3 days.

**Why it is HIGH and not medium:** the failure is invisible from every surface. A frozen
session looks identical to a busy one, the daemon's absence is the *correct* documented
behaviour, and no detector reports "the recovery chore has no owner". It is the silent-disable
shape this project treats as a defect class — the same shape as the 14-day `keep-going-off`
sentinel and the `USER_PRESENT` cancel.

### The ask that is outstanding

ai-maestro **#79 item 1** — asked 2026-07-21, no confirmation recorded since. The question:
does the SERVER take over freeze recovery for standalone sessions while it runs?

### NEXT ACTION

1. **Check #79 for a reply first** (`gh issue view 79 --repo <ai-maestro>`). Do not re-ask; a
   duplicate ask is how this sat 12 days.
2. If they **confirm** → verify the server actually does it (do not take the claim on trust —
   freeze a scratch session and observe), then close this EHT.
3. If they **decline or stay silent** → build the stopgap here, per 5ZVS1DDP's own instruction:
   *"If they decline, keep a stopgap here rather than let it dark."* Shape to decide then; the
   constraint is that it must NOT resurrect a second daemon (that is the corruption 5ZVS1DDP
   exists to prevent). A per-repo cron cannot do it for its OWN session, but it CAN do it for a
   PEER session — mutual recovery across sessions is the obvious candidate and needs its own
   design pass.

**Do NOT "fix" this by making the daemon stay alive.** That reverts 5ZVS1DDP and reintroduces
the two-daemon corruption the owner ruled out unconditionally.

## Provenance

Split out of TRDD-5ZVS1DDP on 2026-08-02 while closing that card's soak condition. I had moved
5ZVS1DDP to `complete` on the strength of the soak alone and reverted it in the same session —
the soak was condition 1 of 3, and this was condition 2, eight lines below it. Filed as its own
card because it is a distinct atomic task with a different owner and a different trigger, and
because leaving it as a bullet inside a card being closed is precisely how it would have gone
dark permanently.
