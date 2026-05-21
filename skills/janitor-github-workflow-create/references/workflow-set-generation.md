# Workflow-set generation reference

Detail for the create skill's project-shape detection (step 1) and workflow-set composition (step 4).

## Project-shape signals

The skill inspects the repo for these signals and records every match in `$REPORT_DIR/<TS>-project-shape.md`. Multiple signals may apply at once.

| Signal | What it detects | What it implies |
|---|---|---|
| `pyproject.toml` | Python project | Add ruff / pyright / pytest jobs |
| `package.json` | Node project | Add npm/pnpm/yarn install + lint + test jobs (detect lock file to pick PM) |
| `Cargo.toml` | Rust project | Add cargo fmt / clippy / test jobs |
| `go.mod` | Go project | Add `go vet ./...` + `go test ./...` |
| `.claude-plugin/plugin.json` | Claude Code plugin | Add CPV strict validate gate |
| `tests/`, `**/test_*.py`, `**/*.test.ts` | Has tests | Wire the test gate; otherwise emit a stub job that prints `no tests yet` |
| `Dockerfile` | Containerised | Add `docker build` smoke + zizmor scan of `docker/` workflows |
| `requirements.txt` + no `pyproject.toml` | Old-style Python | Use `pip install -r requirements.txt` instead of `uv sync` |

## Workflow set composition

The skill writes the following files into `.github/workflows/`, in dependency order. Optional files are emitted only when the project shape (above) implies them.

**a) `ci.yml`** — `push` to `main` + `pull_request` to `main` + `merge_group` (when branch protection requires it). Top-level `permissions: contents: read`, concurrency-cancel on same ref, jobs scoped to lint / test / validate.

**b) `release.yml`** — `push` on tag `v*.*.*`. Job permissions `contents: write` (for GitHub releases), `id-token: write` ONLY if the project publishes via OIDC. Uses `enable-cache: false` on setup-uv / setup-node to prevent cache-poisoning the release artifact.

**c) `zizmor-scan.yml`** — `push` to `main` + `pull_request` + weekly cron (off-minute). Job permissions `security-events: write` + `contents: read` + `actions: read`. SARIF uploads to GitHub Code Scanning.

**d) `notify-marketplace.yml`** — Optional. Only emitted for plugins that publish to a marketplace; otherwise skipped.

**e) `weekly-audit.yml`** — Optional. Off-minute weekly cron. Only emitted for plugins that ship long-running detector pipelines (ai-maestro-janitor pattern).

## Generation invariants

Every generated workflow MUST satisfy ALL of the following at write time. The skill validates each invariant before committing; any miss aborts the run.

- `permissions:` set at the workflow root, default `{}`; per-job grants explicit and minimal.
- Every `actions/checkout@<sha>` step sets `with: persist-credentials: false`.
- Every third-party action pinned to a full commit SHA with a `# v<tag>` comment.
- Every `run:` block that references `${{ ... }}` routes the expression through `env:` first — no direct interpolation.
- Cron schedules avoid `:00` and `:30` minutes (per `~/.claude/rules/gh-actions.md`).
- `pull_request_target` is NOT used unless the user has explicitly asked AND confirmed the security implications.
- Container images pinned to `@sha256:<digest>`, never `:latest`.
- `timeout-minutes:` set on every job (default: 15).
- Concurrency cancels in-flight on the same ref (for CI) or queues (for release / deploy).

## SHA-pinning helper

Every third-party action used in the generated workflows MUST be SHA-pinned. The skill resolves at generation time:

```bash
resolve_sha() {
  local repo="$1"
  local tag
  tag="$(gh api "repos/$repo/releases/latest" --jq .tag_name)"
  sha="$(gh api "repos/$repo/commits/$tag" --jq .sha)"
  printf '%s  # %s\n' "$sha" "$tag"
}
```

Cache the lookups so a repeated SHA is fetched once. Bake `<sha>  # v<X.Y.Z>` into every `uses:` line so the version tag survives in the comment.

## Repo bootstrap

When the GitHub repo does not yet exist:

```bash
REPO_OWNER="${GITHUB_OWNER:-$(git config --get user.email | awk -F@ '{print $1}')}"
REPO_NAME="$(basename "$(pwd)")"
if ! gh repo view "$REPO_OWNER/$REPO_NAME" >/dev/null 2>&1; then
  gh repo create "$REPO_OWNER/$REPO_NAME" --public --source . --remote origin --push
fi
```

If `git remote get-url origin` already points elsewhere, abort with `[FAILED] origin already configured: <url>` and ask the user. Default to `--public` unless the user explicitly requested private. Honour an optional user-supplied description.

## Secret installation

For each secret the workflows reference, iterate the env-var list — the value flows through the shell's existing env, never through Claude's prompt:

```bash
for var in MARKETPLACE_PAT NPM_TOKEN CARGO_TOKEN ANTHROPIC_API_KEY ; do
  if [ -n "${!var:-}" ]; then
    gh secret set "$var" --body "${!var}" --repo "$REPO_OWNER/$REPO_NAME"
  else
    echo "[skip] secret $var not exported in current shell — workflows that need it will fail until you 'gh secret set $var --body <value>' manually"
  fi
done
```

The skill never echoes the value, never writes it to a file.

## Branch protection (best-effort, non-fatal)

```bash
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
