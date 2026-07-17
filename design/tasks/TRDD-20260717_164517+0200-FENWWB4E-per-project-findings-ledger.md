---
trdd-id: FENWWB4E
title: Per-project findings ledger — the traceable per-project index + concise session-start surfacing
column: design
created: 2026-07-17T16:45:17+0200
updated: 2026-07-17T16:45:17+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
severity: high
related-trdd: [X92VBFNF, 4649ZLE0, PZLVT2RN, CGYMUKO6]
blocked-by: []
coordination-issue: janitor#100
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-17

**What this is.** The genuinely NEW piece of the two-harness redesign (approved plan
`~/.claude/plans/staged-kindling-lynx.md`, Phase 4 implements it after #100 ratification):
today findings become tickets (`.janitor/state/tickets/`, T-ids, archive-never-delete),
proposal TRDDs, or global-state JSON — but NOTHING accumulates per-project for the NEXT
session to read, and `on-session-start.py` reads no findings inbox at all (verified by
exploration 2026-07-17). Owner requirements (verbatim intent): findings about a project
whose Claude is not running must be *"traceable, recorded"*, the human must be able to
*"easily reference to it when speaking with the claude of the correspondent project when
it is restarted"*, and the accumulated session-start reports *"must be as concise as
possible to avoid burning the context before even starting to work"*.

**Design (authoritative copy in `design/ARCHITECTURE.md` §4 — this TRDD implements it):**
- `<project>/.janitor/state/findings-ledger.ndjsonl` — append-only INDEX, one sanitized
  JSON line ≤ ~200 chars per finding event:
  `{"ts","sev","code","src","ref":"T-…|TRDD-…|-","msg"}`. Bodies live in the ticket /
  proposal TRDD named by `ref` — the ledger is never a payload. Structural trim caps
  (reuse the `token_meter.trim_log` pattern). Gitignored (lives under `.janitor/`).
- `lib/findings_ledger.py::record()` — the ONE choke point, three sinks: (1) the AFFECTED
  project's ledger (the daemon writes X's findings into X's own state dir — the
  per-project mailbox; per-session detectors write their own project's); (2) the firing
  session's drift line (own project only — X92VBFNF); (3) the TRDD-4649ZLE0 human push
  when the affected project has no live session (`fleet_scan.gather_fleet` liveness).
  Wire `issue_catalog.raise_issue` through it so every raised issue lands in the ledger
  with its ticket/proposal ref for free.
- SessionStart reader: `findings-ledger.cursor` offset file; `on-session-start.py`
  injects ONLY unread entries, newest-first, cap ~10 lines + one fold line
  ("…N older — `/janitor-findings` to browse"), ≤ ~1 KB, then advances the cursor.
- `/janitor-findings` command: list / show `<ref>` (resolves the ticket/TRDD body) / ack.

**Isolation contract (tests must prove):** a ledger only ever contains its OWN project's
findings; a daemon write for repo B leaves repo A's ledger AND a live repo-A session's
stdout untouched; cursor semantics (no re-injection, no loss); cap/fold correctness;
sanitization of attacker-controlled `msg` content (`state.sanitize_for_drift_line`).

**Sequencing:** implement in plan Phase 4, AFTER the #100 ratification rounds (Phases 2–3)
— the ledger line shape is the dashboard feed contract ai-maestro consumes, so the shape
must be ratified before code freezes it. Phase 4 also reroutes `window-burn-rate` through
`record()` (token alarms only in the culprit's own sessions — owner token-quietness
directive).

**NEXT ACTION:** wait for #100 round-1 feedback on `design/ARCHITECTURE.md` §4 (posted
with the doc); fold refinements here; on ratification → column `todo` and implement.

## Notes and lessons learned

[^1]: [id:ATOM-LEDG-IDX1, status:valid, keywords:"findings lost between sessions no inbox session start context budget concise accumulated reports", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT surface accumulated findings by injecting report BODIES at session start,
  BECAUSE the context budget burns before work begins — the owner's explicit constraint.
  DO inject a capped index of one-line refs (ticket/TRDD ids) and let the Claude pull
  bodies on demand.
