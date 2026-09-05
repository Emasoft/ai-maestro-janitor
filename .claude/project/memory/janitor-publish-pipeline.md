---
name: janitor-publish-pipeline
description: "publish blocked / how do I release the janitor / CPV flagged a finding / can I skip a gate / push rejected by pre-push hook / version mismatch on publish / no changelog / publish exited 3 but every test passed / rc=3 with nothing failing / the gate timed out but the test passes on its own / TimeoutExpired on an xdist worker / is this flaky or a real regression — the janitor's fail-fast publish pipeline (a CPV plugin), its gate order, the write-guard, and the CPV-only validate policy / the test gate blocks a publish at random / tests fail only in the full suite and pass alone / a detector exits 0 with empty stdout / assert something in an empty string / which load-flake category is this / should I scale every timeout call site or enumerate them / enumerating call sites keeps missing some / scale timeouts at a seam not per site / my timeout scaling looks applied but does nothing / a module-level constant reads the env before the fixture sets it / timeout_scale frozen at 1.0 / a vacuous fix that looks scaled / gh-reply-watch floor test flaked under load / two projects reported the same reply / the deferred project polled again / a wall-clock floor spanning sequential spawns / I checked the gate would pass but it blocked anyway / hand-wrote a regex to approximate the lint / how do I dry-run the address lint before publishing / phantom hits from a stub known_for / an email-shaped filename blocked the release / dot-invalid is allow-listed but the publish still blocked / the release tag points at an old commit / tag and HEAD disagree after publish / duplicate chore bump version commits on main / publish exited 0 but the tag is wrong / renamed a test file and the address lint exploded / grandfathered addresses stopped being grandfathered"
ocd: 2026-06-13
lmd: 2026-09-05
metadata:
  node_type: memory
  type: project
  tier: hub
  globs:
    - "scripts/publish.py"
    - ".cpv-version"
    - "cliff.toml"
    - "CHANGELOG.md"
publish-globally: false
split-lineage: 08b34684a6214833bc3d78b80244d2cd
---

# ai-maestro-janitor — publish pipeline hub

The janitor ships via `scripts/publish.py` — a strict, **fail-fast** release
pipeline. **It is a CPV plugin**, so its pipeline includes the CPV plugin-schema
+ security gate; any gate failing exits non-zero and the release stops — there
is no skip, no force, no bypass.

## Parts map

This page is the entry point; the detail lives in four sub-pages (split from
this page on 2026-09-05 — it had outgrown a single load). Each still carries
its own lessons-learned section and links back here.

## Applies to

- [[janitor-publish-pipeline-gate-sequence]] — the full gate order (Step 0
  through Step 14), the CPV-only validation policy (devitalize-or-remove,
  never suppress), the admin-bypass branch-ruleset model, and the `--dry-run`
  / run-form contract.
- [[janitor-publish-pipeline-gate-timeouts-and-flakiness]] — the four
  categories of test-gate load-flake, the REAL-STATE write-guard's rc=3
  signature, gate-4 CPV-validate timeouts (hang vs slow vs host-saturation),
  and the tree-freeze / publish-lock enforcement.
- [[janitor-publish-pipeline-address-lint]] — the `[G1b]` personal-address
  lint: how it scopes to added lines, its false positives (email-shaped
  filenames, file renames), and how to dry-run it before a real publish
  attempt.
- [[janitor-publish-pipeline-cpv-and-release]] — CPV `--strict`
  frontmatter/pin gates, the release-tag drift after an interrupted-publish
  recovery, the card-acceptance chicken-and-egg with a live-observation box,
  and why a green publish gate is not evidence the CI-judged release is good.

## See also

- `[[project_janitor_publish_blocked_cpv_fps]]` — the publish-gate history + the
  devitalize-or-remove unblock recipe (RESOLVED; v0.7.x shipped).

## Notes and lessons learned
