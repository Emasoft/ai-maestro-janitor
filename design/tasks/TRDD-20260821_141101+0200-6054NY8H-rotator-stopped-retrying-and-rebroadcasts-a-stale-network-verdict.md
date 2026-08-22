---
trdd-id: 6054NY8H
title: The OAuth rotator stopped retrying and re-broadcasts a stale verdict - component ownership unresolved
column: todo
created: 2026-08-21T14:11:01+0200
updated: 2026-08-22T11:12:16+0200
current-owner: janitor-main-session
task-type: bugfix
project-id: ai-maestro-janitor
scope: project
severity: major
deadline: 2026-08-30
priority: high
approval-tier: 0
labels: [oauth-rotator, alerts, self-heal, upstream-ai-maestro]
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
`session-start.log`'s advice to run `/janitor-refresh-cc-logins` is **RIGHT for slots #0
and #1** and wrong only for #2. I generalised one slot's alert text ("do NOT re-login on this
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

## ⛔ CORRECTION 2 — 2026-08-21 14:25. **THE JANITOR IS NOT RUNNING THIS CHORE.**

`global-state/daemon.log`, today:

```
04:45:33  chore-coordination: yielding to active ai-maestro server:
          ['github-config-audit', 'marketplace-refresh', 'oauth-rotator-supervisor',
           'oauth-rotator-ti…]
11:40:14  chore-coordination: server no longer confirmed active — resuming singleton chores
11:40:18  task 'oauth-rotator-tick' starting
11:40:18  task 'oauth-rotator-tick' done in 0s
11:40:23  chore-coordination: yielding to active ai-maestro server: [… same list …]
```

The janitor **yields `oauth-rotator-tick` AND `oauth-rotator-supervisor` to the ai-maestro
server**. It ran the tick exactly twice today — 04:45 and 11:40 — each in the brief window
before the server was re-confirmed active, each finishing in 0 s. Every alert line in
`rotator.log` is tagged **`aim-server/alert:`**, not the janitor's own.

**So the "stopped retrying" behaviour belongs to the SERVER's schedule, not the janitor's**, and
the month-old `oauth-rotator-tick.last-run.ts` stamp is not a dead daemon — it is exactly what a
healthy ABSORBED chore looks like (CLAUDE.md documents the identical pattern for
`version-update`: "for an absorbed chore a frozen janitor stamp is exactly what healthy
server-side execution looks like").

**This is the THIRD correction on this card, and the most consequential: I was reading janitor
source to explain behaviour the janitor is not performing.** The source findings above are still
TRUE of `rotator.py` — cause-blind counter, max 3, all slots far past it — but whether they are
the operative code path depends on an unanswered question.

**THE UNANSWERED QUESTION — now ANSWERED, 14:35.** It was: does the server INVOKE the janitor's
`oauth_rotator/rotator.py`, or run its own implementation that merely writes into the janitor's
`rotator.log`?

**The server has its OWN implementation.** `grep -rn "aim-server" scripts/ --include=*.py`
returns **nothing** — the string does not exist anywhere in the janitor's source. Every
`aim-server/alert: ONSET …` / `CLEARED …` line is written by code this repo does not contain.
(The five `CLEARED` hits a naive grep finds are unrelated prose inside comments in
`dispatch.py`, `ticket_proposal.py` and `global_state.py` — checked, not assumed.)

It writes into the janitor's OWN data dir
(`plugins/data/ai-maestro-janitor-ai-maestro-plugins/oauth-rotator/rotator.log`), which is why
the log looked like the janitor's all day and why three separate diagnoses went to the wrong
component.

**So the whole retry/alert behaviour on this card belongs to ai-maestro, not here.** The
`rotator.py` findings above describe code that is NOT the one running.

**Per `~/.claude/rules/how-to-fix-issues-of-other-projects.md` this is NOT mine to edit**, and
that rule requires stating the situation and WAITING for explicit direction rather than picking
a route. The two permitted routes, for the USER to choose:

1. **File an issue on `Emasoft/ai-maestro`** — recommended. The report is already written
   (frozen count, the 8 ms/47 ms transport measurement, the three slots' `refresh_failures` +
   `last_refresh_failure` + expiry), and the fix is a design call about whether a
   cause-blind failure counter should latch on transport errors.
2. **Fork → clone to `/tmp` → fix → PR.** Only if the USER asks for the patch itself.

**Neither has been done.** No issue filed, no comment posted — a shared `gh` identity means a
stray comment is indistinguishable from the owner speaking, so it waits for a word.

**What stays on THIS card even though the fix is upstream:** the misleading output lands in the
JANITOR's data dir and is read by janitor users as the janitor's own, and the janitor's
`session-start.log` amplifies it with contradictory advice. Whether the janitor should surface
a foreign component's alerts unlabelled is a question this repo owns.

## ⛔ CORRECTION 3 — 2026-08-21 16:10: **the cookie layer is ALIVE. Two slots need NO human.**

I reported "two accounts need a human re-login" from `last_refresh_failure: credential-dead`.
That field describes the **OAuth refresh token**, and I generalised it to the account. The
alert's own words were the ones to follow: *"a live claude.ai cookie can still mint these with
NO human; check the cookie layer before re-logging in."* **I never checked the cookie layer.**

Measured now (`safe_storage.retrieve(cv.COOKIE_KEYCHAIN_SERVICE, <email>)`, values redacted):

| slot | cookie jar | auth cookie | expires | verdict |
|---|---|---|---|---|
| #0 `fmu***` | **PRESENT** 15,242 B, 23 cookies | `sessionKeyLC` | **2026-08-30** | **VALID, +9.2 d** |
| #1 `ema***` | PRESENT 13,686 B, 21 cookies | `sessionKey` | 2026-08-20 | EXPIRED −0.9 d |
| #2 `ipa***` | **PRESENT** 15,242 B, 23 cookies | `sessionKey` | **2026-08-30** | **VALID, +9.2 d** |

The keychain is reachable (`detect_backend() == macos`, `keychain_denied_latched() == False`),
so nothing is blocking a read.

**So the fleet is NOT down to zero recoverable accounts.** Two slots hold live browser sessions
the cascade's `RENEW_COOKIE` leg is designed to mint fresh tokens from, with no human at all.
Only `ema***` genuinely needs a re-login, and only because its cookie lapsed **yesterday**.

**What that makes urgent:** the two live cookies expire **2026-08-30**. If whatever stopped the
cookie leg from running is not fixed before then, the no-human recovery path closes and all
three accounts become human-only. That is a 9-day clock, and it is the real deadline on this
card — not the refresh tokens, which are already dead.

**Why the leg is not running is UNKNOWN and belongs to ai-maestro** (correction 2): the server
owns `oauth-rotator-tick`, and the janitor's own copy of the cascade is not the code executing.

**Method note, because this is the third correction here:** each one came from reading a FIELD
and inferring the SYSTEM. `credential-dead` was true of the refresh token and false of the
account. The alert text named the thing to check and I did not check it.

## ⚠ `2d30dd7b` CITES THIS CARD BUT DOES NOT CLOSE IT — read this before trusting the commit log

Commit `2d30dd7b` ("the daemon finishes a 429 recovery the hook could not") carries
`TRDD-6054NY8H` in its subject, so a `git log --grep` makes this card look implemented. It is
not. That commit is USER decision #2 — a daemon-hosted `oauth-recovery` chore that services the
`recovery-requested.ts` marker the session hook can no longer finish once its own turn is
rate-limited. Adjacent subsystem, different defect.

**This card's defect is untouched by it:** the rotator LATCHES on a cited failure reason and
re-broadcasts that verdict for hours without ever re-testing it (measured: frozen at one value
for 6 h 40 m). A recovery chore that runs does not make a stale verdict fresh.

Recorded here because the citation is exactly the kind of thing that closes a card by accident:
the commit is real, it names the id, and nothing about it says "partial". Boxes 2-5 below are
genuinely open and the card stays in `todo`.

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
