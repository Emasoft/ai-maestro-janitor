# Fork-PR attack vectors

## Table of contents

- [Background: the TanStack incident](#background-the-tanstack-incident)
- [Detector patterns (D1–D4)](#detector-patterns-d1d4)
- [Why severity is graded this way](#why-severity-is-graded-this-way)

## Background: the TanStack incident

The TanStack supply-chain compromise (mid-2024) chained two GitHub Actions misconfigurations: a `pull_request` workflow that warmed a cache key shared with the trusted-branch build pipeline, and a `pull_request_target` workflow that checked out the PR head SHA with secrets in scope. A fork PR was crafted so that:

1. Its CI run wrote a poisoned tarball into the shared `actions/cache` key for the toolchain.
2. The next push-to-`main` build restored that poisoned cache, ran post-install hooks from it, and published a tampered release artifact.

The lesson: a cache restored by a trusted-branch build is **as trusted as the least-trusted workflow that can write to the same key**. Forks must be fenced out of every cache write path that the trusted-branch path will later read.

## Detector patterns (D1–D4)

### D1 — fork-PR cache write (HIGH)

**Pattern matched:**

```yaml
on:
  pull_request:                # NOT pull_request_target
    branches: [main]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
      - uses: actions/cache@<sha>      # OR actions/cache/save@*, OR actions/cache/restore@*
        with:
          path: ~/.cache/foo
          key: foo-${{ runner.os }}-${{ hashFiles('lockfile') }}
```

**Why it's HIGH (not CRITICAL):** the workflow runs in the fork's reduced-permission GITHUB_TOKEN context, so secrets are NOT leaked here. The blast radius is contained to cache-key collisions — but those collisions feed into trusted-branch builds, which IS where exploitation happens. Treat any cache write from a `pull_request` workflow as a future-poison vector unless explicitly fenced (see D2).

**Reference recipe:** [cache-fencing-recipes.md → R1](cache-fencing-recipes.md#r1--fence-the-save-step) — wrap the cache step in `if: github.event.pull_request.head.repo.full_name == github.repository`.

### D2 — half-fenced cache (HIGH)

**Pattern matched:**

```yaml
- uses: actions/cache/restore@<sha>
  if: github.event.pull_request.head.repo.full_name == github.repository
  with: { ... }
- run: ./build.sh
- uses: actions/cache/save@<sha>          # NO if: — fork PR can still save
  with: { ... }
```

The intent is correct (fence forks out) but applied only to RESTORE. A fork still reaches the SAVE step and writes the cache. The trusted-branch run then restores it.

**Why it's HIGH:** the half-fence gives a false sense of safety. Reviewers see the `if:` on restore and assume the workflow is hardened; the actual exploit path is on save.

**Reference recipe:** [cache-fencing-recipes.md → R2](cache-fencing-recipes.md#r2--fence-both-restore-and-save) — duplicate the same `if:` on the save step (or move both to a job-level fence).

### D3 — pull_request_target with fork checkout (CRITICAL)

**Pattern matched:**

```yaml
on:
  pull_request_target:
    branches: [main]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
        with:
          ref: ${{ github.event.pull_request.head.sha }}    # or .head.ref
      - run: npm ci && npm test
```

**Why it's CRITICAL:** `pull_request_target` runs with the BASE repo's secret scope (full `GITHUB_TOKEN`, every `secrets.*`, every protected env), AND the explicit ref override checks out untrusted fork code. The fork's `package.json` postinstall hook now executes with full write access to the base repo. This IS the TanStack exploit shape — direct RCE on the runner with secrets.

**Reference recipe:** [cache-fencing-recipes.md → R3](cache-fencing-recipes.md#r3--never-checkout-fork-code-under-pull_request_target) — change to `on: pull_request` if the job genuinely doesn't need elevated permissions, OR remove the `ref:` override and accept that you're linting the merge commit, not the fork's HEAD.

### D4 — implicit setup-action cache (MAJOR)

**Pattern matched:**

```yaml
on: { pull_request: {} }
jobs:
  test:
    steps:
      - uses: astral-sh/setup-uv@<sha>       # enable-cache defaults to true
      - uses: actions/setup-node@<sha>       # cache: 'npm' may be enabled
      - uses: actions/setup-python@<sha>     # cache: 'pip' may be enabled
      - uses: actions/setup-go@<sha>         # cache: true by default on recent versions
      - uses: actions/setup-java@<sha>       # cache: 'maven' / 'gradle' optional
```

Setup actions transparently call `actions/cache` under the hood. A `pull_request` workflow using any of these inherits D1 without an explicit `actions/cache` step — easy to miss in review.

**Why it's MAJOR (not HIGH):** the cache scopes are narrower (toolchain binaries, package managers) than a hand-rolled `actions/cache` key. The damage path is still real (poisoned npm registry mirror, malicious uv-resolved tarball) but the attack surface is smaller and many of these caches are content-addressed.

**Reference recipe:** [cache-fencing-recipes.md → R4](cache-fencing-recipes.md#r4--disable-setup-action-default-cache-on-pull_request) — pass `with: { enable-cache: false }` (or the action's documented opt-out: `cache: ''`, `cache: false`).

## Why severity is graded this way

| Class | Secret access | RCE on runner | Cache-write reachable | Severity |
|---|---|---|---|---|
| D1 | fork-token only | no | yes (poison future trusted run) | HIGH |
| D2 | fork-token only | no | yes (save side unfenced) | HIGH |
| D3 | **base-repo secrets** | **yes** | (irrelevant, full RCE) | **CRITICAL** |
| D4 | fork-token only | no | yes (toolchain-scoped) | MAJOR |

CRITICAL findings block PR merge. HIGH and MAJOR are written to the report and surfaced in the summary line; remediation is mandatory but does not gate merge automatically — the audit is an inspection tool, not a hook.
