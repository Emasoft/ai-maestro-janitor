---
trdd-id: STLUO7MB
title: CPV ci-preflight tells the operator CI will enforce checks that the consuming repo does not run
column: todo
created: 2026-09-04T01:53:00+0200
updated: 2026-09-04T01:53:00+0200
current-owner: main-session
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
relevant-rules: []
npt: []
eht: []
implementation-commits: []
---

# CPV ci-preflight tells the operator CI will enforce checks that the consuming repo does not run

## Facts

- `cpv-remote-validate ci-preflight .` prints, for each unavailable tool:
  "CI's Mega-Linter WILL enforce it; install `<tool>` for full local parity".
  Observed 2026-09-04 for cspell, checkov and trivy.
- No workflow in ai-maestro-janitor runs Mega-Linter, so for this repo that
  statement is false, and it is printed at the exact moment the operator
  decides whether a skipped check matters.
- This is the same false-backstop defect that TRDD-MYQGMAQZ removed from
  `publish.py`'s own warnings the same night.
- CPV is generic tooling used by many plugins and cannot know whether the
  consuming repo runs Mega-Linter. The general fix is for a skip message to
  name what it FAILED TO VERIFY rather than predict another system's
  behaviour.
- CROSS-PROJECT: `claude-plugins-validation` is a different repo. Per
  `~/.claude/rules/how-to-fix-issues-of-other-projects.md` this must NOT be
  edited from here — it needs either an issue filed on that repo or a fork +
  PR, and the USER chooses which. Nothing has been filed yet.

## Acceptance criteria

- [ ] User chooses issue vs fork+PR.
- [ ] The report or patch is submitted.
- [ ] Link recorded here.
