---
trdd-id: 8524H5V1
title: C24 — ledger suppression and host-load registration
column: backburner
status: tasked
created: 2026-10-01T19:45:15+0200
updated: 2026-10-05T02:06:48+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:15+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, 8524H5V1]
blocker-holds-if: not-match:READY
---

# C24 — ledger suppression and host-load registration

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C24, wave W2.

Writes (exclusive): scripts/lib/findings_ledger.py, scripts/dispatch.py
Task: Route ledger records and drift lines through is_suppressed; register host-load.py; map system-daemon-runaway to HOST-002
Verify: One heartbeat with ignore=["HOST"] in .janitor.toml prints no HOST line; without it the line prints with its code
Depends on: C1A, C1C
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:15+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:12+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on U2VUXGBP, UDE86OSZ per DSN035UN wave order
- 2026-10-01 — REQUIREMENT (wave-1 review finding 2, HIGH): the ledger and drift paths MUST NOT crash on a malformed .janitor.toml. Catch the error from suppression.is_suppressed, record ONE finding CONFIG-001 bad-janitor-toml (add the code to design/specs/issue-codes.toml via the generator flow, coordinate with C10) and fall back to "nothing suppressed". Fail-fast stays right for the CLI, wrong for a background observer. Also dedupe HOST-001 (finding 4): emit on state change or at most once per hour, not every heartbeat.
- 2026-10-01 — OWNS (wave-1 review finding 2): catch C1A's is_suppressed config error in the ledger/drift path, emit CONFIG-001 bad-janitor-toml, treat nothing as suppressed; never let one config typo stop the heartbeat. May also take C1C's HOST-001 dedupe if C1C hands it over.
- 2026-10-03T14:43:59+0200 — column → todo. blockers U2VUXGBP (C1A) and UDE86OSZ (C1C) are complete and archived Cleared blocked-by (--clear-blocker override).
2026-10-03 — RECON (reports/board/20261003_154755+0200-c24-recon.md): Registering host-load means adding a tuple to the module-level _DETECTORS list in scripts/dispatch.py (L80-508; no filename discovery). fastedit cannot edit module-level constants, so this part waits on the owner's pending one-off plain-edit decision (the same decision listed on TRDD-MMUSDJHQ).
2026-10-03 — RECON (reports/board/20261003_154755+0200-c24-recon.md): CONFIG-001 is absent from design/specs/issue-codes.toml; adding it needs the toml plus the generated files (scripts/build_issue_codes.py --write regenerates scripts/lib/issue_codes_gen.py, docs/ISSUE-CODES.md, src/rules_gen.rs). Give it NO kind field so it stays a ledger finding, not a ticket. These files are outside this card's Writes list; widen Writes before dispatch.
2026-10-03 — RECON (reports/board/20261003_154755+0200-c24-recon.md): HOST-001 dedupe already exists per episode: host-load.py uses dedupe.emit_once / emit_forget (prints once, silent until load drops below threshold). The 'state change' half of the requirement is met; only the optional hourly re-emit is missing, and it would live in host-load.py (outside Writes).
2026-10-03 — RECON (reports/board/20261003_154755+0200-c24-recon.md): HOST-002: the system-daemon-runaway line carries no code. Map it by detector name inside dispatch.py's drift-line path (_run_detector, L1160/L1179) rather than editing scripts/lib/daemon_runaway.py.
2026-10-03 — RECON (reports/board/20261003_154755+0200-c24-recon.md): The ledger has no path field; is_suppressed(code, path) can only use ref. Catch (ValueError, OSError) around is_suppressed: TOMLDecodeError and UnicodeDecodeError are ValueError subclasses. Tests (tests/test_findings_ledger.py, a dispatch drift test) are also outside Writes; widen Writes to include them.
2026-10-03 — CORRECTION (review of 3754d0b8): The fastedit limit is now VERIFIED, not inherited: on a scratch copy, `fastedit edit --after _DETECTORS`, `--replace _DETECTORS` and `batch-edit` all fail with "Symbol '_DETECTORS' not found" (exit 1); edit targets only functions, classes and methods, and has no line-anchor mode (reports/board/20261003_155026+0200-fastedit-module-level-test.md). Registration still waits on the owner's plain-edit decision.
2026-10-03 — CORRECTION (review of 3754d0b8): RECON line 3 is unverified: the episode dedupe in host-load.py was read, not run, and host-load has never fired from a heartbeat because it is unregistered. The repeating heartbeat line seen 2026-10-03 was the system-daemon-runaway ps-timeout line (HOST-002), so the dedupe question applies to HOST-002 first.
2026-10-03 — CORRECTION (review of 3754d0b8): RECON line 4: write the detector-name to code mapping inline in _run_detector, not as a new module-level dict, or it hits the same fastedit limit.
2026-10-03 — CORRECTION (review of 3754d0b8): Before dispatch: widen Writes to include design/specs/issue-codes.toml, the files build_issue_codes.py regenerates (scripts/lib/issue_codes_gen.py, docs/ISSUE-CODES.md, src/rules_gen.rs), tests/test_findings_ledger.py and a dispatch drift test; and confirm with the owner that the 'nothing suppressed' fallback on a malformed .janitor.toml is an accepted exception to the fail-fast rule.
- 2026-10-03T15:51:18+0200 — column → backburner. waits on the owner's plain-edit decision (registration in module-level _DETECTORS) and on confirming the malformed-config fallback; not workable as written

## STATE

2026-10-05, carried over from C20 (archived TRDD-BHIS99XE): rule_sev in scripts/memgrep/src/memory.rs panics on a code name that is not in the registry (rules_gen.rs, generated from design/specs/issue-codes.toml), which aborts the whole lint run. Any code this card adds or wires must be registered first and written as a plain quoted literal, and needs a CLI test that triggers it. Second carry-over: CONFIG-001 is NOT in the registry (found by the C21 worker on 2026-10-05); C21 prints it on stderr. If this card needs CONFIG-001 as a finding, register it in issue-codes.toml and regenerate first.
