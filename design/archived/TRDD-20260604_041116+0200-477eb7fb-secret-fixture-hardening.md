---
trdd-id: 477eb7fb-a16d-40af-b199-5055d9c555a4
title: Harden the janitor's own secret-shaped test fixtures — fragment at rest
column: published
created: 2026-06-04T04:11:16+0200
updated: 2026-06-04T19:18:52+0200
current-owner: janitor-dev-session
assignee: janitor-dev-session
priority: 1
severity: HIGH
effort: L
labels: [security, tests, reputation, secret-scanning]
task-type: security
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, lint]
audit-requirements: [secret-scan]
impacts: [ci-pipeline]
runtime-targets: [macos, linux]
last-test-result: pass
last-test-at: 2026-06-04T19:13:00+0200
implementation-commits: [be57abd, c124f49]
published-version: 0.6.0
published-at: 2026-06-04T19:15:07+0200
---

# TRDD-477eb7fb — Harden the janitor's own secret-shaped test fixtures

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-04

**✅ PUBLISHED v0.6.0 (2026-06-04T19:15:07+0200).** User chose **B2 (squash)**.
HEAD `be57abd` (squash) + `c124f49` (release) pushed to origin/main; tag
`v0.6.0`; GH release live. publish.py gates all green: 10492 tests, ruff,
CPV strict (0 CRIT/MAJ/MIN/NIT). **Post-publish filesystem TruffleHog on the
shipped tree = 0.** Backups kept: branch `backup-pre-squash-133` + tarball
`~/janitor-pre-squash-20260604_190040+0200.tar.gz` (local-only, never pushed).

**KEY CORRECTION discovered during the squash** (the TRDD/summary were WRONG):
of the 116 pre-squash TruffleHog git-history findings, **only 2 were in the
133 unpushed commits — 110 were backup-branch-only after squash, and 4 URI
findings were ALREADY-PUBLISHED in v0.5.1** (`remote-credentials.py/.sh` +
`README.md` — `user:secret@host` doc placeholders, on GitHub ~1mo, no ban).
The squash removed all 10 Stripe + 4 Slack-webhook + Google/Atlassian/Infura
partner-patterns + all 35 JDBC/36 Postgres/7 Mongo conn-strings from the
pushable line. My squash commit introduced **0** findings. The 4 pre-existing
public URI placeholders in deep history were deliberately NOT force-rewritten
(disproportionate + destructive for already-public doc placeholders; user
chose squash, not full-history filter-repo). One working-tree occurrence
(`README.md` L70) was fixed `user:secret`→`user:****` so the shipped-tree
filesystem scan is 0.

**Current state:**
- **Working-tree hardening: DONE & verified, smart-scanner-proof.** Every
  secret-shaped fixture is now **runtime-generated** (`tests/_fake_secrets.py`:
  `secret`/`dsn`/`joinpath`/`b62`/`hexs`) — the realistic value is sha256-derived
  at call time from a seed and **never written as a literal** (whole,
  fragmented, OR reconstructable). **TruffleHog `--no-verification` = 0** on the
  tracked tree (the user switched us off gitleaks — single-process/flaky). Full
  suite = **10492 passed**. ruff = clean. Fragment-interpolation grep = empty.
- Working-tree commits (HEAD = `4fb7ee2`):
  - `8285718` — fragment-the-prefix (superseded in spirit).
  - `19fa249` — **runtime-generation** core: new `_fake_secrets.py`, 31 files +
    7 detector sources.
  - `c2fefb7` — last conn-string creds (rtsp/sip/mssql/redis) + scheme-agnostic guard.
  - `4fb7ee2` — **long-tail**: generic un-prefixed secrets, token/credential
    literals (several only `# gitleaks:allow`-suppressed), base64-WRAPPED creds
    (Docker auth→ghp_, PowerBI→Password=). Guard now 4-class.
- **The guard (`tests/test_secret_fixture_hygiene.py`) is the authoritative
  gate — sees far more than TruffleHog.** Four classes, entropy heuristic +
  placeholder allowlist: (1) vendor token prefixes; (2) conn-strings for ANY
  scheme with embedded creds; (3) generic secret-NAMED assignments
  (secret/password/token/credential/…) with realistic high-entropy value;
  (4) base64 blobs that DECODE to a token prefix. **Guard = 0** on all classes.
- **Verified clean by 3 independent methods**: TruffleHog `--no-verification`
  = 0, the 4-class guard = 0, broad greps = empty. 10492 tests pass, ruff clean.
  Deliberately LEFT (non-credentials): SHA hashes, ETH `0x…` addresses, JWT
  *header* fragments, obvious test vectors — the janitor's detectors need them.
- **History still dirty:** the unpushed commits' diffs still hold the original
  literals (TruffleHog `git` ~116). Tree clean; squash removes them.

**NEXT ACTION:** USER picks the history-clean (endorsed the rewrite; awaiting
explicit `go B2`/`go B1` per RULE 0.6). **B2 (recommended) = squash**:
`tar czf ~/janitor-pre-squash-<ts>.tar.gz .git` ; `git branch
backup-pre-squash-129 HEAD` ; `git reset --soft f2ec394` ; `git commit -m
"<v0.6.0 notes>"`. B1 = `git filter-repo --replace-text` (preserves 129
commits; now viable since the clean tip has no literals to corrupt). After
clean → `uv run python scripts/publish.py --minor` (0.5.1→0.6.0) → post SHA on
janitor #14 / maintainer #7.

**Load-bearing facts / gotchas:**
- The 129 commits are **local-only / unpushed** (`origin/main` = `f2ec394`
  v0.5.1, 0 ahead). Nothing dirty ever reached GitHub.
- **Use TruffleHog, not gitleaks** (user instruction). Correct flags:
  `--no-verification --results=verified,unknown,unverified` (NOT `--results=all`
  — invalid). gitleaks `# gitleaks:allow` comments do NOT suppress trufflehog —
  that's how the first pass looked clean but wasn't.
- The janitor's placeholder allowlist (`is_hardcoded_secret_placeholder`) only
  suppresses `*EXAMPLE`/`*TEST*`/`xxxx` — sha256 high-entropy bodies pass it and
  fire the detectors. Keep `AKIAIOSFODNN7EXAMPLE` verbatim only where a test
  asserts placeholder behavior.
- `.pyc` bytecode re-appears in trufflehog filesystem scans after a test run
  (gitignored, not tracked) — `find tests scripts -name __pycache__ -exec rm -rf
  {} +` then re-scan to see the true tracked count.
- `[:]`/`[/]` one-char regex classes break a literal in a *regex* string while
  matching byte-identically. In *data* strings use `+` concat or a generator.
- `UID` is a readonly zsh variable — use a different name in shell.
- `reportMissingImports` Pyright warnings on `lib.*` (+ 2 unused
  `_file_contains`/`_slice_forward` in wiki_kb/backup_restore detector sources)
  are PRE-EXISTING (runtime `sys.path` / dead local-copies); NOT regressions.

**SUPERSEDED — do NOT carry forward:**
- ✗ "Option A (click the GitHub allow URLs) then publish" — the user
  rejected this: it leaves the realistic fixtures in the tree + history, so
  every downstream scanner re-flags them (reputational risk). Replaced by
  the fragment-at-rest refactor + history clean.

**Durable artifacts:**
- `reports/secret-fixture-hardening/` — per-batch agent reports + the literal
  inventories + gitleaks JSONs.
- `docs_dev/secret-fixture-hardening-spec.md` — the agent spec (the technique).
- Reference implementation: `tests/test_payment_sdk_patterns.py`.

## Problem

The janitor is a secret scanner. Its detector tests are fed secret-shaped
strings. The most realistic of those (notably Stripe `sk_live_51…` keys)
trip GitHub partner-pattern push-protection — blocking the v0.6.0 publish —
and, more importantly, would make every downstream scanner (gitleaks,
GitGuardian) flag the published plugin's OWN repo as "full of secrets."
For a security tool that is a permanent reputational hazard.

## Decision (user-chosen, thorough path)

Refactor so **no contiguous, real-format credential literal exists at rest**
in the source, while the detector still receives the fully-assembled string
at runtime (byte-identical → zero semantic change → all tests keep passing).
Then clean the unpushed history so no commit that reaches GitHub ever held a
contiguous secret. This is strictly better than GitHub's "allow this secret"
button, which would leave the literals in the tree + history.

## Technique (three variants)

1. **Vendor-prefix secrets → fragment the prefix.** A module constant splits
   the prefix with `+` (`_SK_LIVE = "sk_" + "live_"`), then `f"{_SK_LIVE}…"`.
   Runtime value identical; no contiguous prefix at rest.
2. **PEM markers.** Data strings: fragment with `+`. Regex strings: `[ ]`
   one-char class for the space (identical match, breaks the literal).
3. **Prefix-less high-entropy blobs → inline `# gitleaks:allow  pragma:
   allowlist secret`** (value unchanged; nothing to fragment).
- Kept verbatim: `AKIAIOSFODNN7EXAMPLE` (AWS docs canonical; universally
  allowlisted, self-documenting).

## Scope & execution

- ~190 secret-shaped literals across 53 tracked source files.
- Reference file done by hand; remaining 38 test files via 7 parallel agents;
  17 more (realistic GitHub-token/PEM) via 3 second-pass agents; detector
  source + doc + stragglers by hand.
- Each agent gated on: pytest green + gitleaks-0 + ruff clean.

## Verification evidence

- gitleaks `--no-git` tests/ scripts/ skills/ = 0.
- Whole-repo contiguous-marker sweep = empty (excl. AWS canonical).
- `tests/test_secret_fixture_hygiene.py` (new guard) passes — scans tracked
  source on every run, fails on any reintroduced literal.
- Full suite: 10492 passed. ruff: clean.

## Step 3 — history rewrite (PENDING USER APPROVAL — RULE 0.6)

The 127 commits are unpushed, so this carries none of the usual
"rewrite published history" danger. Two options to present:
- **B1 — `git filter-repo --replace-text`**: preserves all 127 commits,
  redacts the ~108 historical literals. Keeps granular dev history.
- **B2 — squash to `origin/main`**: collapse the 127 unpushed WIP commits
  onto the clean tree. Simplest; loses granular history.

Recommend B1 (preserve history). Show the exact command, get explicit OK,
run, then publish.

## Approval log

- 2026-06-04 — USER approved steps 1–2 ("yes, that is a better plan,
  proceed with it"). Step 3 (history rewrite) still requires explicit
  RULE-0.6 approval before execution.
