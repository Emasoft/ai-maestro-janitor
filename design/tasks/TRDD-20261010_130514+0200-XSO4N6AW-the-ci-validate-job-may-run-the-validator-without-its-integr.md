---
trdd-id: XSO4N6AW
title: The CI Validate job may run the validator without its integrity check ever verifying anything
column: blocked
status: tasked
created: 2026-10-10T13:05:14+0200
updated: 2026-10-18T03:31:30+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T13:05:14+0200
unblock-when: [issue:Emasoft/claude-plugins-validation#243, decision:owner accepts or refuses the silent integrity skip]
blocked-by: []
review-after: 2026-11-18
pre-block-column: verify_assumptions
---

# The CI Validate job may run the validator without its integrity check ever verifying anything

## Approval log

- 2026-10-10T13:05:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T03:31:05+0200 — column → blocked by main-agent@ai-maestro-janitor. verified; waits on upstream claude-plugins-validation issue 243 (unblock-when), re-check by 2026-11-18

## Question

2026-10-10 13:05 Minted from TRDD-CWKM5218. Read from the validator's code (v5.16.2) and a local run, not observed in CI: under uvx the integrity check resolves no version, its fallback manifest URL returns 404, and with no cached manifest it returns True silently, so every janitor release's Validate job would have run a validator nobody verified. TO VERIFY FIRST: one CI run with a step that calls verify_self_integrity(fail_on_mismatch=False, quiet=False) from the same uvx build and prints the result, or read a CI log with the validator's own debug output. IF TRUE, decide: a CI step that fails when the check could not verify, or accept the skip until the upstream fix (Emasoft/claude-plugins-validation issue 243). No code before the verification.
2026-10-18 REPRODUCED LOCALLY under fresh-runner conditions, NOT observed in CI (main session). (1) CI log of run 37686495589 (2026-10-07, main, the v3.8.11 CI): the Validate job prints no integrity line at all (grep -i integrity over the whole log hits only Smoke's detector names and one skill WARNING). (2) Local reproduction matching a fresh runner: HOME and UV_CACHE_DIR set to empty temp dirs, the same uvx spec CI uses (claude-plugins-validation@v5.16.2 with pyyaml), calling scripts._plugin_verify_hashes.verify_self_integrity(fail_on_mismatch=False, quiet=False) printed '[CPV integrity] WARNING: Could not fetch the canonical hash manifest from GitHub (https://raw.githubusercontent.com/Emasoft/claude-plugins-validation/main/.plugin-self-hashes.json) and no cached copy is available ... Cannot verify validat[or]' and returned True. So on a fresh environment the check verifies nothing and passes; CI's quiet run hides even the warning. Not run inside CI itself (that needs a workflow change and a push).
PROPOSED, FOR THE OWNER (a supply-chain security call, which the drain mandate keeps with the owner): accept the skip until the upstream fix (Emasoft/claude-plugins-validation issue 243, OPEN on 2026-10-18). A CI step that fails when the check cannot verify would fail every janitor release IF CI also cannot fetch the manifest (only the local fetch was seen to fail; whether CI can fetch it, and whether the URL is a 404, is unknown), and the owner's release path runs through that CI. Re-open the decision when issue 243 closes: then add the failing step, or confirm the fixed validator fails closed by itself.
