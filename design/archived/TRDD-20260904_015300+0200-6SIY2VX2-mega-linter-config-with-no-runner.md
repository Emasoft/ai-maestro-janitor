---
trdd-id: 6SIY2VX2
title: decide the fate of a mega-linter config that no workflow in this repo runs
column: complete
created: 2026-09-04T01:53:00+0200
updated: 2026-09-04T02:35:00+0200
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
- COUNT CORRECTION: `ENABLE_LINTERS` holds **12**, not 11. Earlier text here
  said 11 because it was read from a truncated `head -12` that cut
  `REPOSITORY_TRIVY` off the end. The full list is PYTHON_RUFF, PYTHON_MYPY,
  PYTHON_BANDIT, BASH_SHELLCHECK, BASH_SHFMT, JSON_JSONLINT, YAML_YAMLLINT,
  MARKDOWN_MARKDOWNLINT, SPELL_CSPELL, COPYPASTE_JSCPD, REPOSITORY_CHECKOV,
  REPOSITORY_TRIVY.
- REPO-INVARIANT: no workflow runs ANY of the 12. That is the fact the
  delete-vs-keep decision rests on, and it holds on every machine.
- DO NOT map the config onto the preflight by count — the two are different
  sets that happened to both look like 11. CPV's preflight reported 11 CHECKS,
  of which three (`actionlint`, `uv-sync-dev`, `ci-parity`) are CPV's own and
  correspond to no configured linter at all.
- The honest mapping, measured on the owner's laptop 2026-09-04:
  - **5 RAN** in the preflight — mypy, bandit, shellcheck, shfmt, jscpd.
  - **3 SKIPPED** because the tool was absent — cspell, checkov, trivy. This
    is MACHINE-DEPENDENT: install cspell and it moves to RAN with no change to
    the repo. Coverage that varies by publishing host is the sharper hazard.
  - **3 NEVER APPEARED** — jsonlint, yamllint, markdownlint. WHY is UNDETERMINED.
    An earlier draft argued "CPV warns for a configured-but-missing tool, and
    emitted no warning for these, so they are probably not implemented" — that
    is CIRCULAR: CPV can only warn about tools it implements, so silence is
    exactly what you would observe whether they are unimplemented OR merely
    absent-and-unknown-to-it. The inference distinguishes nothing and is
    withdrawn.
    A VALID argument for the same conclusion does exist, and it does not touch
    the warning logic: these three appear in NEITHER list. An implemented check
    that PASSES prints `✓`; an implemented check whose tool is MISSING prints
    `!`. Absent from both ⇒ either not implemented, or folded into `ci-parity`
    (CIP-1..8, which is opaque). That rests only on the reported-checks list
    being complete — not on CPV reading this config, which the perturbation test
    showed it does not.
    What would settle the remaining disjunction: install one (e.g. `npm i -g
    jsonlint`) and re-run — if it appears, it was implemented and merely
    missing; if not, it is unimplemented or inside ci-parity.

  The 12-count above is from a `yaml.safe_load` of the file, not a grep — the
  original "11" came from a truncated `head -12`, and a `sed` bounded by a
  blank line would have been the same class of error.
  - **1 elsewhere** — ruff runs in `stage_lint`, not the preflight.

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
- [x] Decide: delete / restore a workflow / adopt wanted linters
      individually.
      — DECIDED 2026-09-04: **keep the file, annotate it as dormant.** Neither
      of the other two options survives its own cost check:
      · DELETE loses four documented decisions carrying issue references
        (gitleaks #138, reporter-schema #29, the single-quote/yamllint escape
        gotcha, the fixture-exclusion rationale). A deleted tracked file is
        recoverable only by someone who already knows to look for it, which is
        the worst kind of recoverable. The criterion was named BEFORE reading
        the file — "if it holds no knowledge beyond the linter list, delete
        wins" — and the file failed it four times over.
      · RESTORE A WORKFLOW would newly enforce seven linters this repo has
        never run (jsonlint, yamllint, markdownlint, cspell, checkov, trivy,
        shfmt); the other five are already covered (ruff+mypy in `stage_lint`;
        bandit/shellcheck/jscpd at G2b/G2f/preflight). That is an unbounded
        new-findings change, not a restoration, and it is the user's call.
      · ADOPT INDIVIDUALLY is the same change wearing a smaller name — it still
        turns on linters nothing has ever run.
      The hazard the card actually names — that the file makes it LOOK like CI
      enforces these — is addressed at BOTH ends: the false "CI's Mega-Linter
      WILL enforce it" operator messages were corrected in `publish.py`
      (`3bf69302`/`aea0483e`), and the config now says so in its own header.
- [x] Execute that decision.
      — Header added to `.mega-linter.yml` stating it is dormant, that no
      workflow or pre-commit config invokes Mega-Linter (re-verified 2026-09-04:
      `.github/workflows/` holds ci, memgrep-release, notify-marketplace,
      release, weekly-audit, zizmor-scan — none reference it; no
      `.pre-commit-config.yaml` exists), that CPV does not parse it, and why it
      is kept rather than deleted. Comment-only: `yaml.safe_load` after the edit
      returns the same 11 keys, 12 linters, `--threshold 5`.

## Approval log

- 2026-09-04T02:35:00+0200 — COMPLETED by janitor-main-session, deciding for the
  USER under their standing delegation ("you are in charge... you can do the
  review columns of the kanban in my stead", 2026-09-03). Keep-and-annotate; no
  workflow added, no linter newly enforced, no runtime value changed.
