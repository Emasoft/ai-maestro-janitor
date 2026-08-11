---
name: janitor-credential-window-audit
description: Audits the window during which long-lived credentials exist in repo, shell, and CI configuration. Surfaces .env leaks, plaintext token files, suspicious env-var NAMES (never values), and CI workflows that persist secrets. Reports only — no auto-fix. Use when the user asks to "audit credential exposure", "find leaked tokens", "check secret window", "shai-hulud audit", or after a supply-chain incident. Trigger with /janitor-credential-window-audit.
---

# Janitor credential-window-audit

## Overview

Walks three credential surfaces and emits a single categorized report:

1. **Repo-side** — files holding (or about to hold) secrets not in `.gitignore`.
2. **Shell-environment** — env-var NAMES (never values) that look like secrets.
3. **GitHub Actions** — workflows that persist secrets across steps, leave `persist-credentials: true` on `actions/checkout`, or use excessive `timeout-minutes`.

Surfaces `file:path` / env-var-NAME / severity / remediation. Never auto-fixes. Pairs with `/janitor-github-workflow-doctor` which DOES auto-fix the CI surface via zizmor.

Repo-side detail in references/repo-side-checks.md. Env-name regexes in references/shell-env-heuristics.md. CI checks in references/ci-runner-checks.md.

## Prerequisites

- Project root (`$CLAUDE_PROJECT_DIR` or `git rev-parse --show-toplevel`).
- `grep`, `find`, `git` on PATH. Optional: `yq` (falls back to `python3 -c "import yaml"`).

## Instructions

1. Resolve report path:

   ```bash
   # --porcelain, NOT plain + awk: plain output is columns, so `awk '{print $1}'`
   # truncates any repo path containing a space and the report is written somewhere
   # nobody will look — while reporting success. Paths with spaces are routine on macOS.
   MAIN_ROOT="$(git worktree list --porcelain | sed -n '1s/^worktree //p')"
   REPORT_DIR="$MAIN_ROOT/reports/janitor-credential-window-audit"
   mkdir -p "$REPORT_DIR"
   TIMESTAMP="$(date +%Y%m%d_%H%M%S%z)"
   REPORT_FILE="$REPORT_DIR/$TIMESTAMP-audit.md"
   ```

2. **Repo-side.** Apply the repo-side-checks reference: `.env*` not gitignored (CRITICAL), `.npmrc`/`~/.npmrc`/`~/.netrc`/`~/.gitconfig` token persistence, plaintext token files matching the name heuristic, missing gitleaks/trufflehog config.

3. **Shell-environment.** Enumerate `env | cut -d= -f1` against the regex table in the shell-env-heuristics reference. Echo NAMES only — never values, never `printenv VAR`. Mark stale NAMES (`*_OLD`, `*_BAK`, `*_TMP`).

4. **CI runner.** For each `.github/workflows/*.yml`, apply the ci-runner-checks reference: job-level `env:` with `${{ secrets.* }}` shared across multiple steps, `actions/checkout` without `persist-credentials: false`, `timeout-minutes` > 30 on jobs that touch secrets.

5. **Aggregate.** One section per surface; each finding is `<severity> | <path-or-NAME> | <remediation>`. Severities: CRITICAL (secret about to be committed), HIGH (persists outside necessary window), MEDIUM (long attack window), LOW (hardening hint).

6. **Print summary line:** `janitor-credential-window-audit: <N> CRITICAL, <M> HIGH, <K> MEDIUM, <L> LOW. Report: $REPORT_FILE`.

## Output

Markdown report at `$REPORT_FILE`. Stdout: one summary line. No commits, edits, or pushes.

## Error Handling

- `git rev-parse` fails → `[FAILED] not a git working tree`.
- `.github/workflows/` missing → skip surface 3 (not an error).
- YAML parse fails on a workflow → record `[PARSE-FAILED] <file>` in the report, continue.
- A secret VALUE captured anywhere in scratch state → abort report write, surface `[FAILED] value leak guardrail tripped`.
- Missing optional tool (`yq`) → fall back; never abort.

## Examples

```text
User: /janitor-credential-window-audit
User: audit credential exposure
User: shai-hulud audit
User: how long is my token window
User: find leaked tokens in the repo
```

## Remediation (fix)

The **janitor-security-agent** loads this skill to apply remediations after detection. If `/janitor-autofix-off` is set, this section is skipped — detect and report only.

### Finding class: `.env*` not in `.gitignore` (CRITICAL — secret about to be committed)

**SAFE-TO-AUTO-FIX** — add the missing gitignore pattern:

1. Append the entry to `.gitignore` atomically (`echo '.env*' >> .gitignore`).
2. If the file is already tracked by git (`git ls-files --error-unmatch <file>` exits 0), run `git rm --cached <file>` to stop tracking it (does NOT delete the file on disk).
3. Commit only `.gitignore` (and the `git rm --cached` change if applicable). Never commit the secret file itself.
4. Record `[AUTO-FIXED] added <pattern> to .gitignore` in the report.

### Finding class: plaintext token/credential literal in a working-tree file (HIGH)

**SAFE-TO-AUTO-FIX** (working tree only, file NOT committed with this content):

1. Confirm the file is either untracked or the secret literal does not appear in `git log -S "<literal>" -- <file>` (not in history).
2. Replace the literal with a reference to an env var or secret store (e.g. `os.getenv("MY_TOKEN")` / `process.env.MY_TOKEN`).
3. Record `[AUTO-FIXED] redacted literal in <path>` in the report.

**FLAG-FOR-HUMAN** — when the literal IS in git history (`git log -S` returns commits):

- Do NOT touch git history automatically.
- Record `[FLAGGED] secret in git history at <file> — rotate credential + purge history (git filter-branch / BFG)`.
- Exit non-zero.

### Finding class: CI workflow `persist-credentials: true` / missing `persist-credentials: false` (HIGH)

**FLAG-FOR-HUMAN** — delegate to `/janitor-github-workflow-doctor` which owns the CI surface auto-fix via zizmor. Record `[FLAGGED] run /janitor-github-workflow-doctor to fix persist-credentials in <workflow>`.

### Finding class: job-level `env:` sharing `${{ secrets.* }}` across steps (MEDIUM)

**FLAG-FOR-HUMAN** — scoping changes require understanding the workflow's intent. Record `[FLAGGED] refactor env: block in <workflow>:<job> to step-level secrets`.

### Finding class: suspicious env-var NAME in shell environment (MEDIUM/LOW)

**Never auto-fix** — env vars are runtime state, not files. Record `[FLAGGED] stale/exposed env-var NAME <NAME> — unset in shell profile or CI configuration`.

### What is NEVER auto-fixed

- Rotating a live credential (call `gh secret set`, external APIs, OAuth flows).
- Purging git history.
- Force-pushing branches.
- Touching secret VALUES anywhere in the process (the value-leak guardrail aborts before any fix path is reached).
- Suppressing a finding to pass a gate.

## Scope

ONLY reads. Does NOT rotate secrets, edit `.gitignore`, modify workflows, or call `gh secret set`. Pairs with `/janitor-github-workflow-doctor` for the CI surface auto-fix.

## Resources

- [repo-side-checks](references/repo-side-checks.md) — file-system checks.
  - [Check matrix](references/repo-side-checks.md#check-matrix)
  - [Per-check detail](references/repo-side-checks.md#per-check-detail)
  - [Value-leak guardrail](references/repo-side-checks.md#value-leak-guardrail)
- [shell-env-heuristics](references/shell-env-heuristics.md) — env-var NAME regex table.
  - [Enumeration recipe](references/shell-env-heuristics.md#enumeration-recipe)
  - [Pattern matching](references/shell-env-heuristics.md#pattern-matching)
  - [Reporting format](references/shell-env-heuristics.md#reporting-format)
- [ci-runner-checks](references/ci-runner-checks.md) — workflow checks.
  - [Check matrix](references/ci-runner-checks.md#check-matrix)
  - [Per-check detail](references/ci-runner-checks.md#per-check-detail)
  - [Cross-reference and parse contract](references/ci-runner-checks.md#cross-reference-and-parse-contract)
- `/janitor-github-workflow-doctor` — auto-fix companion for the CI surface.
