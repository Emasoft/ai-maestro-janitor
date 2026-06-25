---
name: janitor-publish-pipeline
description: "publish blocked / how do I release the janitor / CPV flagged a finding / can I skip a gate / push rejected by pre-push hook / version mismatch on publish / no changelog — the janitor's fail-fast publish pipeline (a CPV plugin), its gate order, and the CPV-only validate policy"
ocd: 2026-06-13
lmd: 2026-06-25
metadata:
  node_type: memory
  type: project
  tier: component
  globs:
    - "scripts/publish.py"
    - "cliff.toml"
    - "CHANGELOG.md"
---

The janitor ships via `scripts/publish.py` — a strict, **fail-fast** release
pipeline. **It is a CPV plugin**, so its pipeline includes the CPV plugin-schema +
security gate. Not every fleet project is a plugin: **non-plugin agents (e.g.
service-style or library projects) have their OWN pipelines** — this page
documents the janitor's specifically; do not assume another project releases the
same way. The pipeline auto-detects the project (it is language-agnostic:
claude-plugin / python / rust / go / node / bash can coexist) and runs an
ordered set of gates; **any gate failing exits non-zero and the release stops**
— there is no skip, no force, no bypass.

**Gate sequence (in order; each is mandatory; failure = stop):**

1. **Self-integrity + env-bypass rejection** — before anything runs, `main()`
   greps its OWN source for forbidden bypass patterns (`--skip-tests`,
   `--skip-lint`, `--skip-validate`, `--no-validate`, `--force-publish`,
   `--bypass`, `skip_*` variables) and refuses to run if any appear outside the
   two authorized allowlists. It then rejects a set of bypass env vars
   (`SKIP_TESTS`, `SKIP_VALIDATE`, `CPV_SKIP`, `CPV_NO_STRICT`, `FORCE_PUBLISH`,
   `BYPASS_VALIDATION`, …). This makes the no-skip policy self-enforcing against
   future edits.
2. **Step 0 — auto-detect** git root, plugin root (walks up to
   `.claude-plugin/plugin.json`), plugin info, marketplace (from git remote),
   default branch, and whether the plugin lives in a subfolder.
3. **Step 0.5 — install/refresh the pre-push hook** (the strict gate; see the
   push-guard model below). Regenerated from an inline template on every run so
   a locally-edited hook can't survive as a bypass. This is the ONE intentional
   side effect of `--dry-run`.
4. **Step 1 — clean working tree** (`git status --porcelain`); a `uv.lock`-only
   dirty tree is auto-committed (skipped under `--dry-run`), anything else
   aborts.
5. **Step 2 — language-native TESTS** (mandatory, per detected language; any
   failure exits). A no-op only if no test infra exists for any detected
   ecosystem.
6. **Step 3 — language-native LINT** (mandatory, zero errors): ruff (Python),
   clippy (Rust), go vet, the `lint` npm script (Node), shellcheck (bash), plus
   the by-extension linters (pymarkdown, yamllint, json, toml).
7. **Step 4 — CPV `--strict` VALIDATE** (only when the project is a claude
   plugin): `uvx --from git+<CPV repo> cpv-remote-validate plugin <plugin-root>
   --strict`. This is the SOLE validation invocation — it covers the full plugin
   schema check + the strict rule set.[^2] (Historical: a separate `cpv … lint` step
   existed; CPV ≥ v2.71.0 retired it after fixing its gitignore-walk bug, so the
   single `plugin --strict` pass now covers everything.)
8. **Step 6 — version consistency** across plugin.json / pyproject.toml /
   package.json / Cargo.toml / Python `__version__`; a mismatch aborts.
9. **Step 7 — git-cliff availability pre-check** (fail BEFORE any file mutation —
   every release MUST produce a CHANGELOG entry + release notes).
10. **Step 8 — compute the bumped semver** from `--major | --minor | --patch`
    (exactly one is required).
11. **Step 9 — bump the version** in every applicable config file (and re-`uv
    lock` so the lockfile tracks the new version).
12. **Step 10 — git-cliff CHANGELOG + release notes**: `git cliff --bump
    --unreleased --tag vX.Y.Z -o CHANGELOG.md`, extracting the notes for the
    GitHub release into a gitignored `.git-cliff-release-notes.md`.
13. **Step 11 — commit** the bump + CHANGELOG (stages only known-modified files
    by name — NEVER `git add -A`, which could pick up secrets or scratch).
14. **Step 12 — annotated tag** `vX.Y.Z` whose body is the extracted release
    notes.
15. **Step 13 — push** commit + tag to `origin/<default-branch>`.
16. **Step 14 — create the GitHub release** (mandatory; `gh release create` with
    `--notes-file`) so Claude Code's plugin-update detector sees the new version.
    Missing/unauthenticated `gh` fails the pipeline (no silent skip).

`--dry-run` runs every validation gate fully, then stops before the bump/commit/
push (it mutates nothing in git history; its only side effect is installing the
push-guard hook).

**CPV-ONLY validation policy + devitalize-or-remove (PRRD S5.1):** the pipeline
invokes ONLY the CPV plugin for validation — there are NO local copies of any
validator script. A CPV finding is cleared by **devitalizing or removing** the
offending code, **NEVER** by exempting/suppressing a rule or relaxing `--strict`.
The exempt-list mechanism was dropped fleet-wide as trivially exploitable.
Concretely: an execution-class security finding (live `os.system` /
`subprocess(shell=True)`, pipe-to-shell install docs, `eval`/`exec` of a string,
backtick command substitution, hardcoded tokens in docs, raw detection-pattern
signatures) is rewritten into provably-inert data the scanner recognizes
(see the CPV `devitalize-threats` catalog) — you make the code's executable
shape inert, you do not silence the rule.

**Admin-bypass-for-publish.py branch-ruleset model:** the default branch carries
the ratified baseline ruleset pair (history-protect: no force-push / no deletion
/ linear history with NO bypass actor; pr-and-checks: PR ≥ 1 approval + required
status checks, with an admin direct-push bypass). The admin bypass exists
precisely so `publish.py` can push the release commit + tag directly to the
default branch while ordinary contributions still go through PRs. Two layers
guard this: (a) the GitHub ruleset's admin bypass, and (b) a local **pre-push
hook** that verifies its caller by **process ancestry** — it walks the PID tree
looking for a `python … scripts/publish.py` ancestor and only then allows the
push. No env var is involved (process trees can't be spoofed), so a stray
`git push` from outside the pipeline is refused locally even before GitHub.

Run forms: `scripts/publish.py --patch` (or `--minor` / `--major`), add
`--dry-run` to exercise every gate without releasing.

**Machine-specific facts live in LOCAL scope** (named here, not stored): the
absolute repo-root path, the owner GitHub identity / `gh` auth, account emails,
and any OAuth tokens. This page is git-tracked and host-global, so it carries
only generic procedure (use `<repo-root>`, `$HOME`, `<email>`, the CPV repo by
name, never literal paths or secrets).

## See also

- `[[project_janitor_publish_blocked_cpv_fps]]` — the publish-gate history + the
  devitalize-or-remove unblock recipe (RESOLVED; v0.7.x shipped).

## Notes and lessons learned
[^1]: [ocd:2026-06-13 lmd:2026-06-13] The step numbers intentionally skip 5 —
  the old "Step 5: CPV lint" was folded into the single Step 4 `plugin --strict`
  pass when CPV retired its `lint` subcommand, but the later step numbers were
  kept on their original sequence (Step 6 follows Step 4) so log greps against
  any existing release-history line still hit. Lesson: when removing a pipeline
  stage, preserve downstream step numbering if logs are grepped by it, rather
  than renumbering and breaking historical log queries.
[^2]: [ocd:2026-06-25 lmd:2026-06-25] Step-4 CPV `--strict` runs a markdownlint
  that scans MORE files than Step-3's own pymarkdown — notably `design/tasks/*.md`
  (the TRDDs), which Step 3 does NOT scan. So a markdown formatting bug in a TRDD
  passes the local lint and only fails at the CPV gate (v0.24.6 hit this). The trap
  (issue #113): a hard-wrapped prose line beginning `+ ` (or `* `) is read by
  markdownlint MD004/ul-style as a rogue `+`-marker list item, "mixing" it with the
  file's `-` bullets → a blocking NIT. Lesson: never start a wrapped markdown
  continuation with `+ `/`* `/`- `. Companion gotcha, same incident: a background
  `publish.py > LOG; echo "EXIT=$?"` wrapper reports exit 0 (the echo's status, not
  publish.py's), MASKING a validate failure — drop the trailing echo, and ALWAYS
  recheck version+branch after a "successful" publish (a failed validate bumps
  nothing and pushes nothing).
