---
name: janitor-fork-pr-cache-audit
description: Audits .github/workflows/*.yml for the fork-PR cache-poisoning and pull_request_target checkout patterns from the TanStack supply-chain incident. Use when the user asks to "audit cache poisoning", "scan for cache-poisoning PRs", "check pull_request_target workflows", "TanStack-style audit", or after touching any workflow that uses actions/cache or pull_request_target. Trigger with /janitor-fork-pr-cache-audit.
---

# Janitor fork-pr-cache-audit

## Overview

Parses every `.github/workflows/*.yml` and emits a per-finding report for the four supply-chain attack classes exploited in the TanStack incident:

- **D1 (HIGH)** — `pull_request` job (NOT `pull_request_target`) using `actions/cache@*`. Fork PRs share the trusted-branch cache key and can poison entries the next trusted run blindly restores.
- **D2 (HIGH)** — `actions/cache@*` fenced on the RESTORE step only; the SAVE step stays exposed.
- **D3 (CRITICAL)** — `pull_request_target` AND `actions/checkout` of the PR head SHA. Runs untrusted fork code with base-repo secrets.
- **D4 (MAJOR)** — setup-action default cache (`astral-sh/setup-uv`, `actions/setup-node`, `setup-python`, `setup-go`, `setup-java`) on `pull_request` workflows where `enable-cache` is not explicitly disabled.

Attack class detail in references/fork-pr-attack-vectors.md. Surgical YAML fixes in references/cache-fencing-recipes.md.

## Prerequisites

- `.github/workflows/` with at least one `.yml`. Empty → `[FAILED] no workflows under .github/workflows/`.
- `python3 -c "import yaml"` succeeds. Missing → `[FAILED] PyYAML required`.

## Instructions

1. **Resolve paths and timestamp:**

   ```bash
   MAIN_ROOT="$(git worktree list | head -n1 | awk '{print $1}')"
   REPORT_DIR="$MAIN_ROOT/reports/janitor-fork-pr-cache-audit"
   mkdir -p "$REPORT_DIR"
   TIMESTAMP="$(date +%Y%m%d_%H%M%S%z)"
   REPORT_FILE="$REPORT_DIR/$TIMESTAMP-audit.md"
   ```

2. **Enumerate** `.github/workflows/*.yml`. Zero matches → `[FAILED] no workflows under .github/workflows/`.

3. **Parse each file** with `python3 -c 'import yaml,sys; yaml.safe_load(open(sys.argv[1]))' <file>`. YAML error → record `[PARSE-FAIL] <file>: <err>`, continue.

4. **Run the four detectors** per workflow. Exact YAML shapes each one matches live in the attack-vectors reference. Each finding records `path`, `line`, `severity`, `detector`, `fix-recipe-id`.

5. **Capture file:line for every finding** by walking the parsed YAML with a `Loader` that preserves `Mark` objects (`node.start_mark.line + 1`, `.column + 1`). Top-of-file findings get line `1`.

6. **Write `$REPORT_FILE`** with: header (timestamp, workflow count, count per severity); one section per finding with file:line, detector ID, severity, offending YAML excerpt, recipe-id pointer into the cache-fencing-recipes reference.

7. **Print one summary line:** `janitor-fork-pr-cache-audit: <N> CRITICAL, <N> HIGH, <N> MAJOR across <M> workflow(s). Report: <REPORT_FILE>`.

## Output

The single summary line. Full per-finding report at `$REPORT_FILE`.

## Error Handling

- No `.github/workflows/` or zero `.yml` → `[FAILED] no workflows under .github/workflows/`.
- `python3 -c "import yaml"` fails → `[FAILED] PyYAML required (pip install pyyaml)`.
- Workflow fails to parse → `[PARSE-FAIL] <file>: <err>`, continue. Do NOT abort the audit on one bad file.
- `git worktree list` empty → `[FAILED] not a git working tree`.

## Examples

```text
User: /janitor-fork-pr-cache-audit
User: audit fork PR cache
User: TanStack-style cache poisoning scan
```

## Remediation (fix)

> **janitor-security-agent** runs this remediation after an audit finds findings.
> If `/janitor-autofix-off` is set for the project, DETECT + FLAG only — apply no changes.

### Per-class fix policy

| Class | Fix | Mode |
|---|---|---|
| **D1** — `pull_request` + `actions/cache` | Gate the cache step: `if: github.event_name != 'pull_request' \|\| github.event.pull_request.head.repo.full_name == github.repository`. Re-scan to confirm 0 D1 findings. | **SAFE-TO-AUTO-FIX** |
| **D2** — restore-only fence (SAVE exposed) | Apply the same fence expression to the SAVE step as well, matching the RESTORE step already in place. Re-scan to confirm 0 D2. | **SAFE-TO-AUTO-FIX** |
| **D3** — `pull_request_target` + `actions/checkout` of PR head | Remove the `ref: ${{ github.event.pull_request.head.sha }}` (or `ref: refs/pull/…/head`) from checkout, restoring to the base ref. If the workflow genuinely needs to run fork code, flag it for human review — the remediation is architectural. | **FLAG-FOR-HUMAN** — auto-fix only when the unsafe `ref:` is the SOLE diff from a safe template |
| **D4** — setup-action implicit cache on fork-PR workflow | Add `enable-cache: false` to the setup-action step. Re-scan to confirm 0 D4. | **SAFE-TO-AUTO-FIX** |

### Auto-fix procedure

1. For each SAFE-TO-AUTO-FIX finding, compute the minimal YAML patch (single-line `if:` insertion or `enable-cache: false` addition).
2. Apply the patch to a working copy; do NOT touch the file in-place until all patches for that file are computed.
3. Write the patched file atomically (write to tmp, then `os.replace`).
4. Re-run the four detectors on the patched file. If the re-scan still emits a finding for the same file, **REVERT the patch** and FLAG the finding for human review.
5. Stage the fixed file. Do NOT commit — leave that to the human or the release pipeline.

### Flag-for-human procedure

Write a `## Findings requiring human review` section to the audit report with: file:line, detector ID, reason auto-fix was skipped, and the surgical recipe-id from [cache-fencing-recipes](references/cache-fencing-recipes.md) the human should apply.

Never suppress a finding to pass a gate. Never force-push.

## Scope

ONLY reads `.github/workflows/*.yml` and writes a report under `$MAIN_ROOT/reports/janitor-fork-pr-cache-audit/`. Does NOT modify workflows, commit, push, or call zizmor. For mechanical fixes use `/janitor-github-workflow-doctor`.

## Resources

- [fork-pr-attack-vectors](references/fork-pr-attack-vectors.md) — attack classes the auditor matches.
  - [Background: the TanStack incident](references/fork-pr-attack-vectors.md#background-the-tanstack-incident)
  - [Detector patterns (D1–D4)](references/fork-pr-attack-vectors.md#detector-patterns-d1d4)
  - [Why severity is graded this way](references/fork-pr-attack-vectors.md#why-severity-is-graded-this-way)
- [cache-fencing-recipes](references/cache-fencing-recipes.md) — before/after YAML fixes.
  - [The fence expression](references/cache-fencing-recipes.md#the-fence-expression)
  - [Surgical recipes (R1–R4)](references/cache-fencing-recipes.md#surgical-recipes-r1r4)
  - [Alternatives and escape hatches](references/cache-fencing-recipes.md#alternatives-and-escape-hatches)
- `~/.claude/rules/gh-actions.md` — GitHub Actions conventions.
