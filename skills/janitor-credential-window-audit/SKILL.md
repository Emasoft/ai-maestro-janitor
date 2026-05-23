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
   MAIN_ROOT="$(git worktree list | head -n1 | awk '{print $1}')"
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
