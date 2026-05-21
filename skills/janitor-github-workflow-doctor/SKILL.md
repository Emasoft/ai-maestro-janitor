---
name: janitor-github-workflow-doctor
description: Audits and auto-fixes GitHub Actions workflow security findings using zizmor. Use when the user asks to "audit workflows", "harden GitHub workflows", "fix workflow security", "run zizmor", "scan github actions", or after creating/modifying any .github/workflows/*.yml file. Trigger with /janitor-github-workflow-doctor or "doctor the workflows".
---

# Janitor github-workflow-doctor

## Overview

Scans every `.github/workflows/*.yml` file with [zizmor](https://zizmor.sh) and applies surgical fixes for each actionable finding. Re-validates until clean. Validations are mandatory — the skill does NOT exit clean while findings remain, and does NOT add suppression comments.

Runtime contract: `gh` installed and authenticated; secrets exported as env vars in the current shell. Secrets are installed via `gh secret set --body "$ENV_VAR_NAME"` (env-var name, never value). `uv` on PATH for the zizmor install.

## Prerequisites

- `.github/workflows/` with ≥ 1 `.yml`. Otherwise route to `/janitor-github-workflow-create`.
- `uv` and `gh` on PATH, `gh auth status` zero, working tree clean.

## Instructions

1. **Install / refresh zizmor.** `uv tool install --quiet zizmor`. Re-run with `--upgrade` if `zizmor --version` lags `gh api repos/zizmorcore/zizmor/releases/latest --jq .tag_name`.

2. **Snapshot the workflow set.** `ls -1 .github/workflows/*.yml` → `$REPORT_DIR` for loop-termination on mid-run changes. Abort if zero files.

3. **Scan with zizmor.** Capture text + SARIF:

   ```bash
   MAIN_ROOT="$(git worktree list | head -n1 | awk '{print $1}')"
   REPORT_DIR="$MAIN_ROOT/reports/janitor-github-workflow-doctor"
   mkdir -p "$REPORT_DIR"
   TS="$(date +%Y%m%d_%H%M%S%z)"
   zizmor .github/workflows --format sarif --output "$REPORT_DIR/$TS-scan.sarif" 2>&1 | tee "$REPORT_DIR/$TS-scan.txt"
   ```

4. **Classify and fix.** Parse SARIF, group by `ruleId`, look up the surgical fix in [references/zizmor-audit-fix-recipes.md](references/zizmor-audit-fix-recipes.md). Findings whose `ruleId` is not in the recipe table → `[NEEDS-HUMAN-REVIEW]`, stop.

5. **Apply fixes file by file** using the Edit tool — never `sed`/`awk` automation (every change is reviewable). After each edit, validate YAML: `python3 -c "import yaml; yaml.safe_load(open('<file>'))" || exit 1`.

6. **Re-run zizmor.** Iterate fix → re-validate up to 5 times; abort if the count is not strictly decreasing.

7. **Write fix report** to `$REPORT_DIR/$TS-fixes.md` (file:line, audit id, diff hunk per change).

8. **Stage and commit explicitly** (never `git add -A`):

   ```bash
   git add .github/workflows/<file1>.yml .github/workflows/<file2>.yml
   git commit -m "ci(workflows): fix N zizmor finding(s) (auto-applied)"
   ```

9. **Print summary:** `janitor-github-workflow-doctor: fixed N findings in M file(s) (0 remaining). Report: <path>`.

## Output

Step-9 line. Detailed report at `$REPORT_DIR/<TS>-fixes.md`.

## Error Handling

- `uv tool install zizmor` fails → abort.
- `gh auth status` fails → abort with `[FAILED] gh CLI not authenticated`.
- `ruleId` has no recipe → `[NEEDS-HUMAN-REVIEW]`, never comment-suppress.
- YAML parse fails after Edit → `git checkout HEAD -- <file>`, mark `[FIX-FAILED]`, continue.
- 5 iterations no strict decrease → abort with current findings.
- Working tree dirty → abort with `git status` (auto-fix commits would entangle WIP).

## Examples

```text
User: /janitor-github-workflow-doctor
User: doctor the workflows
User: zizmor scan and fix
User: harden the github workflows
```

## Scope

ONLY edits `.github/workflows/*.yml`. Does NOT touch source code, README, plugin.json, or anything outside `.github/workflows/`. Does NOT push or bump version.

Pairs with `/janitor-github-workflow-create`.

## Resources

- [references/zizmor-audit-fix-recipes.md](references/zizmor-audit-fix-recipes.md) — every `ruleId` ↔ surgical fix + the secret-handling contract.
- [zizmor](https://zizmor.sh) / [audit catalogue](https://docs.zizmor.sh/audits/) — upstream.
- `~/.claude/rules/gh-actions.md` — project-wide GitHub Actions conventions.
- `.github/workflows/zizmor-scan.yml` — CI job; doctor and CI share the matcher.
