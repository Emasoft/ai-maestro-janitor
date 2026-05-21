---
name: janitor-github-workflow-doctor
description: Audits and auto-fixes GitHub Actions workflow security findings using zizmor. Use when the user asks to "audit workflows", "harden GitHub workflows", "fix workflow security", "run zizmor", "scan github actions", or after creating/modifying any .github/workflows/*.yml file. Trigger with /janitor-github-workflow-doctor or "doctor the workflows".
---

# Janitor github-workflow-doctor

## Overview

Scans every `.github/workflows/*.yml` file with [zizmor](https://zizmor.sh) and applies surgical fixes for each actionable finding. Re-validates until the workflows are clean. Validations are mandatory — the skill does NOT exit clean while CRITICAL / MAJOR / MEDIUM findings remain, and does NOT add suppression comments to silence the matcher.

The skill assumes ai-maestro's runtime contract:

- `gh` is installed and authenticated to the repo's owner; the skill does not prompt for tokens.
- Secrets / API keys / passwords are already exported as environment variables in the current shell. The skill installs them into GitHub repo secrets via `gh secret set --body "$ENV_VAR_NAME"` — referencing the env var NAME, never its value, so secrets never appear in argv, hook logs, or shell history.
- `uv` is on PATH (used to install zizmor on first run).

## Prerequisites

- A `.github/workflows/` directory with at least one `.yml` file at the project root, OR a sibling `.git/` plus the user's request to bootstrap one (route to `/janitor-github-workflow-create` in that case).
- `uv` on PATH for `uv tool install zizmor`.
- `gh` on PATH and authenticated (`gh auth status` exits zero).
- A clean working tree before fixes are applied (so the post-fix diff is reviewable). If dirty, abort with a `git status` summary.

## Instructions

1. **Install / refresh zizmor.** `uv tool install --quiet zizmor 2>&1 | tail -3`. Re-run with `--upgrade` if `zizmor --version` reports anything older than the latest GitHub release (`gh api repos/zizmorcore/zizmor/releases/latest --jq .tag_name`).

2. **Snapshot the workflow set.** `ls -1 .github/workflows/*.yml` → record into `$REPORT_DIR` so the fix loop terminates if the set changes mid-run. Abort if zero files match.

3. **Run zizmor against every workflow.** Capture full output AND the JSON SARIF form:

   ```bash
   MAIN_ROOT="$(git worktree list | head -n1 | awk '{print $1}')"
   REPORT_DIR="$MAIN_ROOT/reports/janitor-github-workflow-doctor"
   mkdir -p "$REPORT_DIR"
   TIMESTAMP="$(date +%Y%m%d_%H%M%S%z)"
   REPORT_FILE="$REPORT_DIR/$TIMESTAMP-scan.txt"
   SARIF_FILE="$REPORT_DIR/$TIMESTAMP-scan.sarif"

   zizmor .github/workflows --format sarif --output "$SARIF_FILE" 2>&1 | tee "$REPORT_FILE"
   ```

4. **Classify each finding.** Parse the SARIF and group by `ruleId`. The fix table below maps every documented zizmor audit to its surgical remediation. Findings whose `ruleId` is not in the table are surfaced to the user verbatim and the skill stops at step 7 with `[NEEDS-HUMAN-REVIEW] <count> finding(s) with no auto-fix recipe`.

   **Fix recipes:**

   | zizmor audit | Surgical fix to apply per match |
   |---|---|
   | `unpinned-uses` | Replace `owner/repo@v<X>` or `@<branch>` with `owner/repo@<sha>  # v<X.Y.Z>`. Resolve the SHA via `gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`. Always append a `# v<tag>` comment so future readers can map the SHA back to a version. |
   | `artipacked` | Add `with:\n  persist-credentials: false` (preserving existing `with:` keys) under every `actions/checkout@<sha>` step. Indentation matches the surrounding YAML. |
   | `cache-poisoning` | When the offending setup-action enables caching by default (e.g. `astral-sh/setup-uv`, `actions/setup-node`, `setup-python`, `setup-go`, `setup-java`), pass `with:\n  enable-cache: false` (or the action's documented opt-out) on release / tag-triggered workflow paths only. CI / PR paths may keep the cache. |
   | `template-injection` | Move every `${{ ... }}` expression used inside a `run:` shell block into an `env:` key on the same step (e.g. `PLUGIN_NAME: ${{ steps.x.outputs.name }}`), then reference `$PLUGIN_NAME` in the shell. Never inject the expression directly. |
   | `dangerous-triggers` | If `pull_request_target` is used, verify the workflow writes only to the base-repo secret scope; if not, change to `pull_request`. Add a comment explaining the security choice. |
   | `excessive-permissions` | Replace the offending `permissions:` block with the minimum needed: top-level `permissions: {}` plus per-job scoped grants. The skill computes the minimum from the actions actually invoked in each job. |
   | `github-env-injection` | Stop writing `>> $GITHUB_ENV` / `>> $GITHUB_OUTPUT` from a `run:` block that interpolates a non-literal value. Move the value to an env var first, then `echo "key=$ENV_VAR" >> "$GITHUB_OUTPUT"`. |
   | `obfuscation` | Surface to the user — obfuscated code in a workflow is intentional and the doctor refuses to "clean it up" silently. Mark `[NEEDS-HUMAN-REVIEW]`. |
   | `hardcoded-container-tag` | Replace `image: foo/bar:latest` with `image: foo/bar@sha256:<digest>`. Resolve via `docker buildx imagetools inspect foo/bar:latest \| grep Digest`. |
   | `bot-conditions` | Pin `if:` checks to the documented sender pattern, not the actor name; e.g. `if: github.event.pull_request.user.type == 'Bot'` rather than `github.actor == 'dependabot[bot]'`. |
   | `forbidden-uses` | If a flagged action has a known-safe replacement, swap it. Otherwise surface as `[NEEDS-HUMAN-REVIEW]`. |
   | `ref-confusion` | Replace `github.ref` interpolation in run blocks with `${GITHUB_REF}` from `env:` (which is `refs/heads/<branch>` or `refs/tags/<tag>` — unambiguous). |
   | `self-hosted-runner` | Surface as `[NEEDS-HUMAN-REVIEW]` — moving to GitHub-hosted runners or adding job restrictions is a policy decision, not a mechanical fix. |
   | `unredacted-secrets` | Move the bare-secret reference behind `mask-aws-credentials`, `add-mask`, or an env var with a logged-as-secret name. |
   | `secrets-inherit` | Replace the `secrets: inherit` line with an explicit `secrets:` mapping listing only the secrets the called workflow needs. |
   | `unsound-contains` | Replace `contains(<haystack>, <needle>)` with `==` or `startsWith` where the comparison is actually identity-based. |
   | `stale-action-refs` | When an action has been deprecated upstream, swap to the documented replacement (e.g. `actions/upload-artifact@v3` → `@v4`). |
   | `superfluous-actions` | Replace the third-party action with the equivalent shell command if the runner already provides it (e.g. `softprops/action-gh-release` → `gh release create`). Skip if the swap would lose a feature the workflow uses. |

5. **Apply fixes file by file.** For each file with at least one fixable finding, edit the YAML in place using the Edit tool — never `sed`/`awk` automation. After each file is edited, validate the YAML still parses:

   ```bash
   python3 -c "import yaml; yaml.safe_load(open('<file>'))" || exit 1
   ```

6. **Handle secrets via `gh secret set`.** When a fix surfaces a new secret requirement (e.g. moving a hardcoded token reference to a repo secret), set the secret using ONLY the env var name — never the value:

   ```bash
   # ai-maestro has already exported MY_TOKEN=... in the shell.
   gh secret set MY_TOKEN --body "$MY_TOKEN" --repo "$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
   ```

   The value flows through the shell process's existing env, not through Claude's prompt, not through argv visible in `ps`, not through hook logs.

7. **Re-run zizmor.** If new findings appear (because a fix introduced a different audit hit), apply the recipe again. Maximum 5 fix→re-validate iterations; abort if the count is not strictly decreasing.

8. **Write a fix report** to `$REPORT_DIR/$TIMESTAMP-fixes.md` summarising every change, with the file:line of each fix, the audit id, and the diff hunk. The report is the audit trail the user reviews before committing.

9. **Stage AND commit the fixes** by file name (never `git add -A`):

   ```bash
   git add .github/workflows/<file1>.yml .github/workflows/<file2>.yml ...
   git commit -m "ci(workflows): fix N zizmor finding(s) (auto-applied)"
   ```

   The commit body lists every audit id touched.

10. **Print a one-line summary**:

    ```
    janitor-github-workflow-doctor: fixed N findings in M file(s) (0 remaining). Report: <path>
    ```

## Output

One line as above. The detailed fix report lives at `$REPORT_DIR/<TS>-fixes.md`; the user reviews it before pushing.

## Error Handling

- `uv tool install zizmor` fails → abort. The skill is useless without zizmor.
- `gh auth status` fails → abort with `[FAILED] gh CLI not authenticated; run 'gh auth login' first`.
- A finding's `ruleId` has no fix recipe in the table → surface to the user, mark `[NEEDS-HUMAN-REVIEW]`, do NOT comment-suppress.
- YAML parse fails after an Edit → revert the file via `git checkout HEAD -- <file>`, mark the audit id as `[FIX-FAILED]`, continue with other files.
- 5 iterations of fix→re-validate with no strict decrease → abort with the current finding set so the user can decide whether to escalate.
- Working tree is dirty before the scan → abort with `git status` summary. The doctor commits its own fixes; running on an already-dirty tree would entangle the user's WIP with the auto-fixes.

## Examples

```text
User: /janitor-github-workflow-doctor
User: doctor the workflows
User: zizmor scan and fix
User: harden the github workflows
```

## Scope

ONLY edits `.github/workflows/*.yml`. Does NOT touch source code, README, plugin.json, or anything outside `.github/workflows/`. Does NOT push to remote — committing is the boundary. Does NOT bump version or run `publish.py`.

Pairs with `/janitor-github-workflow-create` (bootstrap a new workflow set from scratch).

## Resources

- [zizmor](https://zizmor.sh) — `uv tool install zizmor`, source: https://github.com/zizmorcore/zizmor
- [zizmor audit catalogue](https://docs.zizmor.sh/audits/) — every `ruleId` ↔ documented behaviour
- `~/.claude/rules/gh-actions.md` — project-wide GitHub Actions conventions (off-minute crons, least-privilege permissions, SHA-pinned third-party actions)
- `.github/workflows/zizmor-scan.yml` — the SARIF-uploading CI job that runs zizmor on every push (the doctor and the CI job share the same matcher; the CI job catches what the doctor missed)
