---
trdd-id: BMITQ2MN
title: Bulk-import long-lived setup-token OAuth keys from a CSV into the rotator vault
column: testing
created: 2026-09-09T16:37:29+0200
updated: 2026-09-09T16:37:29+0200
current-owner: ai-maestro-janitor session
task-type: feature
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
implementation-commits: [f4457513]
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

**NEXT ACTION:** two small changes are under adversarial review and not yet written —
(1) `run_import` in the test module does not stub `imp.gs.global_state_dir`, so the `main()`
tests read the REAL machine-wide state dir and would fail if a real ai-maestro rotation tick
held its lock during a run; (2) the skill's exit-code table documents `1` as "every row was
rejected, or none parsed", which is false — the lock-refusal path also returns `1`.

**BLOCKED / OWNER DECISION OUTSTANDING:** see "The live cross-repo hazard" below. Filing keys
is close to a no-op while both rotators classify a setup-token slot as dead on sight. The
janitor half of that fix is described under "The stay-put branch"; the ai-maestro half is
theirs and must go through an issue or PR, never a direct edit.

**SUPERSEDED — do not act on these, they were wrong:**
- *"Widen `usage_probe.http_get` to return the 403 body so the rotator can distinguish
  `oauth_scope_insufficient` from a real refusal."* Overturned: a deliberately corrupted
  bearer token returns **401**, not 403. Genuine credential death already surfaces as 401,
  which is already fatal — so gating on slot type alone is equally good and needs no change
  to a frozen contract.
- *"Treat an empty server lockfile as held (`if not raw.strip(): return -1`)."* Overturned by
  reading `~/ai-maestro/lib/server-lockfile.ts:60-63`: the server itself reclaims an empty
  file (`if (!Number.isInteger(pid) || pid <= 0) return true // empty / corrupt file →
  reclaim`), and `createExclusive`'s `finally` deliberately "leaves an empty → stale lock"
  when a write throws. Treating empty as held would make the importer stricter than the
  lock's own owner and could deadlock it permanently while the server is down.

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

## The live cross-repo hazard (verified in `~/ai-maestro/lib/oauth-rotator/tick.ts`)

The network-down branch pushes a slot into `degraded` with **no refreshToken check**:

```ts
} else {
  const eh = expiresInH(b)
  if (eh === null) continue
  degraded.push([email, b, eh])
}
```

while the sibling branch ~35 lines above has
`if (oauthOf(b).refreshToken && eh !== null && !blobLocallyExpired(b)) degraded.push(...)`.
Selection is max expiry-hours (`for (const c of degraded) if (c[2] > target[2]) target = c`),
and a setup-token blob's fabricated one-year `expiresAt` outranks every real slot. So the
first network-down tick after an import selects the slot that cannot refresh.

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
neither currently implements.

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
- [ ] `main()` tests are isolated from the real machine-wide state dir
- [ ] the skill's exit-code table matches what `main()` actually returns
- [ ] the stay-put branch lands, so filing a key is not a no-op
- [ ] the ai-maestro degraded-selection hazard is raised with that project (issue or PR only)

## Approval log

- 2026-09-09T16:37:29+0200 — Authored after the implementation landed, not before. The work
  was carried across eight rounds on a direct owner instruction with no card; this TRDD is the
  retroactive record and the home for the outstanding decisions above.
