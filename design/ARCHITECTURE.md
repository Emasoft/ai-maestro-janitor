# ai-maestro-janitor — two-harness architecture (v0.50.0 baseline, revision 7 — PROPOSED)

> **Status: rev 7 PROPOSED (2026-07-24) — revs 5–7 are authored janitor-side and rev 7 is
> not yet posted; and rev 4 still carries only the JANITOR's `RATIFIED` on
> [janitor#100](https://github.com/Emasoft/ai-maestro-janitor/issues/100) — ai-maestro's
> match is outstanding.** (This status line said "rev 4 PROPOSED" while the title said
> revision 7: the header was not updated as revs 5–7 were appended to the log below. A
> ratification contract whose own status line disagrees with its title is worse than an
> unfinished one — each side reads whichever half it happens to look at.) Rev 3 was
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
> whichever daemon is on will read it and switch the mode accordingly"* + *"put it under
> some standard janitor folder"* — §7.1 defines the PUBLIC control plane as a FIXED
> directory, `~/.claude/janitor-control/`, with no resolution ladder, split by audience
> from the private daemon state that stays in `<DATA>/global-state/`. (b) *"when the ai-maestro server is running, the daemon process must
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
   `version-update`, and — since 2026-08-18 (janitor#274, settled by measurement on
   the rev-8 round) — `github-config-audit`. (`user-plugins-update` LEFT the set
   2026-08-19 — TRDD-TIZHEPNC / ai-maestro TRDD-PE54D95Q AC6 — and was then RETIRED
   from the chore roster entirely 2026-08-20, TRDD-E39YT9G6: the Claude Code harness
   self-updates installed plugins, so no bulk sweep exists anywhere; the daemon keeps
   only the targeted per-plugin requests-consumer.)

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
   `memory-guard`, `cache-prune`, `rules-cleanup`. (`github-config-audit` left this
   class 2026-08-18 — the server has executed and stamped it since 2026-08-05, so it
   is absorbed, class 2; janitor#274.)

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

**Additive amendment 2026-08-13 — the OPTIONAL `actor` key.** A human-only finding (one
whose remedy is a GUI toggle or a credential decision an agent structurally cannot
perform) now carries `"actor":"human"`; the `HUMAN_ONLY_DIRECTIVE` prose it used to be
spelled with is applied by `render_line` at delivery instead. Rendering a finding the
janitor marked human-only should carry that marker through, but a consumer that reads
named fields needs no change: an entry WITHOUT the key is byte-identical to the original
shape, and a human-only entry is now SHORTER than before (the 98-char directive left
`msg`; the key costs ~17), so the ≤200-char promise is honoured more comfortably, not
less. The change was forced: the directive was concatenated onto `msg` ahead of the
120-char cap, so marking a finding human-only truncated it to 22 characters of itself —
the feature destroyed the content it was meant to escalate.

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

- **Directory — `~/.claude/janitor-control/`, FIXED.** No ladder, no resolution logic, no
  environment lookup: an external chore owner stats a literal path. Owner directive
  2026-07-21: *"put it under some standard janitor folder."*

  This is a deliberate split by AUDIENCE, and it is **not** a reversal of TRDD-2U8AH82F
  (which moved daemon state out of `~/.claude/janitor-global-state/` into the plugin DATA
  dir — TRDD-ULEGRT01 later retired that legacy dir's read-fallback entirely, so resolution
  no longer falls back to it at all). That migration was about STATE — pid, flock, heartbeat,
  last-run stamps, injection stamps — which must survive plugin updates and be purged on
  uninstall, and
  which stays in `<DATA>/global-state/` under the standing "prefer `${CLAUDE_PLUGIN_DATA}`
  over a custom `~/.claude/` folder" principle. The control plane is the opposite kind of
  thing: a handful of ephemeral MODE flags whose whole purpose is to be read by software
  that knows nothing about this plugin's internals. Surviving an uninstall is not merely
  unnecessary for them, it is wrong — an uninstalled janitor must leave no flag behind
  claiming the host is in maintenance. The DATA dir's four-rung resolution ladder
  (`$JANITOR_GLOBAL_STATE_DIR` → `$XDG_STATE_HOME/janitor/` → DATA → legacy) is exactly
  what a foreign reader cannot safely reproduce: hardcoding rung 3 silently reads the
  wrong file whenever rung 1 or 2 applies.

  `$JANITOR_CONTROL_DIR` overrides the path for TESTS ONLY. Production is the literal
  path — a consumer that honors the override is welcome to, but must not require it.
- **What lives here — the scope rule.** Owner directive 2026-07-21: *"make sure all global
  flags written by the daemon are written in the same folder, so the ai-maestro server
  daemon and the normal daemon process can both share it and always be in synch."* The
  test is **audience, not kind**: if a SECOND chore owner must observe it or contend on
  it, it belongs in the control dir. Splitting coordination data across two directories is
  precisely how the two daemons desynchronise.

  | goes in `~/.claude/janitor-control/` | why it must be shared |
  |---|---|
  | the six MODE flags (below) | either daemon must switch mode on them |
  | the coordination LOCKS — `marketplace-op.lock`, `oauth-rotator-tick.lock`, `settings-ensurer.lock` | §2 names these the collision backstop for the 90 s handoff window. A lock only excludes processes contending on the SAME file — a server holding a lock in a directory the janitor never opens excludes nobody. |
  | the per-chore `*.last-run.ts` stamps | so either owner can see a chore was just done and skip it, instead of both redoing it inside the handoff window |
  | the daemon singleton — `daemon.pid`, `daemon.flock`, `daemon.heartbeat.ts` | makes "one daemon per host" (§7.2) enforceable by CONTENTION rather than only by polling liveness. Moving the flock carries TRDD-2U8AH82F's flock-moves-LAST invariant — take the new lock before retiring the old, or a two-daemon window opens during the upgrade. |

  Stays PRIVATE in `<DATA>/global-state/` — janitor-internal, no second reader, and
  durability is a virtue rather than a defect: `recovery-audit.ndjson`, the
  token-attribution cache, `migrated-from-legacy.ts`, the fleet injection stamps, and the
  `daemon.spawn-attempt.ts` crash-loop ring.

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
- **Provenance is MANDATORY** (added rev 5 after a live incident — see TRDD-QK7M2B0X).
  Each flag body is one line of JSON: `{"set_at": <epoch>, "by": "<actor>", "pid": <pid>,
  "reason": "<free text>"}`. A flag was found set on this host with the bare content
  `"maintenance"` and no way to determine who wrote it — which is how a fleet-wide
  suppression became invisible while `daemon.heartbeat.ts` kept advancing and the daemon
  looked healthy. **Readers still switch on PRESENCE alone**: a malformed or legacy body
  means SET with `by: unknown`, never "ignore the flag". Provenance serves humans and
  diagnostics; it must never gate the switching decision, or a corrupt body would swallow
  a stop signal.
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

Janitor-side implementation is tracked per section: §7.1's move of the mode flags out of
`<DATA>/global-state/` into the fixed `~/.claude/janitor-control/` is TRDD-QK7M2B0X, and
§7.2's mutual exclusion is TRDD-5ZVS1DDP. Everything else in §7.1 — presence-is-signal,
atomic writes, fail-open reads, the flag vocabulary — is already true of the janitor
today and needs only a reader on the server side.

## 8. Retry-wedge recovery — REQUESTED of ai-maestro (round 3, 2026-07-24)

Owner directive 2026-07-24: a session that hits a usage/throttle limit enters CC's
retry-watchdog loop (`429 Rate limited · Retrying in 0s · attempt N/300`, up to 300×). The
turn stays **alive and spinning**, so it never ends — no `on-stop-failure`, no
`rate-limited.flag`, no idle cron. The whole existing freeze-recovery ladder is gated on that
flag (`session_liveness.diagnose_instance` returns `frozen` only when `rate_limited` is set),
so it never engages. The session wedges until a human presses ESC. An EXTERNAL actor pressing
ESC is the only break; **inside a harness agent that actor is the SERVER** (it owns the PTY and
Family-A continuity; the janitor is THIN and HANDS OFF a `server_owned` pane per §1/§3). Janitor
tracking: **TRDD-WKTD5JTC** (the standalone `#N` iTerm/tmux path is janitor Python code; this §8
is the harness `#J` half the server owns). The `is_retry_wedge` matcher SHOULD be shared
byte-for-byte across the standalone Python and the server TS so both agree on "wedged".

**8.1 What to DETECT (server, on each registry agent it supervises).**
- **Surface — the RENDERED alt-screen frame, read from the dashboard's own xterm.js, NOT the raw PTY
  bytes (load-bearing).** CC is a full-screen TUI on the ALTERNATE screen buffer (`\e[?1049h`): it has
  **no scrollback**, and the raw PTY stream is escape-code redraw noise — the retry status line is
  REWRITTEN in place as `attempt N` increments, never a clean appended line — so a byte-grep of the
  stream FAILS. The dashboard ALREADY renders each agent's terminal with an **xterm.js** component, so
  the emulator exists; the detector just reads its grid. Read it from a **server-side
  `@xterm/headless` instance fed the same PTY stream** the dashboard consumes — NOT the browser's
  `Terminal`, because the browser tab is usually CLOSED for an unattended agent, which is exactly when
  the wedge bites; a server-side headless emulator is always present. Read the ALTERNATE buffer:
  `term.buffer.active` (its `.type` is `'alternate'` during the TUI), joining
  `getLine(viewportY + y).translateToString(true)` for `y` in `0..rows`, and run the shared
  `is_retry_wedge` regex over the joined rows. Do NOT use `@xterm/addon-search` (`findNext`) for this:
  that addon is for interactive UI — it mutates the terminal selection/viewport and wants the DOM
  renderer, whereas a direct buffer read is side-effect-free, works in `@xterm/headless`, and keeps
  the matcher byte-for-byte identical to the standalone side. Because it is the SAME xterm.js parse the
  dashboard shows a human, the detector sees exactly the visible frame. (The
  `buffer.active.type`/`viewportY`/`getLine`/`translateToString` API and the `addon-search` shape are
  VERIFIED against the `xtermjs/xterm.js` typings, 2026-07-24; `onDidChangeResults` fires only when
  decorations are enabled — another reason the headless detector reads the buffer directly.) Poll the
  grid each supervision tick; there is no output log to tail. This is NOT the transcript (which does
  not advance during the wedge — it is the independent progress signal used by the gate below).
- **Signature (the wedge line, matched on the rendered grid) — CAUSE-AGNOSTIC.** The retry-watchdog
  status line is the SAME shape regardless of WHY the turn is retrying — verified against three live
  lines: `✻ Rate limited · Retrying in 0s · attempt 5/300`, `✻ 429 Rate limited · Retrying in 0s ·
  attempt 5/300`, and `✻ Session limit reached · Retrying in 2m 50s (2:10pm) · attempt 1/300`. The
  load-bearing invariant is `Retrying in <dur> … attempt <n>/<m>`, NOT the cause word — a
  `429`/`rate-limit`-only regex MISSES the session-limit wedge (observed 2026-07-24). Reference regex
  (share byte-for-byte with the janitor's `is_retry_wedge`):
  `/retrying\s+in\b.*\battempt\s+\d+\s*\/\s*\d+/i`. The cause tags (`429`, `Rate limited`,
  `Session limit reached`, server-throttle text) are OPTIONAL context to log, never required to match.
- **Detection may be EVENT-DRIVEN, not only polled.** xterm.js core exposes `term.onWriteParsed`
  (`IEvent<void>`, verified `xterm.d.ts:1100`) and `term.onRender` — fire the buffer-read + regex on
  each write instead of a fixed tick. Do NOT use `@xterm/addon-search`'s `searchResultsChanged` /
  `onDidChangeResults` for this: that event fires only when an ACTIVE search with DECORATIONS enabled
  re-computes its highlighted-match set — it signals "the match set changed," not "this string
  appeared," and it drags in the search state + decoration/DOM path a headless detector must avoid.
- **Gate (avoid false positives — load-bearing):** fire ONLY when genuinely wedged: (a) the signature
  on the CURRENT rendered grid, (b) `attempt` counter ≥ 2 (past the first transient) — and the counter
  ADVANCING across successive polls while nothing else on the grid changes is itself the positive
  wedge signal (the frame redraws, but only the retry counter moves = not real progress), AND (c) NO
  transcript progress since the signature appeared (the "no progress after the signal" clause the
  janitor applies in `fleet_scan.diagnose_root` → `session_liveness.diagnose_instance`). Debounce
  ≥ one supervision tick. (That clause used to live in `session_liveness.is_session_frozen`, which
  TRDD-L32WC0H7 F0 deleted as dead code — it had no callers; `diagnose_instance` is and was the
  live predicate.)
- **Do NOT gate on the statusline usage %.** The statusline (`5h … 98% @2:10pm`, `7d …`) is a LAGGING
  indicator — it refreshes on its own slow cadence, so at the moment `Session limit reached` renders
  the meter can still read 98% when the true window is 100% (owner observation 2026-07-24). A
  detector that required "5h ≥ 99%" before treating a wedge as real would MISS real wedges. The wedge
  LINE is the authoritative live signal; the % is decorative. (Rotation decisions are unaffected —
  the OAuth rotator reads LIVE `/api/oauth/usage` via `rotator_usage`, never the statusline.)

**8.2 What to INJECT (server, into that agent's PTY stdin).**
- **Raw `ESC` byte(s) — `0x1B`.** Send ONE to abort the retrying turn; a SECOND only if the wedge
  signature persists past the cooldown. NEVER a command, NEVER a newline / `Enter`, NEVER `Ctrl-C`
  (a 2nd `Ctrl-C` exits CC). ESC is what the retry-watchdog treats as "abort the retry and return
  control." The real danger is a stray `Enter`: a 2nd ESC on an empty input can surface CC's rewind
  overlay, which destroys nothing UNLESS an `Enter` confirms a selection — so the server must never
  send `Enter`. A typed command would queue behind the wedge and mis-fire when it breaks.
- **After ESC:** do nothing else — the abort ends the turn, which fires the janitor's in-agent
  `on-stop-failure` → writes `rate-limited.flag` → the agent's normal resume path (or the server's
  `ensure-resume <self>`, §6.3) takes over. The server's ONLY job is to break the wedge with ESC;
  recovery is already wired on both sides.
- **ESC is a PREREQUISITE for rotation, not an alternative to it (owner incident 2026-07-24: "you
  failed to rotate again").** A wedged turn holds the OLD credential INSIDE its retry loop, so
  rotating the live credential (daemon OAuth tick / server rotation) while the turn spins does NOT
  rescue it — the spinning turn never re-reads the credential. The ONLY correct order is **ESC first
  (end the turn) → THEN the rotated credential is picked up on resume.** So on a `Session limit
  reached` / `Rate limited` wedge the actor must ESC even when it is ALSO rotating; rotation alone is
  a no-op against a live wedge. (This is also why the session-limit wedge is in scope here at all —
  it is the SAME wedge as a 429, and the same ESC breaks it.)

**8.3 Guardrails (must hold, mirror the janitor's).**
- **Only the server's own registry agents** (per-agent isolation, §3) — never another host's, never
  a non-agent pane.
- **Never inject into a PROGRESSING agent** — the "no transcript progress" gate is the single
  safety clause; a false ESC discards real work.
- **ESC only, never a kill** — a rate-limited agent is not a crashed process; the hard/restart rungs
  do not apply to this state.
- **Cooldown** — at most one ESC per agent per window (mirror `recovery_cooldown_ok`); if the wedge
  persists across cooldowns the account is genuinely exhausted → rotate (server's OAuth path) or
  surface, do not ESC-storm.
- **Fail-open** — an agent whose PTY tail cannot be read is simply not wedge-detected; degrade to
  today's behavior, never to a wrong action.

**8.4 Division of labor.** Standalone `#N`: the janitor daemon detects+injects via Python
(osascript `contents of session` + `write text (character id 27)`; `tmux capture-pane` +
`send-keys Escape`) — TRDD-WKTD5JTC. Harness `#J`: the SERVER implements §8.1–§8.3 on the PTY it
owns. No new janitor↔server *file* contract is needed — this rides the PTY the server already
holds; §8 is a behavior request, and the shared `is_retry_wedge` regex is the only artifact both
sides must keep identical.

## 9. Claimed-chore alignment contract — the chore⇄token⇄stamp⇄bound table (round 4, 2026-08-18)

**Why (TRDD-6CRC9SQQ; incident janitor#221).** Rev 4 made the claim BINARY: a fresh
`server-liveness.json` claims ALL absorbed chores. What it did not pin is the EVIDENCE
vocabulary: which completion stamp each claimed chore writes, and how stale that stamp may go
before someone alarms. The janitor's `claimed-chore-stale` watchdog (v2.5.0,
`lib/claimed_chore_watch.py`) closes the observability half, but today it derives every bound
from the JANITOR's roster cadence — for a claimed chore that is the NON-executor's cadence, the
exact class the fleet has measured producing deterministic false "wedged" alerts (and the same
class this repo's CLAUDE.md documents for `version-update`: a frozen janitor stamp is what
healthy server-side execution looks like when the server's own cadence differs). The fix is the
executor declaring its own bound — this table plus one small file.

**9.1 The table (janitor side of the contract; the server repo mirrors it).**

| chore | claim token (informational since rev 4) | completion stamp (the evidence channel, ai-maestro#111) | janitor cadence | default bound `max(3×c, c+600)` |
|---|---|---|---|---|
| `oauth-rotator-tick` | `oauth-rotator-tick` | `~/.claude/janitor-control/oauth-rotator-tick.last-run.ts` | 60 s | 660 s |
| `oauth-rotator-supervisor` | `oauth-rotator-supervisor` | `~/.claude/janitor-control/oauth-rotator-supervisor.last-run.ts` | 600 s | 1 800 s |
| `marketplace-refresh` | `marketplace-refresh` | `~/.claude/janitor-control/marketplace-refresh.last-run.ts` | 3 600 s | 10 800 s |
| `version-update` | `version-update` | `~/.claude/janitor-control/version-update.last-run.ts` | 21 600 s | 64 800 s |
| `github-config-audit` | `github-config-audit` | `~/.claude/janitor-control/github-config-audit.last-run.ts` | 21 600 s | 64 800 s |

Sources of truth: chore names + cadences `harness_backend.GLOBAL_CHORES`; absorbed set
`harness_backend.SERVER_ABSORBED_TASKS`; bound formula + floor
`claimed_chore_watch.stale_bound_s` / `DEFAULT_MIN_GRACE_S`. The table is prose FOR the
negotiation — code reads the code.

**9.2 Executor-declared bounds (the contract ask).** The executor of a claimed chore declares
its OWN staleness bound in `~/.claude/janitor-control/claim-bounds.json` —
`{"<chore>": <bound_s>, …}` — written/refreshed by whichever side currently executes. The
watchdog consults it with **widen-only** semantics: a declared bound REPLACES the default only
when larger (self-calibration must never introduce a false positive; same rule the watchdog
already applies to its own observed-cadence widening). File absent or unparseable ⇒ the §9.1
defaults stand, fail-open. This makes a server that legitimately runs `version-update` daily
(not every 6 h) alarm-free WITHOUT the janitor guessing, and keeps janitor#221's 3.7-day wedge
detected in ≤ the declared bound.

**9.3 What stays true regardless (already ratified, restated so §9 cannot be read as
reopening it).** Alarm-only: the janitor NEVER un-yields a stale claimed chore (rev 4 / owner
directive 2026-07-17 — a claiming server that does not execute is a SERVER bug to fix there;
two writers on a machine-global chore is worse than zero). Unknown chore ⇒ skipped, never
guessed. `no-evidence` (claimed, no stamp ever) is itself a finding.

**9.4 Known discrepancies this round must settle (cross-cited per the hub's 2026-08-18
constraints — the server lanes are NOT assumed healthy; two hub cards exist precisely because
they are not).**
- **ai-maestro TRDD-FXPV7L4D** (marketplace refresh claims every marketplace from ONE exit
  code while ten were months stale): §9.2's per-chore stamp+bound gives the wedge a detection
  channel, but a stamp written on a false "success" is still a lie — the stamp MUST mean "the
  chore's work product is actually current", which is that card's fix to land server-side.
- **ai-maestro TRDD-PE54D95Q** (absorbed auto-update lane has no cadence control, retries
  permanent failures hourly): once cadence control exists, its chosen cadence is exactly what
  §9.2 asks the server to declare.
- **`github-config-audit` (janitor#274) — RESOLVED 2026-08-18, same round:** settled by the
  hub's measurement (server executes it since 2026-08-05, `lib/janitor-chore-stamp.ts`;
  stamp verified fresh on this host at epoch 1787060644) — it JOINS
  `SERVER_ABSORBED_TASKS` and the §9.1 table. Note on its declared bound: the server
  declares 14 400 s, BELOW the 64 800 s roster default — §9.2's widen-only rule ignores a
  narrowing declaration by design, so detection stays at the roster bound; a server that
  wants faster detection of its own wedge lowers the JANITOR default, not the declaration.

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
- rev 6 — 2026-07-24, owner directive: the CC retry-watchdog wedge
  (`429 · Retrying · attempt N/300`) keeps a turn alive so the flag-gated freeze ladder never
  engages; a session sits wedged until a human presses ESC. Added §8 (retry-wedge recovery,
  REQUESTED round 3): the standalone `#N` janitor detects+injects ESC via Python
  (TRDD-WKTD5JTC); the harness `#J` server detects the PTY wedge signature and injects one raw
  `ESC` (`0x1B`) into the agent PTY, then lets the existing `on-stop-failure`/`ensure-resume`
  recovery run. Shared artifact: the `is_retry_wedge` regex, kept identical both sides. To post
  to #100 for ai-maestro's match.
- rev 7 — 2026-07-24, owner correction: CC's TUI runs on the ALTERNATE screen buffer → NO
  scrollback, so §8 detection cannot byte-grep the raw PTY stream — the server MUST render the PTY
  through a headless vt emulator and match the RENDERED FRAME (the retry line is redraw noise,
  rewritten in place as `attempt N` ticks). §8.1 surface + gate rewritten (poll the rendered grid;
  the advancing counter is itself the positive signal); §8.2 injection aligned to the ESC-input
  semantics (1–2 ESC, no text, never `Enter`, never `Ctrl-C`). Standalone reads the frame via tmux
  `capture-pane` / iTerm `contents` (the terminal is the emulator). Refined same session (rev 7 not
  yet posted): the dashboard already renders each agent with **xterm.js**, so the server reads the
  grid from a **server-side `@xterm/headless`** fed the same PTY (`term.buffer.active`, the alt
  buffer) — not the browser `Terminal`, which is closed for unattended agents, exactly when the wedge
  bites. To post to #100.
- rev 8 — 2026-08-18, authored janitor-side under the USER's session delegation ("human review
  is delegated to you… act and decide by yourself"; hub-side holds the mirror delegation this
  session and raised the constraints folded into §9.4): added §9, the claimed-chore
  chore⇄token⇄stamp⇄bound table + executor-declared bounds (`claim-bounds.json`, widen-only,
  fail-open) — TRDD-6CRC9SQQ item 2, routed through ai-maestro#126 item 1 + #111. Posted to
  ai-maestro#126 for the server-side match + mirror; alarm-only semantics (§9.3) unchanged.
  **Server matched same day ⇒ FINAL**: ai-maestro `docs/claimed-chores-contract.md` (commit
  `eccbd02a`), thread comment 5332124288, §9.2 accepted as authored. Same round settled
  janitor#274: `github-config-audit` joined the absorbed set + §9.1 (stamp verified on-host);
  janitor-side reader shipped (`claimed-chore-stale.py::_declared_bounds`, widen-only in
  `claimed_chore_watch.stale_threshold`).
