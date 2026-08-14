---
trdd-id: AM8JD9SG
title: ai-maestro harness preparedness — fleet-injection/presence/recovery gaps when the janitor runs inside an ai-maestro agent
column: todo
created: 2026-07-16T10:27:20+0200
updated: 2026-08-14T18:22:00+0200
current-owner: janitor-session
task-type: audit
scope: project
severity: major
labels: [ai-maestro, fleet-inject, fleet-stop, fleet-recovery, presence, user-intent, terminal-trigger, cross-project]
implementation-commits: [eb9faa1]
blocked-by: []
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

## ⏵ DIRECTION RECEIVED — ai-maestro#68 answered (2026-07-16), the ground shifted under 3 findings

**READ THIS BEFORE the NEXT ACTION list below — it supersedes several findings' framing.**
The ai-maestro Claude gave a decisive answer. The full text is issue **ai-maestro#68** (durable);
the load-bearing deltas:

**R42 LANDED (`6dcc57fd`, `TRDD-BF3JN4TL`, `docs/GOVERNANCE-RULES.md` R42) — cross-agent DRIVE
injection is REVOKED, not restricted.** `lib/authorization.ts DRIVE_ACTIONS = {send-command,
restart-session}` → any caller with `targetAgentId != auth.agentId` is DENIED, no title exempt,
fails closed. The set of principals that may put characters into an agent's session is now
**{USER, the agent itself (R42.4), the janitor's R42.5 GLOBAL switches}**. Mirror the three-class
line: **DRIVE** (arbitrary text → makes victim act — REVOKED cross-agent) vs **LIFECYCLE** (one
fixed key, starts/stops a process — PERMITTED to MANAGER/COS/USER) vs **CONFIGURATION** (changes
what the agent IS — PERMITTED, R42.6).

**R42.5 janitor exception is EXACT** — global disarm/re-arm, pause/unpause heartbeat, global
reload plugins+skills. **Everything else is self-only, `/compact` included.** ⇒ NET-NEW FINDING
**F11 (compliance):** the fleet guardian's gentle rungs inject `/janitor-arm` (per-project, NOT
global) and `/janitor-resume` (not on the list) into OTHER agents' panes — **no longer permitted**.
The global switches (`fleet_stop` disarm/pause) and `/reload-plugins` fleet-wide ARE covered.

### Per-finding verdicts (ai-maestro#68 summary table)

| # | Verdict | Direction |
|---|---|---|
| **F7** relaunch | **(a) exists** | Use `hibernate`→`wake` (LIFECYCLE), NEVER `restart` (DRIVE, revoked). Given F6 undecided the guardian has no principal to call `wake` cross-agent → **refuse + alert, do not spawn the sibling.** Also: ai-maestro agents launch with NO resume flag (fresh convo) while our `claude --continue` RESUMES → that divergence IS the two-claude-one-transcript bug. `TRDD-SB5I53K1` (fleet restart verb) is deliberately HELD. |
| **F10** CLI vs tmux | **(b) YES, always CLI** for a managed pane | Raw tmux is the documented R42 HONEST LIMIT (works because one OS uid — tamper-EVIDENT not tamper-PROOF); the decoupling invariant makes the `aimaestro-*` script layer the ONLY sanctioned boundary. Raw tmux stays legit ONLY for an UNMANAGED pane. |
| **F2** interrupt | **(b) not planned** | No interrupt verb exists (`queue-cancel` ≠ in-flight cancel; `C-c` only inside stop/restart). Shape would be LIFECYCLE (R42-compatible) but the caller collapses into F6. **Ship the janitor-side "stop reporting delivered for a frozen target + escalate" fix NOW — do not wait on the server** (same lesson as `TRDD-3VW434Q8`: a green result never verified is worse than a red one). |
| **F6** daemon auth | **(c) USER** | #55's mechanical half SHIPPED (`bc177864`): a path exists, but the daemon runs as the owner uid → the server believes it is the human OWNER (max authority, no scope, no revocation, no audit split) — collides with R48 (`bf70bf47`, MAESTRO gated on physical console presence). A scoped/revocable THIRD principal class is a new authz model = Tier 2/3, gated on `#46`, adjacent to R16. **Only the USER can pick: third principal class, or confine the daemon to the read-only surface.** |
| **F1** provenance | **(c) USER (mechanism)** | Diagnosis SETTLED (mirror, not a choice): the inject path is raw `tmux send-keys -l` (`agents-core-service.ts:1573`→`agent-runtime.ts:345`) — **no turn object to mark; an env var is process-scoped so cannot mark a running turn; any in-text marker is forgeable.** Provenance EXISTS at the boundary (`aim_session`=human / `AID_AUTH`=agent) but `sendKeys` flattens both to identical bytes. A prefix is a convention, not a control. **The MECHANISM (a signing root of trust vs. a server side-channel vs. narrow-the-injectors) is a new machine-wide root of trust → USER, batched with F6.** |
| **F3/F4** | **(c) inherited** | ai-maestro needs them STATED (the issue didn't describe them) — done in the #68 reply. |
| **F9** | **unstated** | Named nowhere in #68 → stated in the reply. |

### Two F1 halves that are JANITOR-SIDE and fixable NOW (no server change, no USER needed)
1. **The forged `/janitor-disarm` latch — a prompt is DATA, never AUTHORITY.** Minting a durable
   "the user opted out" `disarmed.flag` from prompt TEXT is the bug; no server marker turns text
   into proof. The latch's authority must come from an explicit user action against an authenticated
   route, not from a `[janitor-…]`-looking line. → tighten `user_intent`/`disarm_guard`.
2. **The presence breadcrumb is the JANITOR'S OWN.** ai-maestro's presence record
   (`~/.aimaestro/user-presence.json`) is bumped ONLY by an explicit `POST /api/sessions/me/user-input`
   (AMAMA-only), never by a keystroke. If injected text bumps a presence breadcrumb it is the
   janitor's own (written by `on-prompt-submit.py`) → this is F1/F3/F4's janitor-side core: the
   `[janitor-…]`-prefix discriminator must not count an injected prompt as human input.

### Canonical pointers to mirror (from #68)
- R42 + DRIVE/LIFECYCLE/CONFIG: `docs/GOVERNANCE-RULES.md` R42; `lib/authorization.ts`
  (`DRIVE_ACTIONS`, `SELF_DRIVE_ACTIONS`); `TRDD-BF3JN4TL`. Agent-facing form:
  `rules/aimaestro/aimaestro-agent-rules.md`.
- Relaunch: `aimaestro-agent.sh hibernate|wake` → `POST /api/agents/[id]/{hibernate,wake}`;
  `TRDD-D5XDT49I` (no agent launches with a resume flag), `TRDD-SB5I53K1` (held).
- Agents never face sudo: R32.3, R28 three-check. Janitor strict-route reality: `TRDD-SCLSRS6E`
  (blocked — every strict route 403s every agent caller), `lib/sudo-guard.ts` (`STRICT_AGENT_RULES`).
- USER auth path SHIPPED: `bc177864`; `scripts/shell-helpers/common.sh:370-440`;
  `aimaestro-governance.sh login`. Console presence: `lib/peer-address.mjs` `isConsolePeer`
  (PRESENCE only — "do not apply elsewhere"), R48, `TRDD-P7XKV3N9`/`TRDD-PLOVIPZE` (held).

### Reclassified action buckets (post-direction)
- **JANITOR-SIDE, UNBLOCKED — implement (design pass, this TRDD):** F10 (managed pane → CLI first
  in `fleet_inject.build_command_plan`), F2-honesty (`fleet_inject.fire`: no "delivered" for a
  frozen no-ESC CLI target → escalate), F7 (hard rungs: refuse+alert, never spawn unmanaged
  sibling; if ever relaunching, `hibernate`→`wake` not raw `claude --continue`), F1-two-halves +
  F3/F4 (presence: an injected prompt is NOT human input; the disarm latch needs an authenticated
  user action, not prompt text), **F11 (R42.5 compliance): the guardian must NOT cross-inject
  `/janitor-arm` or `/janitor-resume` — only the global switches + `/reload-plugins`).**
- **USER DECISION (Tier 3), batched F1+F6 — RULED 2026-07-16: "scoped daemon principal +
  provenance root".** The owner chose the MORE CAPABLE option: F6 → the daemon gets its own
  **scoped, revocable** third principal class (NOT owner-wide — that's the R48 collision, avoided
  by scoping); F1 → the system DOES get a prompt-provenance root of trust (signing-root or
  server-side-channel, ai-maestro's choice, subject to the `#56` no-janitor-required invariant).
  **Server-side design is ai-maestro-led (Tier 2/3 authz model), gated on `ai-maestro#46`** (can't
  grant a capability to a principal you can't uniquely identify) — hence `blocked-by: ai-maestro#46`.
  The janitor's `#60` (signed daemon identity) is an INPUT to their design, not a spec. **Interim
  until the principal ships: cross-agent recovery stays refuse+alert** (capability ratified, no
  credential yet). Relayed on ai-maestro#68; awaiting their F6 design issue for key-registration +
  verb requirements to mirror here.
- **F9** — janitor-side timeout-budget fix (make the ai-maestro self-trigger send detached), still
  design-needed, independent of the above.

## ⏵ DAEMON-MIGRATION ARCHITECTURE — coordination in flight (janitor#100, 2026-07-16)

**Owner directed (2026-07-16) a bigger architecture that SUPERSEDES most of this audit's residual:**
ai-maestro absorbs the janitor DAEMON's continuity functions and serves them via api/scripts; a
special LOCAL-scoped `#J` janitor runs in each ai-maestro agent (NO daemon — it delegates to the
server); the NORMAL `#N` janitor flips user→local scope for non-ai-maestro machines.

- **ai-maestro's coordination ask = `Emasoft/ai-maestro-janitor#100`.** I replied with the
  **authoritative daemon inventory** (the durable artifact — read the #100 comment, not this
  summary): 11 daemon tasks split into **Family A = continuity** (OAuth rotation, account-mgmt on
  429/network, session-liveness recovery, resurrection → MOVE TO SERVER) and **Family B =
  dev-hygiene** (plugin/self update, cache-prune, rules-cleanup, OOM guard, gh-config audit → STAY
  with the janitor; moving them breaks ai-maestro's own `#56` "runs with no janitor" invariant).
- **The #J/#N line:** `#J` does only the ~35 workdir-scoped detectors locally + delegates Family A
  to the server via `aimaestro-session.sh slash/queue` (self-targeted, R42-clean, no auth problem —
  `queue` is strictly better than ESC-injection); does NO Family B, NO daemon, NO global writes.
- **The residual `#N` keeps:** Family B on any machine + OAuth-rotation FALLBACK when there's no
  server + recovering the ai-maestro SERVER ITSELF if it dies (server can't resurrect itself). Scope
  flip user→local does NOT reopen #7 — the singleton is guaranteed by the machine-wide `daemon.flock`,
  not by install scope (corrected my earlier caution).
- **R16 token posture (sign-off gate):** tokens live ENCRYPTED in the OS keychain
  (`Claude Code-credentials` live + `Claude Code-rotator-slot` slots), never in a file, **never in
  any API/CLI response an agent/model can read**; one live-credential writer (server-when-up /
  daemon-fallback, mutually exclusive); REAUTH stays a human `/login`.
- **AgentlensPro#2 RESOLVED** — the 3 CLI-contract paths are confirmed + LOCKED by
  `cliContract.janitor.test.ts` (commit `d1a3074`); drift now fails their gate. The token-monitoring
  half is unblocked.

**NEXT ACTION (post-coordination):** wait for ai-maestro to fold the inventory into their server-side
TRDDs + confirm the Q3 api/scripts contract shape → THEN author the **janitor-side TRDD** (`#J` build,
`#N` scope-flip, shared-codebase/two-backends split, and the `#N`-fallback-when-no-server residual).
Process is coordinate → TRDDs → plan mode (owner-directed); do NOT jump to plan mode or author the
big TRDD before ai-maestro confirms the contract. Cross-refs: ai-maestro#68 (parent), ai-maestro#70 /
AgentlensPro#3 (AgentlensPro dependency), ai-maestro TRDD-1222f06a §9.

## COORDINATION + PUBLISH GATE (2026-07-16)

- **Coordination anchor: `Emasoft/ai-maestro#68`** — asks the ai-maestro Claude for the PLANNED/
  ratified direction on the janitor-facing surface each gated finding needs (provenance marker,
  daemon auth, interrupt primitive, managed-agent relaunch, channel priority). Consolidates the
  janitor-side of the overlapping open threads `#60` (my unanswered daemon-auth ask), `#55` (USER
  auth path), `#54` (keystroke-inject classification), `#56` (heartbeat coverage). AMP is down →
  the answer arrives on GitHub (see LOCAL memory `ai-maestro-amp-down-coordinate-via-github-issues`).
- **PUBLISH IS GATED (USER directive 2026-07-16):** do NOT publish a janitor release until (a) all
  pending tasks are complete AND (b) the janitor is brought up to speed with ai-maestro's plans —
  i.e. `#68` is answered and the 8 gated findings below are designed to mirror the ratified
  direction. The 2 safe fixes (F5/F8, commit `eb9faa1`) are committed-not-published and ride the
  next gated release. **The design pass cannot start until `#68` returns direction** — this TRDD is
  `blocked-by: ai-maestro#68`.

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
