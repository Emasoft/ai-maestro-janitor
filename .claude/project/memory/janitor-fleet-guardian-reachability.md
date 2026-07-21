---
name: janitor-fleet-guardian-reachability
description: "the status table says a project is NOT armed but I armed it myself / did the plugin update reset the arming / daemon.log says UNREACHABLE ({}) — would rearm; skipped (no injection channel) / the guardian never rescues my frozen sessions / can the janitor send commands to other claude instances / I disarmed a project and the janitor re-armed it anyway / after a global disarm the other sessions keep firing at a missing file / every project's heartbeat broke after I disarmed one"
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
downgrade, janitor#23), so **"armed" and "firing" are independent facts.**

**Since v0.36.0 the stamp is no longer load-bearing.** The SessionStart arm-nudge
gates on the POSITIVE opt-out (`disarmed.flag` absent) instead of on the stamp being
present, so every wake in a non-opted-out project re-arms — `/janitor-arm` deletes
existing `[janitor-heartbeat]` crons before creating one, so an unconditional re-arm
is free. The stamp survives only as the status table's `armed` column, which still
lies in both directions and is now merely cosmetic (janitor#77 items 2-3, item D
undecided).

## `disarmed.flag` is the opt-out — and until v0.36.0 nobody wrote it

`disarmed.flag` in a project's `.janitor/state/` is the fleet layer's ONE positive
opt-out. `fleet_scan.diagnose_root` reads it into `deliberately_unarmed`;
`session_liveness.diagnose_instance` turns that into `unarmed`, which is sacrosanct
and never touched. Four consumers read it. **Zero wrote it**, for its whole life,
even though `fleet_scan`'s own docstring said "written by `/janitor-disarm`".[^2]

So a user who deliberately ran `/janitor-disarm` got a deleted cron, a deleted
stamp, and **no opt-out record** — and the guardian's next beat saw no cron plus a
stale transcript, diagnosed `cron_dead`, and typed `/janitor-arm` straight back into
their pane. The janitor re-armed exactly what the user had just stopped.

Fixed in v0.36.0 (`57bfe31`): disarm writes the flag; **arm removes it FIRST, before
`CronCreate`**, because ordering decides which way a half-finished arm fails. Clear
first and a turn that dies before the cron exists leaves no cron and no opt-out — the
guardian re-arms, and it self-heals. Clear last and it leaves a cron plus a stale
opt-out, and the guardian files the project under "the user opted out" forever.
Failures must fall toward guarded, not abandoned. `state.DISARMED_FLAG` is now the
single definition of the name.

## `/janitor-disarm` used to delete a machine-wide file

Until v0.36.0, step 4 of `/janitor-disarm` ran
`rm -f "${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py"`, called "a clean inverse of arm".
It is not: `CLAUDE_PLUGIN_DATA` is per-**plugin**, so that stub is ONE file every
project's cron execs, and arm installs it idempotently. The inverse of a shared
idempotent install is nothing.[^3]

The severe part is that `/janitor-disarm` is also what a session runs on the bare
`[janitor-self-disarm]` marker. So `/janitor-global-disarm` had every armed session
on the machine race to that `rm`: the first one won, and every other session's cron
kept firing at a missing path, dying *before* `dispatch.py` — so it never emitted its
own self-disarm marker, never deleted its own cron, and never cleared its
`rate-limited.flag`. A full billed turn every five minutes, forever. That is the
exact cost TRDD-RQ9FIFX6 exists to eliminate ("only NOT firing costs zero"), and step
4 guaranteed at most one session ever escaped it. It compounded with the next section:
after a global disarm nothing recreates the stub until someone runs `/janitor-arm` by
hand.

Nothing deletes the stub now. It is 13 KB, inert without a cron, and `/plugin
uninstall` owns the data dir.

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
them.

**Swept by the daemon since v0.36.0** (`9e6fa2b`) — the daemon is alive when the cron
is not, which is the only thing that breaks the circle. Age is the flag's own mtime,
because the StopFailure hook `touch()`es it on EVERY turn-ending API error: a session
that is genuinely rate-limited right now keeps its flag fresh for the whole limit and
is never swept, while one that has not hit an API error in 24 h is not rate-limited by
any definition. (`rate-limited-since.ts` is useless for this — it is overwritten every
failing turn, so it records the LAST rate limit, not the first.) Window:
`rate_limit_flag_max_age_hours`, default 24, `0` disables. The sweep is opt-in at the
`gather_fleet` seam so `fleet_status` — which renders the read-only status table —
never mutates what it reports on, and it runs BEFORE `diagnose_root` so one beat both
clears the litter and acts on the corrected diagnosis. A `disarmed.flag` project is
skipped entirely: sacrosanct means we do not write into its tree, not merely that we
do not inject into its pane. Reaches only projects with a running claude (that is the
complete set of *harmful* cases — a flag in a dormant project is inert litter).

## Notes and lessons learned

[^1]: [id:ATOM-MG05-0010, status:valid, keywords:"inferred_resolver_from_one_call_site false_missing_channel_alarm read_function_not_one_callsite", ocd:2026-07-09, lmd:2026-07-09] SUPERSEDED, and it shipped: v0.35.5's code
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
[^2]: [id:ATOM-MG05-0011, status:valid, keywords:"four_readers_zero_writers_flag grep_the_write_not_the_prose test_constructs_own_precondition", ocd:2026-07-09, lmd:2026-07-09] `disarmed.flag` shipped with FOUR readers and
  ZERO writers, and nobody noticed for the flag's whole life. Two reasons, and both
  generalize. (1) `fleet_scan`'s docstring asserted "written by `/janitor-disarm`" —
  a sentence naming a writer, a reader and a filename, which reads exactly like
  documentation of a thing that exists. The only way to find out was to grep for the
  WRITE (`grep -rn "disarmed\.flag"` → four readers, one test, no writer), not to read
  the sentence claiming it. (2) `tests/test_fleet_scan.py` supplies the missing
  precondition itself — `(sdir / "disarmed.flag").write_text("")` — then asserts the
  reader honors it. Every assertion passes. **A unit test that constructs its own
  precondition proves the reader is correct GIVEN a writer, and says nothing about
  whether a writer exists.** And `git log` shows no commit ever touched the skill and
  `fleet_scan.py` together (5 commits on one, 7 on the other, 0 on both), so no
  reviewer ever had the two halves on screen at once. The guard test that now exists
  (`test_fleet_scan_reads_the_flag_the_skills_write`) deliberately straddles the
  boundary instead of sitting on one side of it. Same disease as `[^1]` and as the
  release-timeout and CPV-pin errors of the same day: a mechanism asserted in prose and
  never read to the bottom.
[^3]: [id:ATOM-MG05-0012, status:valid, keywords:"inverse_of_shared_idempotent_install check_scope_before_writing_inverse project_command_deletes_machine_wide_file", ocd:2026-07-09, lmd:2026-07-09] The stub deletion in `/janitor-disarm` was
  justified in the skill itself as making disarm "a clean inverse of arm" — a symmetry
  argument, and it was wrong because arm's write is IDEMPOTENT and SHARED. The inverse
  of a shared idempotent install is nothing, not a delete. WHY it survived review: the
  sentence is persuasive, the two commands look symmetric on the page, and the blast
  radius is invisible unless you notice that `CLAUDE_PLUGIN_DATA` is per-plugin rather
  than per-project — a fact one `ls` settles. Lesson: before writing the inverse of an
  operation, check the SCOPE of what it wrote. A project-scoped command that deletes a
  machine-wide file is a fleet-wide outage wearing the costume of a local cleanup.
