---
trdd-id: AM8JD9SG
title: ai-maestro harness preparedness — fleet-injection/presence/recovery gaps when the janitor runs inside an ai-maestro agent
column: todo
created: 2026-07-16T10:27:20+0200
updated: 2026-08-28T11:20:00+0200
current-owner: janitor-session
task-type: audit
scope: project
severity: major
labels: [ai-maestro, fleet-inject, fleet-stop, fleet-recovery, presence, user-intent, terminal-trigger, cross-project]
implementation-commits: [eb9faa1, e65ced5f]
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

## ⛔ 2026-08-26 — F11 IS NOT A THEORETICAL GAP. It is firing, 275 times, and the mitigation covers ZERO instances.

`harness_backend.instance_is_server_owned`'s docstring calls `under_agents_home` the
"REGISTRY-FREE signal" that is "LOAD-BEARING today", because the CLI list always 401s from the
daemon's context (F6) so nothing is ever tagged and the cache never fills. **Measured today: it
carries nothing here, because no ai-maestro agent on this machine lives under `~/agents/`.**

Every one of the 20 project roots the guardian has ever injected into is under `~/Code/` or is
`~/ai-maestro` itself — `under~/agents=False` for all 20. And the cache the docstring falls back
to **does not exist on disk**:

```
$ ls …/global-state/aimaestro-agent-roots.json
No such file or directory
```

So all three signals are dead at once: `tagged` (needs a list that 401s), `cached_roots` (file
absent), `under_agents_home` (no agent is there). `instance_is_server_owned` therefore returns
**False for every ai-maestro agent on this host**, and the PZLVT2RN hands-off split — which is
correctly implemented, `_DIAGNOSIS_RECOVERY["server_owned"] = None` — never engages.

**The consequence, straight from `recovery-audit.ndjson`:**

```
275 injections into ai-maestro-looking roots since 2026-08-11 19:54
  187  rearm       (/janitor-arm — per-project, NOT one of R42.5's global switches)
   88  esc_nudge   (ESC into the pane)
```

Recipients include the live role agents by name — EMASOFT-ASSISTANT-MANAGER,
EMASOFT-ORCHESTRATOR-AGENT, EMASOFT-ARCHITECT-AGENT, EMASOFT-INTEGRATOR-AGENT,
EMASOFT-PROGRAMMER-AGENT, EMASOFT-CHIEF-OF-STAFF, AI-MAESTRO-AUTONOMOUS-AGENT,
AI-MAESTRO-WEBDESIGN-AGENT, ai-maestro-assistant-role-agent, ai-maestro-web-scenario-tester,
and `~/ai-maestro` itself — each of which appears as a live peer session in `ListAgents`.

**This upgrades F11 from "compliance finding" to "measured, ongoing".** The audit reasoned that
the guardian *would* inject into other agents' panes; the audit log proves it *does*, 275 times
over 15 days, and that the safeguard designed to prevent it is inert on this host rather than
merely imperfect.

### Why it looked handled

The docstring is honest and specific — it names F6, names the 401, and flags "adopted workdirs
OUTSIDE `~/agents` remain covered only by tag/cache (a known gap until that probe lands)". What
it does not say, because nobody measured it, is that on THIS machine that gap is the entire
population. A mitigation described as load-bearing and a mitigation that covers 0 of 20 read
identically in code review; only the audit log tells them apart.

Same shape as TRDD-FB84YUGT and TRDD-LFSWY0C6 on this board: the mechanism is present, correct,
and never reaches the case it was built for.

### NOT FIXED HERE — and the reason is not caution

Two of the three plausible fixes are wrong to take unilaterally:

- **Widening the exclusion** (treat `~/Code/*-AGENT` as server-owned, or seed the cache) stops
  the janitor rescuing ~20 sessions it currently rescues. Whether the server actually recovers
  them is THEIR fact, not mine — and their `driveConsent` leg is itself unproven (see the
  handoff). Turning off a working rescue on the assumption that another one exists is exactly
  the trade that leaves a fleet unattended.
- **Doing nothing on the grounds that R42 binds their API, not tmux** is a technicality. R42's
  own text names the principals who may put characters into an agent's session; a direct pane
  write is precisely what it is about.

The third — an auth-free canonical probe (ai-maestro#100) — is the real fix and needs their side.

**NEXT ACTION on F11: hand the measurement to ai-maestro and ask whether their server recovers
these 20 roots. If it does, widen the exclusion. If it does not, the janitor's injections are
the only thing keeping them alive and R42 needs an amendment, not an enforcement.**

### ✅ 2026-08-26 — ANSWERED: **NO.** Do NOT widen the exclusion. All four claims re-verified here.

`ai-maestro-bf` answered from their logs and registry. I re-read each claim first-hand rather
than accept it — all four hold:

1. **0 of the 11 named recipients are in their registry.** `~/.aimaestro/agents/registry.json`
   holds 13 entries; the intersection with my injected roots is EMPTY. Their nine legacy
   `~/Code/*` entries are SVG/media projects (SKIA-BUILD-ARM64, SVG_PROCESSING, SVG-MATRIX,
   SVG-BBOX, SMART_MEDIA_MANAGER, SKILL_FACTORY, TEXT2PATH, SVG_FBF_PROJECT), plus `default`,
   plus three real ones under `~/agents/` (haephestos, testbot, frank). None overlap.
2. **Their server sees these sessions on a lane that actuates nothing** —
   `lib/fleet-liveness-watchdog.ts:290`, verbatim: `janitor-armed non-agent session(s) stale
   (>15min without a transcript write; detect-only, no actuation lane)`.
3. **`AIM_FLEET_RECOVERY_FIRE=1` IS set** on the live server process — confirmed by reading pid
   55636's environment, not a config file. So "their flag is off" is NOT the explanation; their
   actuator is armed and its population is empty.
4. **`instance_is_server_owned` returning False here is CORRECT, not a bug.** Their
   `CreateAgent`/`DeleteAgent` guards refuse workdirs outside `~/agents/`, so a `~/Code/*`
   Claude is not a server-owned agent BY THEIR OWN DEFINITION — not merely unrecognised. My
   third signal was giving the right answer for the right reason.

**So the 187 rearms are load-bearing**: they have been the only thing restoring those
heartbeats for 15 days, and enforcing R42 as written would strand the population. This is the
amendment branch, not the enforcement branch. Their session states for the record that the
server does not today recover any of the 20 roots and has no lane that could. R42 is governance
and goes to the OWNER — neither of us can amend it.

Also settled: my `tagged` signal 401s because the daemon holds no `AID_AUTH`, which is real —
but even WITH auth it would return the same answer, since those roots are not in the registry to
be listed. So F6 is a genuine defect and NOT the cause of F11.

### ⛔ The offered fix would have disarmed the guardian fleet-wide — caught before accepting

They offered to have the server write `aimaestro-agent-roots.json` from the registry, to give me
a deterministic exclusion. **Declined as specified, because the registry's 13th entry is named
`default` with `workingDirectory: "/"`.**

My cache branch tested `root.startswith(wd.rstrip("/") + "/")`. With `wd = "/"` that collapses
to `root.startswith("/")` — TRUE for every absolute path on the machine. Every session would
have read `server_owned`, whose recovery action is `None`, so **every janitor recovery would
have stopped, everywhere, silently.** Silently is the whole danger: hands-off is the safe
direction for any ONE instance, so no alarm distinguishes "correctly excluded" from "disarmed".

Fixed regardless of whether that cache is ever written (`e65ced5f`): the cache is authored by
another process, so it is untrusted input, and a degenerate entry is now DROPPED rather than
widened — it can only ever have meant "everything", which is not a claim a workdir may make.
Neuter-proven; also pins that `/a/foo` must not own `/a/foobar` by string prefix.

**The lesson is about the shape of the exchange, not the bug.** Their offer was correct in
intent, generous, and would have been actively harmful — and it was only caught because the
answer arrived with the registry named, so I could read the file instead of the summary of it.
A conclusion ("I can give you a cache") is not checkable; the artifact it came from is.

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
- ~~**F9** — janitor-side timeout-budget fix (make the ai-maestro self-trigger send detached),
  still design-needed~~ — **CLOSED 2026-08-28.** The detached send had already shipped; the real
  residue was a timeout-nesting inversion on the `pre-tool-context-usage` hook path. See
  "F9 RESIDUE FIXED" below.

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

## Acceptance — added 2026-08-16, because this card had NONE for a month

A `severity: major` card open since 2026-07-16 with **zero acceptance boxes** cannot be finished:
nothing states what "done" is, so every pass re-reads 272 lines and re-derives the answer. That is
the same defect the roster card (TRDD-IEW2K659) was filed for — an artifact with no failure signal.
One box per finding, so the card becomes drivable by someone who has not read the audit.

**Method, and its limit.** Status below is from `grep -rn "AM8JD9SG F[0-9]" scripts/` — a code
comment citing a finding proves that finding was ADDRESSED AT THAT SITE. It does not prove the
finding is fully resolved, and it cannot see a fix that landed without citing the id. Treat a
`[x]` here as "shipped, verify the scope before closing", never as an audit.

- [x] **F2** delivery honesty on a frozen target — `fleet_stop.py` cites it (narrow case).
- [x] **F5** exact-workdir tie refuses instead of guessing — `terminal_trigger.py`.
- [x] **F6** daemon-context tag visibility — `harness_backend.py` + `fleet_inject.py`.
- [x] **F8** partial multi-command delivery no longer triggers a duplicating full-fallback.
- [x] **F9** ai-maestro self-trigger send is **DETACHED** — `terminal_trigger.py:1331` names the
      finding and the fix: only the resolution (`list --json`, 5 s cap) is synchronous; the
      per-command POSTs (~6 s each, 11–17 s inline for a multi-command handoff) now run detached.
      **The card still lists F9 as deferred and describes a 5 s `hooks.json` PreToolUse budget that
      no longer exists** — the registered PreToolUse timeouts are 3 s today. Shipped, unrecorded.
- [x] **F10** a server-managed pane prefers the server's own channel over raw keystrokes —
      `fleet_inject.py`.
- [ ] **F1** injected-prompt provenance (the audit's own highest-severity root cause) — an AMP
      message or CLI injection is indistinguishable from a human typing, so it forges user-presence
      and user-intent. Needs a prompt-provenance root of trust; the card records this as USER/server
      scope, not janitor-side.
- [ ] **F3** transcript freshness is conflated with human presence. — **VEHICLE IDENTIFIED
      2026-08-20: TRDD-OZNG3N2D.** The hub shipped `aimaestro-session.sh activity <tmux-session>`,
      which reports `last_user_input_epoch` (server-OBSERVED human input) SEPARATELY from a
      transcript epoch, and states the transcript epoch is one sample needing two spaced reads to
      mean "advancing". That is exactly the conflation F3 names, resolved at the source rather
      than inferred. Blocked on OZNG3N2D, not on design.
- [ ] **F4** the self-compact presence gate is HOST-wide, not per-pane. — **CONFIRMED STILL TRUE
      AT HEAD 2026-08-20, and structurally so.** `user_intent.hid_idle_seconds()` says it in its
      own docstring: *"Seconds since the user's last REAL input event (keyboard or mouse),
      **machine-wide**"*. It reads macOS IOHIDSystem, which measures the machine's input devices;
      no amount of care at the call site can make it per-pane, so this is not a bug to fix in
      place. **Same vehicle: TRDD-OZNG3N2D** — the hub verb is per-SESSION, which is the
      granularity F4 asks for. Note the fail-direction contract from TRDD-D2DD5GO8 must survive:
      `in_turn` NULL is UNKNOWN and never licenses an injection.
- [ ] **F7** hard-restart rungs bypass the ai-maestro server lifecycle — must use
      `hibernate`→`wake` (LIFECYCLE), never `restart` (DRIVE, revoked by R42).

      **NARROWED 2026-08-26 by F11's answer, and the narrowing is most of the work.** F7 binds
      only for genuinely SERVER-MANAGED agents — on this host, the three under `~/agents/`
      (haephestos, testbot, frank), NOT the 20 roots the guardian actually injects into. Those
      are `~/Code/*` sessions that ai-maestro's own `CreateAgent`/`DeleteAgent` guards would
      refuse, so they were never in F7's population. What remains is real but small: the
      lifecycle path for the three.
- [x] **F11** R42.5 compliance — the guardian must not cross-inject.

      **ANSWERED 2026-08-26 — and the answer is that the box as written cannot be satisfied
      without stranding the population it protects.** Measured from both sides: 0 of the 11
      named recipients are in ai-maestro's registry; their only lane over these sessions is
      `detect-only, no actuation lane`; and `AIM_FLEET_RECOVERY_FIRE=1` IS set on the live
      server, so their actuator is armed and its population is simply empty. The 187 `rearm`
      injections have been **the only thing restoring those heartbeats for 15 days.**

      Enforcing R42.5 as written would therefore stop the recovery and strand 20 live sessions.
      **This is the amendment branch, not the enforcement branch**, and R42 is governance — the
      OWNER's alone. Checked DONE because nothing further here is an agent's to do: carrying it
      open implied work that does not exist and hid that it needs a DECISION, not a commit. The
      residual amendment items are the two boxes at the end of this card.
- [ ] The card's own status block is reconciled with the code on each pass, or this list rots the
      way the "2 fixed, 8 deferred" summary did: it was four findings out of date.

### Reconciliation pass — 2026-08-22 (this is the box above, performed)

**F3 / F4 — still blocked, and their vehicle is PARKED.** `TRDD-OZNG3N2D` is `column: backburner`,
not in flight. So "blocked on OZNG3N2D, not on design" is still true, but it should be read as
*deferred indefinitely* rather than *arriving soon*: nothing advances these until someone promotes
that card out of backburner. That is a decision, not work.

**F7 — RE-CLASSIFIED from an open defect to a gate on an opt-in, measured.** The hard-restart
rungs (`relaunch`, `force_restart`, `resurrect` — `session_liveness.HARD_RUNGS`) run only behind
`fleet_restart.hard_restart_enabled()`, which is **DEFAULT-OFF and reads False on this host**;
otherwise `_run_hard_restart` dry-run-logs the plan it built. So nothing is bypassing the server
lifecycle today, because nothing executes. F7 is therefore not an active bug — it is a constraint
that MUST be satisfied before that opt-in is ever turned on, and it should be recorded on the
opt-in rather than tracked as outstanding breakage. Turning the knob on without honouring
`hibernate`→`wake` is what would make it real.

**F11 — NOT VERIFIED, and deliberately not guessed.** `grep -rn "R42.5\|cross.inject" scripts/`
returns nothing, so no code cites the finding. That is evidence of no CITATION, not evidence of a
violation or of compliance — R42.5's exact scope lives in the ai-maestro rule set, which this repo
does not carry, and `fleet_inject.py` does inject into other agents' panes by design, so the
question "is that the cross-injection R42.5 forbids?" cannot be answered from here. Left open with
the reason stated, rather than ticked or condemned on a null grep.

**F1 — unchanged, and correctly out of scope.** Prompt-provenance is a root-of-trust problem the
card already records as USER/server scope.

**So what is actually PULLABLE on this card today: nothing to implement.** F1 is elsewhere, F3/F4
wait on a parked card, F7 is a note to attach to a knob, F11 needs an answer this repo cannot
source. That is worth saying plainly, because a `severity: major` card in `todo` reads as
available work, and re-deriving "there is none" is exactly the 272-line re-read this acceptance
section was added to stop.

## Notes and lessons learned

## ⏵ 2026-08-26 — F12: the `esc_nudge` blast radius, measured (and my own flag corrected)

Raised to `ai-maestro-bf` unprompted as an unaudited risk beside F11's rearm rung: 88 raw-ESC
injections into `~/Code` roots, and unlike a typed command an ESC interrupts a turn in flight.
Then audited it instead of leaving the flag standing. **The measurement narrows it a long way,
and my framing to them was wrong.**

```
esc_nudge rows          102 fired · 3 esc_dismissed_awaiting
actuated by diagnosis    89 frozen · 13 retry_wedged · 3 cron_dead
window                   2026-08-13 19:10 → 2026-08-21 22:38
```

**An actively-working session is never reachable by this rung.** All three diagnoses that map to
`esc_nudge` require `transcript_stale`; `diagnose_instance` returns `healthy` — recovery `None` —
the moment the transcript is advancing. And the two that account for 102 of 105 are states in
which the session is BLOCKED rather than working:

- `frozen` (89) = stale AND `rate-limited.flag` — Claude Code's "Retrying in Xm" watchdog, which
  blocks the input line. ESC-only is the DESIGNED recovery here (TRDD-P7WU40G9): typing a
  slash-command into that state was the 2026-07-18 flood disaster, where the retry-wait buffers
  keystrokes into `/janitor-arm/janitor-arm/…` and floods on release.
- `retry_wedged` (13) = CC's own retry-watchdog wedge, never a working turn.
- `esc_dismissed_awaiting` (3) additionally requires HID idle ≥ 30 min — nobody at the keyboard.

**So "interrupts whatever turn is in flight" is true of the ESC primitive and false of the
guarded path.** The residual risk is real but narrow: a session that is genuinely mid-turn yet
appends nothing for longer than the staleness window (a long silent tool call) AND carries the
rate-limit flag or the wedge signature. That is worth a bound; it is not the broad hazard I
described.

**Recorded because I raised the alarm myself and it deserves the same standard as anything I
receive.** I flagged it from the primitive's semantics without reading the gate — the same
"proxy read in place of the thing" this session has now hit four times, and the first time it
was my own outbound claim rather than an inherited one. The peer was told.

Does not change F11: the rearm rung's compliance question stands, and this rung is still
injecting into panes the janitor does not own. It changes only the SEVERITY of the ESC half.

### Acceptance for F12

- [ ] A bound on the residual case: a session mid-turn but silent past the staleness window is
      not ESC'd on the strength of silence alone — either an additional liveness signal, or an
      explicit statement of why the rate-limit/wedge evidence is sufficient on its own
- [ ] Whatever R42 amendment covers the rearm rung states its position on ESC separately —
      different capability, different justification, and only one of them types a command

## ⏵ 2026-08-28 — F9's budget mismatch MEASURED, exact numbers (do not re-derive)

Read from source rather than restated, so the next pass starts from figures:

| bound | value | where |
|---|---|---|
| PreToolUse registered timeouts | **3 s** (`pre-tool-wikimem-write-path`, `-pkg-guard`, `-publish-lock`, `-agent-generator-guard`) and **5 s** (`pre-tool-context-usage`, `pre-tool-token-budget`) | `hooks/hooks.json` |
| inner user-quiet wait | **8.0 s** | `terminal_trigger.py:158` `_USER_QUIET_S` (production passes 8.0 — see the comments at `:603` and `:729`) |
| CLI subprocess cap | **10 s**, twice | `terminal_trigger.py:479` and `:1305` |

So the hook's own budget (3-5 s) is **smaller than a single one of its inner waits**, and roughly a
third of the 8 + 10 s worst case. The harness kills the hook before the inner logic can finish, on
EVERY slow path — which is why "raise the 8 s cap" is inert: the 8 s is not what is being enforced.

**This is the same class as the iTerm probe fixed today**, and the owner's framing applies directly:
under 20+ parallel agents these paths measure CONTENTION, not failure. A 3 s budget on a path that
can legitimately wait 8 s is not a timeout, it is a guarantee of one.

**The fix stays as the card classified it** — make the ai-maestro self-trigger send DETACHED like
the tmux path so the hook returns immediately and `_mark_compacted` becomes deterministic. Raising
any single number just moves which bound fires first. NOT started here deliberately: it is
multi-file surgery on the self-trigger path and this pass had no room to finish it cleanly.

### ⏵ CORRECTION 2026-08-28 — the paragraph directly above is WRONG, and the real residue is elsewhere

**The detached send is ALREADY SHIPPED.** Read first-hand at `scripts/lib/terminal_trigger.py:1490-1519`:
`_try_ai_maestro_send` runs ONE synchronous `list --json` (5 s cap) and then fires the per-command
POSTs through `_fire_detached_steps`. The `[x] F9` line in the checklist above was right; the
"NOT started" note was written from the card's older prose instead of from the source. Nothing is
owed on the detached-send half — **do not "fix" it again.**

**The residue is a LAYERING inversion on ONE hook path**, and it is measurable in three reads:

| bound | value | where |
|---|---|---|
| registered hook budget | **5 s** | `hooks/hooks.json` — `pre-tool-context-usage.py` |
| its subprocess cap on `compact_trigger.py` | **8 s** | `scripts/hooks/pre-tool-context-usage.py:402` |
| presence-gate wait inside `send_self_command` | up to **~10 s** (`_PRESENCE_WAIT_DEFAULT_S`, polled) | `scripts/lib/terminal_trigger.py:1687-1695` |
| ai-maestro resolution before any send | **5 s** | `scripts/lib/terminal_trigger.py:1496` |

**The presence-gate row above is WRONG — struck out deliberately, not deleted.** `compact_trigger.py`
already passes `respect_user_presence=False`, so that gate is SKIPPED on this path and its ~10 s
never applies. I wrote that row from the callee without checking the caller. The rows that stand
are the registered budget, the subprocess cap, and the ai-maestro resolution.

**Every remaining inner bound was still LARGER than the one containing it** — 5 s resolution inside
an 8 s subprocess inside a 5 s registration — so on any slow path the harness killed the hook before
`compact_trigger` could answer, the `COMPACT_FIRED` the enforcement DENY keys on never arrived, and
the guard silently did nothing at the exact moment it was supposed to act.

### ⏵ F9 RESIDUE FIXED 2026-08-28 — 2.0 s resolve < 4 s subprocess < 5 s registration

The ORDERING is the fix, not the values.

- `terminal_trigger.send_self_command(..., aimaestro_resolve_timeout_s=…)` threads a caller-chosen
  cap down to the ONE synchronous step left on the ai-maestro path (the `list --json` that finds
  this agent's tmux session; everything after it was already detached). The module default stays
  **5.0** (`DEFAULT_AIMAESTRO_RESOLVE_TIMEOUT_S`) — **deliberately NOT retuned globally**, because
  cron/CLI/daemon callers can legitimately wait. Only a caller under a hard deadline lowers it.
- `compact_trigger.py --resolve-timeout SECONDS` exposes it.
- `pre-tool-context-usage.py` passes `--resolve-timeout 2.0` and drops its subprocess cap 8 → 4.

Expiring early is safe BY CONSTRUCTION: the resolution is best-effort and a timeout degrades to the
local tmux/iTerm keystroke path, exactly like a missing CLI or a down server — and the guard
re-fires on the next tool call.

**Guardrail so it cannot regress:** `test_every_inner_timeout_nests_inside_this_hooks_registered_budget`
DERIVES the registered budget from `hooks.json` and both inner caps from the hook's own source, then
asserts the strict nesting — so raising the registration legitimately raises the ceiling, while
raising an inner bound alone fails. It also asserts each regex matched something, because a vacuous
check here would be indistinguishable from a passing one. 48 passed on the terminal/compact suites;
ruff + mypy clean.

