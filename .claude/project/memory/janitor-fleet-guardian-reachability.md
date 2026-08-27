---
name: janitor-fleet-guardian-reachability
description: "the status table says a project is NOT armed but I armed it myself / did the plugin update reset the arming / daemon.log says UNREACHABLE ({}) — would rearm; skipped (no keystroke channel) / the guardian never rescues my frozen sessions / can the janitor send commands to other claude instances / I disarmed a project and the janitor re-armed it anyway / after a global disarm the other sessions keep firing at a missing file / every project's heartbeat broke after I disarmed one / iTerm Automation channel denied vs empty how to tell them apart / channel-blocked-not-empty vs consistent-empty verdict / claude agents --json as a grant-free second view / does osascript returning zero mean blocked or truly idle / cwd-keyed roster instead of session name matching / the alarm guessed wrong about why the channel was empty / does the fleet guardian actually reach a frozen session / what does the armed column in the status table mean / the daemon.log line says would rearm but skipped why"
ocd: 2026-07-09
lmd: 2026-08-27
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: fleet
publish-globally: false
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
from the MANAGER or the user. This channel is live only where an ai-maestro server is
running — check `~/.aimaestro/server-liveness.json` (30 s beat, 90 s staleness) via
`harness_backend.server_is_alive()` rather than assuming either way.[^4]

**Injection is not execution.** Keystrokes typed into a wedged pane sit in the pty
buffer until the session unwedges. Nothing is lost; nothing is instant.

## When NO channel resolves: prefer the ORIGINAL pane, and never open a window

Only ONE rung creates a surface. `relaunch` (5) and `force_restart` (6) both type into
the pane already in `inst.terminal`, so they restart in place — same tab, nothing new.
`resurrect` (7) is the sole exception, and `daemon._hard_restart_plan` reaches it only
when `build_force_restart` returned `None`, i.e. no channel resolved at all.

That "unreachable" verdict is softer than it reads. `fleet_scan` resolves the terminal
from the **live TTY and deliberately never from a recorded id** — correct, because that
is what lets it reach a zombie instance whose janitor predates
`terminal-identity.json`. But live resolution can fail on a pane that is perfectly
reachable; the known case is the **iTerm TCC denial above**, which the scanner already
flags (`fleet_scan.iterm_automation_blocked` — "iTerm is UP but the osascript enumerated
ZERO sessions"). A healthy tab then reads as unreachable.

So before escalating, `_hard_restart_plan` retries with `fleet_restart.recorded_terminal()`
— the pane the SESSION wrote at its own start (`on-session-start.py`, which is the only
process that can see `TMUX_PANE` / `ITERM_SESSION_ID`). It is a FALLBACK, never a
substitute: live wins whenever it resolves, so a moved or recycled pane is still
preferred over a stale recording.

**The surface mapping that makes this matter.** Under iTerm2's tmux control mode the
correspondence is fixed:

| tmux | iTerm2 |
|---|---|
| session | **window** |
| window | **tab** |
| pane | split pane |

So `tmux new-session` cannot help but open a whole WINDOW. `resurrect` now uses
`tmux new-window -d -t <session>` (a TAB; `-d` creates it without switching, so a 3am
recovery is visible without yanking the user's view), falling back to `new-session` only
when no session exists — this rung must never fail to produce a plan.

The session id is passed to the builder as **data**, not resolved inside it: every
`build_*` is pure by contract, and the suite's sandbox guard rejects a machine-touching
call hidden in one.[^5]

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

See also [[janitor-architecture]] — the L0–L3 immortality layers this reachability
diagnosis lives inside. [[status-lines-to-autonomous-readers-cause-escalation]] — a
control flag with readers and no writers is exactly this page's `armed`-column
mislabeling, generalized: whichever scope is never auto-cleared is where remediation
piles up.

## See also

- [[janitor-daemon-process-identity]] — which interpreter the daemon runs under (the TCC-grantable identity), the restart gate that evicted our own version-less daemons, and the breaker that quarantined a healthy version for it.


^ATOM-O1K6-F8D8 [desc:"Since v2.8.0 the guardian runs a grant-free claude-agents-json second view when osascript returns zero - the alarm states channel-blocked-not-empty vs consistent-empty instead of guessing.", keywords: denied_vs_empty_iterm_channel second_view_claude_agents_json grant_free_enumeration channel-blocked-not-empty_verdict cwd_keyed_roster_never_name alarm_states_which_way_it_discriminated osascript_returned_zero_did_it_mean_blocked_or_idle claude_agents_--json_needs_no_session_or_grant three-way_second_view_verdict iterm-automation-blocked.flag_payload does_osascript_zero_mean_the_channel_is_empty guardian_no_longer_guesses_what_zero_means, ocd: 2026-08-08, lmd: 2026-08-08]

Since v2.8.0 (TRDD-DFKEXO79) the guardian no longer has to GUESS what osascript's zero
means: `scripts/lib/cli_agent_roster.py` runs `claude agents --json` — which needs no
session and no macOS Automation grant (CC 2.1.224) — as an INDEPENDENT second view, probed
only on the rare blocked path in `gather_fleet`. The three-way `second_view_verdict` rides
the `iterm-automation-blocked.flag` payload, and the heartbeat alarm states which way it
discriminated: `channel-blocked-not-empty` (live sessions demonstrably exist while the
channel returns zero — a denial or hung osascript, PROVEN), `consistent-empty`, or a failed
probe reported AS a failed probe ("the ambiguity stands" — an unrun check strengthens
neither reading). Rows are keyed by CWD (+pid), never `name`: name is a mutable display
string (six misroutes in one day were all name-drift); measured, the CLI enumerates MORE
than in-session ListAgents (25 vs 18 rows, including pane-less sessions). What this
deliberately does NOT solve: pane RESCUE — ESC injection and the TCC grant (see the atoms
above) still own that rung; the second view proves the channel is blocked, it cannot type
into a pane. [^6]

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
  than per-project — a fact a directory listing settles. Lesson: before writing the inverse of an
  operation, check the SCOPE of what it wrote. A project-scoped command that deletes a
  machine-wide file is a fleet-wide outage wearing the costume of a local cleanup.
[^4]: [id:ATOM-MG05-0013, status:valid, keywords:"page_asserted_the_ai_maestro_server_is_not_running_yet machine_state_written_into_a_pushed_project_page channel_declared_inert_but_it_was_live probe_server_liveness_instead_of_asserting", ocd:2026-07-29, lmd:2026-07-29]
  DO NOT record a MACHINE's current state as a fact in a PROJECT-scope page, BECAUSE this
  page said "the ai-maestro server is not running on this machine yet, so this channel is
  inert" — true on 2026-07-09, false by 2026-07-29 (a live server with a fresh
  `server-liveness.json`), and PROJECT memory is pushed to every clone, so the claim was
  wrong for other machines the day it was written. It also mattered: that same live server
  absorbs the plugin-update chores, so "inert channel" was exactly backwards. DO write the
  machine-agnostic form — name the PROBE (`harness_backend.server_is_alive()` /
  `~/.aimaestro/server-liveness.json`) and let the reader resolve it — and put per-machine
  state in LOCAL scope.
[^5]: [id:ATOM-MG05-0014, status:valid, keywords:"put_a_live_tmux_call_inside_a_pure_builder sandbox_guard_denied_the_spawn build_star_functions_must_stay_inspectable resolve_io_at_the_caller", ocd:2026-07-29, lmd:2026-07-29]
  DO NOT resolve live machine state inside a `build_*` planner, BECAUSE the first cut of the
  resurrect tab fix called `tmux list-sessions` from within `build_resurrect`, and the suite's
  sandbox guard denied it — correctly: these builders are pure by contract so a plan can be
  inspected and dry-run, and an invisible subprocess in one is the "machine-touching call as
  an invisible default" that guard exists to surface. DO pass the resolved value in as data
  and let the layer that already owns I/O (the daemon) obtain it.
[^6]: [id:ATOM-5GHB-FA72, status:valid, keywords:"backticks_in_double_quoted_shell_argument shell_expanded_an_inline_flag memory_page_gained_foreign_content unclosed_props_lint_error heredoc_quoting_discipline", ocd:2026-08-08, lmd:2026-08-08] DO NOT wrap a CLI name in backtick characters inside a DOUBLE-QUOTED shell argument (a memgrep desc flag, a commit message flag, any inline flag), BECAUSE under double quotes the shell treats a backtick pair as an expansion marker and replaces that span with the named tool's output — while this very atom was being authored, the desc flag's wording was expanded away and unrelated details from a different project landed in the tracked page (caught by memgrep lint's unclosed-props ERROR; the page was corrected while still unpushed). DO pass prose bodies via a quoted-delimiter heredoc (single-quoted EOF marker, under which no expansion applies) and keep inline arguments free of backtick and dollar-paren markers. Deliberately worded without the live characters or action verbs: shipped prose about this hazard must read as quoting discipline, so the release gate sees data, not directions.
