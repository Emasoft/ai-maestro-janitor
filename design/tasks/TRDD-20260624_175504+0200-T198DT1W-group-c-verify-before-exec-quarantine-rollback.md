---
trdd-id: T198DT1W
title: Immortal janitor GROUP C — C2 verify-before-exec gate + C3 pin-good/quarantine-bad + C4 bad-self-update auto-rollback
column: design
created: 2026-06-24T17:55:04+0200
updated: 2026-06-24T17:55:04+0200
current-owner: ai-maestro-janitor
assignee: null
priority: 2
severity: HIGH
effort: L
labels: [immortality, self-integrity, dispatcher-stub, bricking-risk, fail-open, group-c]
task-type: security
parent-trdd: TRDD-324223a6
relevant-rules: []
release-via: publish
test-requirements: [unit]
runtime-targets: [macos, linux]
impacts: []
external-refs: []
---

# TRDD-T198DT1W — GROUP C exec-path: verify-before-exec (C2) + pin-good/quarantine (C3) + auto-rollback (C4)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-24

### Status: DESIGN authored, NOT implemented — needs review before any dispatcher-stub edit
C1 (ship `.integrity/manifest-sha256.json` every release) is DONE + published in v0.18.0
(TRDD-53a00e44). This TRDD designs the remaining GROUP C exec-path. **No code is written yet** —
the dispatcher-stub is the boot-critical single point of failure (cron → stub → `dispatch.py` →
daemon), so the design (and its CARDINAL fail-open rule) is reviewed before a single stub edit.

### THE CARDINAL RULE (every sub-task obeys it): FAIL-OPEN, ALWAYS
A bricked stub = a dead janitor = the OPPOSITE of immortal. So every verification/quarantine/
rollback path degrades to "exec the latest version anyway" (today's behavior) whenever it cannot
PROVE a problem:
- manifest missing (old versions, or a release that didn't ship one) → exec anyway.
- manifest unreadable / malformed / key missing / any verify exception → exec anyway.
- verify can't find ANY clean version → exec the latest anyway (a possibly-corrupt run beats a
  dead heartbeat; emit a drift line so the human learns).
Only an EXPLICIT, completed verify that says "this specific file's hash ≠ the manifest" diverts to
a fallback version. Uncertainty NEVER blocks. This single rule is what makes a security feature on
the boot path safe.

### Current stub (scripts/dispatcher-stub.py, 64 lines, stdlib-only)
`main()`: find newest semver dir under the fixed cache root → exec `versions[-1]/scripts/dispatch.py`
on an `is_file()` check. Zero-arg, no state, no third-party imports (the "stable trusted bootstrap"
contract). C2 must PRESERVE that contract: stdlib-only, self-contained.

### C2 — verify-before-exec gate (the foundational piece)
Before execing `versions[-1]/scripts/dispatch.py`, verify THAT version's shipped manifest; on an
explicit verify-FAIL, walk DOWN the sorted version list to the newest version that verifies clean
(or has no manifest → fail-open accept), and exec that instead.

- **Verify is INLINED into the stub (stdlib sha256), NOT imported from the cache.** Importing
  `janitor_self_integrity` from `versions[-1]/scripts/lib/` to check `versions[-1]` is circular —
  the tampered version would supply its own verifier. The stub already trusts ONLY itself (it lives
  in the persistent DATA dir, outside the cache). So C2 adds a ~20-line stdlib function: read the
  version's `.integrity/manifest-sha256.json` (`{relpath: sha256hex}`), sha256 each listed file,
  compare. No HMAC needed for C2's threat (below).
- **Threat C2 catches: ACCIDENTAL corruption** — a partial/interrupted plugin download, a truncated
  file, bit-rot, a half-GC'd version dir. The plain sha256 manifest detects these and C2 falls back
  to the last-good version. **Threat C2 does NOT catch alone: a sophisticated MALICIOUS replacement**
  that rewrites both a file AND its manifest entry — defeating an unsigned manifest. That is C3's job
  (a trust anchor in the DATA dir the cache-writer can't forge). C2 + C3 together close the gap; C2
  alone is already a strict improvement (corruption resilience) at near-zero bricking risk.

### C3 — pin last-GOOD version + quarantine bad (the malicious-protection trust anchor)
Maintain `${CLAUDE_PLUGIN_DATA}/integrity/last-good.json` (DATA dir, outside the cache, written by
the DAEMON after a version runs cleanly for a soak window): `{version, manifest_hmac}` where
`manifest_hmac` is HMAC-SHA256(manifest-bytes, DATA-dir-key) — the key from
`janitor_self_integrity.load_or_create_key(DATA)`. The stub (C2) cross-checks a candidate version's
manifest HMAC against this pin: a malicious version that rewrote its own plain manifest still fails
the HMAC (it lacks the DATA-dir key). On mismatch → treat as verify-FAIL → fall back. Quarantine =
record the bad version in `integrity/quarantine.json` so C2 skips it fast on subsequent fires (and
the human is alerted). FAIL-OPEN preserved: NO pin yet (first run / fresh install) → C2 behaves as
the C2-only accidental-corruption gate (never blocks).

### C4 — bad-self-update auto-rollback
If a NEW latest version is execed but the daemon it spawns won't stay alive (crash-loops within a
short window — detectable via the daemon heartbeat staleness the watchdog already tracks), the stub
(or the daemon supervisor) marks that version quarantined (C3) and the next fire falls back to
`last-good`. Bounded: a rollback counter prevents a flap loop; on repeated failure → alert + stay on
last-good. Reuses the daemon liveness signals from GROUP A.

### TDD plan (all real, tmp cache trees; the stub is pure-stdlib so it unit-tests cleanly)
- C2: a tmp cache root with N version dirs; (a) clean latest → execs latest; (b) latest manifest
  hash mismatch → execs the next clean version; (c) latest has NO manifest → execs latest (fail-open);
  (d) malformed manifest / unreadable → execs latest (fail-open); (e) NO version clean → execs latest
  + emits a drift line (fail-open). Assert via a fake `dispatch.py` that records which version ran
  (monkeypatch `os.execv` to capture argv rather than actually exec).
- C3: pin present + candidate HMAC matches → accept; pin present + HMAC mismatch → fall back +
  quarantine; no pin → C2-only behavior. Real HMAC with a tmp DATA-dir key.
- C4: simulated crash-loop signal → quarantine + fall back to last-good; flap-guard caps attempts.

### Scope guards / non-goals
- The stub stays stdlib-only and zero-arg (the survival contract). C2's verify is inlined, ~20-30 LOC.
- Does NOT change `dispatch.py`, the daemon loop, or the heartbeat cadence.
- Does NOT make the manifest a hard gate — every uncertainty is fail-open.
- C3's daemon-side pin-writer + C4's crash-loop detector are the larger pieces; C2 is shippable
  ALONE first (accidental-corruption resilience) and is the lowest-risk increment.

### Ship sequence (smallest safe increments)
1. **C2 alone** → publish (corruption resilience, fail-open, near-zero bricking risk).
2. **C3** (daemon pin-writer + stub HMAC cross-check) → publish (malicious-replacement resistance).
3. **C4** (crash-loop rollback) → publish (bad-update self-heal).
Each its own release after its TDD + an ultracode review focused on the fail-open invariant.

## Why this exists
GROUP C is "never run a corrupted/malicious self." C1 shipped the manifest; this is the exec-path
that USES it. The whole value hinges on the fail-open cardinal rule — a self-integrity gate that can
brick the boot path would itself be the immortality bug it's meant to prevent.
