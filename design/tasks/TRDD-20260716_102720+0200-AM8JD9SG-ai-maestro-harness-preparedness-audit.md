---
trdd-id: AM8JD9SG
title: ai-maestro harness preparedness — fleet-injection/presence/recovery gaps when the janitor runs inside an ai-maestro agent
column: dev
created: 2026-07-16T10:27:20+0200
updated: 2026-07-16T10:27:20+0200
current-owner: janitor-session
task-type: audit
scope: project
severity: major
labels: [ai-maestro, fleet-inject, fleet-stop, fleet-recovery, presence, user-intent, terminal-trigger, cross-project]
relevant-rules: []
---

# ai-maestro harness preparedness audit — janitor fleet machinery inside an ai-maestro agent

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-16

**What this is:** a high-effort (`/code-review high`, 35 agents, 1-vote recall-biased verify)
compatibility audit the USER requested: *"audit the janitor plugin for preparedness to work inside
ai-maestro and use ai-maestro scripts."* Ten findings, ALL verifier-CONFIRMED, all in the
fleet-injection / presence / recovery machinery that governs how a janitor session behaves when it
runs inside an ai-maestro multi-agent fleet (tmux panes on custom sockets, the `aimaestro-agent.sh`
CLI channel, AMP-injected prompts, shared agent workdirs, the launchd daemon).

**Provenance:** the review report is the evidence; the run is `wf_9c0148d9-fec` (this session,
2026-07-16). Each finding below was CONFIRMED by an independent verifier, THEN re-checked against the
live source by the orchestrator before disposition (several agent claims were sharpened on read —
F2 is working-as-designed, not the naive bug the summary implied).

**Two dominant root causes (the audit's own synthesis):**
1. **Provenance blindness** — the only discriminator of "a human typed this" is the `[janitor-…]`
   prefix on the prompt. Inside a fleet, AMP messages and CLI-injected commands are *not*
   `[janitor-…]`, so they forge user-presence + user-intent → the emergency self-compact is
   suppressed fleet-wide and a forged `/janitor-disarm` can mint a fake "the user opted out" latch.
2. **CLI-channel semantic loss** — the `aimaestro` injection channel has no ESC/interrupt primitive
   and `fire()` reads CLI-exit-0 as "delivered", so a stop/compact aimed at a *frozen* agent is
   stamped delivered while it enqueues behind the wedged turn forever.

### DONE THIS PASS — 2 safe, self-contained fixes applied (see NEXT ACTION for the deferred 8)
- **F5** `terminal_trigger.match_agent_tmux` — an exact-workdir TIE (two agents on the same repo)
  silently picked first-in-registry-order, violating the function's own "must never guess"
  invariant. Fixed to REFUSE (return None) on a genuine ambiguous tie → the self-trigger degrades to
  "ask the user" instead of typing into the wrong agent's pane.
- **F8** `terminal_trigger._try_ai_maestro_send` — a PARTIAL multi-command delivery (command 1 sent,
  command 2 failed) returned None, and `send_self_command` then re-typed the WHOLE list via tmux,
  duplicating the delivered command. Fixed to report partial delivery so the caller does NOT
  full-fallback (losing the undelivered tail is strictly safer than double-running a handoff+compact
  on an already-compacted session).

**F9 was RE-CLASSIFIED to design-needed on read** (below): the naive "raise the 8s inner timeout"
fix is INERT — the PreToolUse hook's OWN registered timeout in `hooks/hooks.json` is 5s, shorter than
both the 8s inner cap and the CLI's ~11s worst case, so the harness kills the whole hook at 5s
regardless. The real fix reconciles the whole 5s/8s/11s budget (most likely: make the ai-maestro
self-trigger send DETACHED like the tmux path, so the hook returns fast and `_mark_compacted` is
deterministic). Not a one-liner → deferred.

## NEXT ACTION — the 8 DESIGN-NEEDED findings (do NOT blind-fix; each needs a decision or ai-maestro API knowledge)

Ranked most-severe first. These touch fleet-stop / disarm / recovery SAFETY (getting them wrong
bills money or corrupts sessions), so they are captured here for a design pass, not patched blind.

1. **F1 — injected-prompt provenance (root cause, highest severity).**
   `hooks/on-prompt-submit.py` + `user_intent.py` treat every non-`[janitor-…]` prompt as a genuine
   human keystroke → bumps the machine-wide presence breadcrumb and mints user-intent tokens. In a
   fleet, AMP/CLI prompts arrive continuously so `user_is_present()` is permanently true (emergency
   self-compact / reload / resume suppressed fleet-wide), and any injected line containing
   `/janitor-disarm` (incl. the daemon's OWN fleet-stop) stamps a forged "the user asked" intent →
   `disarmed.flag` claims a human opt-out → the guardian never re-arms that agent. **Decision
   needed:** how does a prompt prove human origin inside ai-maestro? (an env marker the CLI/AMP sets
   on injected prompts? `AID_AUTH` presence? a per-turn nonce?) The `[janitor-…]` prefix is
   necessary-but-not-sufficient — extend the discriminator, do not widen it.
2. **F4 — self-compact presence gate is HOST-wide, not per-pane.**
   `terminal_trigger.send_self_command` gates on `user_intent.injection_allowed()` which reads the
   machine-global presence breadcrumb, so the ≥85% emergency compact is blocked in EVERY agent pane
   whenever the human types anywhere. The fleet path (`fleet_stop.is_injectable`) is per-instance;
   the self-trigger never got the per-pane equivalent. **Decision:** per-pane presence for the
   self-trigger (needs a per-pane "is THIS pane's human active" signal), coupled with F1.
3. **F3 — transcript-freshness conflated with human presence.**
   `daemon.py` (`user_active_pids`) + `fleet_stop.is_injectable` treat `transcript mtime < 300s` as
   "a human is here", but a busy agent — or one merely receiving FAST-tier `*/5` heartbeats, which
   advance the transcript at exactly the 300s bound — is excluded from fleet-stop forever. The
   biggest token consumers are exactly the ones `/janitor-global-disarm` never reaches. **Decision:**
   distinguish agent-activity from human-activity (tie to F1's provenance signal, not mtime).
4. **F6 — daemon has no ai-maestro CLI auth.**
   `fleet_scan._aimaestro_agents` / `fleet_inject.fire` run the CLI with the daemon's own env, but
   the CLI's auth (`AID_AUTH` / `AIMAESTRO_SUDO_TOKEN`) lives only inside agent sessions; a
   launchd/detached daemon has neither, and nothing restores it the way `daemon_path.py` restores
   PATH → CLI-only-reachable frozen agents are never tagged/recovered (mute failure). **Needs
   ai-maestro API knowledge:** how does a machine-global daemon authenticate to the ai-maestro
   server? (a service token? a daemon identity the server trusts?)
5. **F2 — fire() claims delivery for an un-interruptible CLI target (residual of a working-as-designed
   choice).** The `aimaestro` branch of `fleet_inject.build_command_plan` dropping `esc_first` is
   DELIBERATE and documented (the CLI has no ESC primitive). The residual gap: `fire()` returns True
   (CLI exit 0 = delivered) for a FROZEN target whose wedged turn will never dequeue the command, so
   the stop is stamped delivered and never retried/escalated. **Decision:** the aimaestro channel
   should NOT report "delivered" for a `frozen` diagnosis (or the daemon should escalate to a hard
   rung when the only channel is the no-ESC CLI). Depends on whether the ai-maestro CLI can expose an
   interrupt (F6-adjacent).
6. **F10 — channel priority is inverted vs the self-trigger.**
   `build_command_plan` tries tmux first, aimaestro third; the self-trigger path treats the
   ai-maestro CLI as authoritative. For an ai-maestro-managed pane whose tmux TTY is visible to the
   daemon, fleet recovery/stop does raw `tmux send-keys` (incl. ESC) into a pane the ai-maestro
   server ALSO types into → interleaved keystreams → garbled/wrong agent actions. **Decision:** when
   a pane is ai-maestro-managed, prefer the CLI channel (server-serialized) over raw tmux — align the
   two paths on one priority order.
7. **F7 — hard-restart rungs bypass the ai-maestro server lifecycle.**
   `fleet_restart.build_resurrect` / `build_force_restart` relaunch a stuck agent as a raw
   `tmux new-session … claude --continue` outside ai-maestro's registry → the dashboard shows the
   agent dead while a rogue unmanaged claude runs the same workdir/transcript; a later operator
   restart yields TWO claude instances on one transcript, interleaving edits. **Needs ai-maestro
   API:** the hard rungs must relaunch THROUGH the ai-maestro server for a managed agent (or refuse
   and alert), never spawn an unmanaged sibling. `fleet_restart` is opt-in/DEFAULT-OFF today, which
   bounds the blast radius but does not fix it.
8. **F9 — the context-guard compact-trigger timeout budget is mis-layered for the CLI path.**
   `hooks/hooks.json` registers `pre-tool-context-usage` with a **5s** timeout; the hook's internal
   `_run_compact_trigger` caps `compact_trigger.py` at **8s**; and inside an ai-maestro agent
   `compact_trigger` runs the CLI SYNCHRONOUSLY (5s `list --json` + 6s `session command` + `uv`
   startup ≈ 11–13s). So the harness kills the hook at 5s — before `compact_trigger` can confirm —
   `_mark_compacted` never runs, and the next tool call re-injects `/compact` (double compaction).
   Raising the inner 8s cap is INERT while the outer is 5s. **Decision:** make the ai-maestro
   self-trigger send DETACHED (like the tmux/iTerm channels already are) so the hook returns fast and
   marks-compacted deterministically — at the cost of losing the CLI's synchronous delivery
   confirmation for the self-trigger (acceptable: the tmux path already fires-and-forgets). Touches
   `terminal_trigger.send_self_command` (the `state.in_ai_maestro_agent_env` branch) +
   `compact_trigger.py`; keep the fleet-recovery path's SYNCHRONOUS CLI use unchanged (it needs the
   exit code).

**Grouping guidance:** F1 is the keystone — F3, F4 all resolve once a trustworthy human-vs-injected
provenance signal exists, so design F1 first and derive F3/F4 from it. F2, F6, F10 are the CLI-channel
cluster (auth + interrupt + priority) — one design pass over "how the janitor talks to the ai-maestro
server". F7 is the hard-restart cluster (relaunch-through-server), gated behind `fleet_restart`'s
opt-in. Each cluster may become its own child TRDD once the ai-maestro API surface is confirmed.

## Verification
- The 3 applied fixes: `uv run pytest tests/ -q` green (esp. `test_terminal_trigger*`,
  `test_fleet_inject*`, the context-guard hook tests), `ruff check` clean.
- The 7 deferred: each needs its own reproducer + a design decision + (for F6/F7) reading the
  ai-maestro server/CLI API before any janitor-side change. Do NOT patch fleet-stop/disarm/recovery
  code blind — a wrong fix here bills real money or corrupts a live agent session.

## Notes and lessons learned
