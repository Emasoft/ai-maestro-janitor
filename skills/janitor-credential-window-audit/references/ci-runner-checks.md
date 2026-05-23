# CI runner credential-window checks

How the credential-window auditor inspects `.github/workflows/*.yml` for patterns that widen the window during which a CI-resident secret remains usable. Pairs with `/janitor-github-workflow-doctor`, which uses zizmor to AUTO-FIX many of these — this skill only reports.

## Table of contents

- [Check matrix](#check-matrix) — per-pattern severity and remediation.
- [Per-check detail](#per-check-detail) — env persistence, persist-credentials, timeout-minutes.
- [Cross-reference and parse contract](#cross-reference-and-parse-contract) — how the auditor maps to doctor recipes and reads YAML safely.

## Check matrix

| Pattern | Severity | Remediation recipe |
|---|---|---|
| `env:` block at JOB scope containing `${{ secrets.* }}` AND that env value is used by MORE THAN ONE step | HIGH | Move the `env:` block down to the single step that needs it. Each step that needs a different secret gets its own minimal `env:` |
| `env:` at WORKFLOW (top) scope containing `${{ secrets.* }}` | HIGH | Same — push down to the step level |
| `actions/checkout@<sha>` without `with: persist-credentials: false` | MEDIUM | Add `with:\n  persist-credentials: false` to the checkout step. The doctor auto-fixes this via the `artipacked` zizmor recipe |
| `timeout-minutes: N` with N > 30 on a job that references `${{ secrets.* }}` anywhere | MEDIUM | Reduce `timeout-minutes` to the smallest realistic value (typically 5-15). Long-running jobs holding a token are the Shai-Hulud attack surface |
| `timeout-minutes` MISSING on a job that references `${{ secrets.* }}` | LOW | Add `timeout-minutes: 15` (or job-appropriate). Default is 360 (6 hours) — way too long for a secret-bearing job |
| Same secret referenced from a `run:` shell block via `${{ secrets.X }}` directly (not via `env:`) | MEDIUM | Move secret into `env:` on the step, reference as `$X` in the shell. Avoids expression-injection AND limits exposure |
| `pull_request_target` trigger + `actions/checkout` of the PR ref | CRITICAL | `pull_request_target` runs with base-repo write secrets; checking out PR ref ≈ running attacker code with secrets in env. Switch to `pull_request` unless write-to-base is required |
| Secret value passed as a CLI argument (`run: foo --token ${{ secrets.X }}`) | HIGH | `argv` is visible in `ps`, in step-debug logs, and in some monitoring tools. Pipe via stdin or env var instead |
| Step `with:` that takes a secret as an action input which the action then logs | HIGH | Switch to env-var passing if the action supports it. Add `add-mask` step before the action. The auditor flags by NAME-of-input pattern (`*token*`, `*password*`) |

## Per-check detail

### Job-scope `env:` secret persistence

Detection — find `env:` blocks whose value is `${{ secrets.X }}` and which sit at job (or workflow) scope rather than step scope:

```bash
yq -o=json '.jobs | to_entries | .[] |
  {job: .key,
   env: (.value.env // {}),
   step_count: (.value.steps | length)}' .github/workflows/*.yml
```

For each job whose `env:` is non-empty AND `step_count > 1`, examine each env-key's value. Match against `${{ secrets.[A-Z0-9_]+ }}`. Report:

```
HIGH  | .github/workflows/release.yml:jobs.publish.env.NPM_TOKEN | persists across N steps; move env: to the single publish step
```

The auditor does NOT capture the secret NAME from `secrets.NAME` if NAME could in itself leak information — `secrets.PROD_DB_PASSWORD` reveals the existence of a production database. The auditor reports `secrets.<REDACTED>` and the env-key NAME on the workflow side (the user already knows the workflow).

Exception: if the secret NAME matches a well-known harmless pattern (`GITHUB_TOKEN`, `NPM_TOKEN`, `CACHE_BUST`), it can appear verbatim. The pattern list is conservative — when in doubt, redact.

### `actions/checkout` and `persist-credentials`

`actions/checkout@v4` sets `extraheader=AUTHORIZATION: basic <token>` in the cloned repo's `.git/config` by default. Without `persist-credentials: false`, that header survives in the runner filesystem for the lifetime of the job and is available to every later step — including third-party actions that have no business reading it.

Detection:

```bash
yq -o=json '.jobs | to_entries | .[] | {job: .key, steps: .value.steps}' \
  .github/workflows/*.yml | \
  jq -r '.steps[]? |
    select(.uses != null and (.uses | startswith("actions/checkout@"))) |
    {uses, with: (.with // {})}'
```

For each checkout step:

- `with.persist-credentials == false` → OK.
- `with.persist-credentials == true` OR field absent → MEDIUM finding.

Remediation: doctor's `artipacked` recipe in `references/zizmor-audit-fix-recipes.md` of the doctor skill. The credential-window auditor's job is to REPORT; the doctor's job is to FIX.

### `timeout-minutes` on secret-bearing jobs

The runner holds the token for the duration of the job. A 6-hour job with `NPM_TOKEN` in its env is a 6-hour window during which any compromise (malicious dependency, post-checkout step, log-extraction action) can exfiltrate the token.

Detection — for each job that references `${{ secrets.* }}` ANYWHERE in its tree (env, steps[].env, steps[].run, steps[].with):

```bash
yq -o=json '.jobs | to_entries | .[] |
  {job: .key,
   timeout: (.value."timeout-minutes" // 360),
   has_secret: (.value | tostring | test("\\${{\\s*secrets\\."))}' \
  .github/workflows/*.yml | \
  jq -r 'select(.has_secret) | select(.timeout > 30 or .timeout == 360)'
```

`360` is GitHub's silent default — flag it as "MISSING" for clarity. `> 30` is the threshold for MEDIUM. Recipe in the remediation column of the check matrix.

## Cross-reference and parse contract

### Cross-reference with zizmor recipes

| Audit finding | Zizmor `ruleId` | Doctor recipe |
|---|---|---|
| `persist-credentials` not set on `actions/checkout` | `artipacked` | Add `persist-credentials: false` |
| Secret passed via `${{ secrets.X }}` in `run:` shell | `template-injection` | Move into `env:` on the same step |
| Excessive permissions block | `excessive-permissions` | Scope to minimum |
| `pull_request_target` + PR checkout | `dangerous-triggers` | Switch to `pull_request` |
| `>> $GITHUB_ENV` writing non-literal | `github-env-injection` | Indirect via env var |
| Bare-secret echo in logs | `unredacted-secrets` | `add-mask` or env var |

The credential-window auditor's report should LINK each finding to the corresponding doctor recipe so the user can apply both — the auditor surfaces, the doctor fixes.

### Parse contract

The auditor parses YAML with `yq` (preferred) or `python3 -c "import yaml; yaml.safe_load(open(f))"`. Findings depend on a successful parse. If parsing fails for a file:

- Record `[PARSE-FAILED] <path>` in the report (LOW severity).
- DO NOT skip the file silently — the user needs to know coverage is incomplete.
- DO NOT attempt a regex-based fallback parse — false negatives on a malformed YAML file are worse than a clean failure.

The auditor never EDITS the workflow file. The doctor does that. The auditor's deliverable is the report.
