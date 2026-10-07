---
trdd-id: V5V1CBLM
title: Nothing installs or updates the memgrep binary after a plugin update, so a machine keeps a stale build
column: testing
status: tasked
created: 2026-10-06T20:14:55+0200
updated: 2026-10-07T15:21:39+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T20:14:55+0200
implementation-commits: [c5ec956c]
---

# Nothing installs or updates the memgrep binary after a plugin update, so a machine keeps a stale build

The plugin ships the Rust source and plugin.json tells the user to run cargo install. The release workflow .github/workflows/memgrep-release.yml builds binaries, but no script installs them (not verified beyond a grep of scripts/). On 2026-10-06 the binary on PATH was a day older than three fix commits, and TRDD-3HLI7DMK sat in testing waiting for a release that could never update it. Acceptance: after a plugin update the installed memgrep reports the commit of the installed plugin version (memgrep --version prints commit and date), or a detector reports the mismatch.

## Approval log

- 2026-10-06T20:14:55+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Design

2026-10-07 design: a new detector scripts/detectors/memgrep-binary-stale.py. Inputs: `memgrep --version` stamp (build.rs already prints '<ver> (<commit7>, <date>)'), and the user-scope janitor entry's gitCommitSha in ~/.claude/plugins/installed_plugins.json. Equal commits, or the stamp an ancestor-equal of the installed sha with no memgrep change: quiet. Different: ask `gh api repos/Emasoft/ai-maestro-janitor/compare/<stamp>...<installed>` and report STALE only when status is 'ahead' or 'diverged' AND some file under scripts/memgrep/ changed; status 'behind' (a dev build newer than the release) is quiet. Can't tell (memgrep absent, stamp 'unknown', gh missing or failing, no user-scope entry): one advisory line, never a fixable proposal. Machine-global binary: dedupe machine-wide per (stamp, installed sha), never once per project. No Rust and no publish.py change.
