---
trdd-id: 6054NY8H
title: The OAuth rotator stopped retrying 6h ago and re-broadcasts a stale network verdict it will never re-test
column: todo
created: 2026-08-21T14:11:01+0200
updated: 2026-08-21T14:20:00+0200
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

## ⏵ CAUSE FOUND IN SOURCE + STATE — 2026-08-21 14:20. **And it CORRECTS this card's premise.**

Read from `oauth-rotator/state.json` (non-secret metadata only — slot indices, no emails, no
tokens):

| slot | `refresh_failures` | `last_refresh_failure` | token expires in |
|---|---|---|---|
| #0 | 572 | **credential-dead** | **−191.9 h** (expired ~8 days ago) |
| #1 | 224 | **credential-dead** | **−237.6 h** (expired ~10 days ago) |
| #2 | 775 | network | **−160.5 h** (expired ~6.7 days ago) |

**THE CORRECTION, and it matters because this card was filed partly on the opposite premise:**
only **ONE of three** slots last failed on the network. The other two recorded
**`credential-dead`** — for those the credential WAS judged, and it is dead. So
`session-start.log`'s advice to run `/janitor-refresh-cc-logins` is **RIGHT for slots #0 and
#1** and wrong only for #2. I generalised one slot's alert text ("do NOT re-login on this
evidence") to all three; that was an over-reach, and the state file refutes it.

**The mechanism, from source, not guessed:**
1. `rotator.py:2305` increments `refresh_failures` on EVERY failure, and its own comment says
   the recorded cause "is purely diagnostic and must NEVER change the escalation counter".
   So 775 network failures count exactly like 775 revocations.
2. `DEFAULT_MAX_REFRESH_FAILURES = 3` (`cascade.py:57`). All three slots are 74×–258× past it,
   so the cascade classifies every one as dead-refresh.
3. The runway gate at `rotator.py:2288` (`eh > KEEPALIVE_AHEAD_H`, 6 h) is **NOT** what stops
   the attempts — every token is already EXPIRED, so `eh` is deeply negative and inside the
   window. Something upstream skips these slots before keepalive is reached. That last hop is
   the one piece still unread.
4. `rotator.py:1888` documents this trap already: a rescued slot "would otherwise keep
   `refresh_failures >= max` forever (keepalive skips it: a freshly-refreshed token is outside
   `KEEPALIVE_AHEAD_H`, so it never re-runs the reset)". The reset exists; the path to it does
   not, for a slot in this state.

**So the headline is bigger and simpler than "a stale verdict": all three accounts' tokens
expired 6.7–10 days ago and the automatic refresh path is exhausted for all of them.** Two need
a human re-login. The stale-verdict defect is real but is now the SECOND finding, not the first.

Distinct from [[TRDD-A8DPTDOU]], which is about two alert KEYS describing one condition. This
card is about a state machine that latched and a verdict that is never re-tested. Fixing the
key hygiene would not fix this, and vice versa.

## Acceptance

- [x] The cause of the stall is identified from evidence (which loop, which state), not guessed
      — see the CAUSE FOUND section: the counter is cause-blind by design, max is 3, all three
      slots are 74x-258x past it, and every token expired 6.7-10 days ago. One hop still unread:
      exactly where a dead-refresh slot is skipped before keepalive.
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
