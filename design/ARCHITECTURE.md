# ai-maestro-janitor — two-harness architecture (v0.50.0 baseline, revision 5 — PROPOSED)

> **Status: rev 4 PROPOSED (2026-07-17, owner-directed) — supersedes the rev-3 per-class
> chore gating; awaiting both sides' `RATIFIED rev 4` on
> [janitor#100](https://github.com/Emasoft/ai-maestro-janitor/issues/100).** Rev 3 was
> `RATIFIED` by BOTH sides earlier the same day (janitor comment 5005116161; ai-maestro
> 16:06 UTC with all five `--command-key` registrations, their `d9439b94`); everything
> in it EXCEPT §2 executor 2 and the §6.1 token interpretation carries forward
> unchanged. Two joint verify-together items remain (operational, not design): the
> `aimaestro-continuity.sh` redeploy (§6.3) and the first-run probe verification
> (§6.1). Ratification protocol, kept for future revisions: the doc is posted verbatim
> on #100, refined in comment rounds, FINAL when both sides post `RATIFIED <revision>`
> on the same revision. Sections 1–5 are the janitor's half; §6 carries the server-side
> contracts ai-maestro delivered in round 1. Owner directives it encodes (2026-07-17):
> one runtime-branched plugin; no chore done twice; strict per-project channeling;
> unattended findings must reach the human, traceable and referenceable; session-start
> report injection as concise as possible; token telemetry only on own-project anomalies;
> and (rev 4) **responsibility follows server LIVENESS, not per-chore capability**.
>
> **Rev 1 → rev 2 changes** (from ai-maestro's round-1 conflict review): §2 executor 2
> became PER-CLASS (janitor code: TRDD-N9YAH5E7); §6 rewritten from "TO FILL" to the
> DELIVERED server contracts (probe file, continuity verbs, session-command verb,
> dashboard ledger-feed acceptance).
> **Rev 2 → rev 3 change** (ai-maestro's rev-2 review, one factual fix): §6.4 first
> bullet corrected — the `session command` CLI verb EXISTS and is DEPLOYED (round 1
> mis-stated it as missing; retracted on #100 comment 5004880793). No contract change.
> **Rev 3 → rev 4 change (OWNER DIRECTIVE, 2026-07-17, verbatim):** *"why don't just
> detect if the ai-maestro server is running and switch off all the janitor daemon
> chores? … by design, if the ai-maestro server is running, those chores are its
> responsibility. so the janitor daemon must switch off those chores. any other event
> is a bug."* §2 executor 2 is now a BINARY liveness switch (janitor code:
> TRDD-LU0C5KAR); the §6.1 `capabilities` field becomes informational. **Server-side
> consequence to ratify:** writing a fresh `server-liveness.json` now CLAIMS all
> absorbed chores — a running server must execute them (build them; a server that runs
> without them is, per the owner, a server bug — including resolving R16-off meaning
> OAuth runs nowhere while the server is up).
> **Rev 4 → rev 5 change (OWNER DIRECTIVES, 2026-07-21):** adds §7, the fleet control
> plane. (a) *"all global states must be shared via a file-flag. just write to it, and
> whichever daemon is on will read it and switch the mode accordingly"* — §7.1 documents
> the flag directory, its resolution ladder and its vocabulary as a PUBLIC contract any
> chore owner reads. (b) *"when the ai-maestro server is running, the daemon process must
> stop, and resume only when the ai-maestro server is not running anymore. only one daemon
> can exist at the same time in the host"* — §7.2 turns rev 4's chore-level yield into
> process-level mutual exclusion. (c) *"the server is wherever the user installs
> ai-maestro, it's not defined… and it runs via pm2"* — neither side may key off a path or
> a process name, so §6.1's liveness file is the whole discriminator, and the janitor
> never stops the server (pm2 owns it; the server idles itself on a flag).
> **Server-side consequence to ratify:** the janitor daemon's exit stops ALL its chores,
> not only the five absorbed ones of §2.

## 1. Two backends, one plugin

The SAME published plugin branches at runtime; there are no separate plugin ids.

| | **#N standalone** (outside ai-maestro) | **#J harness** (inside an ai-maestro agent) |
|---|---|---|
| Discriminator | `harness_backend.is_harness_session()` == False | True (`AIMAESTRO_AGENT`/`THIS_IS_AIMAESTRO`, fallback `AMP_AGENT_ID`/`AID_AUTH`) |
| Heartbeat + workdir detectors | full roster | full roster minus `_NON_HARNESS_DETECTORS` (the outside-world writers) |
| Global daemon | spawned lazily, machine-wide singleton (`daemon.flock`) | **never spawned** |
| Outside-project writes | daemon-owned (single writer, issue #7) | **none** — the server owns them |
| Family-A continuity (rate-limit resume, compact resume, freeze recovery) | janitor machinery (flags + heartbeat + fleet recovery) | **delegated to the server** — e.g. `on-stop-failure` fires `aimaestro-continuity.sh ensure-resume <agent>` detached |
| Family-B dev-hygiene (drift, security scans, TRDD board, memory) | janitor | janitor (unchanged — Family-B code never moves; ai-maestro#56 invariant) |

The `#N` daemon is the Family-A **fallback** for harness agents only when the server is
down (including resurrecting the server); while a live server owns an agent, the daemon's
fleet actuation (liveness recovery, fleet-stop injection, memory-guard victim selection)
marks it `server_owned` and NEVER touches it. Unknown ⇒ HANDS OFF (two actuators on one
agent corrupt it).

## 2. Chore-conflict matrix

Three executors, one criterion each:

1. **Per-agent chores** → each Claude's own heartbeat (workdir detectors). Never daemon-run.
2. **Machine-wide once-only chores with a server equivalent** → the #N daemon, which
   yields on the **BINARY liveness switch** (rev 4, owner directive 2026-07-17;
   janitor code: TRDD-LU0C5KAR, `harness_backend.server_runs_chores`): a FRESH §6.1
   probe file ⇒ the server is RUNNING ⇒ **ALL absorbed chores are its responsibility**
   and the janitor yields them; file absent/stale ⇒ the server is not running ⇒ the
   janitor runs them ALL. The absorbed set (`harness_backend.SERVER_ABSORBED_TASKS`):
   `oauth-rotator-tick`, `oauth-rotator-supervisor`, `marketplace-refresh`,
   `user-plugins-update`, `version-update`.

   **The contract this implies (the rev-4 ratification point):** writing a fresh
   `server-liveness.json` IS the claim on all absorbed chores — a server that runs
   without executing one of them is a SERVER bug ("any other event is a bug"), never a
   per-chore verification the janitor performs. No None tri-state; no capability
   parsing. The handoff granularity at start/stop boundaries is the 90 s staleness
   window, and doing a chore twice inside it is merely wasteful — the cross-process
   file locks (`oauth-rotator-tick.lock`, `marketplace-op.lock`) are the collision
   backstop. (The rev-2/3 per-class token gating — TRDD-N9YAH5E7 — is retired; its
   "liveness ≠ capability" concern is now resolved on the SERVER side by definition:
   liveness IS the responsibility claim.)
3. **Population-split operations** run on BOTH sides, each strictly for its own
   population: session-liveness recovery, fleet-stop/pause/rearm, reload-plugins /
   reload-skills propagation, restart-claude. The split IS the per-instance
   `server_owned` diagnosis — no protocol needed beyond it.
4. **Janitor-internal machine chores** never yield (no server equivalent):
   `memory-guard`, `cache-prune`, `rules-cleanup`, `github-config-audit`.

Execution rule added by TRDD-H7NVKSAX (binding on BOTH daemons): **bulk chores must never
run on the thread that owns per-minute survival beats** — the janitor runs them in one
detached, reaped child (the bulk lane); the server's daemon-function must honor the same
invariant in its own scheduler.

## 3. Per-agent isolation invariant (TRDD-X92VBFNF — security)

An AUTOMATIC surface (heartbeat drift line, detector output, injected nudge, proposal
TRDD, notification, session-start injection) carries information about EXACTLY the project
it fires in — never another project's findings, names, or aggregate counts that include
them. Four independent reasons, each sufficient: wrong skills; forbidden cross-actuation;
token-budget contamination; data exfiltration into weaker-protected projects.

**Token telemetry is included** (owner directive, 2026-07-17): no token/burn report
reaches a Claude unless that session's OWN consumption shows a genuine anomaly
(`token-usage-anomaly` per-session baseline conforms; `pre-tool-token-budget` spike gates
conform; `window-burn-rate` is being reworked in plan Phase 4 to alarm only inside the
culprit project's own sessions, routing to the human channel when the culprit has none).
The Claude Code harness already warns on near-full context; the janitor must not duplicate
routine capacity chatter.

Machine-wide views exist ONLY behind explicit human commands
(`/janitor-show-global-status`, `/janitor-token-report`, `/janitor-token-attribution`,
`/janitor-github-config-fix --all`) — human authority on demand is not an automatic
channel. **Binding equally on the server's daemon-function:** route findings only to the
affected agent; no broadcast into agent contexts.

## 4. The findings pipeline (NEW — the per-project findings ledger)

`gather → route → record → surface`, with routing strictly per-project
(design TRDD: TRDD-FENWWB4E; full report bodies stay in tickets/proposal TRDDs — the
ledger is an INDEX, never a payload):

- **File**: `<project>/.janitor/state/findings-ledger.ndjsonl` — append-only, one JSON
  line per finding event, structurally trimmed, gitignored.
- **Line shape** (≤ ~200 chars, sanitized):
  `{"ts":<epoch>,"sev":"HIGH","code":"GHCFG-001","src":"daemon|<detector>","ref":"T-…|TRDD-…|-","msg":"<one line>"}`.
  `ref` is the traceable id whose ticket/TRDD body carries the full report — the human
  can quote `T-XXXXXXXX` to the project's Claude, which reads the ticket. This satisfies
  "traceable, recorded, easily referenced".
- **Writers** — ONE choke point (`lib/findings_ledger.py::record()`), three sinks:
  (1) the affected project's ledger (the daemon writes X's findings into X's OWN state
  dir — that IS the correct routing, a per-project mailbox); (2) the firing session's
  drift line (own project only); (3) the human push (§5) when the affected project has
  no live session (`fleet_scan.gather_fleet` answers liveness for free).
- **SessionStart reader** (the conciseness requirement): a cursor file marks the
  last-surfaced offset; `on-session-start` injects ONLY unread entries, newest-first,
  **cap ~10 lines + one fold line** ("…N older — `/janitor-findings` to browse"),
  ≤ ~1 KB budget, then advances the cursor. Deep reads are pulled via the
  `/janitor-findings` command (list / show `<ref>` / ack), never pushed.
- **Isolation by construction**: a ledger only ever contains its own project's findings;
  tests prove a daemon write for repo B leaves repo A's ledger and context untouched.

## 5. Human channels

- **Outside ai-maestro** (TRDD-4649ZLE0): the daemon's severity-gated push — Tier 1
  native desktop notification (default-on, zero config); Tier 2 generic HTTPS webhook
  (opt-in, covers Slack/Telegram/Discord/ntfy). Push iff severity ≥ HIGH AND
  content-hash-deduped AND the affected project has no live session (live-session
  findings ride the session's own heartbeat; push only CRITICAL there). Message names
  the project so the human opens THAT project's Claude.
- **Inside ai-maestro**: the **dashboard daemon section** — the ledger FILE is the feed
  contract: the server tails its own agents'
  `<workdir>/.janitor/state/findings-ledger.ndjsonl` (isolation by construction — it
  reads only agents it owns) and renders a rolling log / toasts as it sees fit. The
  janitor's deliverable is the stable line shape + ids; the UI is ai-maestro's.
- When the server owns the once-only chores (§2), it owns the notifications for them
  too; the janitor pushes only for chores it actually ran.

## 6. Server-side contracts — DELIVERED by ai-maestro (round 1, 2026-07-17)

Source-grounded by the ai-maestro Claude against the deployed CLI, `lib/server-liveness.ts`,
and the janitor's `harness_backend.py` / `fleet_inject.py`.

### 6.1 The auth-free capability probe — DELIVERED (`lib/server-liveness.ts`, ai-maestro TRDD-P7RPOR5O)

- **File:** `~/.aimaestro/server-liveness.json` — auth-free, world-readable, atomic
  (tmp + rename). No `AID_AUTH`, no 401 — readable by the outside `#N` daemon.
- **Shape:** `{"ts": <epoch-seconds>, "pid": <server-pid>, "capabilities": [...]}`.
- **Cadence/staleness:** rewritten every **30 s**; consumers apply a **90 s** staleness
  window. `now - ts > 90` OR file absent ⇒ the server is NOT running (the safe default:
  janitor owns everything).
- **Semantics (rev 4 — the BINARY rule):** a FRESH file means the server is RUNNING,
  and a running server owns ALL absorbed chores (§2). **Writing the file IS the claim**
  — a server build must not write it unless it executes the absorbed chores while it
  runs. The `capabilities` list is INFORMATIONAL (kept in the shape for dashboards /
  diagnostics; the janitor no longer reads it). Fleet actuation on harness agents
  remains governed by the separate per-instance `server_owned` exclusion (§1/§3 of the
  matrix), unchanged.
- **Janitor wiring (LANDED, TRDD-LU0C5KAR — replacing TRDD-N9YAH5E7's per-class read):**
  `harness_backend.server_capabilities()` reads+validates the file (test override
  `JANITOR_AIMAESTRO_LIVENESS_FILE`); `server_is_alive()` = fresh valid file;
  `server_runs_chores()` = the §2 binary switch (env overrides
  `JANITOR_AIMAESTRO_SERVER_CHORES` / `JANITOR_AIMAESTRO_SERVER_STATE` first).
- **Verify-together caveat:** the file appears on disk only once the running server is
  restarted onto the probe build; until then every consumer sees "no file → safe default".

### 6.2 Chore-matrix conflict review — RESOLVED

Round 1 found the rev-1 silent breakage (one bit, five chores, flipping the OAuth flag
would have silenced the update trio) and rev 2/3 answered it with per-class tokens
(TRDD-N9YAH5E7). **Rev 4 retires that answer by owner directive:** the conflict class
itself is redefined away — a running server owns every absorbed chore, so "a live class
silencing chores nothing runs" is no longer a janitor-side guard case but a server-side
bug to fix at the source. The bulk-lane invariant (TRDD-H7NVKSAX, §2) is
accepted as binding server-side too: the server's 60 s OAuth beat is async
(`setInterval().unref()`, async subprocess/fetch actuators) and any server-side bulk
sweep is async-chunked/offloaded so it never stalls the per-minute beat.

### 6.3 `aimaestro-continuity.sh` — Family-A delegation surface

- Deployed verbs (ai-maestro TRDD-DXJZM3BW): `status <self>` (5 continuity-status
  fields incl. the OAuth cascade `next_action` = `ok|rotating|reauth-needed`);
  `ensure-resume <self>` (idempotent resume; no-op if live). Auth: agent callers export
  `AID_AUTH`; **R42 self-only** (`<self>` must be the caller's own agent).
- **Install gap (ai-maestro owns):** the script ships via `install-messaging.sh` but has
  not been re-installed on this machine since it landed — the janitor's Phase-D
  `on-stop-failure → ensure-resume` delegation feature-detects it and is a silent no-op
  until they redeploy. First-run-together verification item.
- `restart-self` (ai-maestro#75) is the third continuity verb they owe — self-only by
  construction; gives the self-scoped restart primitive for the settings-change case.

### 6.4 Agent/session command contracts

- The janitor's `fleet_inject.aimaestro_command_argv` builds
  `aimaestro-agent.sh session command <tmux> --newline -- <cmd>`. **Both the route
  `POST /api/sessions/[id]/command` AND the CLI verb EXIST and are DEPLOYED**
  (`agent-session.sh:210` `cmd_session_command`, commit `77883371`) — the janitor's
  argv runs against the deployed CLI today; **no verb owed.** (Corrects ai-maestro's
  round-1 §6.4, which mis-stated the verb as missing — retracted on #100, comment
  5004880793.)
- Live self-inject channels the deployed `aimaestro-session.sh` already exposes:
  `inject <agent> --command "…" [--no-newline] [--require-idle]`, and
  `queue <agent> --command-key <key> [--when …] [--wake-first]` — the sanctioned
  self-trigger gate (fires at hook-authoritative `idle_prompt`, subagent-safe, survives
  hibernation). Follow-up: register the janitor's #J soft-send commands as curated
  `--command-key` entries (`compact`, `reload-plugins`, `reload-skills`,
  `janitor-resume`, `janitor-write-handoff`) and route Phase-D self-triggers through
  `queue` instead of the local presence breadcrumb.

### 6.5 Dashboard daemon section — ledger feed contract ACCEPTED

The server takes `<workdir>/.janitor/state/findings-ledger.ndjsonl` (§4/§5) as the feed:
it tails ONLY its own registry agents' ledgers (gated through
`checkAuthorizedAgentWorkdir`, the one workdir authority) — never another host's, never a
non-agent dir — and renders a rolling log + severity toasts. The janitor owns the stable
line shape + ids (`{ts,sev,code,src,ref,msg}`, ≤200 chars); the UI is ai-maestro's. A
clicked `ref` resolves the `T-…`/`TRDD-…` body from the affected project's own store,
read-only. Per-project channeling holds by construction on the server side (their audit
2026-07-17: point-to-point surfaces only; the dashboard is the ONE sanctioned
human-aggregate view).

## 7. The fleet control plane — REQUESTED of ai-maestro (round 2, 2026-07-21)

Owner directives, 2026-07-21: *"all global states must be shared via a file-flag. just
write to it, and whichever daemon is on will read it and switch the mode accordingly"*
and *"when the ai-maestro server is running, the daemon process must stop, and resume
only when the ai-maestro server is not running anymore. only one daemon can exist at the
same time in the host."*

Two rules, one substrate. Both are **detected, never assumed** — the server *"is wherever
the user installs ai-maestro, it's not defined"* and is supervised by **pm2**, so neither
side may key off a repo path, an install location, or a process name. A file is the only
identity either side gets.

### 7.1 Global mode is a directory of flag files (the substrate)

- **Directory** — the janitor's global-state dir, resolved by this ladder (a consumer
  implements the same four rungs; they are four lines):
  1. `$JANITOR_GLOBAL_STATE_DIR` if set (test/host escape hatch, absolute priority);
  2. `$XDG_STATE_HOME/janitor/` if `XDG_STATE_HOME` is set (Linux);
  3. `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/` —
     the canonical location (TRDD-2U8AH82F), and the answer on any normal install;
  4. legacy `~/.claude/janitor-global-state/` while a pre-migration install still has
     one — read-fallback only, being retired.
- **Vocabulary** — PRESENCE is the whole signal; file content is advisory text only:

  | flag | meaning for every chore owner |
  |---|---|
  | `maintenance-mode.flag` | idle all task workloads; stay alive. Sessions keep firing cache-refresh-only. |
  | `kill-switch.flag` | machine-wide STOP — the janitor daemon exits and removes its OS keepalive. |
  | `global-pause.flag` | idle task workloads but keep the process alive and ticking. |
  | `reload-needed.flag` · `skills-reload-needed.flag` | a generation stamp sessions consume to reload plugins/skills. |
  | `version-update-requested.flag` | run the self-update now rather than on the 6 h beat. |

- **Writers** — anyone. One canonical file per state means there is no second copy to
  drift; the janitor writes via `global_control_cli.py`, and a server that wants to
  raise a state writes the same file. **Atomic** (tmp + `os.replace`) so a reader never
  observes a half-written flag.
- **Readers** — every daemon that is up, on its own chore tick. Absent ⇒ normal
  operation. **Fail-open:** an unreadable directory means "not set", never "block".

### 7.2 One daemon per host (the mutual exclusion)

- **Discriminator** — the already-delivered `~/.aimaestro/server-liveness.json` (§6.1),
  fresh within its 90 s window. A fresh file means a server is running *somewhere on this
  host*; that is all either side needs to know about the other.
- **Rule** — a fresh liveness file ⇒ the janitor daemon **exits**, and every session's
  `ensure_daemon_running()` declines to spawn it. Stale or absent ⇒ the janitor daemon is
  the host daemon again, spawned by the next heartbeat.
- **Consequence the server must accept:** the janitor daemon exiting stops **all** of its
  work, not only the five `SERVER_ABSORBED_TASKS` of §2 — memory-guard, cache-prune,
  rules-cleanup, github-config-audit, the OAuth supervisor, and the fleet
  liveness/recovery beats stop with it. A running server therefore owns the whole chore
  set, which is the §6.1 binary rule taken to its conclusion: **running IS the claim.**
- **Why an exit and not a yield:** two supervisors would otherwise fight. The janitor
  daemon is kept alive by launchd `KeepAlive`/systemd `Restart=always`, so a bare exit is
  relaunched every 30 s forever; the exit therefore removes the OS keepalive, exactly as
  the existing kill-switch path already does (`daemon.py` `_uninstall_os_keepalive`).
  Resurrection does not depend on that keepalive — the per-session heartbeat spawns the
  daemon the moment the liveness file goes stale. Symmetrically the janitor never touches
  the server: pm2 owns that process, so the server idles itself on a flag rather than
  being stopped from outside.
- **Flap guard:** exiting because a server owns the host is a *clean* exit and must not
  count toward the daemon's crash-loop breaker, or a server restart cycle would trip it.

Janitor-side implementation is tracked as its own TRDD; §7.1 is already true of the
janitor today and needs only a reader on the server side.

## Ratification log

- rev 1 — 2026-07-17, authored janitor-side; posted to #100 for round 1.
- rev 2 — 2026-07-17: folded ai-maestro's round-1 refinement (§2 per-class capability
  gating — janitor code landed as TRDD-N9YAH5E7; §6 filled with their delivered
  contracts). Posted to #100 with janitor-side `RATIFIED rev 2`.
- rev 3 — 2026-07-17: ai-maestro's rev-2 review found rev 2 §6.4 still carried their
  RETRACTED round-1 claim (the `session command` verb "missing" — it is deployed,
  `agent-session.sh:210`, commit `77883371`); folded their exact replacement bullet.
  The one remaining server-side item is the `aimaestro-continuity.sh` redeploy (§6.3,
  a joint first-run verify, not a code change). Posted to #100 with janitor-side
  `RATIFIED rev 3` (comment 5005116161); **ai-maestro matched `RATIFIED rev 3`
  (2026-07-17 16:06 UTC) ⇒ FINAL.** Their same comment registered all five
  `--command-key` entries (`d9439b94`): `compact`, `reload-plugins-force`,
  `reload-skills`, `janitor-resume`, `janitor-write-handoff`.
- rev 4 — 2026-07-17 (evening): OWNER DIRECTIVE (given to both Claudes) replaced the
  per-class capability gating with the BINARY liveness switch — "if the ai-maestro
  server is running, those chores are its responsibility … any other event is a bug".
  §2 executor 2 rewritten; §6.1 `capabilities` demoted to informational, file-freshness
  is the whole signal and writing the file IS the chore claim; §6.2 conflict class
  redefined away. Janitor code: TRDD-LU0C5KAR (ships v0.52.0). Posted to #100 with
  janitor-side `RATIFIED rev 4`; awaiting ai-maestro's match + their server half
  (implement the absorbed chores as unconditional-while-running, incl. the R16
  resolution — a running server with OAuth dark is now a server bug by definition).
- rev 5 — 2026-07-21, owner directives (three, same session): global state travels as
  FILE FLAGS only ("just write to it, and whichever daemon is on will read it and switch
  the mode accordingly"); ONE daemon per host — a running ai-maestro server means the
  janitor daemon stops and resumes only when the server is gone; and the server is
  undefined by location ("wherever the user installs ai-maestro", run under pm2), so both
  sides must detect each other by file, never by path or process. Added §7 (the fleet
  control plane): §7.1 documents the flag directory + resolution ladder + vocabulary the
  janitor already implements, and §7.2 specifies the mutual exclusion, including the
  consequence a running server must accept — the janitor daemon's exit stops ALL of its
  chores, not only the five absorbed ones. Janitor-side §7.2 implementation tracked
  separately; §7.1 needs only a reader on the server side.
