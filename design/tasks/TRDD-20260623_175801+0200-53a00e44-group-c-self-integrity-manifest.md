---
trdd-id: 53a00e44-e4b5-4b92-a4e5-9083ac017728
title: Immortal janitor GROUP C — ship the self-integrity manifest as a release artifact (C1-bounded)
column: published
created: 2026-06-23T17:58:01+0200
updated: 2026-06-24T06:06:23+0200
published-version: 0.18.0
published-at: 2026-06-24T04:37:06+0200
current-owner: claude-janitor-dev
assignee: claude-janitor-dev
parent-trdd: TRDD-324223a6
task-type: security
release-via: publish
relevant-rules: []
test-requirements: [unit]
impacts: [public-api]
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues"]
---

# GROUP C — self-integrity: ship the file-hash manifest as a release artifact (C1-bounded)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-24

**✅ C1 SHIPPED in v0.18.0 (2026-06-24).** Verified: `.integrity/manifest-sha256.json`
is git-tracked and present in the `v0.18.0` tag — `publish.py` Step 10.5 regenerated
it during tonight's release (GROUP B's persistence now clears CPV via the #152 fold,
so `main` was no longer publish-blocked). Self-integrity is now FUNCTIONAL data-wise;
the detector stays OPT-IN + alert-only (the default-on flip + C2/C3/C4 remain DEFERRED
below — exec-path / machine-wide, USER-review-gated). This C1 TRDD is now terminal
(`column: published`).

**Scope of THIS TRDD = the NON-BRICKING subset of GROUP C C1 only.** The plan
(`glittery-hatching-shell.md`, GROUP C) bundles four sub-pieces; this TRDD ships
exactly the one that is safe to land autonomously and DEFERS the three that are
bricking-risk or machine-wide-blast-radius (see "DEFERRED" below). Task #228.

### ✅ DONE + SHIPPED (committed, pushed, released in v0.18.0)
- **`scripts/generate_integrity_manifest.py`** (NEW) — regenerates
  `.integrity/manifest-sha256.json` (sha256 of the prompt surface:
  README/CLAUDE/skills/commands/rules = `DEFAULT_MANIFEST_GLOBS`). Thin glue over
  the already-tested `compute_manifest`/`write_manifest` lib. Modes: default
  writes; `--dry-run` computes+reports but writes nothing; `--root` targets an
  arbitrary checkout (publish passes the resolved root; tests pass a fixture).
- **`scripts/publish.py` Step 10.5** — runs the generator on EVERY release, after
  the bump (Step 9) + changelog (Step 10) — neither touches a globbed file — and
  before the release commit (Step 11), which now stages
  `.integrity/manifest-sha256.json` by name. Placed before the dry-run return so
  `--dry-run` exercises the generator (writing nothing). Fail-fast via `run()`.
- **`tests/test_generate_integrity_manifest.py`** — 5 tests: clean round-trip,
  dry-run-writes-nothing, manifest-excludes-itself (self-reference trap guard),
  prompt-surface coverage, real-repo dry-run smoke. All green; ruff clean.

### WHY this is the right C1 slice (not the whole group)
The plan deliberately ordered **C before B** ("don't run a corrupt self" before
adding OS persistence). B (launchd/systemd keepalive) shipped FIRST (out of
order), which is exactly why `main` is publish-blocked: CPV flags B's persistence
as CRITICAL and the no-exempt policy can't clear it. **C is the missing safety
layer for the very persistence that blocks the branch.** The
`janitor-self-integrity` DETECTOR already exists (opt-in, alert-only) but is a
permanent no-op because no manifest ships (`if not _MANIFEST_PATH.is_file():
return None`). Shipping the manifest as a fresh-per-release artifact is what makes
self-integrity FUNCTIONAL — the bounded, additive, non-bricking core of C1.

### 🔻 DEFERRED — user-gated / bricking-risk (do NOT do autonomously)
1. **C1 default-on flip** — flipping `JANITOR_SELF_INTEGRITY_ENABLED` default
   ON makes the detector run in EVERY project on the machine. Machine-wide blast
   radius: any stale-vs-shipped manifest would make every heartbeat in every
   project cry wolf. ONE-LINE change once the manifest-freshness guarantee is
   reviewed. **Needs USER review.**
2. **C2 verify-before-exec gate in `dispatcher-stub.py`** — the stub blindly
   execs `versions[-1]`; gating it on a manifest verify is the real protection
   BUT a bug there bricks the heartbeat (the lifeline of this very session).
   **Bricking-risk → USER design review.**
3. **C3/C4 pin-last-good + quarantine-bad-version + auto-rollback** — rollback
   record so a bad self-update/malicious push can't brick the janitor. Touches
   the exec path. **Bricking-risk → USER design review.**
4. **The plan's mandated ultracode review loop** — GROUP C "is done" only after
   the multi-agent opus review loop. That needs USER opt-in to Workflow
   orchestration (not granted this session). **OWED before the group is closed.**

### NEXT ACTION (C1 done; remaining GROUP C work is the DEFERRED set below)
- ✅ C1 shipped in v0.18.0 — manifest verified in the tag. Nothing left for THIS TRDD.
- The remaining GROUP C pieces (default-on flip, C2 exec-gate, C3/C4 rollback, the
  ultracode review loop) stay DEFERRED — every one touches the heartbeat EXEC PATH
  (a bug bricks the lifeline) or is MACHINE-WIDE (every project on the host). With
  no OAuth rotation alternate, an autonomous exec-path mistake is hard to recover,
  so they are authored as DESIGN before any live deploy. Each becomes its own child
  TRDD under TRDD-324223a6 when taken up — NOT folded back into this terminal C1 TRDD.

### Load-bearing facts
- Generator root resolution: the script is at `scripts/…` so plugin root =
  `__file__.parent.parent` ONE level up (the sibling DETECTOR at
  `scripts/detectors/…` is `.parent.parent.parent`-style two levels — do not copy
  its `_HERE.parent.parent`).
- Manifest globs are NOT touched by the version bump (plugin.json + `*.py`
  `__version__` only) or git-cliff (CHANGELOG.md is not globbed), so the manifest
  is self-consistent with the committed release tree.
- The manifest never lists itself (`.integrity/manifest-sha256.json` matches no
  glob) → its own presence can't be reported as an `extra`.
- publish.py Step 1 enforces a clean tree, so at Step 10.5 the glob matches ==
  the git-tracked files that ship (no untracked-dev-file skew).
- CPV runs at Step 4 (before 10.5); the manifest JSON (path→sha256 map, no
  secrets/exec/injection) is innocuous to every CPV scanner.

## Safety / invariants
- Additive + opt-in: the detector default stays OFF; this TRDD only feeds it data.
- Fail-fast: a generator error aborts the publish (no silent integrity gap).
- No exec-path change: `dispatcher-stub.py` is UNTOUCHED (C2 deferred).
- No machine-wide flip: default-on deferred to USER review.
