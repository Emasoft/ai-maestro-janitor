---
trdd-id: PZLVT2RN
title: ai-maestro-tailored janitor (#J) + normal-janitor scope-flip (#N) + shared-codebase two-backend split
column: published
created: 2026-07-16T15:44:27+0200
updated: 2026-07-17T17:05:00+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
related-audit: AM8JD9SG
server-trdds: [KCRMSNL7, H24DF6ZC]
coordination-issue: janitor#100
implementation-commits: [0874122, e613314, 47926b3, 27684dc, cbfd43c, 2758241, a88ddd4, 103c84a]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-17

**What this is.** The janitor-side design TRDD for the owner-directed daemon-migration
architecture. The plan is ALIGNED with the ai-maestro Claude (janitor#100, comments 13:05 +
13:42) and the AgentlensPro Claude (AgentlensPro#2/#3). This TRDD captures the janitor half; the
server half is ai-maestro's `TRDD-KCRMSNL7` (parent) + `TRDD-H24DF6ZC` (R16 token NPT).

**Current state of each component (implementation IN FLIGHT — approved plan at
`~/.claude/plans/staged-kindling-lynx.md`):**
- **Phase A (backend SSOT `harness_backend.py`)** — DONE, commit `0874122`.
- **Phase B (daemon-side harness exclusion: `server_owned` diagnosis, fleet-stop skip,
  agent-roots cache, `~/agents/` registry-free signal)** — DONE, commit `e613314`.
- **Phase C (#J thin mode: no daemon spawn, no outside-world writers at SessionStart,
  `_NON_HARNESS_DETECTORS` roster filter)** — DONE, commit `47926b3`.
- **Phase B2 (daemon singleton-chore coordination — the SECOND owner directive below)** —
  code done this session: `server_owns_singleton_chores()` (TTL-memoized, chores-only env
  override `JANITOR_AIMAESTRO_SERVER_CHORES`), daemon `_SERVER_ABSORBED_TASK_NAMES`
  {marketplace-refresh, user-plugins-update, version-update, oauth-rotator-supervisor,
  oauth-rotator-tick} gated in due-loop + maintenance-keepalive + both consume paths +
  next-due sleep (busy-spin guard), `daemon_watchdog` suppression, tests in
  `tests/test_chore_coordination.py`.
- **Phase D (#J delegation + self-trigger hardening)** — code done this session:
  `on-stop-failure.py` fires `aimaestro-continuity.sh ensure-resume <self>` DETACHED,
  best-effort, strictly after the critical flag write (feature-detected via
  `harness_backend.continuity_cli` + new `self_agent_ref` = `$AMP_AGENT_ID`); F9 — the
  ai-maestro self-send delivery is DETACHED (only the 5 s-capped `list` runs inline; the
  F8 partial-delivery ambiguity is structurally gone); F10 — SOFT sends to a
  server-managed pane prefer the `aimaestro` channel over raw tmux (HARD keeps tmux —
  the CLI has no ESC primitive; aimaestro-only identities still get the hard-intent
  fall-through for reachability parity); F2 (narrow) — fleet-stop refuses to enqueue at
  a FROZEN target whose ONLY channel is the ESC-less CLI (no dedupe stamp burned;
  frozen+tmux keeps the hard ESC-first stop per `test_frozen_target_is_hard`). Probe
  functions hardened NEVER-RAISE (a sandboxed env proved the subprocess spawn can
  throw). Related same-day fix: the PostCompact resume push self-cancels when nothing is
  pending (`cbfd43c`, TRDD-8IZ8COQ8 — user-reported injection spam).
- **Phase B2 commit:** `27684dc`. **Phase D commit:** `2758241` (self-cancel fix `cbfd43c`).
- **Phase E (docs + repomap + full suite + v0.50.0 release + #100 update)** — IN FLIGHT
  2026-07-17: owner GO given ("Ship v0.50.0 first", AskUserQuestion answer in the approved
  plan `~/.claude/plans/staged-kindling-lynx.md`); CLAUDE.md two-backend section + README
  harness note written; release train also carries TRDD-X92VBFNF (per-project channeling,
  `41eecae`) and TRDD-H7NVKSAX (daemon background bulk lane — oauth-starvation incident fix,
  `0bbd2ff`).
- **Known flaky (pre-existing, tracked):** `test_marketplace_refresh_scoped` e2e worker
  race — TRDD-UO93APWN (proven pass/pass/fail on an identical tree; not a Phase B2/D
  regression).

**SECOND OWNER DIRECTIVE (2026-07-17, verbatim):** *"it is important that the ai-maestro server
daemon-function will coordinate with the janitor daemon (non-aimaestro-version) to avoid doing the
same chores twice. if the ai-maestro server is active, the non-aimaestro-janitor daemon must
deactivate all the chores that only need to be executed once (i.e. oauth rotation, upgrade all
marketplaces, ~/.claude config monitoring, etc.), while it must execute the operations that can be
done by both daemons (like global reload-plugins, global disarm, global rearm, global pause, global
reload skills, global restart claude, etc.) because those are split between the two types of
agents: those inside the ai-maestro harness are managed by the server ai-maestro janitor
daemon-function, while those outside ai-maestro harness are managed by the external janitor daemon
subprocess."* Implementation = Phase B2 above. Policy: yield a once-only chore IFF the ownership
signal is CONFIDENTLY True (None/False ⇒ run — a machine with no visible server must never lose
its chores; the cross-process file locks are the collision backstop). Owner also confirmed
(mid-turn, same day): the single runtime-branched plugin "simplifies things enormously" — the
packaging decision stands.

**OWNER DIRECTIVE RECEIVED (2026-07-17, verbatim):** *"coordinate with the ai-maestro claude while
creating the new version of the plugin (of, if you can, making this same plugin behave differently
in the ai-maestro harness and outside, making the daemon outside only affecting the claude code
instances running outside of the ai-maestro harness, while those inside the ai-maestro harness
will use the very ai-maestro server as the daemon. right now the ai-maestro claude is porting the
functionality of the daemon into ai-maestro server."* This (a) is the go for the janitor-side
build, and (b) SETTLES the packaging choice this TRDD had left open: **ONE plugin, runtime-branched
backends** ("this same plugin behave differently") — NOT two plugin ids. It also makes EXPLICIT a
deliverable that was implicit in "neither touches the other's agents": **the OUTSIDE daemon's
fleet actuation (session-liveness recovery, fleet-stop injection, memory-guard victim selection)
must EXCLUDE harness agents while a live server owns them** — with the already-agreed residual
(server down ⇒ `#N` daemon is the Family-A fallback, incl. resurrecting the server) governing when
the exclusion lifts.

**Verified 2026-07-17:** `~/ai-maestro/scripts/aimaestro-continuity.sh` EXISTS beside
`aimaestro-session.sh` (their DXJZM3BW shipped) — the Q3 contract surface `#J` consumes is real.

**SHIPPED: v0.50.0 published 2026-07-17 (release commit `103c84a`,
https://github.com/Emasoft/ai-maestro-janitor/releases/tag/v0.50.0).** Residuals carried
FORWARD (not by this TRDD): the chore-yield stays DORMANT until ai-maestro lands the
auth-free capability probe (janitor#100, F6: agent-list 401s without AID_AUTH — zero
call-site changes needed when it lands); no #J local install exercised end-to-end yet; the
two-harness architecture-doc ratification + findings ledger continue in the approved plan's
Phases 1–5 (`~/.claude/plans/staged-kindling-lynx.md`).

**Load-bearing facts / gotchas:**
- The #7 machine-wide singleton is the `daemon.flock`, NOT install scope — so `#N`'s USER→LOCAL
  flip does NOT reopen the two-daemon window.
- Family B (dev-hygiene) STAYS with the janitor. Moving it into the server would break ai-maestro's
  own #56 invariant ("server boots + runs with NO janitor installed") — its mirror binds us: a
  non-ai-maestro machine must still get Family B, so the server must not own it.
- The token DESIGN (R16) is USER-sign-off-gated (server's H24DF6ZC). Non-token Family-A parts
  proceed; token-touching code waits for explicit USER sign-off.
- The one machine-wide-locked credential writer (server-when-up / #N-daemon-when-not, never
  concurrent) is the single highest-risk seam.

**SUPERSEDED — do NOT carry forward:** an earlier framing had ai-maestro absorbing the WHOLE daemon
(incl. Family B). REJECTED — only Family A moves as OWNERSHIP. Refined by the second directive
(2026-07-17): the Family-B *code* stays janitor-side forever (the #56 mirror binds), but the
RUNTIME EXECUTION of the machine-wide once-only chores (marketplace refresh, user-scope plugin
updates, janitor self-update) DEFERS to the server whenever the server confirms it is active and
owns them — runtime dedup ("don't do the same chore twice"), not code migration. A note that says
"the janitor loses plugin-update / OOM / cache-prune / github-config CODE to the server" is still
wrong; a note that says "the janitor never yields chore execution" is now ALSO wrong.

**Durable artifacts to read before acting:** this STATE block; `janitor#100` comments (the real
alignment, not a summary); `TRDD-AM8JD9SG` STATE (the 8 audit findings + F11, the janitor-side
implementation batch); `.janitor/state/agent-handoff.md` (rich handoff, if still present).

---

## Problem

The owner directed (2026-07-16) that ai-maestro agents run a special janitor that does NOT carry a
background daemon — because inside the ai-maestro harness an agent (a) cannot write outside its
workdir, (b) cannot execute `claude` from the CLI, and (c) the daemon is not authenticated to the
ai-maestro server, so it cannot reach the server api/scripts. The daemon's continuity/guardian
functions must therefore be served BY the ai-maestro server (which already owns auth, the frozen
CLI scripts per R23, and partial session-resurrection), and consumed by a thin, LOCAL-scoped
janitor variant. A parallel change lets the NORMAL janitor run LOCAL-scoped on non-ai-maestro
machines so the two never collide.

## The two variants

- **`#J` — ai-maestro-tailored janitor.** Installed LOCAL-scoped in each ai-maestro agent workdir.
  NO daemon process. THIN: runs only the ~35 workdir-scoped detectors and writes only
  `.janitor/state/`. Does NO Family-A and NO Family-B itself. Delegates Family-A to the ai-maestro
  server via the frozen CLI. Self-manages (arm/compact/reload/resume) via the EXISTING
  `aimaestro-session.sh slash|queue <self>` (R42-clean self-targeting; `queue` beats ESC-injection
  — never mid-turn, survives hibernation).
- **`#N` — normal janitor.** Flips USER→LOCAL install scope; installed on non-ai-maestro machines.
  Keeps Family B everywhere AND is the Family-A FALLBACK when there is no live server (including
  resurrecting the ai-maestro server itself — the server cannot resurrect itself).

## Family A / Family B split (the load-bearing decision)

- **Family A (continuity / guardian) → ai-maestro server.** OAuth key rotation; automatic account
  management on api-errors / rate-limits / network interruptions; work-continuity + automatic
  resume ("guardian"); session resurrection after reboot ("immortality" — server HARDENING, not
  from zero: `services/boot-restore-service.ts::restoreActiveAgentsOnBoot()` already exists).
- **Family B (dev-hygiene) STAYS with the janitor.** plugin/marketplace/self-update, cache-prune,
  rules-cleanup, OOM guard, github-config audit. Reason (§STATE): moving it breaks ai-maestro's own
  #56 invariant, whose mirror is that a non-ai-maestro machine must still receive Family B.

## Architecture — one shared codebase, TWO backends

Discriminated at runtime by `state.in_ai_maestro_agent_env()` — NOT a fork (a fork double-maintains
the ~200 pattern libs + ~35 detectors and drifts the security base):

- **SHARED (both backends):** ~200 `*_patterns.py` pattern libs + ~35 workdir-scoped detectors +
  the whole security knowledge base + memory subsystem + rules installer.
- **BRANCHED (only these ~5 actuation subsystems differ):**
  1. self-trigger send → `aimaestro-session.sh slash|queue` (inside) vs raw iTerm/tmux (outside);
  2. daemon-spawn → OFF inside (`#J` has no daemon);
  3. fleet inject / scan / recovery → OFF inside (the server owns fleet actuation);
  4. global-scope writes → OFF inside (`#J` writes only `.janitor/state/`);
  5. OAuth / keychain → OFF inside (the server owns token material).

## Confirmed Q3 contract (ai-maestro builds `aimaestro-continuity.sh` to this)

- `aimaestro-continuity.sh status <self>` → read-only, self-scoped (AID), **NO token material**:
  `{ account_healthy, window_5h_pct, window_7d_pct, cache_ttl_minutes, next_action }`. Server derives
  from AgentlensPro: window pcts ← `get_account_status.usageWindows.{fiveHourPct,sevenDayPct}`
  (fallback `get_burn_status.accountWindows`); `cache_ttl_minutes` ← `get_account_status.cacheTtl.minutes`.
- `aimaestro-continuity.sh ensure-resume <self>` → idempotent; the server owns actuation. `#J`
  never drives another agent.
- Self arm / compact / reload / resume → REUSE existing `aimaestro-session.sh slash|queue`. No new API.

## R16 token posture (binding; the token DESIGN is USER-sign-off-gated)

Tokens are infrastructure-only, NEVER in any agent/model-readable response; encrypted at rest in
the OS keychain (`Claude Code-credentials` live; `Claude Code-rotator-slot` + mirror; `safe_storage`
macOS `security` / Linux libsecret / Windows DPAPI); ONE machine-wide-locked writer
(server-when-up / #N-daemon-when-not, never concurrent); REAUTH stays a human `/login` (ROTATE /
RENEW auto). AgentlensPro confirmed observe-only, no rotation, emits no token material
(`accountInfo.ts:10-13`). The token-handling DESIGN lives in the server's `TRDD-H24DF6ZC` and awaits
explicit USER sign-off before any token-touching code.

## Governing cross-repo rules (not this repo's PRRD)

ai-maestro governance (cross-repo, authoritative for the harness behaviour): **R42** (revokes
cross-agent DRIVE injection; principals who may inject = USER, agent-self, janitor R42.5 GLOBAL
switches only), **R23** (the frozen `aimaestro-session.sh` CLI is the sanctioned "drive claude via
scripts"), **R16** (token posture, above). These constrain `#J`'s actuation backend directly (F11
in AM8JD9SG: `#J` self-triggers are R42.5-clean because they are self-targeted).

## Scope of this TRDD (the janitor half only)

1. `#J` thin build — the ai-maestro backend (branched actuation subsystems 1–5 above; delegate
   Family-A to `aimaestro-continuity.sh`; self-manage via `aimaestro-session.sh`).
2. `#N` USER→LOCAL scope-flip — install mechanics; coexistence with `#J`; the #7-singleton-unchanged
   proof; the Family-A-fallback-when-no-server residual (incl. server resurrection).
3. The shared-codebase / two-backend split — `state.in_ai_maestro_agent_env()` as the discriminator;
   keep the ~200 libs + ~35 detectors shared; branch only the ~5 actuation subsystems.
4. Fold in the AM8JD9SG janitor-side implementation batch (now all ai-maestro-backend actuation
   work): F10 (CLI-first send), F2 (delivery-honesty), F7 (hibernate→wake refuse+alert), F1 (the
   two janitor-side halves), F3/F4 (presence), F9 (detached self-trigger), F11 (R42.5 gating).

## Explicitly NOT in scope here

- The server-side build (Family-A absorption, the `continuity.sh` verbs, OAuth manager,
  fleet-recovery, resurrection hardening) — ai-maestro's `TRDD-KCRMSNL7`.
- The R16 token-handling DESIGN — ai-maestro's `TRDD-H24DF6ZC`, USER-sign-off-gated.

## Gates / do-NOT

- Do NOT enter plan mode or write plugin CODE before the owner directs (process: coordinate →
  TRDDs → plan mode). This TRDD IS the "TRDDs" step; authoring it does not license implementation.
- PUBLISH is held (owner gate: all pending done + up-to-speed with ai-maestro plans). The CPV pin
  bump to ≥v2.159.0 + verify-then-close CPV#167/#168 is publish-prep, not part of this design.
- No token-touching code until the server's H24DF6ZC clears USER sign-off.
