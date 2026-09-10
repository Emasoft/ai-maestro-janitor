---
trdd-id: BMITQ2MN
title: Bulk-import long-lived setup-token OAuth keys from a CSV into the rotator vault
column: testing
created: 2026-09-09T16:37:29+0200
updated: 2026-09-10T14:33:32+0200
current-owner: ai-maestro-janitor session
task-type: feature
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
implementation-commits: [f4457513, 780c811d, 1c797cfe, 9ef139d0]
relevant-rules: []
---

# Bulk-import long-lived setup-token OAuth keys from a CSV into the rotator vault

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-09

**Shipped and committed** as `f4457513` (5 files, +1161/-72). Gate at commit time: 39 tests
pass, ruff clean, mypy clean, pyright 0 errors.

**What exists:**
- `skills/janitor-import-oauth-tokens/SKILL.md` — the `/janitor-import-oauth-tokens` skill.
- `scripts/oauth_rotator/import_oauth_tokens.py` — the importer.
- `scripts/oauth_rotator/slot_capture_token.py` — now the shared library as well as the
  single-account filer (`extract_token`, `account_status`, `setup_token_blob` made public).
- `tests/test_slot_capture_token.py` — 39 cases.

**DONE 2026-09-09 in `780c811d`** (both were reviewed before writing, and the review caught
that the second fix reproduced the defect it was fixing): `run_import` now stubs
`imp.gs.global_state_dir` to a SUBDIR of `tmp_path`, so the `main()` tests no longer read the
real machine-wide state dir; and the skill's exit-code row for `1` now names all four paths
that return it, not three. Gate re-run green after both.

**DONE — the janitor half of the ship-blocker has LANDED.** `rotator.is_setup_token_slot()`
plus the `cmd_auto` branch: a 403 on a readable no-refresh slot is no longer read as death.
401 stays fatal for every slot type, a full-OAuth slot's 403 stays fatal, and an EXPIRED
setup-token slot still rotates. Four branch-level tests through the real `cmd_auto` via the
existing `_setup_auto` harness, plus three helper tests, mutation-verified by forcing
`is_setup_token_slot` to False (the stay-put test dies; the full-OAuth control survives,
proving it is not falsely coupled to the gate).

**THE GATE REMOVES AN ACCIDENTAL MITIGATION — record this, it inverts the naive reading.**
Before the gate, a setup-token slot could never stay live for long: the janitor thrashed it away
within a tick. That thrash was destructive, but it also guaranteed no such slot ever SAT as the
live credential. With the gate one can now sit live for up to a year — which is the intended
behaviour, and is also the precondition that makes ai-maestro's ungated `degraded` sites
reachable in a way they were not before, because the long-lived fabricated one-year `expiresAt`
is exactly what outranks every real slot in their max-expiry selection. Still net-positive
(continuous cache destruction is worse than a latent inversion that needs `best === null`), but
"the janitor half is strictly an improvement" is false and should not be written anywhere.

**A DEFECT THAT HID FOR FOUR COMMITS, and the reason it hid.** `DEFAULT_CSV = Path.home() / …`
shipped as a module-level constant in `f4457513`. That is an import-time home capture, which
`tests/test_no_frozen_home_paths.py` fails the build over (TRDD-ZNN0UK5K — it escapes test and
env isolation). It is now a call-time `default_csv()` resolver. **It went unnoticed because
every "gate green" claim in this card's history was a SCOPED run** — this feature's own test
file, plus lint — never `pytest tests/`. Four commits asserted a green gate that had never been
run. Run the full suite before claiming it.

**NEXT ACTION — the remaining half is ai-maestro's and is not ours to write.** Both their
`degraded` push sites still rank a fabricated one-year `expiresAt` above every real slot, so
the skill's warning stays until their cards land. They have queued the `isStale` comment ask as
`TRDD-UIDK2SDL` (`column: todo`), awaiting their owner.

**Still unshipped by choice, owner's call:** whether the importer should REFUSE by default
while the ai-maestro half is open, rather than warn. A review argued a prose warning discharges
urgency where a refusal cannot be skimmed past. Not done unilaterally — it changes the
command's behaviour.

**BLOCKED / OWNER DECISION OUTSTANDING:** see "The live cross-repo hazard" below. Filing keys
is close to a no-op while both rotators classify a setup-token slot as dead on sight. The
janitor half of that fix is described under "The stay-put branch"; the ai-maestro half is
theirs and must go through an issue or PR, never a direct edit.

**SUPERSEDED — do not act on these, they were wrong:**
- *"Widen `usage_probe.http_get` to return the 403 body so the rotator can distinguish
  `oauth_scope_insufficient` from a real refusal."* Overturned: a deliberately corrupted
  bearer token returns **401**, not 403, so that death mode is already fatal without any body
  read — gating on slot type alone is equally good and needs no change to a frozen contract.
  **Do not restate this as "credential death surfaces as 401" full stop.** That generalises
  from ONE control. A revoked grant, a suspended account and a withdrawn client are different
  server paths and could plausibly answer 403; none was measured. The design does not depend
  on the general claim, but it is NOT free — an earlier version of this line said a wrong
  verdict "costs nothing, because the recovery is a human re-mint either way", and that is
  **false**. It swaps recovering the CREDENTIAL for recovering SERVICE, and service is the
  rotator's whole job. The honest form: **if the generalisation is wrong, this change converts
  a working rotation into a permanent pin on a dead live credential, for as long as it stays
  live.** Today a revoked no-refresh slot's 403 is fatal, so the tick rotates to a healthy
  alternate and the user keeps working; with the gate it holds, logs a deliberate hold that
  reads as correct, and healthy alternates idle. That exposure is accepted only because no
  no-refresh slot exists in this vault yet. Close it by measuring one non-corrupted-token
  death mode (a revoked grant, a suspended account), or record it as accepted.
- *"Treat an empty server lockfile as held (`if not raw.strip(): return -1`)."* Overturned by
  reading `~/ai-maestro/lib/server-lockfile.ts:60-63`: the server itself reclaims an empty
  file (`if (!Number.isInteger(pid) || pid <= 0) return true // empty / corrupt file →
  reclaim`), and `createExclusive`'s `finally` deliberately "leaves an empty → stale lock"
  when a write throws. Treating empty as held would make the importer stricter than the
  lock's own owner and could deadlock it permanently while the server is down.

**DONE 2026-09-10.** Skill prose reworded under CPV `--strict` pressure (`1c797cfe`) — the
`credential_theft` NIT fired on the `claude setup-token` bigram, so the mint step now reads as
the human's own terminal action, never the plugin's. Fixture e-mail domains moved to the
reserved `.test` TLD (`9ef139d0`) after `publish.py`'s G1b gate correctly refused `x.com`-style
example addresses. Released as **3.5.0** at `61191d32`, tag on the final commit.

## Why

The owner runs several Pro/Max subscriptions. `claude setup-token` mints a ~1-year
inference-scoped token per account, but each one had to be filed by hand, one command per
account. The owner specified a flow that ends in a single command: keys accumulate as
`email,token` lines in a CSV, and one invocation imports every new or updated key into the
encrypted vault and rotates onto it **without exiting any Claude Code session**.

## What a setup-token key is, and why it breaks the usual validator

`claude setup-token` returns an access token with **no refreshToken**, scoped to inference
only. It **403s** on `/api/oauth/usage` and on every identity endpoint (`/roles`, `/profile`,
`/claude_cli_profile`). So the ordinary "is this credential alive?" probe reports death for a
perfectly good key.

`POST /v1/messages/count_tokens` returns **200** for these keys, costs nothing, and does not
share the inference rate limit — measured 2026-09-09, two of three accounts returned 429 on
`/v1/messages` while `count_tokens` returned 200 for all three. That is the prover the
importer uses.

## The three-state validator

| state | meaning | codes |
|---|---|---|
| `ok` | proof of life | only a 200 |
| `unverified` | nothing was learned | 5xx, timeout, reset, **and 429** |
| `bad` | a refusal | 401, 403 |

**429 is `unverified`, not `ok`.** A rate limiter answering proves a request *arrived*, not
that the credential was accepted. The pre-existing code returned `ok` on 429, so a wrong
User-Agent turned the genuine 403 into a 429 and every key filed unvalidated — a revoked one
included. That single misclassification is the root cause of the whole User-Agent defect
class.

## The live cross-repo hazard (read first-hand in `~/ai-maestro/lib/oauth-rotator/tick.ts`)

Selection among `degraded` is max expiry-hours
(`for (const c of degraded) if (c[2] > target[2]) target = c`), and a setup-token blob's
fabricated one-year `expiresAt` outranks every real slot. **Two** sites push into `degraded`
without testing `refreshToken`, and the second is the dangerous one.

**Site 1 — the probe-else branch (network down).** Reached only when the live blob is
**locally expired**; the ai-maestro peer supplied that precondition and it is confirmed: with
the network down and the live token still valid locally, the tick logs *"usage unreachable
(status N) but token still valid locally; staying put"* and returns before the loop. An
earlier version of this card asserted "the first network-down tick after an import selects the
slot that cannot refresh" — that was missing this precondition and overstated the hazard.

**Site 2 — the `unread` fall-through (network UP).** Reachable without any outage:

```ts
const unread = st2 === 0 && (o2.reason === 'cooldown' || o2.reason === 'lock_contended')
if (st2 !== 200 && st2 !== 429 && !unread) {        // SKIPPED when unread
  ...
  if (oauthOf(b).refreshToken && eh !== null && !blobLocallyExpired(b)) degraded.push(...)
  continue                                           // ← this site HAS the test
}
if (st2 !== 200) {
  if (st2 !== 429) {
    const eh = expiresInH(b)
    if (eh !== null && !blobLocallyExpired(b)) degraded.push([email, b, eh])   // ← NO test
  }
  continue
}
```

A probe in `cooldown` or `lock_contended` returns status 0, so `unread` is true, the refresh
block is skipped, and control reaches the untested push. A setup-token blob is not
`blobLocallyExpired` (its `expiresAt` is a year out), so it enters `degraded` and wins the
ranking.

**NO RANKING BETWEEN THE TWO SITES — an earlier version of this card had one and it was
backwards.** It said site 2 was "materially worse, because it needs no outage at all". That
compared the PUSH preconditions and stopped there. A push only matters if `degraded` is
CONSULTED, and it is guarded: `tick.ts:1367` sits under the comment *"2) DEGRADED fallback —
no usage-confirmed target"*, after the drain-first selection and after an early return on
`scopedWall && best === null`. So site 2 additionally requires every healthy alternate to have
failed its usage probe.

**Scope of that, because the first version of this paragraph overreached too.** It said site 1
"gets `best === null` free from the outage". That is an INFERENCE, not something read: I traced
the guard, not `best`'s assignment nor `selectDrainFirst`. And it is probably too strong —
"network down" is per-request, not global, so a live probe that fails while alternate probes
succeed leaves `candidates` populated and `degraded` is never consulted at all. Site 1's
precondition is "likely under a TOTAL outage", not free.

What survives: the original ranking compared push preconditions and ignored the consult guard
entirely, so it was not sound. **Gate both; the second gate is one line, and offering a partial
fix manufactures a decision nobody needs.**

Both sites are ai-maestro's to fix. That project is not ours to edit: issue or PR only. The
peer holds cards `TRDD-WLHP34KZ` (the ranking inversion, both sites) and `TRDD-W11LAPSC` (the
403 thrash loop), both at `column: proposal` and unauthorised — nothing is written to
`tick.ts`.

## The stay-put branch (the janitor half, NOT yet implemented)

`cmd_auto` has `elif live_status in (401, 403): near = True` — a death path that **bypasses**
the usage-based trigger (`SWITCH_AT_5H = 97`). A setup-token key 403s permanently, so every
tick classifies a healthy key dead and rotates. `MIN_DWELL_S = 60` equals the tick interval,
so the dwell guard is no brake: one switch per minute, forever, destroying the prompt cache
continuously.

Fix: gate on **slot type**, not on the response body. `refreshToken is None` ⇒ a 403 is
expected and non-fatal; **401 stays fatal for every slot**, because that is what a genuinely
dead credential returns.

## Locking, and why the importer only observes

The janitor serialises with POSIX `fcntl.flock(2)` on `oauth-rotator-tick.lock`. ai-maestro
uses an O_EXCL lockfile named `oauth-rotator-server-tick.lock` in the same state dir, because
Node has no `flock`. **The two cannot exclude each other** — this is deliberate and documented
on both sides; the distinct filename exists to make the absence of coordination honest.

The importer therefore **reads** the server's lockfile and refuses to run while it is held,
but never creates, reclaims, or unlinks it. Reclaiming another repo's lock on a staleness
judgement that might disagree with its owner's by a little would delete a lockfile a live tick
is holding — a silent failure, and mine. Refusing is loud, costs a re-run, and cannot corrupt
anything.

**This narrows the write window; it does not close it.** A tick that starts mid-import still
races, and there is no mechanism available to either side that would close it without a native
addon in ai-maestro (ruled out by its Node-22 ABI constraint) or a shared lock protocol
neither currently implements. **So the refusal is a courtesy, not a guarantee** — it sees only
a tick that was already running when the check ran. Stopping the ai-maestro server first is
the only sound way to be sure, and the skill's stdout must not offer it as a co-equal
alternative to "re-run in a minute".

### An undeclared cross-repo dependency, named here because nothing else names it

`server_tick_holder()` returns `None` for an empty or corrupt lockfile. That is only SAFE
because ai-maestro's `isStale` reclaims such a file (`if (!Number.isInteger(pid) || pid <= 0)
return true`). **If that predicate ever changes to treat an empty file as held — a defensible
hardening for them — their tick would wait while this importer files straight through it.**
Their change would be locally correct and would break this caller silently.

Nothing detects that break: not the 39 tests (they stub `global_state_dir` and never read a
real ai-maestro lockfile), not the gate, not CI. The only thing standing between that change
and a silently orphaned slot is the peer session's promise to message us if `isStale` moves —
a promise held in a transcript, not in either repo. The durable fix is one comment in
ai-maestro's source naming this out-of-repo reader; ask for it on their card, since that file
is theirs.

### The blob shape both gates rest on — MEASURED 2026-09-09

Both gates test the same field (`oauthOf(b).refreshToken` on their side, `refreshToken is
None` on ours), and neither had been checked against what the importer actually writes. Traced
end to end: `setup_token_blob` sets `"refreshToken": None`; `write_slot` does `inner =
_oauth(blob)` and re-wraps it, preserving the inner dict verbatim; both the keychain path and
the plaintext fallback serialise with `json.dumps(blob, separators=(",", ":"))`. So the field
is **present with the JSON value `null`** — not absent, not `""`, not a placeholder string,
not nested differently. `null` is falsy in TypeScript and round-trips to `None` in Python, so
**both gates fire.** Had it been a placeholder, both would have silently never fired while
both cards still read as correct.

Scope of that claim: it is a SOURCE TRACE through both write paths, corroborated independently
by the peer reading the same files. Neither of us read a stored slot back, and nobody watched
ai-maestro's gate evaluate a real blob. An earlier version of this card said "provably fire";
"traced in source, not observed on a stored artifact" is what the evidence supports.

### WITHDRAWN — the "one-way door" framing was false, and it was labelled INTENDED

An earlier version of this card claimed the two gates form a one-way door: a no-refresh
credential that becomes live has "exactly one exit, a 401", marked as intended design. **Both
halves are wrong**, verified first-hand in `tick.ts` after the peer session retracted it:

1. **Expiry makes rotation ELIGIBLE, which is enough to falsify "exactly one exit".**
   `tick.ts:1169` is `near = usageNear || scopedWall || liveExpired`, so the blob passing its
   own `expiresAt` sets the same flag a usage wall does. A fabricated one-year expiry defers
   that by a year; it does not remove it.
   **Not "a second automatic exit" — I wrote that first and it overstates in the same way the
   thing it corrects did.** `near` is eligibility, not rotation: the dwell guard, the
   drain-guard, and the requirement that a target actually EXIST all still stand between the
   flag and a switch. A no-refresh credential that is expired AND has no viable alternate
   stays live indefinitely — which is the very "pinned on a dead credential" case this card
   treats as the danger elsewhere.
2. **The gates are not two halves of one thing.** Their candidate loop opens with
   `tick.ts:1218  if (email === liveEmail) continue` — it never examines the live blob at all.
   Theirs governs which ALTERNATES may enter a target list; ours governs whether a 403 on the
   LIVE blob counts as death. Different objects, different roles. The symmetry was tidiness,
   not a property of the design.

Accurate form: both gates restrict movement around a no-refresh credential — theirs keeps it
out of the target list, ours keeps a 403 from evicting it. The automatic exits that remain are
a 401 and the blob's own expiry.

**The label was the dangerous part.** The error overstated how locked-in the design was, which
is the safer direction — but "intended" is precisely the word that stops the next reader
checking, and someone acting on it would have built an exit that already exists.

## Secret handling

- Field 2 of the CSV is never printed, logged, or placed on a command line.
- Network errors print `type(e).__name__` only, never the exception — a failure's repr can
  embed `HTTP(S)_PROXY`, which can carry `user:pass@host`.
- The default key file is chmod 0600 by the importer; a path given explicitly with `--csv` is
  warned about but not modified.
- **Nothing can bind a token to an email.** The token carries no identity the janitor can
  read, so the email in column 1 is a label the human supplies and the importer trusts.

## Acceptance

- [x] `/janitor-import-oauth-tokens` exists and reads the owner's stated path
- [x] one invocation imports every new/updated key
- [x] a key is only filed after a real 200, or filed with an explicit `unverified` note
- [x] the live swap requires a proven key, except when the live credential is already expired
- [x] gate green: 39 tests, ruff, mypy, pyright
- [x] `main()` tests are isolated from the real machine-wide state dir (`780c811d`)
- [x] the skill's exit-code table matches what `main()` actually returns (`780c811d`)
- [x] the blob's `refreshToken` shape is measured, not assumed, so both gates provably fire
- [ ] the skill says filed keys are inert until the stay-put branch lands
- [ ] `main()`'s refusal path is tested — that it returns BEFORE `_secure()` and `read_rows()`,
      which is what "the key file was never read" promises the user. The six
      `server_tick_holder()` tests cover the predicate and structurally cannot cover this
- [ ] the stay-put branch lands, so filing a key is not a no-op
- [ ] the ai-maestro degraded-selection hazard is raised with that project (issue or PR only)
- [ ] ai-maestro's `isStale` carries a comment naming this repo's `server_tick_holder` as an
      out-of-repo reader (their file, their card)

## Corrections to this card's own commit messages

Recorded because a commit message cannot be rewritten, and both are the same error:

- `f4457513` states `count_tokens` **"does not share the inference rate limit"** as a property
  of the API. The evidence is one measurement — three accounts, one occasion, two of which
  429'd on `/v1/messages` while `count_tokens` returned 200. That is consistent with a
  separate limit, and equally with the same limiter accounting a cheaper call differently, or
  with the 429s simply lapsing between the two calls. The defensible claim is "did not share
  it in the one measurement taken."
- `780c811d` frames its TRDD corrections as **"verified first-hand in ai-maestro's tree"**.
  True of the three code facts. But "which makes it the worse of the two" about site 2 is a
  judgement about relative reachability, not something read out of the file — reasonable, and
  not verified, sitting inside a sentence whose frame claims verification.

- `bc85bf62` called the new order-test **"mutation-checked"** on the strength of a probe that
  OMITTED the lockfile. That is the no-holder case; it proves `_boom` is reachable, which is a
  wiring check. It says nothing about ORDER, and the message's parenthetical — "the same
  observable state as the check having moved below them" — is false: under a real reorder
  there IS a live holder and the refusal DOES fire. **The real mutation has since been run**
  (the `holder = server_tick_holder()` block moved below `_secure`/`read_rows` with the
  lockfile in place): the test FAILS on its own guard, so the order-sensitivity is now
  genuinely established rather than asserted.
- `bc85bf62` also said the blob trace made both gates **"provably"** fire. See the scope note
  in the blob-shape section.

**The class, since this is now four for four:** a specific observation promoted to a general
property — one rate-limit measurement as an API property, a judgement inside a "verified
first-hand" frame, a source trace as proof, a wiring check as a mutation. Every one was caught
by review rather than at writing time, which is the part worth fixing. The peer session made
three retractions of the same shape on the same day, so it is not idiosyncratic.

**`implementation-commits` discipline, decided after it lagged twice.** A SHA cannot be known
before its own commit, so this field will always trail by one and chasing it with an amend is
not worth rewriting history. It means "commits known at the last card edit". The authoritative
list is `git log --grep=TRDD-BMITQ2MN`, which is complete by construction because the id is in
every subject line.

## Approval log

- 2026-09-09T16:37:29+0200 — Authored after the implementation landed, not before. The work
  was carried across eight rounds on a direct owner instruction with no card; this TRDD is the
  retroactive record and the home for the outstanding decisions above.
