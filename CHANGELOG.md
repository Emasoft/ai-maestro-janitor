# Changelog

All notable changes to this project will be documented in this file.

## [0.61.0] — 2026-07-26

### Bug Fixes

- **rules:** Keep markdown-memory-recall under the shipped-rule floor cap (d53b15c)
- **memgrep:** Use repeat_n for inline-code masking (clippy manual_repeat_n, Rust 1.97) (7522c71)
- **spec:** Pymarkdown-clean wikimem-memgrep-spec (MD007/MD031) + repair a mis-flagged prose '+' (914d4d1)
- **publish:** Exclude design/specs/ from the Step-3 pymarkdown scope (9420a42)
- **trdd:** Unwrap 8 prose lines whose leading '+' was read as a list bullet (c2af384)
- **agent:** Reword the repair-agent's attack-example list so it stops tripping prompt_injection scanners (791fbc2)
- **trdd:** Rejoin a code span wrapped across 3 lines that parsed as a bogus H1 (d68c7c6)
- **mypy:** Point mypy at scripts/ so 'from lib import X' resolves (kills 19 false errors) (125a94e)
- **types:** Clear mypy type debt + actionlint SC2129 + shfmt (v3.11 ci-preflight) (cf2fc1c)
- **bandit:** Declare the 11 detector SHA1 digests non-security (B324 -> usedforsecurity=False) (337d103)
- **bandit:** Justified per-site # nosec for 25 verified false-positives -> bandit -ll = 0 (759d3e8)
- **jscpd:** Scope out the deliberate uniform catalog + design docs -> under 5% threshold (acdf2c1)
- **ci,release:** Drop the stale scanner-finding narrative from the pin comments (407b0f1)
- **memory:** Accept a str scope_root; stop the bootstrap doc from faking a file reference (6f5dea2)
- **mypy:** Silence two optional-import type errors that blocked the publish gate (11df106)
- **daemon:** Make the bulk-lane recheck beat env-tunable like every sibling cadence (3d778ff)
- **daemon:** Give the bulk lane a fair, starvation-free winner (1c8e773)
- **publish:** Let the test gate run to completion instead of timing out at 300s (948ca7f)
- **repomap:** Stop a torn read from destroying the human CLAUDE.md narrative (7639afb)

### Documentation

- **memory:** Capture the arm-nudge escalation loop as a PROJECT wiki page (fe49fa0)
- **memory:** Record the control-dir test-isolation and publish write-guard traps (TRDD-QK7M2B0X) (40e4188)
- **TRDD-QK7M2B0X:** Record 78879d4 as the phase-B step-1 implementation commit (b3cadff)
- **map:** Refresh the fenced CLAUDE.md project map (68a8c39)
- **rules:** Name the TRDD overlay by its pinned filename (ai-maestro#83) (6417b47)
- **memory:** Capture the fleet control plane and the 3-pillars rules ownership (e02debf)
- Add TRDD-E8LNOXLQ — merge-protocol.md contradicts memory_txn_cli.py (df989f0)
- Add TRDD-4ZTNMQL3/DOJ2LE1G/WN7M829Y/VJCMZ2OP — wikimem atom-authoring correctness design set (5cefced)
- **TRDD:** Record impl commits f469f07/d9ef41f + binary-live state (DOJ2LE1G, VJCMZ2OP) (0058cdb)
- **rules:** Add the AUTHORING-integrity contract to markdown-memory-recall (TRDD-4ZTNMQL3) (ebd7445)
- **TRDD-4ZTNMQL3:** Rule + gate shipped (ebd7445, 33a1f7f) → column testing (78ce538)
- **TRDD-WN7M829Y:** Unblock retroactive repair; scope it as deliberate editorial work (94da87a)
- Add 4 proposal TRDDs — janitor heartbeat-cost improvements D1/D2/D4/D5 (068b5e9)
- Revise D1/D2/D4/D5 proposals against their must-fix lists (Stage A) (2503128)
- Promote TRDD-B0SABNP8 proposal -> complete (D4 implemented in 959a1e2) (373b622)
- **TRDD-B0SABNP8:** Apply the promotion content git mv left unstaged (80fcc39)
- **spec:** Add the wikimem + memgrep conformance SPEC (design/specs/) (714d021)
- **spec:** Make the wikimem+memgrep SPEC complete + add the anti-deletion guardrail (v1.1.0) (bf61cd3)
- Promote TRDD-X07E7HTN proposal -> complete (D1 v1 shipped in 3c18208) (d350058)
- Promote TRDD-ZCODD6YS proposal -> complete (D2 shipped in efb2781) (396337f)
- Promote TRDD-82JRK0CY proposal -> complete (D5 shipped in 0ae6256) (21c61d9)
- Add TRDD-GZXTSJSR — proactive all-accounts OAuth login nudge (real notification, capture before crisis) (42a04f6)
- Add proposal TRDD-739N4CUF — close the janitor↔server OAuth-rotation ownership gap (verified live root cause) (7a7cdcd)
- Add proposal TRDD-D1UKVNUY — cache-thrash detector + marathon-session root cause (token-burn incident) (63ab43c)
- **daemon:** Clarify server-alive binary-exit supersedes the per-chore yield (c555deb)
- **ci:** Record the exhaustive CPV pin bisect (v2.153.2 … v3.5.0) (e976f05)
- Add TRDD-6WM4BFKF — gitignore-coverage chore (tracked == shipped) (21435d0)
- Add TRDD-WKTD5JTC — daemon injects ESC to break the CC 429-retry-watchdog wedge (2af7243)
- **TRDD-WKTD5JTC:** Split retry-wedge ESC recovery across both backends + server contract (ARCHITECTURE §8 rev 6) (3e18bf7)
- **TRDD-WKTD5JTC:** Alt-screen correction — detect the RENDERED frame, not raw PTY (ARCHITECTURE §8 rev 7) (1ded32f)
- **TRDD-WKTD5JTC:** Pin the server detection surface to the dashboard's xterm.js (§8.1) (43b751f)
- **TRDD-WKTD5JTC:** §8.1 — read buffer directly (not addon-search), API source-verified (7213ebe)
- **TRDD-WKTD5JTC:** Wedge is cause-agnostic (session-limit too) + ESC-before-rotation + onWriteParsed (d97ed69)
- **TRDD-WKTD5JTC:** Statusline % is a lagging indicator — never a detection gate (3bcf176)
- **TRDD-WKTD5JTC:** Fold advisor (Fable 5) review — approve-with-changes (7a79494)
- **TRDD-WKTD5JTC:** Record server notification via ai-maestro#90 (63cc0a3)
- **memory:** MEMORY.md is the harness's — the janitor maintains ONE bridge line (d11e516)
- **memgrep:** State the coexistence memory model in --help; add overview exit-code regression test (c89daa3)

### Features

- **control-plane:** Publish the three coordination locks to the fixed control dir (TRDD-QK7M2B0X) (78879d4)
- **memgrep:** Add-lesson --supersedes + four authoring-integrity lint checks (TRDD-DOJ2LE1G) (f469f07)
- **memgrep:** Add the migrate verb — move an atom + baggage between pages (TRDD-VJCMZ2OP) (d9ef41f)
- **memory-txn:** Delta authoring-integrity gate on commit (TRDD-4ZTNMQL3) (33a1f7f)
- **harness-selftest:** SessionStart CC-drift self-test (TRDD-B0SABNP8) (959a1e2)
- **daemon-wake:** The daemon owns the rate-limit resume wake, v1 (TRDD-X07E7HTN) (3c18208)
- **security:** Guard against dependency CLIs that write agent-context files without consent (janitor#110) (c71f8d1)
- **self-budget:** The janitor meters + self-throttles its OWN heartbeat cost (TRDD-ZCODD6YS) (efb2781)
- **heartbeat:** Funnel dispatch markers through one auto-flushed decision helper (TRDD-82JRK0CY) (0ae6256)
- **memory:** Implement the MEMORY.md bridge line — verify + re-add, append-only (b44c4cd)

### Miscellaneous Tasks

- **config:** Register the agent_generator_guard_enabled knob in plugin.json (janitor#110) (61a60a6)

### Revert

- **spec:** Undo the pymarkdown auto-format of the wikimem spec (0b035e7)

### Styling

- **memgrep:** Shfmt stage.sh so the CI-parity preflight passes (d1eb81c)
- **oauth_rotator:** Shfmt the remaining two shell scripts (0c074db)

### Testing

- **daemon:** Pin the chore-ownership signal so a live ai-maestro server can't break the suite (c8a7392)

### Build

- **pipeline:** Land the v3.11.0 canonical-pipeline migration (60e1b6b)
- **pipeline:** Upgrade canonical pipeline to CPV v3.16.0 (all three pin sites) (c7abd34)
- **pipeline:** Bump CPV pin v3.16.0 -> v3.19.0 (all three sites) — clears the last --strict finding (71bbfa5)
---
*Generated by [git-cliff](https://git-cliff.org)*
