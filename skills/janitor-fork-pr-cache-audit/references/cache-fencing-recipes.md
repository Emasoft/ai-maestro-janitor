# Cache-fencing recipes

## Table of contents

- [The fence expression](#the-fence-expression)
- [Surgical recipes (R1–R4)](#surgical-recipes-r1r4)
- [Alternatives and escape hatches](#alternatives-and-escape-hatches)

## The fence expression

Across every recipe below, the canonical "is this a same-repo PR?" check is:

```yaml
if: github.event.pull_request.head.repo.full_name == github.repository
```

This is `true` when:

- The trigger is a `push` (the property chain resolves to `null` on both sides; some workflows prefer to OR with `github.event_name != 'pull_request'`).
- The trigger is `pull_request` AND the PR comes from a branch in the same repo (not a fork).

It is `false` (the safe direction) when the PR comes from a fork. Hold this property as the single source of truth — do not invent equivalents like `github.actor == 'Emasoft'` (actor can be spoofed by a malicious bot account) or `contains(github.event.pull_request.labels.*.name, 'trusted')` (labels can be applied by a reviewer who hasn't read the diff).

## Surgical recipes (R1–R4)

### R1 — Fence the save step

**Detector match:** D1 (fork-PR cache write).

**Before:**

```yaml
on:
  pull_request:
    branches: [main]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
      - uses: actions/cache@<sha>
        with:
          path: ~/.cache/foo
          key: foo-${{ runner.os }}-${{ hashFiles('**/lockfile') }}
      - run: ./build.sh
```

**After:**

```yaml
on:
  pull_request:
    branches: [main]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
      - name: Restore cache (always)
        uses: actions/cache/restore@<sha>
        with:
          path: ~/.cache/foo
          key: foo-${{ runner.os }}-${{ hashFiles('**/lockfile') }}
      - run: ./build.sh
      - name: Save cache (same-repo only)
        if: github.event.pull_request.head.repo.full_name == github.repository
        uses: actions/cache/save@<sha>
        with:
          path: ~/.cache/foo
          key: foo-${{ runner.os }}-${{ hashFiles('**/lockfile') }}
```

Forks read the cache (fine — the cache is content-addressed by lockfile hash, and reading a known-good entry is safe). Forks never write. Trusted-branch and same-repo PRs continue to populate the cache.

### R2 — Fence both restore and save

**Detector match:** D2 (half-fenced cache).

**Before:**

```yaml
- uses: actions/cache/restore@<sha>
  if: github.event.pull_request.head.repo.full_name == github.repository
  with: { path: ~/.cache/foo, key: foo-${{ hashFiles('**/lockfile') }} }
- run: ./build.sh
- uses: actions/cache/save@<sha>
  with: { path: ~/.cache/foo, key: foo-${{ hashFiles('**/lockfile') }} }
```

**After:**

```yaml
- uses: actions/cache/restore@<sha>
  with: { path: ~/.cache/foo, key: foo-${{ hashFiles('**/lockfile') }} }
- run: ./build.sh
- uses: actions/cache/save@<sha>
  if: github.event.pull_request.head.repo.full_name == github.repository
  with: { path: ~/.cache/foo, key: foo-${{ hashFiles('**/lockfile') }} }
```

The author meant to fence forks; they fenced the wrong side. Restore-from-cache is safe to leave unfenced (the cache key already includes the lockfile hash, so a fork can only read entries whose lockfile content they already control). Save-to-cache is the dangerous side.

### R3 — Never checkout fork code under pull_request_target

**Detector match:** D3 (CRITICAL).

**Before:**

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
          ref: ${{ github.event.pull_request.head.sha }}
      - run: npm ci && npm test
```

**After (Option A — most jobs):**

```yaml
on:
  pull_request:                          # NOT pull_request_target
    branches: [main]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>     # checks out the merge commit by default
      - run: npm ci && npm test
```

`pull_request` already runs the test suite against the merge of fork-HEAD into base; you keep the safety guarantees AND lose the secret-scope footgun.

**After (Option B — the job genuinely needs base secrets, e.g. comment-posting):**

```yaml
on:
  pull_request_target:
    branches: [main]
jobs:
  post-comment:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@<sha>     # checks out BASE, not fork HEAD
      - run: |
          gh pr comment "$PR" --body "Build started"
        env:
          PR: ${{ github.event.pull_request.number }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

Never combine `pull_request_target` with a `ref: ${{ github.event.pull_request.head.* }}` checkout. If the job must inspect fork code AND have base secrets, split it into two workflows: a `pull_request` job that produces an artifact, and a `workflow_run` job that consumes the artifact with secret scope.

### R4 — Disable setup-action default cache on pull_request

**Detector match:** D4 (MAJOR).

**Before:**

```yaml
on: { pull_request: {} }
jobs:
  test:
    steps:
      - uses: astral-sh/setup-uv@<sha>
      - uses: actions/setup-node@<sha>
        with: { node-version: 22, cache: npm }
      - uses: actions/setup-python@<sha>
        with: { python-version: '3.12', cache: pip }
```

**After:**

```yaml
on: { pull_request: {} }
jobs:
  test:
    steps:
      - uses: astral-sh/setup-uv@<sha>
        with: { enable-cache: false }
      - uses: actions/setup-node@<sha>
        with: { node-version: 22 }            # `cache:` removed
      - uses: actions/setup-python@<sha>
        with: { python-version: '3.12' }      # `cache:` removed
```

Opt-out keys per action:

| Action | Opt-out |
|---|---|
| `astral-sh/setup-uv` | `enable-cache: false` |
| `actions/setup-node` | omit `cache:` (or `cache: ''`) |
| `actions/setup-python` | omit `cache:` |
| `actions/setup-go` | `cache: false` |
| `actions/setup-java` | omit `cache:` |

Trusted-branch (`push: { branches: [main] }`) and tag (`push: { tags: ['v*'] }`) workflows MAY keep caching enabled — they don't run on fork PRs, so the cache write path is closed by default.

## Alternatives and escape hatches

**Split workflows by trigger.** Move all caching to a `push`-only workflow that runs on `main`. The `pull_request` workflow becomes cache-less but secret-less.

**Use environment-scoped caches.** GitHub's cache is keyed by `(ref, key)` since November 2024; a fork PR with `actions/cache@v4+` cannot directly overwrite the trusted-branch entry. This is a defense-in-depth layer, NOT a substitute for fencing — older runners and self-hosted caches still allow cross-ref collisions.

**Pin everything to commit SHAs.** Required by `~/.claude/rules/gh-actions.md`. Doesn't prevent cache poisoning, but limits the blast radius if a fork manages to inject an upstream action update.

**Add a CODEOWNERS gate.** Workflows under `.github/workflows/` should require explicit review from a designated owner; combine with a branch protection rule that prevents merging if `.github/` was touched without owner approval. Cache-poisoning attacks frequently arrive as innocuous-looking workflow tweaks.
