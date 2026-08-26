---
trdd-id: 6054NY8H
title: The OAuth rotator stopped retrying and re-broadcasts a stale verdict - component ownership unresolved
column: todo
created: 2026-08-21T14:11:01+0200
updated: 2026-08-27T01:29:25+0200
current-owner: janitor-main-session
task-type: bugfix
project-id: ai-maestro-janitor
scope: project
severity: major
blocker-probe: bash ~/.claude/account-rotator/lifetime-status.sh
blocker-probe-canary: match:cookie/session
blocker-holds-if: match:ACTION DUE
priority: high
approval-tier: 0
labels: [oauth-rotator, alerts, self-heal, upstream-ai-maestro]
npt: []
eht: []
implementation-commits: [2d30dd7b]
relevant-rules: []
---

# The rotator gave up, kept the reason, and stopped checking whether it still applies

## ⛔ CORRECTION 4 — 2026-08-27 01:29: **the deadline is VOID and this card caused a false alarm to the USER**

**Everything below about dead refresh tokens and a 2026-08-30 cookie expiry is SUPERSEDED.** It
was true on 2026-08-21. The owner re-captured all three accounts on **2026-08-26 morning**, which
silently invalidated the whole card — and the card kept asserting the old state, in
`human_review`, with `deadline: 2026-08-30` in its frontmatter.

Measured just now, first-hand, read-only, no browser:

```
$ bash ~/.claude/account-rotator/lifetime-status.sh          # exit 0
ema***   27.4 d   refresh-capable (auto)   ok
fmu***           27.3 d   refresh-capable (auto)   ok
ipa***     27.4 d   refresh-capable (auto)   ok
✓ All accounts healthy; cookie vs OAuth lifetimes are staggered — nothing to do.
```

Corroborated by `oauth-rotator/state.json`: all three slots `captured_at: 2026-08-26T09:43 /
09:56 / 10:00`, `via: slot_capture_browser(full-oauth)`. Cookie lifetime ≈ **2026-09-23**, not
08-30.

**What that measurement does and does NOT prove — checked at the source, `lifetime-status.sh`
lines 80-105, not inferred from the column headers:**

| output | what it actually reads | strength |
|---|---|---|
| `27.4 d` | `cookie_days()` → sqlite `SELECT expires_utc … WHERE name='sessionKey'` on the live Chrome profile DB | **the thing itself**. The 08-30 deadline is dead on this evidence alone |
| `refresh-capable (auto)` | `bool(h.get("has_refresh"))` — **PRESENCE of a refreshToken string** | **a proxy**, structurally blind to `invalid_grant`. Cites nothing about validity |
| `refresh_failures: 0` | a counter the 08-26 re-capture RESET | **a proxy**. Zero failures can mean zero ATTEMPTS |

So: the **cookie** leg is proven live and that is what voids the deadline and the re-login ask.
The **refresh-token** leg is unproven in BOTH directions — and this card must not now assert
"the tokens are alive" from a reset counter, which would be the identical proxy-for-the-thing
error in the opposite direction. The peer flagged both traps (`refresh=yes` is presence; `tick`
returns before the candidate loop while usage is within limits, so a clean tick never exercises
the refresh path). Neither instrument can settle it; only an actual exchange can.

**The cost, and it landed on the USER.** This card's stale text was relayed to the ai-maestro hub
session, which relayed it to the owner twice and was about to have them re-do a full three-account
cookie re-login that was **not needed**. The owner stopped it. The bad datum originated HERE.

**Why it rotted invisibly:** the card stored the ANSWER ("tokens are dead, 3.1 days left") instead
of the QUESTION ("run `lifetime-status.sh`; the blocker holds iff it reports refresh-due"). An
answer has a silent timestamp; parking the card is exactly what stops anyone re-deriving it. The
frontmatter now carries `blocker-probe:` / `blocker-holds-if:` so the claim is re-runnable in one
second instead of re-read as current. `ACTION DUE` is the script's REAL failing-state banner
(`lifetime-status.sh:135`), read from source, not guessed — a first regex here was invented from a
single healthy run and matched nothing the script can emit, which is fail-open by construction.

**STILL DEFECTIVE, and it is the grammar, not this instance:** `blocker-holds-if: match:<regex>`
is a TWO-VALUED predicate. A timeout, a non-zero exit, a missing script and an empty file all
collapse to no-match, i.e. "blocker cleared" — the exact fail-open shape I made condition 3 of
accepting the design when replying to the peer. No `stale-blocker` detector may consume this field
until the grammar can express a third verdict (could-not-run ≠ cleared). Raised with the peer;
their half owns the grammar.

**What survives:** the ORIGINAL defect — a cited failure reason re-broadcast for hours without
being re-tested — is untouched and still open. Per CORRECTION 3 it belongs to **ai-maestro**, not
this repo. The card returns to `todo` with no deadline; the only open decision is the routing one
already stated below (file an issue on `Emasoft/ai-maestro`, or fork + PR).

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

## ⛔ CORRECTION 6 — 2026-08-27 01:36: **`match:<regex>` is TWO-VALUED and therefore fail-open by construction**

Fixing my invented regex (CORRECTION 5, defect 1) left the deeper defect standing, and an
adversarial review caught it: **`blocker-holds-if: match:<regex>` has no third state.** A timeout,
a non-zero exit, a deleted script, an empty output file — every one of them produces *no match*,
and no-match means *cleared*. I made "could-not-run is NEVER cleared" the condition I said I would
hold hardest, and then shipped, in the same turn, a worked example that cannot express it.

**The minimal fix is a CANARY**, and it is now on this card:

```yaml
blocker-probe:        bash ~/.claude/account-rotator/lifetime-status.sh
blocker-probe-canary: match:cookie/session     # MUST appear in any run that really ran
blocker-holds-if:     match:ACTION DUE
```

Three verdicts, decided in this order:

| verdict | condition |
|---|---|
| **2 · could-not-run** | non-zero exit **OR** timeout **OR** canary ABSENT — never "cleared", never un-parks |
| **1 · holds** | canary present **AND** `blocker-holds-if` matches |
| **0 · cleared** | canary present **AND** `blocker-holds-if` does not match |

The canary is what makes verdict 0 mean *"the probe ran and said no"* instead of *"nothing was
observed"*. Without it, an empty result is indistinguishable from a clean one — the same shape as
the lenient reader in TRDD-NB70FKKT, and the reason grep's exit-2 exists at all.

**Note on adoption:** no detector, lint, or schema in this repo parses `blocker-probe*` yet. These
three lines are inert documentation today. That is deliberate — the detector ships DISABLED under
NB70FKKT — but it also means a consumer built later against a slightly different spelling would
silently no-op, so the spelling above is the one to implement against.

## ⛔ CORRECTION 5 — 2026-08-27 01:33: **I committed this card's OWN defect while correcting it**

Ten minutes after writing CORRECTION 4 I told the owner "the one real alert on this host is
`rotator-stuck:all-maxed` — the Fable window is 100% spent". I read that out of
`active-alerts.json`, whose mtime was minutes old, and reported it as the current state. Measured:

| field | age |
|---|---|
| `firstSeenAt` | **8.31 h** |
| `lastDeliveredAt` | 8.06 h |
| `lastSeenAt` | **7.55 h** ← the newest evidence the alert still holds |
| `updatedAt` (file bookkeeping) | **0.01 h** ← what makes the file *look* live |

The payload had not been re-observed in **7.5 hours**; only the envelope was being rewritten. The
peer independently re-ran `rotator.py tick` → *"live ipazia 5h=6% 7d=11% — within limits"*, which
contradicts the alert's own `5h 2% / 7d 67%`. Worse, its remedy — "move agents OFF Fable" — names
a population that on the peer's side does not exist (0 of 13 registered agents carry a Fable
model).

**So the alert I quoted as fresh evidence IS an instance of the exact defect this card is about.**
A latched verdict, re-broadcast for hours, never re-tested. I read the newest line instead of
comparing occurrences — the same mistake recorded in this card's own `## Notes` section from
2026-08-21, committed again 2026-08-27 by the person who wrote that note.

**The generalisation, which is the durable part** — two state files on this host mislead about
age in OPPOSITE directions, so neither is readable as freshness:

- `findings-ledger.ndjsonl` is **append-only** → a resolved HIGH stays maximally alarming forever.
- `active-alerts.json` **is** rewritten, but only its bookkeeping → the file looks fresh while the
  payload is frozen.

**Rule:** an alert's own `lastSeenAt` is the only age it has. A file mtime is not evidence about
its contents, and `seen: 46` counts re-emissions, not re-observations.

**And the alert may not even be about the account it claims.** It says `5h 2% / 7d 67%` and
attributes that to "the live ACCOUNT". `state.json` says the live account is `ipazia`, whose
newest sample is **`5h 6.0 / 7d 11.0`**. The alert's `67` is within rounding of **`fmuaddib`'s
68** — a different, non-live account. Two readings, both bad: it is quoting a stale sample, or it
is mixing accounts. (In fairness the ONSET lines DO vary over time — `5h 45%`, then `47%` — so the
message is recomputed *sometimes*; "latched" is too strong, "not re-observed in 7.5 h" is exact.)
Either way it is not a fact about the live account right now, and I broadcast it as one.

**What that made urgent (2026-08-21, now VOID — see CORRECTION 4):** the two live cookies expire
**2026-08-30**. If whatever stopped the
cookie leg from running is not fixed before then, the no-human recovery path closes and all
three accounts become human-only. That is a 9-day clock, and it is the real deadline on this
card — not the refresh tokens, which are already dead.

**Why the leg is not running is UNKNOWN and belongs to ai-maestro** (correction 2): the server
owns `oauth-rotator-tick`, and the janitor's own copy of the cascade is not the code executing.

**Method note, because this is the third correction here:** each one came from reading a FIELD
and inferring the SYSTEM. `credential-dead` was true of the refresh token and false of the
account. The alert text named the thing to check and I did not check it.

## ⏰ 2026-08-26 20:26 — THE CLOCK IS **3.15 DAYS**. And this card's own deliverable had not happened.

The 08-22 entry below ends: *"What was missing was nobody telling the USER the clock exists — that
is this update, and the report to them."* **The report did not reach them.** This card has sat at
`column: human_review` for four days, and every board summary I gave this session named the
`dev`/`testing` columns and omitted `human_review` entirely — so the one column that means
"waiting on the USER" was invisible in exactly the reports meant to tell them what they were
waiting on. Found only by enumerating every column instead of the ones I expected.

**Re-measured now, non-secret metadata only (no keychain access):**

- **Cookie expiry 2026-08-30 → 3.15 days left**, down from 8.4. After it, all three accounts are
  human-only and the `RENEW_COOKIE` leg — the one path that mints fresh tokens with NO human — is
  gone.
- `rotation-stuck.json` (25.7 h): `all-accounts-maxed`,
  `fmu***:refresh-failed; ipa***:refresh-failed`.
- `active-alerts.json` — ⚠ **the "6 minutes old" I wrote here was the FILE's mtime, not the
  message's age; its `firstSeenAt` was 3.6 h earlier. See the retraction below before quoting any
  number from it.** Verbatim, as a stored snapshot: `STUCK: no alternate is healthy — but the live
  ACCOUNT is NOT exhausted (5h 2% / 7d 67%). Only the Fable window is spent (100%), so the remedy
  is to move agents OFF Fable, not to rotate the credential.` The account-wide figures happen to
  match live readings; **the Fable clause does not and is retracted.**

**That last line matters and is NEW since 08-22.** Two distinct problems were being read as one:

1. **The 3-day credential clock** — real, unchanged, and the only irreversible one.
2. **Fable's model window at 100%** — ⛔ **RETRACTED 2026-08-26 20:52, see below.**

> ### ⛔ RETRACTION 2026-08-26 20:52 — I quoted a FROZEN alert string as a live measurement
>
> The "Fable window is spent (100%), so the remedy is to move agents OFF Fable" text above is
> **quoted from `active-alerts.json`, and it is a stored snapshot, not a reading.** Its
> `firstSeenAt` is **3.6 h before I read it**, while the FILE's mtime was 6 minutes — delivery
> bookkeeping rewrites the file without recomputing the message. I checked the file's age and
> treated it as the claim's age.
>
> **Neither half survives measurement:**
> - **No usage probe carries a Fable window at all.** All 16 probes have `seven_day_fable: null`;
>   the only model-scoped window present is `nimbus_quill` at **0.0%**. So the 100% figure is not
>   substantiable from the probes right now.
> - **The remedy it names is empty on this host.** The ai-maestro peer measured the registry:
>   **0 of 13 registered agents are Fable-backed**, so "move agents OFF Fable" has nothing to
>   move. I had relayed it to them as "the lever available today"; it is available in principle
>   and empty in practice here.
>
> **What survives:** the FRAME — window-spent and credential-dead are different failures, and
> the rotator can report STUCK while the account itself is healthy. That distinction is sound and
> is why the alert exists. What does not survive is treating its numbers as current.
>
> **Unresolved and deliberately not guessed:** what IS consuming that window, if anything. The
> peer named the `fable-advisor` plugin as the obvious candidate and explicitly declined to assert
> it unmeasured. I note only what my own agent roster states first-hand — `fable-advisor:advisor`
> is described as running on Fable 5 — which makes it *consistent* with the candidate and proves
> nothing about consumption. If that window ever is spent, the consequence is narrow and worth
> separating from the deadline: it removes the advisor review step this project's rules mandate,
> it does not end unattended operation.
>
> Recorded as `ATOM-QP4H-ZY1H`. This is the sibling of `ATOM-W30O-YTBD` (the append-only ledger
> trap) written earlier **in this same session** — there an entry never expires; here the entry is
> rewritten while its payload is not. I wrote the first lesson and then made its exact mistake
> against a different file three hours later.

Nothing here changes the two remedies (`/janitor-refresh-cc-logins`, or re-arming `reauth-repair`
which the owner disabled 2026-08-07) — both remain USER decisions, and re-arming reverses a
deliberate call. What changed is that the clock is now short enough that the choice cannot keep
waiting for a quiet moment.

### ⏵ 2026-08-26 20:45 — THE ASK ON THE OWNER IS SMALLER THAN THIS CARD SAYS

The peer's `tick.ts:228` already emits, as its own reason string: *"the OAuth rung is dead, but a
live claude.ai cookie can still mint these with NO human; **check the cookie layer before
re-logging in**"*. That sent me back to our own skill, and it is right — this card (and my report
to the owner) named `/janitor-refresh-cc-logins` as though it were one indivisible human re-login.
**It is five steps, and steps 3 and 4 are separable.**

- **Step 3** = the human re-login per account (`open-login.sh`), which saves COOKIES only.
- **Step 4** = minting OAuth tokens FROM cookies already on disk, via a CDP-attach capture:

  ```bash
  ROT="$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator"
  env -u CLAUDE_PLUGIN_DATA bash "$ROT/check-login.sh" <email>      # are the saved cookies still good?
  env -u CLAUDE_PLUGIN_DATA CLAUDE_ROTATOR_AUTO_BOOTSTRAP=1 \
      python3 "$ROT/rotator.py" tick                                 # _bootstrap_seeded_slots → mint
  env -u CLAUDE_PLUGIN_DATA python3 "$ROT/rotator.py" list           # verify slots hold refresh tokens
  ```

**Our exact situation is step 4's precondition**: cookies LIVE until 08-30, refresh tokens dead.
So step 4 alone may restore all three slots with **no re-login at all** — which is precisely what
the deadline is a deadline ON. After 08-30 the cookies are gone and only the full step-3 REAUTH
remains.

Caveats, stated so nobody runs it blind: each capture opens a REAL Chrome window per account
(flashes, then closes). `CLAUDE_ROTATOR_AUTO_BOOTSTRAP=1` authorizes that for THAT user-initiated
run only — the unattended daemon keeps auto-bootstrap OFF and per-slot capped (TRDD-5OJX3SCF), and
the owner's 2026-08-07 call was about the DAEMON opening surprise windows, not about a command the
owner types. So this is a smaller decision than re-arming `reauth-repair`, not the same one.

**Not run here.** Credential-affecting and browser-launching; the owner's to type. What changed is
that the ask shrank from "re-login three accounts" to "run one command, after a one-line check
that the cookies are still good".

### THE FINDING, separate from the deadline — because the deadline expires and this recurs

The peer's editorial point, taken: **the column that means *escalated to the user* is the one a
status summary omits.** This card carried a hard deadline in `human_review` for four days while
every board report enumerated `dev|testing|ai_review`. A deadline expires; that shape does not.
Recorded as `ATOM-IEUR-NTPU` (USER scope) with its measurement half — read `column:` per file,
never `grep -h '^column:' *.md | uniq -c`, which counts prose inside card bodies.

The peer checked their own tooling on the strength of it and does NOT have this failure
(`trdd-doctor.ts` enumerates `human_review` in `PAST_DEV`) — but found the same SHAPE in a
different filter (`PENDING_COLUMNS = {proposal, superseded}`), which is the transferable half.

## ⏰ RE-MEASURED 2026-08-22 11:2x — the clock was 8.4 days

Every number below read fresh today (non-secret metadata only), against the 2026-08-21 16:10 row
above.

| slot | `refresh_failures` 08-21 → now | cause 08-21 → now | token expiry | cookie expiry | days |
|---|---|---|---|---|---|
| #0 `fmu***` | 572 → **572** (frozen) | credential-dead → credential-dead | −213 h | 2026-08-30 | **+8.4 VALID** |
| #1 `ema***` | 224 → **224** (frozen) | credential-dead → credential-dead | −259 h | 2026-08-20 | −1.7 EXPIRED |
| #2 `ipa***` | 775 → **776** (+1) | **network → credential-dead** | −182 h | 2026-08-30 | **+8.4 VALID** |

**Three things this measurement settles.**

1. **The "stale verdict never re-tested" defect is REAL but narrower than filed.** Slot #2 WAS
   re-tested in the last 19 h — once — and its verdict CHANGED from `network` to
   `credential-dead`. So the verdict is not frozen by construction. Slots #0 and #1 did not move
   at all, which is consistent with their being skipped rather than latched.
2. **`last_reconcile_at` is 2026-08-22 09:33** — about two hours before this reading. The rotator
   IS beating. This corroborates the peer's box 1 on `ai-maestro#95` ("the chore beats", verified
   live from the server side) from the janitor's side of the same system.
3. **All three refresh tokens are genuinely dead**, which the peer confirmed independently as
   `invalid_grant`. Nothing here is a misdiagnosis to unwind.

**THE DEADLINE, and it is the only urgent thing on this card.** Two slots hold claude.ai session
cookies valid until **2026-08-30 — 8.4 days from this reading**, and the `RENEW_COOKIE` leg is
designed to mint fresh tokens from exactly those with NO human. After that date all three accounts
become human-only. The 9-day clock recorded yesterday is now 8.4.

**Why nothing automated will close it, established on the ai-maestro side and not re-litigated
here** (`Emasoft/ai-maestro#95`, comment 2026-08-21T21:01Z): cookie access is deliberately outside
the server tick's reach (`tick.ts` docstring, TRDD-XV9BLQC5), the server owns `oauth-rotator-tick`
so the janitor's own cascade is not the code executing, and the two remaining recovery paths are
both USER decisions —

- run `/janitor-refresh-cc-logins` (a human re-login), or
- re-arm `reauth-repair`, **which the owner disabled on 2026-08-07** because it opened disruptive
  headed browser windows. Re-arming it reverses that decision and is credential-affecting.

**No comment was posted to `#95` for this.** The peer's analysis is complete and correct, the ball
is not on their side, and restating their own findings back at them is noise on a tracker. What
was missing was nobody telling the USER the clock exists — that is this update, and the report to
them.

**Nothing was run against the credentials.** `/janitor-refresh-cc-logins` and re-arming
`reauth-repair` are both the user's calls; an agent picking either would be reversing a
credential decision the owner made deliberately.

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
