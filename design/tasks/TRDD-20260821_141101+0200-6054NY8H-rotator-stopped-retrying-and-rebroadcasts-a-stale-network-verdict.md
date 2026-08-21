---
trdd-id: 6054NY8H
title: The OAuth rotator stopped retrying 6h ago and re-broadcasts a stale network verdict it will never re-test
column: todo
created: 2026-08-21T14:11:01+0200
updated: 2026-08-21T14:11:01+0200
current-owner: janitor-main-session
task-type: bugfix
project-id: ai-maestro-janitor
scope: project
severity: major
priority: high
approval-tier: 0
labels: [oauth-rotator, alerts, self-heal]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# The rotator gave up, kept the reason, and stopped checking whether it still applies

## Measured 2026-08-21 14:05, three independent facts that only make sense together

**1. The failure count is FROZEN.** `775 refresh exchanges failed` appears **28 times** in
`oauth-rotator/rotator.log`, first at **07:08:03**, last at **13:48:06** — **6 h 40 m**, and the
number never moves. A counter that is genuinely accumulating failures increments.

**2. Nothing is being attempted.** In the last hour the log contains **zero** non-alert lines:
no exchange, no success, no failure. Only the same alert re-emitted every ~10 minutes.

**3. The network reason it cites is NOT TRUE ANY MORE.** The alert says *"the last one failed
on the NETWORK (timeout/DNS/connection) — the credential itself was never judged. Retryable:
chase the transport, do not re-login on this evidence."* Measured just now from this host:

| host | DNS | TLS | HTTP |
|---|---|---|---|
| `api.anthropic.com` | 8 ms | 47 ms | 404 (a bare HEAD — normal) |
| `claude.ai` | 8 ms | 47 ms | 403 (normal) |
| `platform.claude.com` | 8 ms | 47 ms | 200 |

The transport is healthy. The rotator will never discover that, because it is not retrying.

## Why this is worse than the noise it looks like

The alert is **plausible, specific, and stale**, which is the worst combination: a reader
chasing "the transport" finds nothing wrong and concludes the alert is flapping noise. The real
state is that **OAuth rotation is OFF** — the safety net that keeps an unattended session alive
across a rate limit — and the channel reports it as a retryable transport blip.

It also actively contradicts the other channel: `session-start.log` says *"run
`/janitor-refresh-cc-logins`"* for three accounts, while this one says *"do NOT re-login on this
evidence."* One of them is wrong for the current state, and today it is both — the credentials
were never judged, AND the transport is fine.

## What is NOT claimed

Why it stopped retrying is UNKNOWN — a dead retry loop, an exhausted backoff with no ceiling
reset, a latched terminal state, or a supervisor that stopped scheduling the tick. Do not guess:
the frozen count and the empty log are symptoms, not a diagnosis. The tick process itself IS
alive (the log's own mtime advances with each alert re-emission), so "the daemon is dead" is
already ruled out.

Distinct from [[TRDD-A8DPTDOU]], which is about two alert KEYS describing one condition. This
card is about a state machine that latched and a verdict that is never re-tested. Fixing the
key hygiene would not fix this, and vice versa.

## Acceptance

- [ ] The cause of the stall is identified from evidence (which loop, which state), not guessed
- [ ] A cited failure reason is RE-TESTED before it is re-broadcast — an alert that repeats an
      unverified verdict for 6 h is the defect, independent of whether retrying resumes
- [ ] Retry resumes on its own once the cited cause clears, with a bounded backoff that has a
      reset path — no human action required to un-latch it
- [ ] A test that latches the failure, clears the underlying cause, and asserts the rotator
      retries and the alert clears WITHOUT intervention. It must be RED on today's code
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`

## Notes

Found while chasing the alert text from TRDD-A8DPTDOU rather than the alert count. The count
being frozen at one value for 6 h 40 m is the whole finding, and it is invisible unless you
compare occurrences instead of reading the newest line.

## Approval log
