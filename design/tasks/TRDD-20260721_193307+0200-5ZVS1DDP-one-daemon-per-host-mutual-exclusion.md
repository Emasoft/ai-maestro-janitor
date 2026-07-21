---
trdd-id: 5ZVS1DDP
title: One daemon per host — the janitor daemon exits while an ai-maestro server runs
column: backburner
created: 2026-07-21T19:33:07+0200
updated: 2026-07-21T19:33:07+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
severity: medium
relevant-rules: [1]
implementation-commits: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-21

**NOT STARTED.** The contract is written and committed (`4237fcf`,
`design/ARCHITECTURE.md` §7.2, rev 5); no janitor code has changed for it yet.

**THE OPEN QUESTION IS ANSWERED (owner, 2026-07-21).** One daemon per host is
unconditional: *"of course there must be only one daemon running at any time.. otherwise
they will conflict and write at the same time in the same files, corrupting them.. not to
mention launching chores twice."* For the orphaned chores the owner offered two routes and
delegated the choice — *"either let the ai-maestro server handle them too … or you can
separate those chores from the daemon and make the chron of each repo handle them. you
decide."*

**DECIDED — split by STRUCTURAL CAPABILITY, not by preference.** The test is whether a
per-repo cron is even able to perform the chore:

| chore | route | why |
|---|---|---|
| `cache-prune`, `rules-cleanup`, `github-config-audit`, `memory-guard` | **per-repo heartbeat** | each is idempotent and machine-wide-safe once serialized, and §7.1 just supplied the serialization: the SHARED `*.lock` + SHARED `*.last-run.ts` in `~/.claude/janitor-control/`. N sessions contending on one lock run it at most once per period — precisely the double-chore/corruption the owner named. |
| `session-liveness` / `fleet-stop` freeze recovery | **server only** | STRUCTURALLY impossible from a per-repo cron: a frozen session's own cron is exactly what has stopped, so a session cannot recover itself. This is why it was daemon work. |

So there is no coverage gap for the first four. Freeze recovery for standalone sessions is
covered while no server runs (the janitor daemon owns it, status quo) and needs the SERVER
to own it while a server runs — the one item that genuinely transfers.

**NEXT ACTION:** implement §7.2 in this order — `daemon.py` main loop exit + `finally`
keepalive drop, `global_state.ensure_daemon_running()` refusal, crash-loop-breaker
exemption, tests. Then the chore migration above as its own TRDD (it depends on
TRDD-QK7M2B0X's shared locks landing first — that ordering is a real NPT, not a
preference: moving a chore to the cron BEFORE its lock is shared would let N sessions run
it concurrently, which is the corruption case).

**Load-bearing facts, all verified 2026-07-21:**

- `KeepAlive: true` + `ThrottleInterval: 30` in `scripts/keepalive_install.sh:185-187`,
  and `Restart=always` at :228. A bare `sys.exit` is relaunched every 30 s, forever.
- `daemon.py:2126-2131` already solves exactly this for the kill-switch: the `finally`
  block calls `_uninstall_os_keepalive()` for `exit_reason == "kill-switch"` only, with
  the comment "KeepAlive would otherwise fight the user's explicit disarm". This is the
  pattern to reuse — do NOT invent a second mechanism.
- `harness_backend.server_is_alive()` already exists and is the whole discriminator
  (fresh `~/.aimaestro/server-liveness.json` within 90 s). Test override
  `JANITOR_AIMAESTRO_LIVENESS_FILE`.
- The server side of that file IS implemented — `~/ai-maestro/lib/server-liveness.ts`
  and `server.mjs` in `23blocks-OS/ai-maestro`. It was absent on this machine only
  because the server was not running.
- `SERVER_ABSORBED_TASKS` is FIVE tasks: `oauth-rotator-tick`,
  `oauth-rotator-supervisor`, `marketplace-refresh`, `user-plugins-update`,
  `version-update`. The daemon runs more than that — see the gap below.

**SUPERSEDED — do NOT carry forward:** rev 4's "the daemon keeps running and yields the
absorbed chores". Rev 5 replaces chore-level yielding with process-level exclusion.

## Why

Owner directive, 2026-07-21: *"when the ai-maestro server is running, the daemon process
must stop, and resume only when the ai-maestro server is not running anymore. only one
daemon can exist at the same time in the host."*

Rev 4 already made the janitor yield its five absorbed chores to a live server. That is
chore-level, not process-level: the janitor daemon stays up, holds its singleton flock,
keeps its OS keepalive, and keeps running everything outside the absorbed set. Two
supervisors on one host is the condition the directive removes.

## The design (ARCHITECTURE.md §7.2)

1. **Exit.** In the daemon main loop, alongside the existing kill-switch check: a fresh
   liveness file ⇒ `exit_reason = "server-owns-host"`, break.
2. **Drop the OS keepalive** in the `finally`, for that reason as well as `kill-switch` —
   otherwise launchd/systemd relaunches the daemon within 30 s and it exits again, a
   permanent 30-second thrash that also spams the daemon log.
3. **Refuse to spawn.** `global_state.ensure_daemon_running()` returns early while the
   server is alive, so no session's heartbeat re-spawns what the server displaced.
4. **Resurrect.** Nothing special is needed: once the liveness file goes stale (≤90 s
   after the server stops) the next heartbeat's `ensure_daemon_running()` spawns the
   daemon, which re-installs its OS keepalive on startup. The heartbeat — not the OS
   supervisor — is the resurrection path, which is what makes step 2 safe.
5. **Do not trip the breaker.** A clean "server owns the host" exit must not count toward
   `record_spawn_attempt` / `crash_loop_active`, or a server restart cycle would trip the
   crash-loop guard and suppress a legitimate later spawn.

Detection is by FILE only. The server is *"wherever the user installs ai-maestro"* and
runs under **pm2**, so the janitor can neither locate nor stop it — it can only observe
the flag and step aside. Symmetrically the server never stops the janitor daemon; it
just runs, and the janitor leaves.

## The consequence — THE open question for the owner

The daemon's exit stops **everything it does**, not only the five absorbed chores. These
have no server equivalent today and are explicitly listed in §2 as "janitor-internal
machine chores that never yield":

| chore | what stops |
|---|---|
| `memory-guard` | the Tier-1 OOM guard — no victim selection while the server runs |
| `cache-prune` | stale plugin-cache version dirs accumulate |
| `rules-cleanup` | post-uninstall orphaned rules are not removed |
| `github-config-audit` | the fleet GitHub-config sweep does not run |
| `session-liveness` / `fleet-stop` | frozen/cron-dead session recovery for NON-server-owned sessions stops |

The last row is the sharp one: those beats already exclude `server_owned` instances, so
today they cover exactly the standalone sessions a server does NOT manage. Exiting the
daemon removes recovery from sessions the server was never going to recover.

Three ways out, owner to choose:

- **(a) Accept the gap** — a running server means the host is the server's problem.
  Simplest, and consistent with "running IS the claim".
- **(b) The server absorbs all of it** — extend `SERVER_ABSORBED_TASKS` to the full set
  and require the server to implement them. Largest ai-maestro ask.
- **(c) Exit only the absorbed lane** — keep a minimal janitor daemon for the
  non-absorbed chores. Contradicts "only one daemon can exist at the same time in the
  host" as literally stated, so it needs an explicit owner amendment.

Do not implement until this is answered; the answer changes step 1's condition.

## Verification

- Unit: fresh liveness ⇒ the loop sets `server-owns-host` and the `finally` uninstalls
  the keepalive; stale/absent ⇒ the daemon runs normally.
- Unit: `ensure_daemon_running()` declines while alive, spawns once stale.
- Unit: a `server-owns-host` exit does not increment the crash-loop ring.
- Integration: with `JANITOR_AIMAESTRO_LIVENESS_FILE` pointed at a temp file, write a
  fresh stamp → daemon exits and the keepalive artifact is gone; delete it → the next
  `ensure_daemon_running()` spawns a daemon that re-installs the keepalive.
- Full `uv run pytest` + `ruff check` green before any commit.

## Notes and lessons learned

[^1]: [id:ATOM-5ZVS-0001, status:valid, keywords:"daemon_exits_but_comes_back launchd_KeepAlive_relaunch systemd_Restart_always thrash_every_30s", ocd:2026-07-21, lmd:2026-07-21]
  DO NOT stop a supervised daemon with a bare exit, BECAUSE the janitor's own
  `keepalive_install.sh` sets launchd `KeepAlive: true` / systemd `Restart=always`, so
  the OS relaunches it within `ThrottleInterval` (30 s) and the "stop" becomes a
  permanent restart loop. DO drop the OS keepalive in the same `finally` that ends the
  loop — and only for deliberate-stop exit reasons — the way the kill-switch path
  already does.
