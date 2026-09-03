---
trdd-id: 6SIY2VX2
title: decide the fate of a mega-linter config that no workflow in this repo runs
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

# decide the fate of a mega-linter config that no workflow in this repo runs

## Facts

- `.mega-linter.yml` is present and git-tracked. Its `ENABLE_LINTERS` lists
  11: PYTHON_RUFF, PYTHON_MYPY, PYTHON_BANDIT, BASH_SHELLCHECK, BASH_SHFMT,
  JSON_JSONLINT, YAML_YAMLLINT, MARKDOWN_MARKDOWNLINT, SPELL_CSPELL,
  COPYPASTE_JSCPD, REPOSITORY_CHECKOV. It also sets
  `COPYPASTE_JSCPD_ARGUMENTS "--threshold 5"`.
- VERIFIED 2026-09-04: no file under `.github/workflows/` invokes
  Mega-Linter; there is no `.pre-commit-config.yaml`; `git grep -il
  'mega.\?linter'` finds it referenced only by `.cspell.json`,
  TRDD-MYQGMAQZ, `publish.py` comments, and one test. Note that `git grep`
  covers TRACKED files only.
- HOWEVER: CPV's `cpv-remote-validate ci-preflight .` (`publish.py` stage
  4b, runs on every publish) IS Mega-Linter-aware — it runs jscpd, bandit,
  shellcheck, shfmt, actionlint, mypy and labels several "(Mega-Linter
  `<SUB_LINTER>` parity)". Whether CPV PARSES this config or carries its own
  list is UNPROVEN and is precisely what the delete-vs-keep decision turns
  on.
- Of the 11, shfmt/jsonlint/yamllint/markdownlint/cspell/checkov appear to
  have no runner in this repo's own workflows.

## Acceptance criteria

- [x] Determine whether CPV reads `.mega-linter.yml` (perturb the config and
      re-run the preflight, or read CPV's source).
      — ANSWERED 2026-09-04 by perturbation: removed `- COPYPASTE_JSCPD` from
      `ENABLE_LINTERS` and re-ran `cpv-remote-validate ci-preflight .`. jscpd
      STILL RAN (`✓ jscpd: Copy-paste check passed`). So **CPV does NOT read this
      config** — it carries its own list and merely labels its checks with
      Mega-Linter sub-linter names. The config was restored byte-identically
      (sha match, clean `git status`).
      CONSEQUENCE for the decision below: deleting `.mega-linter.yml` would NOT
      weaken the stage-4b preflight. The file's only remaining function is as
      configuration for a Mega-Linter run that nothing performs — including its
      `COPYPASTE_JSCPD_ARGUMENTS: "--threshold 5"`, which therefore does NOT set
      the threshold the preflight's jscpd actually uses.
- [ ] Decide: delete / restore a workflow / adopt wanted linters
      individually.
- [ ] Execute that decision.
