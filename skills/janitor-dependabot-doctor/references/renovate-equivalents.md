# Renovate equivalents

## Table of contents

- [Why this file exists](#why-this-file-exists)
- [Mapping and baseline](#mapping-and-baseline)
- [Per-ecosystem rules and edge cases](#per-ecosystem-rules-and-edge-cases)

## Why this file exists

Some projects use Renovate (Mend) instead of Dependabot. The doctor's
invariants do not change — schedule, PR cap, commit prefix, grouping,
versioning strategy, pin ignores — only the YAML field names do. This
file maps every Dependabot invariant to its Renovate equivalent so the
audit branch can apply surgical fixes against `renovate.json`.

## Mapping and baseline

### Config-file resolution order

When the doctor finds a Renovate config, it audits exactly ONE file. The
file is discovered in this priority order, first hit wins:

1. `renovate.json`
2. `renovate.json5`
3. `.github/renovate.json`
4. `.github/renovate.json5`
5. `.renovaterc` (JSON5)
6. `.renovaterc.json`

`package.json#renovate` is also supported by Renovate itself, but the
doctor refuses to audit it because edits there entangle dependency state
with renovate config — the doctor surfaces it as
`[NEEDS-HUMAN-REVIEW] move renovate config out of package.json`.

### Invariant ↔ renovate-key mapping

| Dependabot invariant | Renovate equivalent | Notes |
|---|---|---|
| `schedule.interval: "weekly"` + `day: "monday"` + `time: "04:NN"` | `"schedule": ["before 5am on monday"]` | Renovate uses natural-language cron-ish strings. Per-ecosystem stagger is done with `packageRules[].schedule`. |
| `open-pull-requests-limit: 5` | `"prConcurrentLimit": 5` and `"prHourlyLimit": 2` | The hourly cap throttles the burst even when the concurrent cap allows more queueing. |
| `commit-message.prefix: "deps"` + `commit-message.include: "scope"` | `"semanticCommits": "enabled"` + `"commitMessagePrefix": "deps"` + `"semanticCommitType": "deps"` + `"semanticCommitScope": "{{depName}}"` | Renovate emits `deps({{depName}}): ...` headers — matches what git-cliff expects. |
| `versioning-strategy: "increase"` (pip / npm) | `"rangeStrategy": "bump"` | `"bump"` updates the manifest constraint AND the lockfile; the default `"replace"` only edits the lockfile. |
| `groups.dev-dependencies` / `groups.prod-dependencies` | `packageRules` matching on `depTypeList: ["devDependencies"]` / `["dependencies"]` + `"groupName": "dev-dependencies"` | Renovate's grouping is per `packageRules` block, not per-block as Dependabot. |
| `groups.actions.patterns: ["*"]` (github-actions) | `packageRules` matching `"matchManagers": ["github-actions"]` with `"groupName": "github-actions"` | Same end effect: one PR per week for all action bumps. |
| `labels: ["dependencies", "<ecosystem>"]` | `"labels": ["dependencies", "<ecosystem>"]` | Identical field name. |
| `ignore: [{ dependency-name: "X", versions: ["<2"] }]` | `packageRules` matching `"matchPackageNames": ["X"]` + `"enabled": false` (or `"allowedVersions": "<2"`) | Renovate has finer-grained control via `allowedVersions`. |

### Recommended baseline renovate.json

If the doctor decides to audit-rewrite a renovate config that is missing
multiple invariants, it does NOT scaffold from scratch (that is what
`dependabot.yml` is for). It applies the smallest set of patches that
restores compliance. The target shape looks like:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": [
    "config:recommended",
    ":semanticCommits",
    ":semanticCommitTypeAll(deps)",
    ":dependencyDashboard",
    ":prHourlyLimit2",
    ":prConcurrentLimit5"
  ],
  "schedule": ["before 5am on monday"],
  "timezone": "Etc/UTC",
  "labels": ["dependencies"],
  "rangeStrategy": "bump",
  "commitMessagePrefix": "deps",
  "packageRules": [
    {
      "matchDepTypes": ["devDependencies"],
      "groupName": "dev-dependencies",
      "labels": ["dependencies", "dev"]
    },
    {
      "matchDepTypes": ["dependencies"],
      "groupName": "prod-dependencies",
      "labels": ["dependencies", "prod"]
    },
    {
      "matchManagers": ["github-actions"],
      "groupName": "github-actions",
      "labels": ["dependencies", "github-actions"],
      "schedule": ["before 6am on monday"]
    }
  ],
  "ignoreDeps": []
}
```

`config:recommended` (formerly `config:base`) preserves Renovate's safe
defaults around lockfile updates, automerge gates, and PR rebases. The
doctor never disables those gates.

## Per-ecosystem rules and edge cases

### Per-ecosystem packageRules

Most renovate configs already use `config:recommended`, which auto-detects
ecosystems via `enabledManagers` — the doctor does NOT need a per-manifest
manager list. But for the staggered-schedule rule (each ecosystem at a
different off-minute) the doctor adds one `packageRules` entry per
detected ecosystem with its own `schedule`:

| Ecosystem | `matchManagers` | `schedule` |
|---|---|---|
| pip | `["pip_requirements", "poetry", "pip_setup"]` | `["before 5am on monday"]` |
| npm | `["npm"]` | `["before 5:05am on monday"]` |
| cargo | `["cargo"]` | `["before 5:10am on monday"]` |
| gomod | `["gomod"]` | `["before 5:15am on monday"]` |
| bundler | `["bundler"]` | `["before 5:20am on monday"]` |
| github-actions | `["github-actions"]` | `["before 6am on monday"]` |

(Renovate accepts both `"before 5am on monday"` and the more precise
`"before 5:05am on monday"` — minute precision is fine in modern
renovate versions.)

### Cross-doctor edge cases

- **Both files present** (`.github/dependabot.yml` AND any
  `renovate.*`). The doctor aborts — having both is always a config
  conflict. The user picks one before re-running the doctor.
- **Renovate via `package.json#renovate`.** The doctor refuses to edit
  it (commit churn would entangle dep state with renovate config).
  Surfaces `[NEEDS-HUMAN-REVIEW] move renovate config out of package.json`.
- **Renovate config has `"enabled": false`.** The doctor treats this as
  an intentional opt-out and exits clean with a one-line summary
  noting the disable.
- **`packageRules` entries with `"enabled": false` for a whole
  ecosystem.** Same — treated as intentional. Per-package pins use
  `allowedVersions`, not `enabled: false`.
