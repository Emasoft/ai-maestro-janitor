# Audit table — finding ↔ surgical fix

## Table of contents

- [How the doctor applies a fix](#how-the-doctor-applies-a-fix)
- [Findings by config type](#findings-by-config-type)
- [Findings the doctor refuses to auto-fix](#findings-the-doctor-refuses-to-auto-fix)

## How the doctor applies a fix

For every finding the doctor:

1. Records `<file>:<line>` + the audit id.
2. Looks up the row in the table below.
3. Applies the `Edit` (NEVER `sed` / `awk`).
4. Validates: `python3 -c "import yaml; yaml.safe_load(open('.github/dependabot.yml'))"`
   (or `python3 -c "import json; json.load(open('renovate.json'))"` for
   Renovate). If validation fails: `git checkout HEAD -- <file>`, mark the
   finding `[FIX-FAILED]`, and continue with the remaining findings.
5. Logs the before/after hunk to `$REPORT_DIR/<TS>-fixes.md`.

Findings without a recipe row are surfaced as `[NEEDS-HUMAN-REVIEW]`. The
doctor never silently skips a finding.

## Findings by config type

### Dependabot findings

| Audit id | Trigger | Surgical fix |
|---|---|---|
| `db-missing-file` | `.github/dependabot.yml` does not exist AND ≥ 1 ecosystem signal | Write the full template from [dependabot-template.md](dependabot-template.md), one `updates:` block per detected ecosystem. Use the staggered `time:` offsets from the schedule-stagger rule. |
| `db-version-missing` | File has no top-level `version: 2` | Insert `version: 2` as the first non-comment line. |
| `db-schedule-daily` | Any block has `schedule.interval: "daily"` | Replace with `interval: "weekly"`, `day: "monday"`, `time: "04:NN"` (next stagger slot), `timezone: "Etc/UTC"`. |
| `db-schedule-no-time` | Block has `interval: "weekly"` but no `time:` | Add `time: "04:NN"` (next stagger slot) and `timezone: "Etc/UTC"`. |
| `db-schedule-on-minute-zero` | `time:` ends in `:00` | Shift to the next off-minute stagger slot (`:07`, `:12`, …). |
| `db-schedule-no-timezone` | `time:` set but `timezone:` missing | Add `timezone: "Etc/UTC"`. |
| `db-pr-limit-missing` | No `open-pull-requests-limit:` | Add `open-pull-requests-limit: 5`. |
| `db-pr-limit-too-high` | `open-pull-requests-limit: >10` | Lower to `5`. |
| `db-pr-limit-zero` | `open-pull-requests-limit: 0` | Surface as `[NEEDS-HUMAN-REVIEW] — 0 disables updates entirely, confirm intent`. |
| `db-commit-prefix-missing` | No `commit-message.prefix:` | Add `commit-message: { prefix: "deps", include: "scope" }`. |
| `db-commit-prefix-wrong` | `commit-message.prefix:` ≠ `"deps"` (e.g. `"chore"`, `"bump"`) | Replace with `"deps"`. |
| `db-commit-include-missing` | `commit-message.prefix:` set but `include:` missing | Add `include: "scope"`. |
| `db-labels-missing` | No `labels:` | Add `labels: ["dependencies", "<ecosystem>"]`. |
| `db-labels-no-dependencies` | `labels:` set but missing `"dependencies"` | Prepend `"dependencies"` to the list. |
| `db-groups-missing-npm` | `package-ecosystem: "npm"` but no `groups:` | Add `groups: { dev-dependencies: { dependency-type: development }, prod-dependencies: { dependency-type: production } }`. |
| `db-groups-missing-pip` | `package-ecosystem: "pip"` but no `groups:` | Same as `db-groups-missing-npm`. |
| `db-groups-missing-actions` | `package-ecosystem: "github-actions"` but no `groups:` | Add `groups: { actions: { patterns: ["*"] } }`. |
| `db-versioning-missing-pip` | `package-ecosystem: "pip"` but no `versioning-strategy:` | Add `versioning-strategy: "increase"`. |
| `db-versioning-wrong-pip` | `package-ecosystem: "pip"` and `versioning-strategy:` ≠ `"increase"` (e.g. `"lockfile-only"`) | Replace with `"increase"`. |
| `db-versioning-missing-npm` | `package-ecosystem: "npm"` but no `versioning-strategy:` | Add `versioning-strategy: "increase"`. |
| `db-ignore-missing` | No `ignore:` field | Add `ignore: []` (placeholder — future pins land here in-place). |
| `db-ecosystem-missing` | Detected ecosystem (signal table) has no matching `updates:` block | Append a new `updates:` block from the per-ecosystem template, using the next stagger slot. |
| `db-duplicate-ecosystem-dir` | Two blocks share `package-ecosystem` + `directory` | Surface as `[NEEDS-HUMAN-REVIEW] — duplicate block`. |
| `db-schedule-collision` | Two blocks share `day:` + `time:` | Shift the second block to the next stagger slot. |
| `db-allow-too-broad` | `allow:` block has `dependency-type: all` with no further filter | Surface as `[NEEDS-HUMAN-REVIEW]` — `allow: all` defeats the safety gate. |
| `db-rebase-strategy-wrong` | `rebase-strategy: "disabled"` | Surface as `[NEEDS-HUMAN-REVIEW]` — disabling rebase usually means a CI conflict, not a config bug. |

### Renovate findings

| Audit id | Trigger | Surgical fix |
|---|---|---|
| `rn-schedule-missing` | No top-level `schedule:` | Add `"schedule": ["before 5am on monday"]` + `"timezone": "Etc/UTC"`. |
| `rn-schedule-too-broad` | `schedule: ["at any time"]` or equivalent | Replace with `["before 5am on monday"]`. |
| `rn-pr-concurrent-missing` | No `prConcurrentLimit:` | Add `"prConcurrentLimit": 5`. |
| `rn-pr-hourly-missing` | No `prHourlyLimit:` | Add `"prHourlyLimit": 2`. |
| `rn-pr-concurrent-too-high` | `prConcurrentLimit:` > 10 | Lower to `5`. |
| `rn-semantic-commits-missing` | No `extends` entry for `:semanticCommits` AND no top-level `semanticCommits` | Add `":semanticCommits"` to `extends` and `"semanticCommitType": "deps"`. |
| `rn-commit-prefix-wrong` | `commitMessagePrefix:` ≠ `"deps"` | Replace with `"deps"`. |
| `rn-range-strategy-replace` | `rangeStrategy: "replace"` for npm/pip | Replace with `"bump"` (only updates lockfile + manifest together). |
| `rn-groups-missing-actions` | `enabledManagers` includes `github-actions` but no group rule | Add a `packageRules` entry: `{ matchManagers: ["github-actions"], groupName: "github-actions" }`. |
| `rn-groups-missing-devdeps` | `enabledManagers` includes `npm` or `pip_*` but no dev-deps group | Add a `packageRules` entry: `{ matchDepTypes: ["devDependencies"], groupName: "dev-dependencies" }`. |
| `rn-labels-missing` | No top-level `labels:` | Add `"labels": ["dependencies"]`. |
| `rn-labels-no-dependencies` | `labels:` set but missing `"dependencies"` | Prepend `"dependencies"` to the array. |
| `rn-ignoredeps-missing` | No `ignoreDeps:` and no per-package `enabled: false` rules | Add `"ignoreDeps": []` (placeholder, same role as Dependabot's `ignore:`). |
| `rn-dashboard-missing` | `extends` lacks `:dependencyDashboard` | Add `":dependencyDashboard"` (gives the maintainer a single tracking issue). |
| `rn-base-config-missing` | `extends` does not include `config:recommended` (or its predecessor `config:base`) | Prepend `"config:recommended"` to `extends`. |
| `rn-renovate-in-packagejson` | Renovate config lives under `package.json#renovate` | `[NEEDS-HUMAN-REVIEW] move renovate config out of package.json`. |
| `rn-automerge-no-gate` | `automerge: true` AND no `automergeType:` or no test-gate condition | `[NEEDS-HUMAN-REVIEW]` — auto-merge without a CI gate is unsafe. |

### Cross-config findings

| Audit id | Trigger | Surgical fix |
|---|---|---|
| `db+rn-both-present` | `.github/dependabot.yml` AND a Renovate config both exist | Abort with `[FAILED] both dependabot and renovate present; pick one`. |
| `db+rn-neither-present` | Neither exists AND no ecosystem signal in repo root | Abort with `[FAILED] no detectable package ecosystem`. |

## Findings the doctor refuses to auto-fix

These show up frequently and are always `[NEEDS-HUMAN-REVIEW]`. They
involve a policy or release-cycle decision that no auto-fix can make:

- **`automerge: true` for production deps.** The doctor never enables
  auto-merge — a human decides which packages are safe to bump without
  review.
- **`allow:` block restricting updates to a hand-picked list.** The
  doctor leaves it alone — the list represents the maintainer's
  curated trust set.
- **`registries:` block** (private package registries with auth tokens).
  Editing this requires knowing which token names are exported in the
  Dependabot org settings.
- **Per-package `ignore:` with `versions:` lists.** The doctor preserves
  every existing pin verbatim; new pins are added in-place but never
  removed automatically.
- **`pull-request-branch-name.separator:`.** Cosmetic; not a hardening
  concern.
- **`reviewers:` / `assignees:`.** Project-policy decision.
- **`milestone:`.** Project-policy decision.

For any of these, the doctor emits a `[NEEDS-HUMAN-REVIEW] — <reason>`
line in the report and does NOT touch the field.
