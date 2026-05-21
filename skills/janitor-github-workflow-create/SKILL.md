---
name: janitor-github-workflow-create
description: Analyzes a project and creates a zizmor-clean set of GitHub Actions workflows from scratch, including bootstrapping the GitHub repo via `gh repo create` if it does not yet exist. Use when starting a new project, when a project has no .github/workflows/ directory, when the user asks to "set up CI", "create the GitHub workflows", "scaffold CI", "bootstrap github actions", or "set up the repo". Trigger with /janitor-github-workflow-create or "create github workflows for this project".
---

# Janitor github-workflow-create

## Overview

Generates a zizmor-clean GitHub Actions workflow set tailored to the project's languages, package managers, and release model. Bootstraps the GitHub repo via `gh repo create` when missing. Every workflow is hardened so the final `zizmor` pass reports zero findings.

Pairs with `/janitor-github-workflow-doctor`.

## Prerequisites

- `gh` on PATH, authenticated; `git` initialised; `uv` on PATH.
- Secrets exported as env vars; installed via `gh secret set --body "$ENV_VAR_NAME"` (name only, never value).

## Instructions

Detail for every numbered step (signal table, full bash blocks, generation invariants, helper functions) lives in [references/workflow-set-generation.md](references/workflow-set-generation.md) — links below jump to the matching section.

1. **Detect the project shape.** Inspect for language / package-manager / test-runner signals. Map: [project-shape-signals](references/workflow-set-generation.md#project-shape-signals). Record matches in `$REPORT_DIR/<TS>-project-shape.md`.

2. **Bootstrap the repo if missing.** If `gh repo view <owner>/<name>` fails, run `gh repo create --public --source . --remote origin --push`. See [repo-bootstrap](references/workflow-set-generation.md#repo-bootstrap).

3. **Resolve action SHAs.** Every third-party action SHA-pinned with a `# v<X.Y.Z>` comment. See [sha-pinning-helper](references/workflow-set-generation.md#sha-pinning-helper). Cache lookups.

4. **Generate the workflow set** in `.github/workflows/`. Standard: `ci.yml`, `release.yml`, `zizmor-scan.yml`; optional `notify-marketplace.yml`, `weekly-audit.yml`. Composition: [workflow-set-composition](references/workflow-set-generation.md#workflow-set-composition). Every file MUST satisfy the [generation-invariants](references/workflow-set-generation.md#generation-invariants) (`permissions: {}`, `persist-credentials: false`, SHA-pinned actions, env-var indirection, off-minute crons, no `pull_request_target` without consent, `@sha256:<digest>`, `timeout-minutes`, concurrency).

5. **Install required secrets.** Iterate the env-var list. Loop: [secret-installation](references/workflow-set-generation.md#secret-installation). Missing vars → one warning each; commit still lands.

6. **Initialise branch protection** (best-effort, non-fatal). Payload: [branch-protection](references/workflow-set-generation.md#branch-protection-best-effort-non-fatal). Failure → `[warn]`, continue.

7. **Final validation — zero findings required:**

   ```bash
   uv tool install --quiet zizmor 2>/dev/null
   zizmor .github/workflows 2>&1 | tee "$REPORT_DIR/<TS>-final-scan.txt"
   ```

   Any finding → run `/janitor-github-workflow-doctor`. Doctor can't fix → abort BEFORE commit.

8. **Commit (do not push) by explicit file name:**

   ```bash
   git add .github/workflows/<every-file-name>
   git commit -m "ci(workflows): scaffold <N> hardened workflows (zizmor-clean)"
   ```

9. **Print summary + hint:**

   ```
   janitor-github-workflow-create: created <N> workflow(s), repo <owner/name>, secrets set: <list>. Report: <path>
   Next: `git push -u origin main` to put the workflows online.
   ```

## Output

Step-9 line + `$REPORT_DIR/<TS>-create.md` (project shape, action SHAs, secrets installed, branch protection state).

## Error Handling

- `gh auth status` fails → abort `[FAILED] gh CLI not authenticated`.
- No git repo → `git init`; no initial commit → `[NEEDS-USER-ACTION] first commit before scaffolding`.
- `gh repo create` name collision → abort, ask user.
- Action `releases/latest` 404 → abort (won't pin to a non-existent SHA).
- Final zizmor scan has findings AND doctor can't auto-fix → abort BEFORE commit.
- Missing env var → one warning per var, proceed; secret must be installed manually.

## Examples

```text
User: /janitor-github-workflow-create
User: create github workflows for this project
User: scaffold CI for this repo
User: set up a github repo and the workflows
```

## Scope

ONLY writes `.github/workflows/` + optional repo / branch-protection bootstrap. Does NOT touch source code, README, package metadata. Does NOT push.

## Resources

- [references/workflow-set-generation.md](references/workflow-set-generation.md) — full detail for every step.
- [zizmor](https://zizmor.sh) / [audit catalogue](https://docs.zizmor.sh/audits/).
- `~/.claude/rules/gh-actions.md`.
- Companion: `/janitor-github-workflow-doctor`.
