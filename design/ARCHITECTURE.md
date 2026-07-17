# ai-maestro-janitor — two-harness architecture (v0.50.0 baseline, revision 1)

> **Status: DRAFT for co-ratification** with the ai-maestro Claude on
> [janitor#100](https://github.com/Emasoft/ai-maestro-janitor/issues/100). Sections 1–5 are
> the janitor's half; ai-maestro contributes the server-side command contracts (§6, theirs
> to fill) and reviews the chore matrix for conflicts. Convergence protocol: this doc is
> posted verbatim on #100, refined in comment rounds, and is FINAL when both sides post
> `RATIFIED <revision>` on the same revision. Owner directives it encodes (2026-07-17):
> one runtime-branched plugin; no chore done twice; strict per-project channeling;
> unattended findings must reach the human, traceable and referenceable; session-start
> report injection as concise as possible; token telemetry only on own-project anomalies.

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
   **YIELDS iff `server_owns_singleton_chores()` is CONFIDENTLY True**
   (`_SERVER_ABSORBED_TASK_NAMES`: `marketplace-refresh`, `user-plugins-update`,
   `version-update`, `oauth-rotator-supervisor`, `oauth-rotator-tick`).
   None-policy is deliberately the OPPOSITE of actuation: a chore RUNS on unknown —
   nobody doing it breaks the machine; doing it twice is merely wasteful and the
   cross-process file locks (`oauth-rotator-tick.lock`, `marketplace-op.lock`) are the
   collision backstop. **DORMANT** until the capability probe (§6) lands.
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

## 6. Server-side contracts — AI-MAESTRO TO FILL (their refinement half)

Requested on #100:

- **The auth-free capability probe** (the one blocker): must advertise
  `{ts, capabilities: [...]}`, not bare liveness; slots into
  `harness_backend.server_owns_family_a()` rung 2 with zero janitor call-site changes.
- `aimaestro-continuity.sh` — command surface + semantics (`ensure-resume`, …) the #J
  hooks invoke.
- `aimaestro-agent.sh` / `aimaestro-session.sh` — the agent/session command contracts
  the janitor's channel builders use (`session command <tmux> --newline -- <cmd>`).
- The dashboard daemon section consuming the ledger-file contract (§4/§5).
- Conflict review of the chore matrix (§2) against the server scheduler.

## Ratification log

- rev 1 — 2026-07-17, authored janitor-side; posted to #100 for round 1. (pending)
