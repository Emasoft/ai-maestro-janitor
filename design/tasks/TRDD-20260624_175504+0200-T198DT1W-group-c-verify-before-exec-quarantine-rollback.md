---
trdd-id: T198DT1W
title: Immortal janitor GROUP C — C2 verify-before-exec gate + C3 pin-good/quarantine-bad + C4 bad-self-update auto-rollback
column: dev
created: 2026-06-24T17:55:04+0200
updated: 2026-06-24T18:20:09+0200
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

### Status: C2 IMPLEMENTED + TDD-GREEN + committed LOCALLY (NOT published) — C3/C4 still design-only
- **C2 = DONE in source** (2026-06-24 18:20). `scripts/dispatcher-stub.py` now has `_verify_version()`
  (inlined stdlib hashlib+json) and a verify-before-exec ladder in `main()`. 14 new tests in
  `tests/test_dispatcher_stub.py` cover the whole fail-open ladder (clean-latest→latest;
  corrupt-latest→older-clean; missing-listed-file→fall-back; no/malformed/wrong-shape/empty-hash
  manifest→fail-open; all-corrupt→newest-runnable; missing-dispatch→older; no-versions/no-runnable
  →SystemExit; + 3 direct `_verify_version` units). **14 passed, ruff + pyright clean.**
- **PROVEN on the REAL cache**: `_verify_version` returns `verified` for the live 0.17.2 + 0.18.0
  (manifest-shipping) trees and `no-manifest` (fail-open) for every older version — ZERO
  false-rejection, so the real heartbeat execs 0.18.0 exactly as before, now gated.
- **NOT YET ACTIVE**: committed locally only. C2 does not run until the stub is RE-COPIED into
  `${CLAUDE_PLUGIN_DATA}` by a `/janitor-arm` re-arm (the stub is NOT auto-rolling — see the rollout
  caveat below). Per the bricking-risk gate, the USER reviews this commit before any publish + re-arm.
- **DESIGN CORRECTION (load-bearing) — the manifest is WRAPPED, not flat.** This TRDD's C2 section
  below originally assumed the manifest is `{relpath: sha256hex}`. The REAL shipped shape (verified
  against the live 0.18.0 file + `janitor_self_integrity.write_manifest`) is
  `{"version": 1, "files": {relpath: sha256hex}}` — `_verify_version` reads `obj["files"]`. An
  empty expected hash (compute_manifest records `""` for a file that vanished at build time) is
  treated as fail-open-skip, not a mismatch.
- **SCOPE HONESTY — what C2 actually gates.** The manifest's hashed set is the plugin's INSTRUCTION
  SURFACE only (README/CLAUDE.md/skills/commands/rules — `DEFAULT_MANIFEST_GLOBS`), NOT `dispatch.py`
  or the lib code. So C2 is a clean-download canary + instruction-tamper guard: a partial download
  truncates/loses some of those 59 files → C2 detects it and falls back; a corrupt `dispatch.py`
  with an intact instruction surface is NOT caught by C2 alone. Closing that gap = either C3's HMAC
  trust anchor or a separate manifest-scope expansion (out of scope here; noted, not silently
  dropped). C2-alone remains a strict corruption-resilience win at near-zero bricking risk.
- **C3 HAND-OFF NOTE (channel nuance found in C2 self-review)**: C2's fall-back/all-corrupt warning
  is written to **stderr**, deliberately NOT stdout — the heartbeat surfaces the stub's *stdout*
  verbatim (and parses it for bare `[janitor-*]` markers), so a warning on stdout would risk
  polluting that marker-parsed stream and could prepend dispatch.py's output. The price: a
  stderr-only warning may not reach the human via the heartbeat. That is acceptable for C2-alone
  (its job is availability — don't brick); the PROPER human-facing alert on a detected-bad version
  is **C3/C4's** responsibility via the daemon (quarantine.json + a PushNotification / drift line),
  exactly as the C3 design below already states. Do not move C2's warning to stdout to "fix" this.
- **NEXT**: (1) USER reviews the stub commit (9773ff3); (2) publish C2 alone (Tier-2 release step —
  MANAGER/USER gate) → then re-arm to activate; (3) C3 (daemon pin-writer + stub HMAC cross-check);
  (4) C4 (crash-loop rollback). C3/C4 below are still design-only.

C1 (ship `.integrity/manifest-sha256.json` every release) is DONE + published in v0.18.0
(TRDD-53a00e44). The dispatcher-stub is the boot-critical single point of failure (cron → stub →
`dispatch.py` → daemon), so every C2 path obeys the CARDINAL fail-open rule below.

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
  and emits a drift line (fail-open). Assert via a fake `dispatch.py` that records which version ran
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

### Rollout caveat (LOAD-BEARING — the stub is NOT auto-rolling)
Unlike `dispatch.py` (which the stub re-resolves to the latest cache EACH fire), the
**dispatcher-stub itself is installed ONCE into `${CLAUDE_PLUGIN_DATA}` by `/janitor-arm` and does
NOT auto-update** — by design (it is the stable trusted bootstrap). So a C2/C3/C4 change to the stub
source does NOT go live until the user RE-ARMS (`/janitor-arm` re-copies the stub) or the 7-day
`[janitor-renew]` auto-re-arm fires. Implications: (1) the release notes MUST tell the user to
re-arm to activate it sooner than the 7-day boundary. (2) A BUGGY stub shipped this way is NOT
auto-rolled-back by a later publish — the user is stuck on the bad stub until they re-arm to a fixed
one, so a stub bug is STICKIER than a normal-code bug. This doubles down on the fail-open imperative.
(3) Why the gate must live in the stub anyway: `dispatch.py` lives INSIDE the versioned cache being
verified (circular trust — a tampered version supplies its own verifier), so the verify-before-exec
anchor genuinely belongs in the trusted, non-auto-rolling stub. The stickiness is the price of the
trust anchor; mitigate with maximal fail-open + a TINY, audited, rarely-changed inlined verify.

### Ship sequence (smallest safe increments)
1. **C2 alone** → publish (corruption resilience, fail-open, near-zero bricking risk).
2. **C3** (daemon pin-writer + stub HMAC cross-check) → publish (malicious-replacement resistance).
3. **C4** (crash-loop rollback) → publish (bad-update self-heal).
Each its own release after its TDD + an ultracode review focused on the fail-open invariant.

## Why this exists
GROUP C is "never run a corrupted/malicious self." C1 shipped the manifest; this is the exec-path
that USES it. The whole value hinges on the fail-open cardinal rule — a self-integrity gate that can
brick the boot path would itself be the immortality bug it's meant to prevent.
