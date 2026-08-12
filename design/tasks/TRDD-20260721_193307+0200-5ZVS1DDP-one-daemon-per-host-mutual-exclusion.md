---
trdd-id: 5ZVS1DDP
title: One daemon per host — the janitor daemon exits while an ai-maestro server runs
column: testing
created: 2026-07-21T19:33:07+0200
updated: 2026-08-12T12:10:00+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
severity: medium
relevant-rules: [1]
eht: [KQ9WM4TZ]
implementation-commits: [419a470, 3edcf0c, 88e6f45a]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-05

### 2026-08-05 evening — item 2's "SILENT SAFETY GAP … live right now" is SUPERSEDED: closed and verified durable

The gap's own ledger said "the publish is the real and only gate for durable coverage" — and the
publish happened (v2.4.0 + v2.4.1 shipped today, `88e6f45a` in both). The rest of the chain was
then walked BY HAND and verified at each link, because the chore that pulls releases was itself
one of the dark chores (the ai-maestro#102 circularity, made concrete):

1. cache was still 2.3.0 → pulled 2.4.1 via `claude plugin update` (the sanctioned path — this is
   a PUBLISHED release, not the hand-deploy of unpublished code this card refused on 2026-08-05);
2. daemon spawned through the 2.4.1 cache: pid 46125, alive, and it did NOT exit
   `server-owns-host` with the server up — the fix behaving;
3. all of `memory-guard`/`cache-prune`/`rules-cleanup`/`session-liveness`/`fleet-stop` stamped
   within ~45 s (`github-config-audit` on its own longer cadence);
4. the DATA-staged closure now carries `server_owns_every_chore` (re-staged from 2.4.1), so a
   SIGTERM + respawn re-seats the FIXED code — the 8-minute-lifetime failure mode is gone.

Item 2 is DONE. Still open: item 3 only (move the four movable chores to per-repo crons; its
stated blocker QK7M2B0X is now `complete`/released, so it is unblocked work, not a block).
~~EHT KQ9WM4TZ and blocked AWXK0RFT likely have dead premises now (the publish they wait on
shipped) — each needs its own STATE read before closing.~~ **CHECKED 2026-08-12, and the guess
was wrong in both directions — neither had a dead premise:**

- **AWXK0RFT was already `complete`** and had been since 2026-08-05, closed the same evening
  this line was written. It was never "blocked"; the line was stale on arrival.
- **KQ9WM4TZ is `column: human_review`** — it passed ai_review on 2026-08-06 and is sitting in
  the OWNER's queue awaiting their verdict. Not a dead premise, and **not mine to close**.

Worth recording rather than just fixing: a card that speculates about ANOTHER card's state
(*"likely have dead premises"*) ages badly in a way its own STATE block cannot, because nothing
re-reads it when the other card moves. Both guesses cost one `grep` each to falsify. If a line
is worth writing about another card, it is worth opening that card first — otherwise it is a
prediction dressed as a finding.

### The 2026-07-21 head (kept; its "live right now" warning is superseded above)

**STILL `testing`, and that is CORRECT. Shipped v0.59.0 (`419a470`); the real-server soak is
DONE (observed live 2026-08-02, evidence below) — but the soak was only ONE of this card's
three remaining conditions. Items 2 and 3 of "REMAINING" below are still open, and item 2 is a
SILENT SAFETY GAP that is live right now.**

**⚠️ I moved this card to `complete` on the strength of the soak alone and reverted it in the
same session.** The soak was the FIRST listed condition and the one I had just proved, so it
read as *the* blocker. It was not. This is exactly the defect TRDD-N7NZOYAK describes — one
DONE-marked line masking every still-open one — committed against a card whose own body listed
the others eight lines further down. **Satisfying the condition you just measured is not
evidence about the conditions you did not.**

### ✅ SOAK OBSERVED IN PRODUCTION 2026-08-02 — condition 1 of 3, closed

The card sat in `testing` for 11 days waiting on "a real server to soak against". That server
was running the whole time; nobody looked. Measured on this host, all four facts at once:

- **A real ai-maestro server is live:** pid 95175, `~/ai-maestro/node_modules/tsx` under node,
  **up 3 days**. Its liveness probe was **24.8 s** fresh (well inside the 90 s window) and the
  claimed pid answered `kill(pid, 0)` — so the probe is not merely present, it is TRUE.
- **`server_is_alive()` → True**, `server_runs_chores()` → True, capabilities
  `{singleton-chores, family-a}`.
- **ZERO janitor daemons running** — §7.2's exit, doing exactly its job, unprompted.
- `daemon_pid()` → None and the daemon heartbeat is **36.5 h** stale, i.e. it has been yielding
  for the server's whole run rather than exiting once and creeping back.
- `tests/test_one_daemon_per_host.py` — 10 passed.

That is parts (1) and (3) demonstrated together on live infrastructure: the loop exited AND
`ensure_daemon_running()` kept refusing across ~36 h of ordinary heartbeats from armed
sessions. Part (3) is the one that makes the other three non-theatre, and it is the one a
unit test can least convincingly prove.

**⚠️ The "0 janitor daemons" figure nearly became a FALSE ALARM twice, both my own error:**
first `grep -c "daemon.py"` on a `ps` snapshot returned 1 — the snapshotting shell's OWN argv
carried the pattern, because `ps > file` and the grep were one compound command (snapshot-first
does NOT defeat self-match when the snapshotting command itself contains the needle; the
`[d]aemon` bracket trick does). Then "0 ai-maestro server processes" looked like a probe bug
reporting a phantom server — I had grepped `aimaestro`, and the path is `ai-maestro`. Both
readings would have manufactured a defect out of a healthy system.

### 2026-08-05 — what the exit actually costs, measured

The soak proved the exit WORKS. Today measured what it LEAVES BEHIND, which this card never
quantified: the daemon owns **eleven** chores, the server absorbs **five**
(`harness_backend.SERVER_ABSORBED_TASKS`), so **six run nowhere** while a server is up —
`memory-guard`, `cache-prune`, `rules-cleanup`, `github-config-audit`, `session-liveness`,
`fleet-stop`. On this host all eleven stamps are 10-14 days stale, `daemon_pid()` → None.

**§7.2 is not wrong** — two daemons would corrupt shared state, and the owner's ruling stands.
The defect is that the exit was paired with a *partial* absorption contract and no alarm:
`daemon_watchdog.emit_if_daemon_stale` returned early for EVERY chore whenever a server was
alive, so the outage and its own alarm were disabled by the same condition. Fixed in
`95f26646` (gate narrowed to absorbed chores; new `global-chore-blackout` detector). Filed
upstream as **Emasoft/ai-maestro#111**.

### 2026-08-05 later — §7.2's exit had TWO gates and they disagreed (fixed, `88e6f45a`)

**The six chores were dark for a second, self-inflicted reason, on top of the partial claim.**
`d45a843a` moved the SPAWN gate (`global_state._server_owns_host`) to
`server_owns_every_chore()`, but this card's own loop exit still asked
`harness_backend.server_is_alive()`. One question, two answers: `ensure_daemon_running()`
opened the gate and the loop killed the daemon ~4 s later — **a spawn/exit flap, once per
heartbeat**, with the six chores still uncovered. Measured live: `started (tasks=[all 11])`
→ `stopping (server-owns-host)` four seconds later, 0 processes left.

The per-chore yield immediately below that branch (`_task_yielded_to_server`, claim-aware)
was therefore **dead code whenever a server was alive** — the exit always fired first. Exiting
is not the only way to avoid two owners, and it is the blunt one. Now: partial claim ⇒ stay up
and cover exactly the unclaimed remainder; total claim ⇒ §7.2's exit applies unchanged, so the
owner's one-daemon-per-host ruling is preserved intact.

**Verified after the fix on this host:** daemon pid 97639 alive, all six ran within a minute,
the server's five still yielded, `orphaned_chores()` → `[]`.

**The test lesson, which is the transferable part:** all 47 existing tests stayed green through
this bug. The exit was asserted for its EXISTENCE and its ORDER — never for *what guards it* —
so the two gates could drift silently. The new
`test_the_daemons_exit_and_the_spawn_gate_are_guarded_by_the_SAME_decision` pins the invariant
that was actually violated; falsified by reintroducing `server_is_alive` and confirming it fails.

**Framing error worth recording:** this was escalated to the owner for four+ hours as a *decision*
("start the daemon? it is machine-global") when it was a *defect*. The label did the damage — a
consent question is not something you debug, so nothing looked at the exit path.

**NEXT ACTION:** unchanged in target, corrected in status — the EHT **TRDD-KQ9WM4TZ** is now
`blocked` on the publish (TRDD-AWXK0RFT), not in `testing`: its stopgap detector ships in no
cached plugin version, so it has never executed and could not have. This card therefore cannot
reach `complete` until the publish unblocks, independently of condition 3's TRDD-QK7M2B0X.
Nothing else here is forceable.

**SUPERSEDED — do NOT carry forward:** *"work EHT TRDD-KQ9WM4TZ … This card stays `testing`
until that EHT is terminal AND condition 3's blocker TRDD-QK7M2B0X lands its shared locks"* —
accurate on 2026-08-02, but it implied the EHT was workable. It is not, until a release ships.

All four parts landed, each closing a distinct way the exit gets silently undone:
(1) loop exit on fresh liveness, ordered after kill-switch and BEFORE maintenance/pause;
(2) OS keepalive dropped on that exit (shared branch with kill-switch), else launchd
`KeepAlive`/`ThrottleInterval 30` + systemd `Restart=always` relaunch it every 30 s forever;
(3) `ensure_daemon_running()` refuses while a server is live, else the next heartbeat from
any armed session resurrects it in seconds and the exit is theatre; (4) that refusal returns
BEFORE the crash-loop breaker, else a long server run trips the breaker through ordinary
heartbeats and then suppresses the legitimate spawn after the server stops.
`tests/test_one_daemon_per_host.py` — 10 tests, incl. STALE-liveness-is-not-running and the
fail-open probe. Announced to ai-maestro on their #79.

`3edcf0c` is a prerequisite that surfaced during the work, not part of the design: the
suite's write-guard called a daemon SELF-UPDATE a test leak (pid changes on respawn), so the
full suite exited 3 with every test passing — through `publish.py`'s G4 gate, i.e. precisely
while publishing. v0.58.1 shipped only because the daemon happened not to respawn that
minute. Without that fix this TRDD could not be released reliably.

**REMAINING before this can leave `testing`:**

1. ~~**Soak against a REAL running server.**~~ **✅ DONE 2026-08-02** — see the soak section
   above. Note what is STILL unverified even so: the ≤90 s handoff in the OTHER direction
   (server stops → daemon resumes) and that a pm2 restart cycle produces no spawn/exit flap.
   Both need the server to actually stop, which cannot be forced on a borrowed host; neither
   blocks this card, and both are covered by the STALE-liveness unit test.
2. **Freeze recovery must land somewhere** — **STILL OPEN structurally; no longer dark on this
   host.** The ONE chore that structurally cannot move to a per-repo cron (a frozen session's
   own cron is what has stopped). Asked of ai-maestro on #79 item 1.
   **Corrected 2026-08-05, then corrected AGAIN the same hour — read the second one.**
   `88e6f45a` did restore it briefly: `session-liveness`, `fleet-stop`, `cache-prune`,
   `rules-cleanup`, `memory-guard`, `github-config-audit` all ran under a repo daemon
   (pid 97639) alongside the live server. **It lasted 8 minutes.** At 10:07:37 it took
   SIGTERM, was respawned from the DATA-staged closure — which is CACHED code without the
   fix — and that one exited `server-owns-host` immediately. Six chores dark again.

   **A manually-started repo daemon is NOT a viable bridge, and this is structural, not bad
   luck.** `global_state.daemon_needs_restart()` compares the running daemon's argv (expected:
   `.../<plugin-cache-version>/scripts/daemon.py`) against the heartbeat's own
   `daemon_script_path()`. A repo path never matches a cache path, so **every armed session's
   heartbeat SIGTERMs it**, then `ensure_daemon_running()` reseats the daemon from the staged
   cache closure — the one lacking `88e6f45a`. Lifetime is therefore bounded by the next
   heartbeat fire, i.e. minutes. Verified in `daemon.log`: `received signal 15` →
   `started (pid=97669)` → `stopping (server-owns-host)`, all inside 7 seconds.

   **So the publish (TRDD-AWXK0RFT / CPV#189) is the real and only gate for durable coverage.**
   The one alternative — re-staging the closure into the DATA dir from the repo — is a
   hand-deploy of unpublished code machine-wide that bypasses every publish gate, and is an
   OWNER decision, not an agent one. Not taken.

   *(Superseded, do NOT carry forward: "standalone `#N` sessions have NO freeze recovery at this
   moment" — true until `88e6f45a`; and "treat coverage as holding only while pid 97639 lives"
   — that pid is already gone, and the phrasing implied a manual start is a usable stopgap. It
   is not.)* Tracked as EHT TRDD-KQ9WM4TZ.
3. The four movable chores (`cache-prune`, `rules-cleanup`, `github-config-audit`,
   `memory-guard`) still live in the daemon — they need TRDD-QK7M2B0X's shared locks first.
   **STILL OPEN**; QK7M2B0X is at `column: dev`, so this is genuinely blocked, not stalled.

**SUPERSEDED — do NOT carry forward:** the "NOT STARTED / get an owner decision" text this
block replaced, and rev 4's "the daemon keeps running and yields the absorbed chores".

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
