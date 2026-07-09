---
name: janitor-fleet-guardian-reachability
description: "the status table says a project is NOT armed but I armed it myself / did the plugin update reset the arming / daemon.log says UNREACHABLE ({}) — would rearm; skipped (no injection channel) / the guardian never rescues my frozen sessions / can the janitor send commands to other claude instances"
ocd: 2026-07-09
lmd: 2026-07-09
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: fleet
---

## Governed by

`[[janitor-architecture]]` (the hub). See also `[[macos-keychain]]` — the iTerm half
of this page fails for the SAME unstable-binary-identity reason as the keychain flood.

## The `armed` column does not mean "the heartbeat is running"

`fleet_status.py` defines it as one thing: does
`<project>/.janitor/state/heartbeat-armed-at.ts` exist. **Only** `/janitor-arm`
step 6 writes that stamp; **only** `/janitor-disarm` deletes it. No detector, no
purge, no version update touches it, and it is project-scoped — so **a plugin
update can never reset your arming.**

The stamp records how far an agent got through a numbered skill. `CronCreate` is
step 5; the stamp is step 6. A turn that ends, rate-limits, or errors between them
leaves a cron with no stamp (table says "not armed" — a lie). A Claude restart
leaves a stamp with no cron (table says "armed" — also a lie). Both directions are
observed: `agentlens` had 78 state files and detector `last-run-*.ts` stamps
proving its heartbeat fired, with no arm stamp; `genny-bot` had a stamp from Jun 25
while diagnosed `cron_dead`.

Underneath, `~/.claude/scheduled_tasks.json` does not exist on this machine at all.
Zero durable crons have ever persisted (the `durable: true` → session-only
downgrade, janitor#23), so **"armed" and "firing" are independent facts.** Tracked
in janitor#77; the proposed fix is to re-arm on every wake rather than trust a
stamp, since `/janitor-arm` is idempotent.

## `/janitor-global-arm` arms nothing

Its whole body is `clear_kill_switch(); clear_global_pause()`. Its own SKILL Scope
section says so: *"Does NOT arm any per-project heartbeat cron (that is
`/janitor-arm`)."* There is no fleet-wide arm in the plugin. On a machine with
neither flag set it is a strict no-op. Do not run it expecting a fan-out.

## Why the daemon logs `UNREACHABLE ({})`

`({})` is an empty terminal-identity dict from `fleet_scan.resolve_terminal_for_tty`.
The guardian diagnosed the instance correctly and then had no way to reach it.

The split is by **who spawned the daemon**. A session-spawned daemon (its
`daemon.log` lines carry an `[s:<8hex>]` prefix) resolved channels and landed 93
injections. The **launchd** daemon resolved a channel **0 times in 254 consecutive
beats**. Two independent causes:

1. **tmux — PATH.** A launchd child does not inherit the login shell's PATH; it
   gets the uv-python bin dir plus the four system dirs, with no Homebrew prefix.
   `fleet_scan` shells `tmux list-panes` by bare name and `_run` swallows the
   `FileNotFoundError` into `""`. Fixed in v0.35.5 (`daemon_path.ensure_tool_path`
   augments `os.environ` once at daemon start, appending never prepending). Proven
   live: `FIRED rearm → tmux for genny-bot`, the first injection a launchd daemon
   ever landed.
2. **iTerm — TCC.** `osascript` IS on the bare PATH; the daemon simply has no
   Automation grant, and the grant cannot stick because the LaunchAgent plist's
   `ProgramArguments[0]` is a per-version uv-python path. macOS attributes an
   Automation grant to a binary identity, and ours changes every release. **STILL
   OPEN** — TRDD-VQ4LX7ND part 2. iTerm-only instances remain unreachable from the
   launchd daemon.

The blindness was introduced by a *durability* improvement: moving the daemon out
of a session (the L0 OS-keepalive) bought it immortality and cost it its hands, and
nothing noticed because the loss of a capability was encoded as an empty string.

## Channels, and what actually reaches a wedged agent

Fallback order, shared by the gentle rungs (`rearm`/`reload`/`update`) and the hard
ones (`relaunch`/`force_restart`) via `fleet_inject.build_command_plan`:
tmux → iTerm → ai-maestro CLI → Linux GUI.

`aimaestro-agent.sh` is **not** PATH-gated (`_resolve_aimaestro_cli` probes
`$AIMAESTRO_CLI`, then `~/.local/bin`, and only then `shutil.which`).[^1] It is the
only channel that ENQUEUES: the entry persists server-side and drains when the
agent is genuinely idle, so it reaches a hibernated agent that keystrokes cannot.
Its limit is the correct one — `queue` maps to `send-command`, so the self-drive
exemption lets an agent enqueue only on **itself**; a genuine fleet-wide arm runs
from the MANAGER or the user. The ai-maestro server is not running on this machine
yet, so no instance carries an `aimaestro_session` and this channel is inert.

**Injection is not execution.** Keystrokes typed into a wedged pane sit in the pty
buffer until the session unwedges. Nothing is lost; nothing is instant.

## Stale `rate-limited.flag` mislabels quiet projects as `frozen`

17 of 35 projects hold one, up to 50 days old. Only a `dispatch.py` fire clears it,
which needs a live cron — so a project whose cron died can never clear it. In
`session_liveness.diagnose_instance` a fresh transcript always wins (a working
session is never touched), but a stale-transcript session with a stale flag is
classified `frozen` (ladder → rung 6 `force_restart`, a kill) instead of
`cron_dead` (→ a simple `rearm`). Harmless while the hard rungs stay default-off
(`CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED`); a footgun for whoever enables
them. Daemon-side sweep proposed in janitor#77.

## Notes and lessons learned

[^1]: [ocd:2026-07-09 lmd:2026-07-09] SUPERSEDED, and it shipped: v0.35.5's code
  comment, commit message, TRDD and a passing test all claimed the stripped launchd
  PATH disabled the ai-maestro channel "exactly as it disabled tmux". FALSE — that
  resolver checks `$AIMAESTRO_CLI` and an explicit `~/.local/bin` path before ever
  reaching `shutil.which`. WHY: I read the single `shutil.which("aimaestro-agent.sh")`
  call site and inferred the whole resolver from it, instead of reading the function.
  The harm was not only narrative: `resolve_injection_tools` checked with `which`, so
  the daemon would log "aimaestro-agent.sh MISSING — the matching recovery channels
  cannot fire" about a channel that works. A false alarm is the same disease as the
  silent skip that module exists to end, wearing the opposite mask. Corrected in
  v0.35.6. Lesson: when the live evidence names ONE channel (`FIRED rearm → tmux`),
  claim ONE channel; do not decorate evidence with a mechanism you have not read to
  the bottom.
