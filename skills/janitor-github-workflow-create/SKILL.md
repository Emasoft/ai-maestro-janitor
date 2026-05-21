---
name: janitor-github-workflow-create
description: Analyzes a project and creates a zizmor-clean set of GitHub Actions workflows from scratch, including bootstrapping the GitHub repo via `gh repo create` if it does not yet exist. Use when starting a new project, when a project has no .github/workflows/ directory, when the user asks to "set up CI", "create the GitHub workflows", "scaffold CI", "bootstrap github actions", or "set up the repo". Trigger with /janitor-github-workflow-create or "create github workflows for this project".
---

# Janitor github-workflow-create

## Overview

Generates a complete, zizmor-clean GitHub Actions workflow set tailored to the project's language(s), package manager(s), and release model. Bootstraps the GitHub repository itself via `gh repo create` when missing. Every workflow is hardened on the way out — SHA-pinned third-party actions, least-privilege per-job permissions, `persist-credentials: false` on every checkout, off-minute cron schedules, no `${{ }}` interpolation inside `run:` blocks, no `latest` container tags — so the final `zizmor .github/workflows` pass returns zero findings.

Pairs with `/janitor-github-workflow-doctor` (audits + auto-fixes an existing workflow set).

## Prerequisites

- `gh` on PATH and authenticated to the target owner. `gh auth status` exits zero.
- `git` initialised in the project root (`git rev-parse --show-toplevel` succeeds). If absent, the skill runs `git init` first.
- `uv` on PATH for `uv tool install zizmor` (final validation).
- Secrets, API keys, and tokens are already exported as environment variables in the current shell. The skill installs them into repo secrets via `gh secret set --body "$ENV_VAR_NAME"` — value never appears in argv, hook logs, or shell history.

## Instructions

1. **Detect the project shape.** Read the repo to determine:

   | Signal | What to detect | What it implies |
   |---|---|---|
   | `pyproject.toml` | Python project | Add ruff / pyright / pytest jobs |
   | `package.json` | Node project | Add npm/pnpm/yarn install + lint + test jobs (detect lock file to pick PM) |
   | `Cargo.toml` | Rust project | Add cargo fmt / clippy / test jobs |
   | `go.mod` | Go project | Add `go vet ./...` + `go test ./...` |
   | `.claude-plugin/plugin.json` | Claude Code plugin | Add CPV strict validate gate |
   | `tests/`, `**/test_*.py`, `**/*.test.ts` | Has tests | Wire the test gate; otherwise emit a stub job that prints `no tests yet` |
   | `Dockerfile` | Containerised | Add `docker build` smoke + zizmor scan of `docker/` workflows |
   | `requirements.txt` + no `pyproject.toml` | Old-style Python | Use `pip install -r requirements.txt` instead of `uv sync` |

   Multiple signals may apply — record every match in `$REPORT_DIR/<TS>-project-shape.md` for the audit trail.

2. **Bootstrap the GitHub repo if missing.** Check whether the repo already exists upstream:

   ```bash
   REPO_OWNER="${GITHUB_OWNER:-$(git config --get user.email | awk -F@ '{print $1}')}"
   REPO_NAME="$(basename "$(pwd)")"
   if ! gh repo view "$REPO_OWNER/$REPO_NAME" >/dev/null 2>&1; then
     # The repo does not exist on GitHub yet. Create it via gh, default to public unless
     # the user explicitly requested private. Honour an optional --description from the user.
     gh repo create "$REPO_OWNER/$REPO_NAME" --public --source . --remote origin --push
   fi
   ```

   If `git remote get-url origin` already points elsewhere, abort with `[FAILED] origin already configured: <url>` and ask the user.

3. **Resolve action SHAs.** Every third-party action used in the generated workflows MUST be SHA-pinned. The skill fetches the latest release SHA for each one at generation time:

   ```bash
   resolve_sha() {
     local repo="$1"
     local tag
     tag="$(gh api "repos/$repo/releases/latest" --jq .tag_name)"
     sha="$(gh api "repos/$repo/commits/$tag" --jq .sha)"
     printf '%s  # %s\n' "$sha" "$tag"
   }
   ```

   Cache the lookups so a single repeated SHA is fetched once. Bake `<sha>  # v<X.Y.Z>` into every `uses:` line so the version tag survives in the comment.

4. **Generate the workflow set.** Write to `.github/workflows/`. The standard set, in dependency order:

   **a) `ci.yml`** — `push` to `main` + `pull_request` to `main` + `merge_group` (when branch protection requires it). Top-level `permissions: contents: read`, concurrency-cancel on same ref, jobs scoped to lint / test / validate.

   **b) `release.yml`** — `push` on tag `v*.*.*`. Job permissions `contents: write` (for GitHub releases), `id-token: write` ONLY if the project publishes via OIDC. Uses `enable-cache: false` on setup-uv / setup-node to prevent cache-poisoning the release artifact.

   **c) `zizmor-scan.yml`** — `push` to `main` + `pull_request` + weekly cron (off-minute). Job permissions `security-events: write` + `contents: read` + `actions: read`. SARIF uploads to GitHub Code Scanning.

   **d) `notify-marketplace.yml`** — Optional. Only emitted for plugins that publish to a marketplace; otherwise skip.

   **e) `weekly-audit.yml`** — Optional. Off-minute weekly cron. Only emitted for plugins that ship long-running detector pipelines (ai-maestro-janitor pattern).

   Every workflow must satisfy ALL of the following at generation time:

   - `permissions:` is set at the workflow root, defaulting to `{}`; per-job grants are explicit and minimal.
   - Every `actions/checkout@<sha>` step sets `with: persist-credentials: false`.
   - Every third-party action is pinned to a full commit SHA with a `# v<tag>` comment.
   - Every `run:` block that references a `${{ ... }}` expression routes the expression through `env:` first — no direct interpolation.
   - Cron schedules avoid `:00` and `:30` minutes (per `~/.claude/rules/gh-actions.md`).
   - `pull_request_target` is NOT used unless the user has explicitly asked for it and confirmed the security implications.
   - Container images are pinned to `@sha256:<digest>`, never `:latest`.
   - `timeout-minutes:` is set on every job (default: 15).
   - Concurrency cancels in-flight on the same ref (for CI) or queues (for release / deploy).

5. **Set required secrets via `gh secret set`.** For each secret the workflows reference, the env var must already exist in the current shell (ai-maestro contract). The skill iterates the list and installs each one — referencing the env var name, never the value:

   ```bash
   for var in MARKETPLACE_PAT NPM_TOKEN CARGO_TOKEN ANTHROPIC_API_KEY ; do
     if [ -n "${!var:-}" ]; then
       gh secret set "$var" --body "${!var}" --repo "$REPO_OWNER/$REPO_NAME"
     else
       echo "[skip] secret $var not exported in current shell — workflows that need it will fail until you 'gh secret set $var --body <value>' manually"
     fi
   done
   ```

   The skill never echoes the value, never writes it to a file, never passes it through Claude's prompt.

6. **Initialise branch protection** (best-effort, non-fatal):

   ```bash
   # Require the ci.yml jobs to pass before merge; require linear history.
   gh api -X PUT "repos/$REPO_OWNER/$REPO_NAME/branches/main/protection" --input <(cat <<EOF
   {
     "required_status_checks": {"strict": true, "contexts": ["CI / Lint", "CI / Test"]},
     "enforce_admins": false,
     "required_pull_request_reviews": null,
     "restrictions": null,
     "required_linear_history": true,
     "allow_force_pushes": false,
     "allow_deletions": false
   }
   EOF
   ) || echo "[warn] branch protection setup failed — set it manually in repo settings"
   ```

7. **Final validation — zizmor must report zero findings.** Install zizmor if absent, then run:

   ```bash
   uv tool install --quiet zizmor 2>/dev/null
   zizmor .github/workflows 2>&1 | tee "$REPORT_DIR/<TS>-final-scan.txt"
   ```

   If any finding remains, run `/janitor-github-workflow-doctor` on the generated tree to fix it. If the doctor cannot auto-fix, the create skill abort — the workflow set has NOT been written cleanly and must be reviewed before commit.

8. **Commit (do not push)**:

   ```bash
   git add .github/workflows/<every-file-name-explicitly>
   git commit -m "ci(workflows): scaffold <N> hardened workflows (zizmor-clean)"
   ```

   The commit body lists every file added and the project-shape detection result.

9. **Report a one-line summary** plus a follow-up hint:

   ```
   janitor-github-workflow-create: created <N> workflow(s) in .github/workflows/, repo <owner/name>, secrets set: <list>. Report: <path>
   Next: `git push -u origin main` to put the workflows online.
   ```

## Output

One line as above + a single fix report at `$REPORT_DIR/<TS>-create.md` documenting every choice the skill made (project shape, action SHAs, secrets installed, branch protection state).

## Error Handling

- `gh auth status` fails → abort with `[FAILED] gh CLI not authenticated; run 'gh auth login' first`. Workflows that reference repo-scoped secrets would silently fail without this.
- `git rev-parse --show-toplevel` fails (no git repo) → run `git init` first; if the user has not committed anything, the skill stops with a `[NEEDS-USER-ACTION] first commit before scaffolding workflows` line.
- `gh repo create` fails (name collision under the owner) → abort and ask the user for a different name.
- An action repo's `releases/latest` is empty or 404 → abort. Pinning to a non-existent SHA would break the workflow on first fire.
- Final zizmor scan reports findings AND the doctor cannot auto-fix all of them → abort BEFORE the commit. The skill never ships a workflow set with unresolved CRITICAL / MAJOR / MEDIUM findings.
- Required env var not exported in the current shell AND the workflow references that secret → emit one warning per missing var (as in step 5), proceed; the user can `gh secret set` manually later. The commit still lands; the workflows just stay broken for that path until the secret is installed.

## Examples

```text
User: /janitor-github-workflow-create
User: create github workflows for this project
User: scaffold CI for this repo
User: bootstrap github actions
User: set up a github repo and the workflows
```

## Scope

ONLY writes to `.github/workflows/` and (optionally) bootstraps the GitHub repo + branch protection. Does NOT touch source code, README, or package metadata. Does NOT push commits (the user controls when the workflows go live).

After the skill finishes, the user should run `/janitor-github-workflow-doctor` periodically (and the generated `zizmor-scan.yml` workflow does the same automatically on every push / PR / weekly schedule).

## Resources

- [zizmor](https://zizmor.sh) — supply-chain + general workflow security scanner
- [zizmor audit catalogue](https://docs.zizmor.sh/audits/) — what each audit checks
- `~/.claude/rules/gh-actions.md` — project-wide GitHub Actions conventions
- `gh` CLI — used for repo creation, secret installation, branch protection
- Companion skill: `/janitor-github-workflow-doctor` — audit + auto-fix an existing workflow set
