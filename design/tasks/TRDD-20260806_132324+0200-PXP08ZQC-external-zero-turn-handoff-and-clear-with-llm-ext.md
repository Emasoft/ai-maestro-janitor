---
trdd-id: PXP08ZQC
title: Cache-expiry-aware EXTERNAL handoff-and-clear — zero model turns, terminal-driven, handoff composed by llm-externalizer for free
column: dev
created: 2026-08-06T13:23:24+0200
updated: 2026-08-06T18:07:00+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
severity: high
relevant-rules: []
implementation-commits: []
---

# External zero-turn handoff-and-clear (owner failure report 2026-08-06, item 3)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-06

**Column `dev` since 2026-08-06.** Design was pre-authored by the owner in the body below, so
`todo → dev` skipped `design`/`dispatch` (mono-agent self-assignment).

### Component state

| Part | State |
|---|---|
| 1. Watcher (policy + gate) | `scripts/lib/external_clear.py` — NOT YET WRITTEN |
| 2. Handoff writer (llm-ext + template fallback) | NOT YET WRITTEN |
| 3. Typist | **ALREADY EXISTS** — `clear_trigger.py` chain; needs only an out-of-session terminal source |

### NEXT ACTION (one step, runnable)

Write `scripts/lib/external_clear.py` (pure policy + template composer) and
`tests/test_external_clear.py`. Nothing else in Phase 1.

### Load-bearing findings (measured on THIS machine 2026-08-06 — do not re-derive)

- **The card's stated trigger is DEAD as written here.** `.janitor/state/ttl-regime.json` says
  `minutes: 60` (probed) and `armed-cadence.cron` is `*/5 * * * *`. A fire every 5 min against a
  60-min TTL means the prompt cache **never** expires while armed, so a literal `cache-expired`
  predicate is never true — the "threshold high enough to never be met is a feature that does not
  exist" failure `cold_cache_compact` already burned on twice.
  **DEVIATION (owner may veto):** the gate ORs two triggers and names which one fired —
  (a) *next-fire-misses* — `age_since_last_turn + seconds_until_next_fire >= ttl` (the card's
  intent, correctly expressed: the point is that the NEXT fire pays the miss, not that the cache
  is already cold); and (b) *long-idle* — nothing but beats for ≥1 h (owner directive 2026-08-04),
  which is what actually bites here: the handoff records ~10 M cache-**read** per warm fire and
  177.7 M of the 7 d weighted spent on janitor fires alone. Trigger (b) alone justifies the card.
- **Terminal identity is already solved out-of-session.** `.janitor/state/terminal-identity.json`
  exists (`iterm_session_id` = `w0t1p0:<uuid>`); `fleet_restart.recorded_terminal()` reads it. It
  returns the FLEET shape (`iterm_session_id`/`tmux_pane`); `clear_trigger._this_terminal()` and
  `terminal_trigger` use the OTHER shape (`kind`+`pane`/`session_id`). An adapter is required —
  and `ITERM_SESSION_ID` is `<tty>:<UUID>`, so the UUID must be split off exactly as
  `_this_terminal()` does, or `_UUID_RE` rejects it.
- **Unknown-context must NOT veto** (repeat of the 2026-08-04 correction on
  `should_clear_when_long_idle`): an unmeasurable transcript silently disabled the lever. Unknown
  **idle**, however, still vetoes — an unknown idle age may never authorize a destructive act.
- The existing in-model lever (`dispatch._phase_idle_clear_nudge`, TRDD-5C42VCUX) shares the
  `idle-clear-fired.ts` cooldown stamp, so whichever fires first stands the other down. Keep that
  sharing — it is the coexistence contract while both exist.

### SUPERSEDED — do NOT carry forward

- "watcher fires only on idle + **cache-expired** + over-threshold" — replaced by the two-trigger
  OR above. The acceptance box is rewritten accordingly.

### Artifacts to read first

`scripts/clear_trigger.py` (the typist + `check_handoff_concise`) ·
`scripts/lib/cold_cache_compact.py` (the CLEAR section + why size was dropped) ·
`scripts/dispatch.py::_phase_idle_clear_nudge` (the in-model sibling).

## WHY

Today's shape: session idle, prompt cache expired (>5-min TTL), the NEXT heartbeat fire
pays a full ~400–460k cache-miss write just to say "nothing to do" — and the current
handoff flow makes it WORSE, because authoring the handoff is itself a model turn on the
huge context. The owner's requirement, verbatim intent: when the cache is expired and
the session is idle, the janitor must handoff-and-clear WITHOUT triggering a model run —
monitor the terminal from OUTSIDE, compose the handoff for free, and type `/clear` at
the right moment (before the next turn executes).

## Design shape (three parts, all OUTSIDE the model)

1. **Watcher** (daemon task or detached per-session child): detects
   idle + cache-expired + context-above-threshold. Inputs it already has: the
   context snapshot / token meter, transcript mtime, `user_intent.user_is_present`,
   the cadence state. Timing contract: act in the idle gap BEFORE the next cron fire
   would enqueue a turn (it knows the armed cron's schedule).
2. **Handoff writer, zero tokens**: `llm-ext` CLI (chat/scan over the transcript
   JSONL + the TRDD STATE blocks ON DISK — pass paths, never content) composes the
   link-only handoff into `.janitor/state/agent-handoff.md`, honoring the existing
   concision contract (`clear_trigger.check_handoff_concise`). Free mode / auto-free
   makes this ~$0; the model never wakes. Fallback when llm-ext is absent: a
   template handoff from the STATE blocks alone (they are the durable payload anyway).
3. **Typist**: the ALREADY-RATIFIED injection chain (`terminal_trigger.run_chained_inject`
   — pane-free wait, 8s retry, stop-on-keystroke, verified submit) types `/clear` then
   the arm+resume bootstrap. iTerm via python/osascript, tmux via send-keys; inside the
   ai-maestro harness the actuation is the server's per the janitor#100 split — file the
   ask upstream if a harness variant is wanted (see also ai-maestro#110).

## Acceptance

- [ ] watcher fires only on user-absent-per-rules AND (next-fire-misses OR long-idle), never on
      unknown idle; over-threshold applies only when the context is measurable (see STATE)
- [ ] handoff written by llm-ext with ZERO main-model tokens (or template fallback), passes
      check_handoff_concise
- [ ] /clear + bootstrap land via run_chained_inject with no model turn before them
- [ ] one observed end-to-end unattended cycle: big idle session → external handoff →
      clear → re-arm → resume, with the verify harness PASS table
- [ ] cost note: measured per-cycle cost vs today's per-fire cache-miss write

## Pointers

- Sibling/prereq relationship: TRDD-5C42VCUX (make the EXISTING in-model idle-clear
  engage — the stopgap while this lands).
- Reuse: `handoff_clear_verify.py` (proof harness), `clear_trigger._run_chain_payload`
  (the chain child), `lib/token_meter.resolve_context`, `lib/user_intent`.
- llm-ext rule: ~/.claude/rules/use-llm-externalizer.md (paths not content; --estimate
  on paid profiles; auto-free on low balance).
