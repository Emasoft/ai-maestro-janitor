---
trdd-id: a4e41e89-e995-4309-bd15-8e247a34b960
title: Heartbeat token meter + push automation into scripts to minimize per-fire agent tokens
column: dev
created: 2026-06-14T19:42:55+0200
updated: 2026-06-15T12:40:17+0200
current-owner: ai-maestro-janitor
task-type: feature
priority: 2
severity: MEDIUM
effort: L
labels: [heartbeat, tokens, observability, automation, heuristics]
release-via: publish
test-requirements: [unit]
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/23"]
---

# Heartbeat token meter + push automation into scripts to minimize per-fire agent tokens

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-06-15

USER directive (2026-06-14): keep the **5-min** heartbeat; **automate every
possible procedure** so that even when an agent is required, scripts do the
automatable work and the agent acts ONLY for the intelligent decision in
between (heuristics until control must return to the agent); **minimize what
agents read/write** by preprocessing tool input/output; and **log every token
spent per heartbeat** + a command to display the log (so spikes / high averages
are visible).

Two parts, built in order (you can't optimize what you can't measure):

- **Phase 1 — THE METER. ✅ COMPLETE + SHIPPED + LIVE-VERIFIED.** Per-heartbeat
  token accounting (`scripts/lib/token_meter.py`), a separate Stop hook
  (`scripts/hooks/on-stop-token-meter.py`, isolated from the survival-critical
  on-stop hooks), and the `/janitor-token-report` command
  (`scripts/token_report.py`). Shipped across **v0.8.8** (build) → **v0.8.9**
  (the load-bearing fix: tool_result messages are `type:user`, so the turn-
  boundary walk-back must step over them via `_is_tool_result`, else every
  multi-step heartbeat read as a non-heartbeat with zero usage) → **v0.8.10**
  (the real meter, after live-reload caught the empty log). Tests: 10 in
  `tests/test_token_meter.py` (incl. `test_multistep_heartbeat_turn_with_tool_results`).
  **Measured live (2026-06-14): a SILENT heartbeat = ~162 output / ~160 input
  tokens** (the ~870k `cache_read` is the cheap 0.1× context re-read).
- **Phase 2+ — AUTOMATION. ⏸ DECISION PENDING (measure-first says: NOT
  WARRANTED).** The meter's own data shows the detectors are ALREADY scripts —
  a silent fire is just the dispatcher Bash call. **The cost driver is the
  AGENT'S RESPONSE LENGTH, not detection** (the sampled spikes were long status
  messages, 3000–5400 output tokens; the spike alarm correctly flagged a 5394-
  token one). So "push the detectors into scripts to save tokens" yields ≈0 —
  they're already scripts. Two optimizations were explored and REJECTED on the
  data: (a) auto-regenerating the CLAUDE.md project map in the heartbeat would
  INCREASE cost (CLAUDE.md is in the cached prompt prefix → a mid-session
  rewrite busts the whole context cache; this is why `project-map-drift` nudges
  instead of writing); (b) background agents are NOT free (`claude --bg` bills
  the same quota — only `--exec`/the daemon invoke no model). The only real
  lever left is behavioral (keep heartbeat replies terse/silent), not a code
  change. **NEXT ACTION (user's call):** either CLOSE Phase 2 as "not warranted
  on the data" (recommended — `column: dev` → `complete`) OR build the behavioral
  terse-reply guardrail. No autonomous code change pending; the meter is the
  lasting win. See LOCAL memory `reference_heartbeat_token_baseline.md`.

## Verified feasibility (2026-06-14)

- The session transcript JSONL records a `usage` object on every `assistant`
  message: `input_tokens`, `output_tokens`, `cache_read_input_tokens`,
  `cache_creation_input_tokens` (+ server_tool_use, iterations). 3671 in the
  current session.
- A **heartbeat turn** is reliably identified: its triggering `type:user`
  message's content STARTS WITH `[janitor-heartbeat]` (542 found). `promptSource`
  is NOT unique (other system prompts share `system`), so match on content.
- The transcript is large (37 MB / 17k lines) → the meter MUST read only the
  current turn's TAIL (read backwards from EOF until the triggering user
  message), never the whole file.
- The **Stop** hook (and **StopFailure** for rate-limited fires) receives
  `transcript_path` on stdin and fires at turn end, when usage is fully written.

## Phase 1 design — the meter (≤5 files, additive, survival-safe)

DO NOT modify the survival-critical `on-stop-failure.py` rate-limit logic. The
meter is a SEPARATE, additive hook so a meter bug can never break resume.

1. `scripts/lib/token_meter.py` (PURE, testable — no I/O beyond a passed path):
   - `tail_turn_usage(transcript_path) -> TurnUsage | None`: read the JSONL tail
     backwards, collect `assistant` `message.usage` until the triggering
     `type:user` message; return None if that user message does not start with
     `[janitor-heartbeat]` (not a heartbeat turn → log nothing).
   - `TurnUsage`: input, output, cache_read, cache_creation, billable_total
     (define billable = input + output + cache_creation; cache_read shown
     separately — it is the cheap re-read), heartbeat_id (parse from the cron
     prompt's `[janitor-heartbeat]` block if present), assistant_msg_count,
     tool_call_count.
   - `append_log(state_dir, turn_usage, now)`: one JSON line to
     `token-meter.jsonl` (atomic append).
   - `summarize(log_path) -> Stats`: count, total, mean, p50/p95/max, last-N,
     trend — for the report command.
2. `scripts/hooks/on-stop-token-meter.py`: a Stop hook. Reads `transcript_path`
   from stdin JSON; calls `tail_turn_usage`; if a heartbeat turn, `append_log`.
   FAST (tail read only), never blocks (always exit 0), never raises.
3. `scripts/token_report.py` + `commands/janitor-token-report.md`: read
   `token-meter.jsonl`, print a table (per-fire recent + the summary stats),
   flag spikes (> p95) and a too-high mean. `--json` for scripting.
4. Wire `on-stop-token-meter.py` into `hooks/hooks.json` (Stop matcher).
   Consider adding it to StopFailure too so rate-limited fires are also costed
   (handle missing/partial usage gracefully).
5. Tests: `tests/test_token_meter.py` — fixture transcript tails (a heartbeat
   turn with N assistant msgs → correct sum; a non-heartbeat turn → None; an
   empty/partial usage → graceful; the summarize stats).

Log location: `$PROJECT/.janitor/state/token-meter.jsonl` (per-session, like the
other state). Rotate when large (reuse `state.rotate_log_if_big`).

## Phase 2 design — push automation into scripts (planned)

Principle: each detector should do the MECHANICAL work in-script with heuristics
and hand the agent only the irreducible DECISION, with the SMALLEST possible
payload to read and the SMALLEST possible action to write.

Per-detector audit (each its own follow-up TRDD, measured against the meter):
- **project-map-drift** → have the daemon (zero-token) or the detector run
  `repomap_generate.py` directly (it is fully scriptable + has anti-corruption
  verification), surfacing to the agent only on a write-conflict. Biggest pure
  win — moves a whole job off the agent.
- **memory-librarian** → already proposes to a file; tighten the proposal so the
  agent reads a 1-line decision, not 59 findings (pre-rank, pre-dedupe, collapse
  to "apply these N safe merges? y/n").
- **gitignore / tracked-ignored** → auto-stage the unambiguous adds (the `_dev`,
  reports, .janitor patterns) as a script; surface only ambiguous cases.
- **branch-protection / workflow-security** → the apply path is already a Tier-2
  guarded script; widen the safe-auto set, surface only the judgment cases.
- **supply-chain / typosquat / dangerous-actor** → preprocess to a one-line
  verdict + the single actionable command; never dump raw scan output.

Each Phase-2 change: (a) script does the mechanical part, (b) agent gets a
minimal decision-ready payload, (c) re-measure per-fire tokens via the meter to
prove the saving.

## Acceptance criteria

- Phase 1: every heartbeat turn's token cost is logged; `/janitor-token-report`
  shows recent per-fire costs + mean/p95/max + spike flags; the meter adds
  negligible cost itself (tail read, no whole-file parse) and never breaks the
  Stop/StopFailure survival path. Tests green; CI green.
- Phase 2: measurable per-fire token reduction with NO loss of janitor
  capability (each automated job still reaches the agent for the genuine
  decision).

## Durable artifacts

- Feasibility evidence: transcript usage-object shape + heartbeat-ID method
  (this STATE block).
- Cost/ability analysis (which jobs are agent-irreducible vs scriptable): the
  #23 discussion thread + the daemon-vs-cron-vs-bg comparison.
