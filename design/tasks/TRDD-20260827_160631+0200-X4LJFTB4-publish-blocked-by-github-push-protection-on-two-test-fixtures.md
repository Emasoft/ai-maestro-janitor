---
trdd-id: X4LJFTB4
title: Publish 3.4.0 is blocked at the push by GitHub push protection on two synthetic test fixtures
column: todo
created: 2026-08-27T16:06:31+0200
updated: 2026-08-28T21:06:00+0200
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
implementation-commits: []
relevant-rules: []
---

# Publish 3.4.0 is blocked at the push by GitHub push protection on two synthetic test fixtures

## ⏵ STATE — READ THIS FIRST ON RESUME

**The release is code-complete and green through EVERY local gate. It cannot leave the machine.
Both blockers are synthetic test fixtures, not credentials, and both resolutions are the OWNER's
to make — one is a repo security setting, the other is history.** Nothing here is for an agent
to "fix" unattended.

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

For **Blocker 2**: close alert `#1` with resolution `used_in_tests` (the accurate one). Owner
action in the GitHub UI or `gh api … -f state=resolved -f resolution=used_in_tests`.

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
