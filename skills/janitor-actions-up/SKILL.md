---
name: janitor-actions-up
description: Bulk-pin every GitHub Actions reference in .github/workflows/ to a verified commit SHA (with the human-readable tag as a comment), and bring each action to its newest compatible release. Wraps Azat-io's actions-up CLI behind a safety harness — dry-run preview first, optional minimum-release-age gate, refuses to scan the janitor's own repo. Trigger with /janitor-actions-up, "pin GHA to SHA", "update github actions", "actions-up", or "harden workflow refs".
---

# Janitor actions-up — SHA-pin and update GitHub Actions

## Overview

`actions-up` ([github.com/azat-io/actions-up](https://github.com/azat-io/actions-up))
is the upstream-recommended tool for two related supply-chain hardenings
of GitHub Actions references:

1. **SHA-pinning** — replaces floating tags (`uses: actions/checkout@v4`)
   with commit SHAs (`uses: actions/checkout@<40-char-sha> # v4`).
   Pinning is the only defense against the tag-rewriting attack class
   where a compromised maintainer (or compromised CI) silently rewrites
   `v4` to point at a malicious commit.
2. **Latest-version updates** — surfaces newer compatible releases and
   bumps each one (still SHA-pinned at the new release's commit).

The janitor's `workflow-security` detector already SURFACES unpinned
actions (Sentinel `github-dependency-refs` rule). This skill FIXES them
in bulk — the same way `/janitor-supply-chain-watcher` SURFACES lockfile
advisories that the user then upgrades.

## Prerequisites

* `npx` on PATH (Node.js 18+ recommended). The skill invokes
  `npx --yes actions-up@latest`.
* `.github/workflows/` exists in the current project root.
* Working tree is clean — applied changes land as a single discrete
  commit the user can review and revert.
* The project is NOT the janitor's own repo. The skill refuses
  (override: set `CLAUDE_PLUGIN_ALLOW_SELF_SCAN=1` for
  janitor-own-repo testing).

## Arguments

Parse `$ARGUMENTS` for any of (all optional):

* `--check-only` — dry-run preview only; never write to workflow files.
* `--apply` — skip the dry-run preview and apply directly (still honours
  `/janitor-autofix-off`).
* `--min-age <days>` — only consider releases older than N days
  (default: 5, matching the janitor's `pkg_manager_min_release_age_minutes`
  default of 7200 minutes = 5 days). Lower the value if you want fresher
  updates and accept the supply-chain exposure window.
* `--mode <major|minor|patch>` — upgrade scope (default: `major` — same as
  actions-up's own default; the user can pass `minor` or `patch` for a
  conservative pass).
* `--include-branches` — also include actions pinned to branches (off by
  default; branch refs are a separate hazard class the user should opt
  into rewriting).
* `--exclude <regex>` (repeatable) — skip actions matching the regex
  (e.g. an internal action you don't want auto-pinned).

## Instructions

1. **Pre-flight checks** (refuse fast if any fail; report one line):

   ```bash
   # 1a. workflows dir
   test -d "$CLAUDE_PROJECT_DIR/.github/workflows" \
     || { echo "[FAILED] no .github/workflows/ in this project"; exit 1; }

   # 1b. clean tree (so the diff stays reviewable)
   git -C "$CLAUDE_PROJECT_DIR" diff --quiet \
     || { echo "[FAILED] working tree is dirty — commit or stash first"; exit 1; }

   # 1c. self-scan guard
   if [ -f "$CLAUDE_PROJECT_DIR/.claude-plugin/plugin.json" ] && \
      [ "$(jq -r .name "$CLAUDE_PROJECT_DIR/.claude-plugin/plugin.json")" = "ai-maestro-janitor" ] && \
      [ -z "$CLAUDE_PLUGIN_ALLOW_SELF_SCAN" ]; then
     echo "[SKIP] refuses to scan the janitor's own repo (set CLAUDE_PLUGIN_ALLOW_SELF_SCAN=1 to override)"
     exit 0
   fi

   # 1d. npx + node available
   command -v npx >/dev/null \
     || { echo "[FAILED] npx not in PATH — install Node.js 18+"; exit 1; }
   ```

2. **Dry-run** to preview every change. Reports JSON to stdout (the
   skill parses it for the summary table):

   ```bash
   cd "$CLAUDE_PROJECT_DIR" && \
     npx --yes actions-up@latest \
       --dry-run --json \
       --style sha \
       --min-age "${MIN_AGE:-5}" \
       --mode "${MODE:-major}" \
       --recursive
   ```

3. **Render the preview table** to the user. Show: action, current ref,
   new SHA, new tag, severity (major/minor/patch). If `--check-only`
   was set, stop here and exit 0.

4. **Apply** (skip confirmation when `/janitor-autofix-off` is NOT set
   per the project's standing "act, don't ask" feedback for CI/security
   hardening; ask first otherwise):

   ```bash
   cd "$CLAUDE_PROJECT_DIR" && \
     npx --yes actions-up@latest \
       --yes \
       --style sha \
       --min-age "${MIN_AGE:-5}" \
       --mode "${MODE:-major}" \
       --recursive
   ```

5. **Show the resulting diff** so the user can spot anomalies:

   ```bash
   git -C "$CLAUDE_PROJECT_DIR" diff --stat -- .github/workflows/
   git -C "$CLAUDE_PROJECT_DIR" diff -- .github/workflows/
   ```

6. **Suggest the commit** (don't run it — the user reviews + commits).
   The skill returns the exact recommended commit command:

   ```text
   git commit --only -- .github/workflows -m "ci: SHA-pin GitHub Actions via actions-up

   N action references updated (M major, m minor, p patch). Tags preserved
   as comments next to each SHA so dependabot / future updates can still
   resolve them."
   ```

7. **Report one line** to the heartbeat-visible summary:
   * On apply: `actions-up: pinned N action ref(s) under .github/workflows/ — review with: git diff -- .github/workflows/`
   * On no-op: `actions-up: every action ref is already pinned + current (no changes)`
   * On dry-run only: `actions-up [check-only]: N action ref(s) would be updated — run /janitor-actions-up --apply to fix`
   * On error: `actions-up FAILED: <one-line trimmed stderr>`

## Output

ONE line per the four cases above. The full preview table, diff, and
commit suggestion are surfaced as separate blocks the user reviews
inline — they're not part of the one-line summary the heartbeat surfaces.

## Error Handling

* `npx actions-up` returns non-zero → trim stderr to one line, report
  with `FAILED:` prefix, never half-apply.
* Network timeout reaching `api.github.com` (actions-up resolves tags
  via the GitHub API) → report; retry is the user's call.
* Rate-limit (HTTP 403 from GitHub) → suggest `gh auth login` and stop.
* A workflow file becomes syntactically invalid after the rewrite
  (extremely rare — actions-up's own tests catch this) → roll back **only
  the workflow paths this run rewrote**:
  `git restore --source=HEAD -- .github/workflows/<file>`, then report.
  **Do NOT `git stash`** (janitor#188): stash is repo-wide, so in a tree
  several agents share it pockets everyone else's uncommitted work with no
  signal to them. If the user had their own uncommitted edits in that same
  workflow file, copy it aside first — a scoped restore still overwrites it.

## Examples

```text
User: /janitor-actions-up
User: pin all GitHub Actions to SHA
User: harden workflow refs
User: actions-up --check-only
User: update github actions to latest with sha
User: /janitor-actions-up --mode minor --min-age 14
```

## Scope

This skill ONLY rewrites `uses:` lines in `.github/workflows/*.yml`
(and `*.yaml`). It does NOT:

* Modify any source code outside `.github/workflows/`.
* Push commits.
* Open pull requests.
* Touch CODEOWNERS, branch-protection, or any other repo configuration.

For policy + ongoing-monitoring (does my repo STAY pinned over time?),
the `workflow-security` detector + the Sentinel `github-dependency-refs`
rule are the surveillance arm. This skill is the one-shot heal.

## Resources

* [Azat-io/actions-up](https://github.com/azat-io/actions-up) —
  upstream CLI source + rationale for the SHA-pinning approach.
* The janitor's [`janitor-github-workflow-doctor`](../janitor-github-workflow-doctor/SKILL.md)
  skill — runs the deeper Sentinel + zizmor scanners and identifies
  every workflow security issue. After running the doctor for the
  semantic findings, run THIS skill for the unpinned-action heal.
* [`workflow-security`](../../README.md#detectors) — the heartbeat
  detector that auto-flags newly-introduced unpinned actions.

## Checklist

Copy this checklist and track your progress:

* [ ] Pre-flight: `.github/workflows/` exists
* [ ] Pre-flight: working tree clean (or `--apply` was explicit)
* [ ] Pre-flight: self-scan guard (refuse on janitor's own repo)
* [ ] Pre-flight: `npx` on PATH
* [ ] Dry-run via `npx actions-up --dry-run --json`
* [ ] Render the preview table to the user
* [ ] Apply via `npx actions-up --yes` (unless `--check-only`)
* [ ] Show post-apply `git diff` for review
* [ ] Suggest the exact `git commit` command
* [ ] Emit the one-line summary
