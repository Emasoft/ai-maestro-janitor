---
trdd-id: PXP08ZQC
title: Cache-expiry-aware EXTERNAL handoff-and-clear — zero model turns, terminal-driven, handoff composed by llm-externalizer for free
column: todo
created: 2026-08-06T13:23:24+0200
updated: 2026-08-06T13:23:24+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
severity: high
relevant-rules: []
implementation-commits: []
---

# External zero-turn handoff-and-clear (owner failure report 2026-08-06, item 3)

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

- [ ] watcher fires only on idle + cache-expired + over-threshold + user-absent-per-rules
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
