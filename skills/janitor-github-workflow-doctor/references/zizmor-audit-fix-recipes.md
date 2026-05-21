# Zizmor audit fix recipes

One-to-one map from a zizmor `ruleId` to the surgical fix the doctor applies. Findings whose `ruleId` is not in this table are surfaced verbatim with `[NEEDS-HUMAN-REVIEW]` — the doctor never silences the matcher with a suppression comment.

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
