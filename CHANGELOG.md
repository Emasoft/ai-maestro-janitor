# Changelog

All notable changes to `ai-maestro-janitor` follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-18

Initial release.

### Added

- Seven background Monitors: `pr-reconciler`, `worktree-janitor`, `trdd-drift`,
  `trdd-reminder`, `task-pr-mismatch`, `rate-limit-retry`, `cache-keepalive`.
- Four hooks: `SessionStart`, `UserPromptSubmit`, `Stop`, `StopFailure`.
- `/janitor-audit` skill for on-demand aggregate scans.
- Project-local state at `$CLAUDE_PROJECT_DIR/.janitor/`.
- Weekly GitHub Actions audit workflow as a fallback for sessions-off periods.
- `userConfig` entries for every cadence and threshold.

### Requirements

- Claude Code v2.1.105+ (plugin Monitors).
- `gh`, `jq`, git `origin` remote on GitHub.
