---
trdd-id: FENWWB4E
title: Per-project findings ledger — the traceable per-project index + concise session-start surfacing
column: published
created: 2026-07-17T16:45:17+0200
updated: 2026-07-17T19:55:00+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
severity: high
related-trdd: [X92VBFNF, 4649ZLE0, PZLVT2RN, CGYMUKO6, N9YAH5E7]
blocked-by: []
coordination-issue: janitor#100
implementation-commits: [831beb7, 1708bf0, db7cea7, db99022, b8da784]
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

**Round-1 outcome (2026-07-17, folded):** ai-maestro **ACCEPTED the ledger feed contract
as written** (their §6.5 reply): the server tails ONLY its own registry agents'
`<workdir>/.janitor/state/findings-ledger.ndjsonl` (gated through
`checkAuthorizedAgentWorkdir`), renders rolling log + severity toasts, and resolves a
clicked `ref` body read-only from the affected project's own store. The line shape
`{ts,sev,code,src,ref,msg}` (≤200 chars, sanitized) is therefore the FROZEN dashboard
feed contract from rev 2 on — no shape changes after ratification without a new revision.

**RATIFIED (2026-07-17): `design/ARCHITECTURE.md` rev 3 is FINAL** — both sides posted
`RATIFIED rev 3` on #100. The ledger line shape `{ts,sev,code,src,ref,msg}` is the
frozen dashboard feed contract; the server tails only its own registry agents' ledgers.

**IMPLEMENTED (plan Phase 4, 2026-07-17 — all landed on main, full suite 13288 green):**
- `831beb7` — `lib/findings_ledger.py`: `record()` 3-sink choke point (ledger append with
  `token_meter.trim_log` caps; own-session drift line via the X92VBFNF gate; the
  4649ZLE0 `notify` seam — inert until Phase 5), byte-offset cursor with ts fallback
  (trim-safe), `surface_block()` cap 10 + fold ≤~1 KB, whitespace-collapsing field
  cleaner (the base sanitizer keeps `\n` by design). 11 tests.
- `1708bf0` — `issue_catalog.raise_issue` wired: one ledger line per finding BIRTH
  (first_seen; the ticket/proposal dedupe is the birth signal), ref = ticket id /
  `TRDD-<uid>`. 3 tests.
- `db7cea7` — SessionStart inbox injection (before the global-stop return — the mailbox
  outlives the heartbeat) + `/janitor-findings` command + `scripts/findings_cli.py`
  (list / show `<T-…|TRDD-…>` / ack), smoke-tested end-to-end.
- `db99022` — `window-burn-rate` token-quietness: alarms ONLY in the culprit project's
  own sessions (suppression logged, not printed); unattributable trips silent
  everywhere; surfaced alarms indexed (`WINDOW-BURN`). Unrelated-session zero-stdout
  proven by test.
- `b8da784` — context-advisory default 60→80 (one runway band below the 85% enforcement;
  the harness's own near-full warning covers the mid band).

**NEXT ACTION:** human review + ships in v0.51.0 with Phase 5 (TRDD-4649ZLE0's notify.py
plugs into the `record()` seam; the daemon-side no-live-session burn/finding push
belongs there). Doc pass (CLAUDE.md window-burn-rate prose + repomap regen) rides the
v0.51.0 release train.

## Notes and lessons learned

[^1]: [id:ATOM-LEDG-IDX1, status:valid, keywords:"findings lost between sessions no inbox session start context budget concise accumulated reports", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT surface accumulated findings by injecting report BODIES at session start,
  BECAUSE the context budget burns before work begins — the owner's explicit constraint.
  DO inject a capped index of one-line refs (ticket/TRDD ids) and let the Claude pull
  bodies on demand.
