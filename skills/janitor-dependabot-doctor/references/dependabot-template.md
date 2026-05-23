# Dependabot template (per ecosystem)

## Table of contents

- [Signal-detection table](#signal-detection-table)
- [Shared invariants and schedule-stagger rule](#shared-invariants-and-schedule-stagger-rule)
- [Per-ecosystem templates](#per-ecosystem-templates)
- [Full example and rationale](#full-example-and-rationale)

## Signal-detection table

The doctor walks the **repo root only** (not nested dirs — Dependabot's
`directory: "/"` covers nested manifests via the package manager itself).
Each match adds one `updates:` entry to the generated `.github/dependabot.yml`.

| Repo-root signal | ecosystem name | `directory` value |
|---|---|---|
| `pyproject.toml`, `requirements.txt`, `requirements*.txt`, `setup.py`, `Pipfile`, `poetry.lock` | `pip` | `"/"` |
| `package.json` | `npm` | `"/"` |
| `Cargo.toml` | `cargo` | `"/"` |
| `go.mod` | `gomod` | `"/"` |
| `Gemfile` | `bundler` | `"/"` |
| `.github/workflows/*.yml` or `*.yaml` (≥ 1 file) | `github-actions` | `"/"` |
| `composer.json` | `composer` | `"/"` |
| `Dockerfile` (or `*.Dockerfile`) | `docker` | `"/"` |
| `pubspec.yaml` | `pub` | `"/"` |
| `mix.exs` | `mix` | `"/"` |

If none of these signals matches, the doctor aborts (no ecosystem to manage).

## Shared invariants and schedule-stagger rule

### Schedule stagger

When the project has ≥ 2 ecosystems, stagger each ecosystem's `schedule.time`
by 5 minutes so Dependabot's PR-rebase queue does not spike at the same
minute. All ecosystems share `interval: "weekly"` and `day: "monday"`.
Offsets cycle: `04:07`, `04:12`, `04:17`, `04:22`, `04:27`, `04:32`. Off-minute
times (`07`, `12`, `17`, …) are preferred over `:00` to avoid the cron-thunder
that happens server-side at minute zero.

### Shared invariants — every ecosystem block

Every `updates:` block in `.github/dependabot.yml` must have ALL of these
fields. The doctor refuses to land a block missing any of them.

- `package-ecosystem`: one of the names from the signal table.
- `directory: "/"`.
- `schedule.interval: "weekly"`, `day: "monday"`, `time: "04:NN"`, `timezone: "Etc/UTC"`.
- `open-pull-requests-limit: 5`.
- `commit-message.prefix: "deps"`, `commit-message.include: "scope"`.
- `labels: ["dependencies", "<ecosystem>"]`.
- `groups` block when applicable (npm + pip — see per-ecosystem sections).
- `ignore` block — empty by default, but the field is still present so future
  pins are added in-place rather than appended without context.

## Per-ecosystem templates

### Python (pip)

```yaml
- package-ecosystem: "pip"
  directory: "/"
  schedule:
    interval: "weekly"
    day: "monday"
    time: "04:07"
    timezone: "Etc/UTC"
  open-pull-requests-limit: 5
  versioning-strategy: "increase"
  commit-message:
    prefix: "deps"
    include: "scope"
  labels:
    - "dependencies"
    - "pip"
  groups:
    dev-dependencies:
      dependency-type: "development"
    prod-dependencies:
      dependency-type: "production"
  ignore: []
```

`versioning-strategy: "increase"` makes pip update the manifest (pyproject /
requirements) along with the lockfile — without this, Dependabot only bumps
the lock and the manifest goes stale. `lockfile-only` is implicitly `false`.

### Node (npm)

```yaml
- package-ecosystem: "npm"
  directory: "/"
  schedule:
    interval: "weekly"
    day: "monday"
    time: "04:12"
    timezone: "Etc/UTC"
  open-pull-requests-limit: 5
  versioning-strategy: "increase"
  commit-message:
    prefix: "deps"
    include: "scope"
  labels:
    - "dependencies"
    - "npm"
  groups:
    dev-dependencies:
      dependency-type: "development"
    prod-dependencies:
      dependency-type: "production"
  ignore: []
```

Same shape as pip. Yarn / pnpm projects also use `package-ecosystem: "npm"`
(Dependabot detects the lockfile flavour automatically).

### Rust (cargo)

```yaml
- package-ecosystem: "cargo"
  directory: "/"
  schedule:
    interval: "weekly"
    day: "monday"
    time: "04:17"
    timezone: "Etc/UTC"
  open-pull-requests-limit: 5
  commit-message:
    prefix: "deps"
    include: "scope"
  labels:
    - "dependencies"
    - "cargo"
  ignore: []
```

No dev/prod grouping — cargo does not expose the distinction at the
Dependabot layer.

### Go (gomod)

```yaml
- package-ecosystem: "gomod"
  directory: "/"
  schedule:
    interval: "weekly"
    day: "monday"
    time: "04:22"
    timezone: "Etc/UTC"
  open-pull-requests-limit: 5
  commit-message:
    prefix: "deps"
    include: "scope"
  labels:
    - "dependencies"
    - "gomod"
  ignore: []
```

### Ruby (bundler)

```yaml
- package-ecosystem: "bundler"
  directory: "/"
  schedule:
    interval: "weekly"
    day: "monday"
    time: "04:27"
    timezone: "Etc/UTC"
  open-pull-requests-limit: 5
  versioning-strategy: "increase"
  commit-message:
    prefix: "deps"
    include: "scope"
  labels:
    - "dependencies"
    - "bundler"
  ignore: []
```

### GitHub Actions

```yaml
- package-ecosystem: "github-actions"
  directory: "/"
  schedule:
    interval: "weekly"
    day: "monday"
    time: "04:32"
    timezone: "Etc/UTC"
  open-pull-requests-limit: 5
  commit-message:
    prefix: "deps"
    include: "scope"
  labels:
    - "dependencies"
    - "github-actions"
  groups:
    actions:
      patterns:
        - "*"
  ignore: []
```

Single `groups.actions` block batches all action bumps into one PR — actions
update frequently and individual PRs flood the queue.

## Full example and rationale

### Full multi-ecosystem example

When a repo has `pyproject.toml` + `.github/workflows/*.yml`:

```yaml
version: 2
updates:
  # Pip — Monday 04:07 UTC
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "04:07"
      timezone: "Etc/UTC"
    open-pull-requests-limit: 5
    versioning-strategy: "increase"
    commit-message:
      prefix: "deps"
      include: "scope"
    labels:
      - "dependencies"
      - "pip"
    groups:
      dev-dependencies:
        dependency-type: "development"
      prod-dependencies:
        dependency-type: "production"
    ignore: []

  # GitHub Actions — Monday 04:32 UTC
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "04:32"
      timezone: "Etc/UTC"
    open-pull-requests-limit: 5
    commit-message:
      prefix: "deps"
      include: "scope"
    labels:
      - "dependencies"
      - "github-actions"
    groups:
      actions:
        patterns:
          - "*"
    ignore: []
```

### Why these choices

- **Weekly, not daily.** Daily floods review and exhausts CI minutes; weekly schedule plus grouping turns N dependency bumps into ≤ 2 PRs per ecosystem.
- **Monday 04:NN UTC.** Server-side cron load is lowest on Monday morning
  UTC, before the EU and US work day, so the PRs are queued by the time a
  human starts triage on Monday.
- **`open-pull-requests-limit: 5`.** Cap on simultaneous PRs prevents
  Dependabot from flooding when a transitive dep has many leaves to fix.
- **`deps` commit prefix.** Matches the canonical-pipeline / git-cliff
  changelog scheme — bumps land under a single `### Dependencies` section.
- **Dev / prod grouping (npm + pip).** Separating runtime from build-only
  bumps lets the reviewer fast-track dev-only PRs (no production risk) and
  focus on the prod ones.
- **`versioning-strategy: increase`.** Without it the manifest stays at the
  old constraint while the lockfile drifts forward — every fresh `pip
  install --upgrade` would undo the bump.
- **Empty `ignore: []` placeholder.** Future pins are added in-place
  (where the field already exists), not appended without context.
