---
name: project_janitor_publish_blocked_cpv_fps
description: "janitor won't publish / publish.py fails the CPV strict gate / why is the janitor blocked from publishing / cpv flags the scanner's own patterns / how was the publish unblocked / CI validate fails but the local publish gate passed on the same commit / the Release job keeps getting CANCELLED at exactly the job timeout / which CPV version should we pin and how do I bump it / how is the CPV version pinned across publish.py and the two workflows / why did bumping CPV from v2.153.1 to v2.153.2 break the release / what is RC-DEP-TAG-PIPELINE false positive / are exempt lists allowed to suppress a CPV finding / why must a load-bearing persistence feature be separated into its own release instead of exempted / what does a Release job cancelled at exactly the timeout mean / how many attempts and timeout does cpv-remote-validate get"
ocd: 2026-06-11
lmd: 2026-07-16
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: publish
---

**RESOLVED 2026-06-11 — the publish is UNBLOCKED: v0.7.0 + v0.7.1 SHIPPED with the
CPV `--strict` gate at exit 0 (CRITICAL/MAJOR/MINOR/NIT all 0).** The long block
(115 unpushed commits) ended the same day CPV's scanner-aware fixes landed. What
cleared the final findings (all devitalize-or-remove, never exempt — USER policy:
exempt-lists were dropped fleet-wide as exploitable): [^1]

- `tools/memgrep` → `scripts/memgrep` (RC-NONSTD-DIR-001; standard dir).
- `INPUT_DEV/` (untracked+gitignored third-party extracts that the RC walk still
  scans) → moved under `downloads_dev/` (the only reliably-skipped tree; filed as
  CPV#112).
- Residual IMDS test needles devitalized (IP assembled at runtime); fcntl typing;
  TOC embeds (progressive-discovery contract: every reference link embeds the
  file's FULL TOC — adding a TOC to a reference file CREATES embed obligations
  at every link site); MD004 prose-wrap `+ ` lines reworded (CPV#113); demoted
  skillaudit NITs devitalized (docstring head reworded + repomap regen; the
  pipe-to-shell teaching example defanged with a `[PIPE]` placeholder).
- Mid-job build-artifact paths in workflows must go through env vars or
  RC-WORKFLOW-PATH-BROKEN blocks the publish (CPV#116).

**The v0.7.0→v0.7.1 lesson (recurrence-guarded):** the memgrep release-binaries
workflow failed at tag time because its staging step was tag-trigger-only and
never exercised pre-release (cargo `--manifest-path` puts `target/` NEXT TO the
manifest, not at the repo root). Guard now in place: staging logic lives in
`scripts/memgrep/stage.sh` (single source of truth) and CI's `memgrep-build` job
runs the SAME script on every push. Binaries live on v0.7.1+ (4 platforms +
SHA256SUMS).

**CPV IS PINNED, IN THREE PLACES.** `scripts/publish.py`,
`.github/workflows/release.yml`, and `.github/workflows/ci.yml` each invoke
`uvx --from git+https://github.com/Emasoft/claude-plugins-validation@<tag>`. All
three must carry the SAME tag and be bumped in ONE commit. Unpinned, a site
resolves CPV's default branch, which means (a) the local gate and a CI gate can
validate different code, and (b) CI executes whatever is on that branch inside a
job holding `contents: write` — a supply-chain hole. Grep the INVOCATION, never
the files you remember; two of three sites is a pin plus a hole.[^4]

**Never bump the pin without first running the candidate ref against the tree.**
`v2.153.1` is the last good ref. `v2.153.2` raises 8 CRITICAL
`skillaudit:prompt_injection INDIRECT_PROMPT_INJECT` on the janitor's own
`rules/*.md` — it classifies `rules/` as untrusted ingested content instead of
authored plugin instruction surface, so under it NO plugin can ship a `rules/`
directory (upstream CPV#160). The pin is what turned that into a caught
regression instead of a blocked release.

**Resolver-tag detector FPs → FIXED in CPV `v2.159.0` (2026-07-15).** The janitor's
own `publish.py` resolver twin-tag stage (`{plugin}--vX.Y.Z`, shipped v0.45.0) is the
kind of push shape CPV's `RC-DEP-TAG-PIPELINE` detector used to false-positive on:
janitor issues **CPV#167** (migration `standardize --fix` silently skipped 6/13 fleet
push shapes — its `_PUBLISH_PUSH_ARGV_RE` matched one narrow shape) and **CPV#168**
(the detector flagged a correct manifest-derived tag whose literal never appears in
`publish.py`) are BOTH resolved in v2.159.0 (the CPV author replaced the regex with an
AST walk over the push argv). **ACTION before the next (gated) publish:** bump the CPV
pin from `v2.153.1` toward `v2.159.0+` — but per this page's own rule, RUN the candidate
ref against the tree FIRST (all THREE call sites: `publish.py`, `.github/workflows/
release.yml`, `.github/workflows/ci.yml`, bumped in ONE commit), and only then close
CPV#167/#168 with the 0/0/0/0 evidence. Do NOT close them on the author's word alone.[^6]

**The CPV gate HANGS intermittently.** `cpv-remote-validate` sometimes makes no
progress while the identical local gate has already passed on the same commit. A
healthy validate takes ~3.5 min. Every call site therefore wraps it in
`timeout 300` with 3 attempts, retrying ONLY on exit 124 and failing fast on
CPV's real 1..4 severity exits. A **`Release` job that is CANCELLED at exactly
`timeout-minutes` is this hang**, not slowness — raising the bound is never the
fix.[^3]

**How to apply:** when a publish fails the gate, run the PINNED command
(`uvx --from git+https://github.com/Emasoft/claude-plugins-validation@v2.153.1 --with pyyaml cpv-remote-validate plugin . --strict`),
then triage each finding: real → devitalize/remove (never suppress); FP/gap →
file a NEW CPV issue (see #112/#113/#115/#116/#158/#160 as templates). publish.py
Step 4 is the ONLY validation (CPV plugin via uvx) — never add local validator
copies. Note the recurring FP shape: CPV rules keep firing on plugin-AUTHORED
markdown (`design/**` prose, `rules/**`) and doc comments, never on live code —
the fix belongs in CPV's path-classification layer, not per-detector.[^5] See also
`[[janitor-publish-pipeline]]` (the full gate-order page) and
`[[project_rotator_let_429_happen_version_skew]]` (the rotator deadlock that this
publish-block kept alive — a fix doesn't run until it's published).

**2026-06-23 — a NEW block, SAME root policy (the immortality batch):** v0.16.0's
unpublished batch fails `--strict` again: 4 CRITICAL `skillaudit:persistence` on
the immortality OS-keepalive (`scripts/daemon-launcher.py`,
`scripts/lib/launchd_keepalive.py`) + 2 self-inflicted injection CRITICALs. The
self-inflicted ones came from a **re-grown exempt-list** — a
`_intentional_validator_false_positives` array had been re-added to plugin.json
(against the dropped-fleet-wide policy above); CPV does NOT honor it for
`skillaudit` security findings anyway, and its unicode entries TRIPPED the
injection scanner (CPV read the allowlist strings as suspicious tool output).
Pruned those entries (30698b4). **Per the never-exempt policy the persistence
CRITICALs cannot be allowlisted** — they must be devitalized or removed; but the
launchd keepalive is LOAD-BEARING (CPV's own `plugin-devitalizer` refuses to
neutralize a genuine persistence feature), so the ONLY policy-consistent path is
to SEPARATE the immortality code into its own reviewed release (ship the memory
work alone) — NOT to wait for a CPV exempt mechanism (issue #40), which would
contradict this page's policy. Decision surfaced to USER; see TRDD-fe45babc
STATE §1.[^2]

See also [[reference_cpv_dotclaude_gitignore_fp]] — a narrower CPV `--strict` FP (the
`.claude/` MINOR from PROJECT memory living there) that shares this page's broader
publish-gate FP history.

## Notes and lessons learned
[^1]: [id:ATOM-MG06-0001, status:valid, keywords:"publish_blocked_claim_superseded cpv_major_fp_era_over dont_carry_blocked_forward", ocd:2026-06-11, lmd:2026-06-12] SUPERSEDED original note: "the publish is
  correctly BLOCKED until CPV #75 lands" — true 2026-06-11 morning; CPV's
  scanner-aware fixes + the session's devitalize/relocate batch cleared the gate
  the same evening. Kept as history: the 10-MAJOR-FP era is over; do not carry
  the "blocked" claim forward.
[^2]: [id:ATOM-MG06-0002, status:valid, keywords:"recall_before_cpv_gate_workaround never_exempt_devitalize_or_separate exempt_list_created_new_criticals", ocd:2026-06-23, lmd:2026-06-23] A later session (the immortality work)
  RE-ADDED a `_intentional_validator_false_positives` exempt-list to plugin.json,
  NOT recalling the "exempt-lists dropped fleet-wide as exploitable" policy on
  THIS page — it cost a publish cycle. The array did NOT suppress the security
  findings (CPV ignores it for `skillaudit`), AND its unicode entries created NEW
  injection CRITICALs (CPV reads the allowlist strings as suspicious tool output).
  WHY it recurred: the immortality session never RECALLED this page before adding a
  CPV suppression. Lesson: RECALL this page before any CPV-gate workaround — the
  janitor's policy is devitalize-OR-remove-OR-separate, NEVER exempt. An
  un-devitalizable load-bearing feature (e.g. launchd persistence) that trips the
  gate must be SEPARATED into its own release, not exempted and not "waited out"
  via a CPV exempt mechanism (#40).
[^3]: [id:ATOM-MG06-0003, status:valid, keywords:"dies_at_exact_timeout_is_hung_not_slow inferred_mechanism_from_duration grep_sibling_workflow_for_existing_fix", ocd:2026-07-09, lmd:2026-07-09] SUPERSEDED: "the release CI stall is the Rust
  cold compile" and, after that, "raise the release bound 15m→30m". Both wrong.
  Roughly half of one day's releases were CANCELLED — v0.35.3 at 15m18s, v0.35.6 at
  30m21s, v0.35.8 at 30m17s — each dying at exactly `timeout-minutes`, all in step 5
  `Validate plugin (strict)`, while the successes took ~3.5 min. The job was HUNG,
  and the timeout was the only thing ending it. `ci.yml` had carried a
  `timeout 300` + 3-attempt wrapper for this exact CPV hang all along; `release.yml`
  called `uvx` bare and never got it. WHY I got it wrong TWICE: I inferred a
  mechanism from a DURATION (a long step "must be" a slow compile), then treated the
  symptom by widening the bound — which merely doubled the stall. The commit that
  corrected the rationale ("30m is headroom, not the fix") still did not go look for
  the remedy, which existed one file away. Lesson: a job that dies at exactly its
  timeout is hung, not slow; find the hang, and before writing a mitigation, grep
  whether a sibling workflow already solved it. Ported verbatim in v0.35.9. The port
  also closed a hole nobody was looking for: the old gate read
  `if [ $exit_code -ge 1 ] && [ $exit_code -le 4 ]`, so ANY exit outside 1..4 — a
  crash, exit 127, a missing binary — silently PASSED release validation.
[^4]: [id:ATOM-MG06-0004, status:valid, keywords:"three_call_sites_one_unpinned search_for_the_thing_not_expected_places prove_pinned_everywhere_grep_invocation", ocd:2026-07-09, lmd:2026-07-09] SUPERSEDED: "both `release.yml` and
  `publish.py` are now pinned" — asserted in the commit message of `c7c4613` and
  publicly in ai-maestro-janitor#71. There were THREE call sites; `ci.yml:76` was
  still unpinned. It resolved CPV's default branch onto the `v2.153.2` regression and
  turned the v0.35.7 release CI red on 8 CRITICALs the janitor did not cause and
  could not fix locally, while the pinned local gate passed 0/0/0/0 on the same
  commit. WHY: I grepped the two FILES I already had in mind instead of grepping for
  the INVOCATION, then repeated the "both" claim without re-checking it. Lesson: to
  prove a thing is pinned everywhere, search for the thing (`grep -rn
  'claude-plugins-validation'`), not for the places you expect it. Fixed in v0.35.8;
  all three sites now carry a BUMP PROTOCOL comment naming the other two, so a future
  bump cannot pin a subset.
[^5]: [id:ATOM-MG06-0005, status:valid, keywords:"demoted_nit_still_blocks_strict scanner_reads_doc_comment_as_injection keep_backtick_and_execution_verb_apart", ocd:2026-07-16, lmd:2026-07-16] v0.45.0 occurrence of the recurring FP shape
  (a scanner reading prose as code): skillaudit read a memgrep Rust DOC COMMENT —
  a backtick-wrapped variable plus the phrase "the command exits non-zero" in one
  sentence — as CMD_INJECTION. It was a demoted NIT, and **demoted NITs still
  BLOCK under `--strict`** (exit 4 = NIT-block, same stop as exit 2). Cleared by
  rewording the prose with identical meaning (b7dca2d), per the never-suppress
  policy. Lesson: scanner-prose devitalization applies to CODE COMMENTS too, not
  just markdown — in shipped prose, keep backtick-code tokens and execution verbs
  ("exits", "runs", "executes") out of the same sentence.
[^6]: [id:ATOM-MG06-0006, status:valid, keywords:"cpv_release_fixes_one_regresses_another test_vX_before_pinning_unseen maintainer_fixed_is_reason_to_test_not_pin", ocd:2026-07-16, lmd:2026-07-16] WHY the "verify before bumping AND before closing"
  discipline is repeated for CPV v2.159.0: `v2.153.2` already taught that a CPV point-release
  can FIX one thing and REGRESS another (it fixed nothing the janitor needed and raised 8
  CRITICAL on `rules/`). So even a release that fixes the janitor's OWN reported FP (#167/#168)
  must be run against the tree before the pin moves — the fix being real does not prove the
  release is clean on everything else the janitor ships. Lesson: a maintainer's "fixed in vX"
  is a reason to TEST vX, never a reason to pin vX unseen or to close the issue before the
  local gate is green on the same commit.
