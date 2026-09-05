---
trdd-id: STLUO7MB
title: CPV ci-preflight tells the operator CI will enforce checks that the consuming repo does not run
column: complete
created: 2026-09-04T01:53:00+0200
updated: 2026-09-05T10:40:00+0200
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

- [x] User chooses issue vs fork+PR. **Ruled 2026-09-05: ISSUE** — the cross-project rule says issue first whenever the fix is not ours to author, and this one is a message-wording change in CPV's own preflight.
- [x] The report or patch is submitted.
- [x] Link recorded here: https://github.com/Emasoft/claude-plugins-validation/issues/228

## Approval log

- 2026-09-05T10:40:00+0200 — COMPLETED by main-session under the USER's standing autonomous-drain permission (memory ATOM-CCRI-ZRT2, 2026-09-03; re-issued as today's session goal). Issue vs fork+PR: ISSUE, per how-to-fix-issues-of-other-projects (issue first; PR only if asked). Filed as claude-plugins-validation#228 with the reproducer and the suggested shape (a skip message names what it failed to verify rather than predicting Mega-Linter). Nothing blocks on it.
