---
trdd-id: VQ4LX7ND
title: Launchd guardian resolves no injection channel — PATH stripped, TCC absent
column: dev
created: 2026-07-09T18:32:14+0200
updated: 2026-07-09T18:32:14+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: HIGH
effort: M
labels: [fleet, daemon, launchd, recovery]
task-type: bugfix
parent-trdd: null
npt: []
eht: []
blocked-by: []
supersedes: []
superseded-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
must-pass-tests-before-merge: true
test-requirements: [unit, lint, typecheck]
audit-requirements: []
review-requirements: []
runtime-targets: [macos, linux]
impacts: []
attempts: 1
test-failures: 0
last-test-result: pass
last-test-at: 2026-07-09T18:25:00+0200
implementation-commits: [2ff5c7c]
published-version: 0.35.5
published-at: 2026-07-09T18:28:00+0200
external-refs: []
---

# Launchd guardian resolves no injection channel

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-09

**PART 1 (PATH) — FIXED, PUBLISHED in v0.35.5, DEPLOYED and LIVE-VERIFIED.**
`2ff5c7c` adds `scripts/lib/daemon_path.py` + `daemon._repair_tool_path()`.
Live proof after restart (daemon pid 79652, 18:30):
`PATH augmented with: /opt/homebrew/bin:…:~/.local/bin:~/.cargo/bin`, then at
18:31:44 `session-liveness: FIRED rearm → tmux for genny-bot [cron_dead]` — the
FIRST injection a launchd-spawned daemon has ever landed (prior record: 0 fires
in 254 consecutive beats).

**PART 2 (TCC / iTerm) — STILL OPEN. This is the remaining work.**
Same beat, same daemon: `agentlens [frozen] … UNREACHABLE ({})` and
`ANIME2SVG [frozen] … UNREACHABLE ({})`. Both are iTerm-only instances.

**NEXT ACTION:** give the LaunchAgent a STABLE binary identity that macOS TCC can
attribute an Automation grant to, so `parse_iterm_sessions`' osascript returns
sessions instead of "".

## Problem

The fleet guardian (`daemon.task_session_liveness`) diagnosed every frozen /
cron-dead instance correctly every 2 minutes, then skipped each one:

```
session-liveness: agentlens [frozen] attempt=0 UNREACHABLE ({}) — would rearm; skipped (no injection channel)
```

`({})` is the terminal-identity dict from `fleet_scan.resolve_terminal_for_tty`.
Empty. The recovery audit splits cleanly by who spawned the daemon:

| daemon spawned by | resolved a channel | UNREACHABLE |
|---|---|---|
| a session heartbeat (`[s:<id>]` log prefix) | 56 | 54 |
| **launchd (the L0 OS-keepalive)** | **0** | **254** |

93 injections have ever fired (73 `rearm`, 14 `reload`, 4 `update` over iTerm;
2 `rearm` over tmux). Every one came from a session-spawned daemon.

## Root cause — two independent defects, one symptom

Observed launchd daemon PATH (`ps -p 89016 -wwEo command`):
`<uv-python>/bin:/usr/bin:/bin:/usr/sbin:/sbin`

1. **tmux — PATH.** A launchd child does not inherit the login shell's PATH.
   `tmux` is at `/opt/homebrew/bin/tmux`; `aimaestro-agent.sh` at
   `~/.local/bin/`. Neither dir is on the inherited PATH. `fleet_scan` shells
   `tmux list-panes` by bare name and `_run` swallows the `FileNotFoundError`
   into `""`; `terminal_trigger._resolve_aimaestro_cli` uses a bare
   `shutil.which`. Both channels vanished, **with no error logged anywhere**.

2. **iTerm — TCC Automation.** `osascript` IS found (`/usr/bin/osascript`, on
   the bare PATH). But the daemon runs as
   `XPC_SERVICE_NAME=com.ai-maestro-janitor.daemon` with no Aqua-session
   Automation grant, so the AppleScript that enumerates iTerm sessions returns
   nothing. Not verified by reading the TCC db (needs Full Disk Access); inferred
   from: osascript resolves, iTerm is running (the `"iTerm" in ps_text` gate
   passes), the identical call from a GUI-session process returns sessions, and
   the only remaining difference is the process's session/TCC context.

   The grant cannot stick because the plist's `ProgramArguments[0]` is a
   **per-version uv python path** — macOS attributes an Automation grant to a
   binary identity, and that identity changes on every release. **This is the
   same unstable-binary-identity trap as the keychain-prompt flood**
   (TRDD-K3WQ7XM9 defect #4, wikimem `[[macos-keychain]]`).

The bug was not that a channel died. It was that a dead channel degraded into a
**mute skip loop** for hours — which is why it survived a fleet-injector fix
(`b684571`) that made the gentle rungs walk all four channels: that fixed *which*
channels are tried, not the case where *none resolve*.

## Fix — Part 1 (shipped)

`scripts/lib/daemon_path.py`:
- `augmented_path(current, *, candidates, exists)` — PURE (injected `exists`
  predicate), **appends** the platform's standard prefixes that exist on disk and
  are not already present. Appends, never prepends: the launcher's own entries
  keep priority, so this can only make an unresolvable tool resolvable, never
  shadow one the host chose.
- `ensure_tool_path()` — mutates `os.environ` once at daemon start, so every
  probe, every keystroke send, and every future tool inherits it for free. In the
  process rather than in each argv; and unlike a plist `EnvironmentVariables`
  block it survives a plugin update (that would need a reinstall).
- `resolve_injection_tools()` + the startup log line naming any tool that does
  **not** resolve. This is the other half of the fix: a dead channel is now
  visible at boot instead of silent.

`aimaestro-agent.sh` is tracked as an injection tool because — per the USER,
2026-07-09 — the ai-maestro channel **enqueues** a command that a hibernated
agent executes on wake, and needs neither a GUI session nor a TCC grant. It is
therefore the only channel that can reach a wedged agent from a headless daemon.
(It resolves now, but is inert on this host while the ai-maestro server is down,
so `_aimaestro_agents()` returns no agents and no instance carries an
`aimaestro_session`.)

`daemon_path.py` joins the L0 staged import closure automatically (BFS over
imports); `test_closure_includes_daemon_path_module` pins it, because a closure
that omitted it would `ImportError` on every launchd boot → OS relaunch →
crash-loop → the C4 breaker quarantines a good version.

15 new pure tests; closure bound 30 → 40 for the one legitimate new module.

## Fix — Part 2 (OPEN)

Give the LaunchAgent a stable `ProgramArguments[0]`: a fixed shell script staged
in the DATA dir (path constant across versions) that `exec`s the current uv
python. macOS can then attribute an Automation grant to *that* path, and the
grant persists across plugin updates. Requires a one-time user approval of the
TCC prompt — which a headless agent cannot surface, so the approval must be
solicited from a foreground context (a `/janitor-*` command the user runs once).

Open questions:
- Does a LaunchAgent with `LimitLoadToSessionType: Aqua` get to *raise* the TCC
  prompt at all, or must a foreground process pre-seed the grant?
- Fallback if TCC proves unusable: teach `fleet_scan` to resolve iTerm sessions
  without AppleScript (iTerm writes no tty→session map on disk, so probably not),
  or accept that iTerm-only instances are reachable only from a session-spawned
  daemon and keep one such daemon alive by design.

## Load-bearing facts / gotchas

- `fleet_scan._run` returns `""` on ANY exception — including a missing binary.
  Any new bare-name subprocess added there will fail silently the same way.
- `daemon.log` lines from a session-spawned daemon carry an `[s:<8hex>]` prefix;
  launchd-spawned lines do not. That prefix is the cheapest way to tell which
  daemon produced a line.
- Injection ≠ immediate execution. Keystrokes typed into a wedged pane sit in the
  pty buffer until the session unwedges; the ai-maestro CLI enqueues explicitly.
  Neither is lost, but neither is instant.
- The `armed` column in `/janitor-show-global-status` reads
  `<project>/.janitor/state/heartbeat-armed-at.ts` — written ONLY by
  `/janitor-arm` step 6, deleted ONLY by `/janitor-disarm`. It reports "did the
  arm skill run to completion here", NOT "is the cron alive". A project whose
  heartbeat is demonstrably firing can show `armed: no` (agentlens: 78 state
  files, detector `last-run-*.ts` through Jul 1, no arm stamp).

## Notes and lessons learned

The blindness was introduced by a *durability* improvement. The L0 OS-keepalive
exists so the guardian survives every session dying — but a launchd child is
exactly the context that has no login PATH, no Aqua session, and no TCC grants.
Moving the daemon out of a session bought it immortality and cost it its hands,
and nothing in the system noticed, because the loss of a capability was encoded
as an empty string.
