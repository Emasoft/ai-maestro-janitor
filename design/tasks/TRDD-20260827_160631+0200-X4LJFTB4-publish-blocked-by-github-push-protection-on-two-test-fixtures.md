---
trdd-id: X4LJFTB4
title: Publish 3.4.0 is blocked at the push by GitHub push protection on two synthetic test fixtures
column: published
created: 2026-08-27T16:06:31+0200
updated: 2026-08-29T22:35:00+0200
current-owner: janitor-main-session
task-type: security
priority: high
scope: project
project-id: ai-maestro-janitor
severity: major
min-approval-requirement: user
labels: [publish, push-protection, secret-scanning, test-fixtures, owner-decision]
blocked-by: []
npt: []
eht: []
implementation-commits: [cf97521d, 7e4c5772, f5c63798, 5f7a5b19, c7f0bfab, 62b452fd]
relevant-rules: []
---

# Publish 3.4.0 is blocked at the push by GitHub push protection on two synthetic test fixtures

## ⏵ RESOLVED 2026-08-29 — 3.4.0 IS PUBLISHED. `ce03b9cb..62b452fd`, 370 commits, 8 days.

Unblocked under the owner's grant of full decision autonomy. **Option 1 (allow the flagged
string) was taken, via the REST API rather than the web form:**

```
gh api -X POST repos/Emasoft/ai-maestro-janitor/secret-scanning/push-protection-bypasses \
  -f reason=used_in_tests -f placeholder_id=3IbDWxK023HKei6l35y9vYUDHQ9
→ {"reason":"used_in_tests","token_type":"STRIPE_LIVE_API_SECRET_KEY"}
```

`used_in_tests` is the honest reason: the string is a redaction placeholder the bench's own
hygiene gate wrote into a prompt-injection test corpus. **History was NOT rewritten** — RULE 0.6
requires the user's exact command for that, and a grant of autonomy does not revoke a rule whose
text names the approval it needs. The bypass is narrow (one secret), auditable (it appears in the
repo's security tab), and reversible in a way history surgery is not.

One detail the card predicted correctly and is worth confirming: **all three refused refs shared
ONE `placeholder_id`.** The tag refusals were never a tag-ruleset problem, exactly as the STATE
block below argued — a single bypass cleared main and both tags at once.

### But the push protection was not what had been blocking it for the last stretch

Reaching GitHub at all took clearing **four** local gates that had accumulated in front of it,
none of which the card knew about because no attempt had got past them since 2026-08-27:

1. **CPV `--strict` 0/0/0/0** — 5 MINOR + 3 NIT (`cf97521d`, `7e4c5772`).
2. **G2e ran `clippy -D warnings` on 58 gitignored third-party crates** and blocked on a
   stranger's lint debt (`f5c63798`).
3. **G2f shellchecked 311 gitignored scripts** and blocked on a dated backup (`5f7a5b19`).
4. **memgrep's own 18 clippy errors**, which the build gate had literally never reached because
   it died on the third-party crates first (`c7f0bfab`).

**The lesson is #4.** Gate 2 and 3 were not merely noisy — they were HIDING gate 4. A check
scoped too wide does not just cost time; it fails on the wrong thing first and conceals the real
failure behind it, for as long as nobody fixes the scope.

Blocker 2 (the Tailscale alert, open 84 days) needs no action either: it now reads
`state=resolved`.

## ⏵ STATE — 2026-08-27 (superseded by the section above; kept for the diagnosis)

**The release is code-complete and green through EVERY local gate. It cannot leave the machine.
Both blockers are synthetic test fixtures, not credentials, and both resolutions are the OWNER's
to make — one is a repo security setting, the other is history.** Nothing here is for an agent
to "fix" unattended.

### The scale, measured 2026-08-29 — this is not one release, it is eight days

`origin/main` is frozen at `ce03b9cb` (v3.3.26, **2026-08-21 02:23**) — the last push that
succeeded. HEAD is **357 commits ahead, 0 behind**. The blocking commit `9690e5fd` is only the
**16th** past `origin/main`, so it has gated the 341 commits behind it as well: nothing written
since 02:32 on 2026-08-21 has ever left this machine.

That number was misrecorded as "14" and then "16" in the session handoff for days — 16 is the
distance to the BLOCKING commit, not to HEAD, and reading it as the backlog made an eight-day
freeze look like an afternoon's work at risk. Measure it, never recall it:
`git rev-list --left-right --count @{u}...HEAD` (and `git ls-remote origin refs/heads/main`
when the local `origin/main` ref may itself be stale — here it was last fetched 2026-08-27).

### What is green (publish attempt 5, 2026-08-27)

CPV `--strict`: **0 CRITICAL / 0 MAJOR / 0 MINOR / 0 NIT** (five attempts to get there — see
`28ff1b50` for the method). Lint, typecheck, full test suite: pass. Version bumped to 3.4.0
(`776f707d`). The pipeline reached `git push --atomic origin HEAD v3.4.0 …` and GitHub refused
**all three refs** with `GH013 — GITHUB PUSH PROTECTION — Push cannot contain secrets`. `--atomic`
means nothing landed: `origin/main` is unchanged, no tag exists remotely.

**Do not misread the tag refusals.** The two tag refs were refused for the SAME reason as `main`;
they merely carry the same commits. The `baseline-tag-protect` ruleset (`deletion` + `update`,
ratified fleet-wide in TRDD-157OH2D7) is NOT the cause — I chased it for a round before reading
the full block. The two stale local tags from earlier attempts (pointing at superseded bump
commits) were deleted; both were in HEAD's ancestry and are reflog-recoverable.

### Blocker 1 — the one stopping the push: a REDACTION PLACEHOLDER that looks like a Stripe key

| | |
|---|---|
| secret type (GitHub) | Stripe API Key |
| location | `tests/agent_context_bench/corpus-vawikrk2-20260821.jsonl:110` |
| commit | `9690e5fd` (2026-08-21, "commit the fresh BLIND corpus", TRDD-VAWIKRK2) |
| pushed? | **NO — never. `9690e5fd` exists only in this clone (+ a dated local backup branch).** |
| what it is | a captured prompt-injection TEST PAYLOAD: AWS's own documented example key (`AKIAI…` / `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`), `SuperSecret123!`, a truncated RSA stub, and `API_KEY=sk_****_****9999` |

**The irony is the finding.** The bench's hygiene gate (`assemble_corpus.py:120–132`) DID
redact: it rewrote a `sk_live_…` to the literal placeholder `sk_****_****9999`. That placeholder
is what GitHub's Stripe pattern matches. The redaction's output is itself scanner-shaped.

**No leak has occurred.** The commit has never left this machine.

### Blocker 2 — surfaced while diagnosing 1, and already public: an OPEN secret-scanning alert

| | |
|---|---|
| alert | `#1`, Tailscale API Key, **state=open since 2026-06-04**, `validity=unknown` |
| location | `tests/test_zero_trust_patterns.py:516` — `TS_AUTHKEY=tskey-auth-abc1…` |
| what it is | a synthetic `abc…` key inside the test that proves the Tailscale-key DETECTOR fires |
| status | tracked in HEAD, **on a public repo, for 84 days** |

Not a credential. But an open alert on a public repo is a real signal to anyone auditing the
org, and it has been sitting unresolved. It does not block the push (already pushed); it is
listed here because it is the same class and the owner should close it in the same sitting.

## The owner's decision — and why every option is theirs

For **Blocker 1**, redacting the line in a NEW commit does NOT unblock: push protection scans
every commit in the push, and `9690e5fd` would still carry the string. So the choice is binary:

1. **Allow the flagged string via GitHub's unblock URL** (in the push output; it records a
   per-secret, visible bypass in the security tab). Honest here — the value is AWS's published
   example — and non-destructive. **A repo security setting: owner-only.**
2. **Rewrite `9690e5fd` out of history** so the string never existed, then push. Destructive
   history surgery on 327 unpushed commits. **RULE 0.6: owner's exact command, owner's explicit
   approval, nothing less.** Not recommended when option 1 exists for a known-fake value.

For **Blocker 2**: **DONE 2026-08-28 — alert `#1` is `state=resolved`,
`resolution=used_in_tests`**, verified by reading it back from the API, not by the write's own
exit code. Reversible: reopen from the repo's security tab. The fixture behind it was devitalized
first (prefix fragmented, body generated at runtime by `_fake_secrets.secret()`), and
`test_secret_fixture_hygiene.py` gained a `tskey-(auth|api|client)-` MARKER so the class cannot be
reintroduced — a strengthening of the gate, never a suppression. The detector tests keep their
assertions and were re-run (106 pass): a devitalized fixture that stopped proving the detector
fires would be a worse outcome than the alert.

**Either way, ALSO do the durable fix** so this never recurs, as a normal Tier-0 change.
**DONE 2026-08-28, in `tests/agent_context_bench/assemble_corpus.py` — uncommitted, no TRDD of its
own** (filing a card for finished Tier-0 work is bureaucracy; it is recorded here, where the next
reader of this blocker will look):

- The payment mask no longer keeps ANY `sk_` prefix. **This card's own suggestion of
  `sk_REDACTED_TEST` was NOT taken, and deliberately** — the comment block above `_SECRET_MASKS`
  records push protection rejecting an alphabetic tail after `sk_`, so that spelling risks
  re-triggering the exact failure. Every prior attempt kept the prefix and argued about the tail;
  the replacement is now prefix-free (`REDACTED-PAYMENT-KEY`), which cannot match a
  prefix-anchored pattern at all. It also covers `sk_test_`, which the old regex missed.
- Added masks for AWS's published example credentials (`AKIA…`, `wJalrXUtnFEMI…`) and for
  `tskey-(auth|api|client)-…`, the shape behind open alert `#1`.
- Verified behaviourally: all six shapes (including the pre-existing conn-string mask, checked for
  regression) mask as intended. `ruff` clean; 212 bench/zero-trust tests pass.

**NOT done, deliberately: re-assembling the dated corpora.** `corpus-vawikrk2-20260821.jsonl` is a
timestamped measurement artifact; rewriting it would silently change what a past benchmark run
measured, and it would NOT unblock the push anyway (`9690e5fd` keeps the string in history either
way). New captures are clean by construction; the old one stays as evidence.

**So this fix does not unblock the push, and was never going to.** Blocker 1 remains exactly as
stated above: a repo security setting or history surgery, both owner-only.

## NEXT ACTION

Owner picks option 1 or 2 for Blocker 1 and closes Blocker 2. Until then: **nothing to pull.**
The janitor rollout (TRDD-RY0IJBJI, TRDD-VJL1YTCG Part A, `edit_project_scope` flip) is complete
and committed locally; every instance on this machine gets it the moment 3.4.0 lands.

## Provenance

Found on the 5th publish attempt of 2026-08-27, after four CPV false-positive rounds. The
Tailscale alert was found by reading the repo's open alerts while classifying the Stripe block.
