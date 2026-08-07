# Changelog

All notable changes to this project will be documented in this file.

## [2.5.0] — 2026-08-07

### Bug Fixes

- **dispatch:** Bound the heartbeat's presence wait to 9s, not the 120s default (24c2567)
- **daemon:** Stable TCC identity + never evict own version-less daemon + quarantine symmetry (TRDD-DB1P25S4) (75332ba)
- **terminal_trigger:** The verified injector could never send a command WITH ARGUMENTS; add send_verified + ESC-only builder (TRDD-QE390SJA) (dd72291)
- **terminal_trigger:** A selection-menu row is no longer read as the input field (janitor#222) (70afff5)
- **token-burn:** A model-fallback verdict requires a PROVEN-FRESH snapshot (janitor#222) (b08c2d6)
- **rotator:** Stop rotating onto an account whose model window is already spent (TRDD-QE390SJA) (674fe78)
- **agent-context-integrity:** Never aim the auto-fixer at locally-authored safety docs (janitor#167) (30b666a)
- **idle-clear:** Use the ratified injector — the lever was structurally dead on iTerm (TRDD-5C42VCUX) (71e65e9)
- **memory:** Lint wikimem pages AT WRITE TIME — the enforcement never existed (c7089dd)
- **detectors:** Make claimed-chore-stale executable in git (mode 100644 -> 100755) (5ca35d8)
- **daemon:** The crash-loop breaker no longer quarantines a healthy version for orderly restarts (janitor#216, #217) (747c202)
- **detectors:** Narrow three noisy detectors without blinding any of them (janitor#189, #214, #215) (aa24709)
- **memory:** Flow-style frontmatter made harvest treat every curated overview as RAW forever (janitor#212, #210, #201) (4bbe7b3)
- **clear:** Scope CLAUDE_PROJECT_DIR to the spawned child, and redact private paths from two TRDDs (3a224c8)

### Documentation

- **board:** Close FQXBURNR and restore the provenance link it lost (c4e0c34)
- **board:** REOPEN dfc0959a and 5ZVS1DDP — I closed two cards that said they were not done (8771685)
- **TRDD-5ZVS1DDP:** The silent safety gap is CLOSED — deployment chain verified link by link (0cdcfb6)
- **rotator:** OWNER supersedes "the login half must never be automated" (5ac2a5a)
- **TRDD-dfc0959a:** Unbrowse cannot select Chrome profiles — the folder swap is part of every replay (75ebfa7)
- **TRDD-dfc0959a:** The swap folders are unbrowse's OWN clones, not Chrome's profile dirs (ffc90dd)
- **board:** AWXK0RFT resolved as the owner predicted; KQ9WM4TZ unblocked with its stopgap now running (feb92fd)
- Add TRDD-DB1P25S4 — run the daemon under the signed python3.12 so the iTerm TCC grant applies (c4442e6)
- **TRDD-DB1P25S4:** Owner correction — the granted client is uv's MANAGED cpython; the mechanism is PATH STABILITY (1b23d6c)
- **TRDD-DB1P25S4:** The grant is PROVEN and the hot-apply is not durable — stop-rule + the 3-part code fix (c4546b3)
- **TRDD-DB1P25S4:** STATE — 3-part code fix landed in 75332ba0; checklist updated, end-to-end observation + publish remain (07d1663)
- **fleet_inject:** Pin the ai-maestro CLI channel's reachability contract (janitor#218) (d449b5a)
- **TRDD-KQ9WM4TZ:** Testing evidence — one gate-clean dark-window beat proven (stamp 18:33:45, mid eviction-loop); quiet gates are artifact-free so the 300s-window criterion is unobservable now that DB1P25S4 fixed the daemon (d6d2333)
- **TRDD-KQ9WM4TZ:** Testing -> ai_review — breadcrumb shipped (ac419694), dark-window evidence accepted; review focus recorded (055eb24)
- **TRDD-KQ9WM4TZ:** Ai_review PASSED -> human_review — dedupe-vs-pacing, no-peers log line (rejected as duplicate), and the cross-session write race each reviewed with verdicts recorded (2cc0434)
- **repomap:** Refresh the fenced project map — picks up _managed_python_path, _is_own_stable_daemon, record_outcome from today's daemon/detector work (a16c687)
- Add TRDD-5C42VCUX, TRDD-PXP08ZQC, TRDD-UA4FAX67 — the owner's 2026-08-06 janitor failure report as three atomic cards (idle auto-clear never engages; external zero-turn handoff via llm-ext; post-rotation ESC unblock) (ebe5baf)
- Add TRDD-50V256RH, TRDD-AR9IUGIJ, TRDD-6CRC9SQQ — owner failure report items 5-7 (self-update convergence; eliminate re-arm; server-delegation alignment contract) (c17db60)
- Add TRDD-QE390SJA — model-scoped window exhaustion must fall back to another model, not rotate the account (janitor#222; owner typed /model opus by hand today) (0331753)
- **repomap:** Refresh the fenced project map — picks up send_verified, build_esc_only_steps, model_fallback_verdict from the QE390SJA work (f9280a2)
- **TRDD-9MQ25PNH:** Testing -> ai_review — the 05:22 LOCAL dispatch verified BOTH halves in production (read-back consulted; content-hash re-arm fired on a real 08-05 edit, stored 4062c90a vs current 1296d0a5), agent re-judged and re-recorded (3c45896)
- **TRDD-QE390SJA:** Correct the derived task — the scoped-window eviction was the SERVER's rotator, and the janitor's gap is the MIRROR of it (04b8cf1)
- **memory:** Capture the daemon process-IDENTITY + restart-gate lessons (TRDD-DB1P25S4, janitor#211/#219/#216) (27ace42)
- **TRDD-QE390SJA:** Todo -> testing — both halves code-complete; the one open box is the owner-watched live switch (674fe785 closed the rotator mirror gap) (038f1bb)
- **TRDD-UA4FAX67:** Todo -> testing — rotation now triggers the wake (f3f664de); wake-pass default decided (periodic stays dormant, a rotation overrides) (27980a4)
- **TRDD-PXP08ZQC:** Phases 1-2 done — gate + watcher + template handoff; daemon wiring is the one open box (c02906a)
- **TRDD-PXP08ZQC:** Record the llm-ext composer as tried-and-rejected-on-evidence (c8a0f36)
- **memory:** Capture the external zero-turn clear + correct a rationale it outdated (56457ba)
- **TRDD-AR9IUGIJ:** Spike decided — A + C; B was already shipped and cannot do what the card asked (15b6e5c)
- **TRDD-50V256RH:** Root cause found — the reload stamp is a side-effect of a task the daemon SKIPS (0c59765)
- **TRDD-50V256RH:** WITHDRAW my root cause — I inferred it from an API instead of reading the log (32c28eb)
- **TRDD-50V256RH:** Retire the NEXT ACTION written for the withdrawn cause (3e7ff34)
- **TRDD-50V256RH:** Root cause established — /reload-plugins does not re-point live SKILLS (89fde6b)
- **TRDD-50V256RH:** NEXT ACTION is now an owner decision, not a code step (b38f1df)
- **memory:** Capture live-skill staleness — /reload-plugins does not re-point loaded skills (be5186b)
- **TRDD-6CRC9SQQ:** A confirmed contradiction blocks item 1 — the yield path may never have run (f985203)
- **TRDD-6CRC9SQQ:** The 'zero yield lines' evidence is unsafe — log provenance never established (9f7830b)
- **CLAUDE.md:** Refresh the project map + wikimem index (drift I introduced) (e9a93bf)
- **TRDD-6CRC9SQQ:** Record the lsof dead end so it is not repeated (de01185)
- **TRDD-6CRC9SQQ:** The "contradiction" was a wrong log file — daemon DOES yield; item 1 unblocked (1ebdfe6)
- **memory:** Where the global daemon logs, what [s:] means, and why an empty grep proved nothing (eae64fb)
- **TRDD-6CRC9SQQ:** Item 1 shipped (1e803e47) — acceptance box 2 ticked, next action is the un-yield decision (0af7d52)
- **TRDD-6CRC9SQQ:** Un-yield decision recorded (NO — alarm only) + the #221 replay argument (c777d12)
- **TRDD-7PYTX4E9:** Planned -> complete — the column lied for 28 days about finished work (82fbdbb)
- **TRDD-CI6ZTNB9:** Record a withdrawn "live reproduction" — the fix is already shipped (a685cca)
- **memory:** The #212 abstain-burn root cause — a misparsed flow-style frontmatter, not a missing gate (b438b23)
- **TRDD-QE390SJA:** Rewrap a continuation line so markdownlint stops reading it as a list marker (cf3cc34)

### Features

- **peer-freeze-recovery:** Trace every beat outcome, quiet gates included (TRDD-KQ9WM4TZ) (ac41969)
- **token-burn:** Model_fallback_verdict — the pure gate for switching model instead of rotating (TRDD-QE390SJA, janitor#222) (d7d8e9c)
- **terminal_trigger:** Three-state model-switch confirmation (TRDD-QE390SJA, janitor#222) (491a2c3)
- **model-fallback:** The pure planner — decide whether to type /model <target> (TRDD-QE390SJA, janitor#222) (251056e)
- **model-fallback:** The detector — wire the gate to the typist, dark by default (TRDD-QE390SJA, janitor#222) (ab00a40)
- **fleet:** A successful rotation now unblocks the panes it just fixed (TRDD-UA4FAX67) (f3f664d)
- **external-clear:** The zero-model-turn clear gate + template handoff (TRDD-PXP08ZQC) (def783f)
- **external-clear:** The watcher — decide, compose and fire without a model turn (TRDD-PXP08ZQC) (95a5bed)
- **6CRC9SQQ:** Watch the chores the SERVER claimed — and repair the seam 71e65e91 broke (1e803e4)

### Miscellaneous Tasks

- Adopt CPV canon where divergence was accidental; declare it where it is deliberate (eaaaabd)

### Revert

- **external-clear:** Drop the llm-ext handoff composer — the template IS the answer (TRDD-PXP08ZQC) (07e8d98)

### Testing

- **idle-clear:** Guards that bite on the iTerm-blind injector (TRDD-5C42VCUX) (99b9e82)

### Experiment

- **external-clear:** Llm-ext handoff composer + its real measurement (TRDD-PXP08ZQC) (73a426c)
---
*Generated by [git-cliff](https://git-cliff.org)*
