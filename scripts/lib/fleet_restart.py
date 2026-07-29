"""Hard-restart recovery rungs (TRDD-56d24c02 / TRDD-324223a6 A5) — the rungs that
KILL and RESPAWN a claude process when the gentle command-typing rungs
(rearm/reload/update) cannot revive a session.

THREE rungs, escalating:

- **relaunch** — the pid is GONE (`dead`) but the pane lives → type
  ``claude --continue`` into the pane to resume the session IN PLACE. No kill;
  ``--continue`` preserves the transcript, so this is not data loss.
- **force_restart** — the pid is alive but HARD-WEDGED (`frozen`, gentle ladder
  exhausted) → ``os.kill`` the stuck pid, then ``claude --continue`` in the pane.
- **resurrect** — the pane itself is unreachable → spawn a background ``claude``
  (``tmux new-window -d`` in an existing session — a TAB; ``new-session`` only when no
  session exists) that kills + relaunches the stuck one. The "launch a background claude
  to kill+restart a stuck one" the user demanded.

THE SAFETY MODEL (this module kills processes, so it is gated three ways):

1. **DEFAULT-OFF.** ``hard_restart_enabled()`` is false unless the user opts in with
   ``CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED=1``. Until then ``fire_restart``
   builds + returns a ``DRY_RUN`` marker and executes NOTHING.
2. **NEVER the user's working session.** ``is_killable`` refuses unless the pid is a
   real ``claude`` process, the instance is NOT ``active`` (transcript advancing),
   the diagnosis is the genuinely-wedged ``frozen``, and the pid is neither this
   process nor the daemon. ``diagnose_instance`` upstream already guarantees an
   active session is ``healthy`` (never ``frozen``/``dead``), so this is the second
   independent gate, not the only one.
3. **BOUNDED.** The caller wraps every hard-restart attempt in the crash-loop guard
   (``session_liveness.crash_loop_tripped``) so a persistent fault pages a human
   instead of entering a kill/respawn storm.

PURE where it can be: every ``build_*`` returns a plan dict you can inspect/dry-run;
``fire_restart`` takes injectable ``killer``/``spawner`` so tests never touch a real
process. This module is INTENTIONALLY not yet wired into the daemon's live loop
(TRDD-56d24c02 increment 2 does that, behind the opt-in) — it ships tested + inert.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fleet_inject  # noqa: E402  (bare sibling import; lib/ is on sys.path)

# The last-resort relaunch. Deliberately the MINIMUM that resumes a transcript: every other
# flag is MIRRORED from how the session was actually launched (see `relaunch_command`).
_FALLBACK_RELAUNCH_CMD = "claude --continue"
_RESUME_FLAGS = ("--continue", "-c", "--resume", "-r")


def with_resume(argv: str) -> str:
    """`argv` guaranteed to resume rather than start a fresh session.

    A VERBATIM replay is wrong for the one case that matters: a session launched WITHOUT
    `--continue` (the common case — you type `claude`, then work for hours). Replaying that
    line starts an empty session in the recovered pane, and because the process is running
    again the fleet scanner reads it HEALTHY while the entire transcript is gone. That is a
    worse outcome than not recovering at all, because it is silent.

    An existing resume flag is left alone — `--resume <id>` targets a specific session and
    appending `--continue` would fight it.
    """
    argv = (argv or "").strip()
    if not argv:
        return ""
    if any(f in shlex.split(argv) for f in _RESUME_FLAGS):
        return argv
    return f"{argv} --continue"


def relaunch_command(pid: int = 0, project_root: str | None = None) -> str:
    """The command that relaunches a session: MIRROR how it was actually launched.

    WHY MIRRORING, NOT A HARDCODED LINE (owner directive 2026-07-29). The previous version
    hardcoded a resume line carrying a permission-bypass flag plus a guessed set of
    `--add-dir` temp paths. Two things were wrong with that, and the second is the important
    one:

    1. It shipped a literal permission-bypass invocation inside the plugin, which CPV's
       security gate flags CRITICAL — correctly. Obfuscating the string to dodge the scanner
       would hide a real capability while keeping it working, so the honest fix is to not
       ship the capability at all. Mirroring means the bypass (if any) is the USER'S, present
       only because they launched with it; the artifact contains nothing.
    2. It GUESSED two flags and dropped every other one. A real launch line carries things
       recovery must preserve — `--model`, `--add-dir`, `--mcp-config`, `--agent`,
       `--settings`. Hardcoding silently relaunched the session as a DIFFERENT session.

    Resolution ladder, most-authoritative first:
      * the LIVE argv of `pid` (`ps -p … -o args=`) — exact, current, no staleness risk;
      * the argv RECORDED at session start (`terminal-identity.json`) — required for rung 5,
        where the pid is already gone and there is nothing left to read;
      * `claude --continue` — better than refusing to recover.

    Every rung is guarded so it can only ever relaunch something that IS claude
    (`is_killable`, and the `argv_is_claude` filter here), so a recycled pid cannot make this
    replay an unrelated command line.
    """
    if pid > 0:
        live = live_cmdline(pid)
        if argv_is_claude(live):
            return with_resume(live)
    recorded = recorded_argv(project_root)
    if argv_is_claude(recorded):
        return with_resume(recorded)
    return _FALLBACK_RELAUNCH_CMD


def argv_is_claude(argv: str) -> bool:
    """True iff `argv` actually launches claude — the guard on every mirrored replay.

    Matches the EXECUTABLE (argv[0]'s basename), never a substring of the whole line: a
    session whose flags merely mention the word (`--add-dir /src/claude-plugins`) is not a
    claude launch, and replaying a non-claude command line into a pane is exactly the class
    of mistake that turns recovery into arbitrary command execution.
    """
    try:
        parts = shlex.split(argv or "")
    except ValueError:  # unbalanced quotes — untrusted-looking, refuse
        return False
    if not parts:
        return False
    return os.path.basename(parts[0]) in ("claude", "claude.exe")


def hard_restart_enabled() -> bool:
    """Master opt-in for the process-killing rungs. DEFAULT-OFF — these rungs kill and
    respawn processes, so they stay dry-run-only until the user deliberately enables
    them with CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED=1 (the documented true
    spellings). Unlike the gentle rungs (idempotent, on by default), the irreversible
    rungs are opt-in."""
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED", "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_killable(
    *, pid: int, command: str, active: bool, diagnosis: str, self_pid: int, daemon_pid: int | None
) -> bool:
    """The hard gate before any ``os.kill``. True ONLY when killing this pid is safe:

    - ``pid > 0`` and is neither this process nor the daemon (never kill the guardian),
    - the instance is NOT ``active`` — a transcript-advancing session is the user's
      live work and is NEVER killed (belt-and-suspenders: upstream it would be
      ``healthy``, not ``frozen``, and never reach here),
    - ``command`` is a real ``claude`` process (we only ever kill claude, never some
      unrelated pid that happens to share a number),
    - ``diagnosis == 'frozen'`` — the only state with a LIVE-but-wedged pid worth
      killing (``dead`` has no live pid → relaunch types into the pane, no kill;
      ``healthy`` is working; ``unarmed`` is opted out).
    """
    if pid <= 0 or pid == self_pid or (daemon_pid is not None and pid == daemon_pid):
        return False
    if active:
        return False
    if "claude" not in (command or "").lower():
        return False
    return diagnosis == "frozen"


def _command_plan(terminal: dict, command: str, *, esc_first: bool) -> dict | None:
    """Build a keystroke plan that types ``command`` into a resolved terminal.

    Thin delegation to ``fleet_inject.build_command_plan`` — the ONE channel-selection
    builder (tmux -> iterm -> aimaestro -> linux-gui, every identity validated before
    it reaches an argv/osascript sink). This used to be a second, hand-maintained copy
    of that walk, and the copies drifted: the gentle rungs stopped after iterm while
    these hard rungs walked all four, so an ai-maestro agent reachable only by the CLI
    channel was skipped for ``/janitor-arm`` and later KILLED by a hard rung. Delegating
    makes the two rung families share one reachability set by construction.
    """
    return fleet_inject.build_command_plan(terminal, command, esc_first=esc_first)


def command_injection_plan(terminal: dict, command: str, *, esc_first: bool) -> dict | None:
    """PUBLIC raw-command channel builder — the single source of truth for typing an
    ARBITRARY command into another session's validated pane (tmux pane / iTerm UUID /
    ai-maestro CLI session / Linux GUI channel). The daemon's fleet-stop beat
    (TRDD-ME8V2YJF) reuses THIS rather than duplicating the channel logic, so both the
    recovery rungs and fleet-stop share one validated path (a tampered identity can
    never reach the argv/osascript). Returns a plan for ``fleet_inject.fire``, or None
    when no safe channel resolves."""
    return _command_plan(terminal, command, esc_first=esc_first)


def build_relaunch(terminal: dict, *, command: str = "") -> dict | None:
    """rung 5 — resume a `dead` (pid-gone) session by typing the relaunch line into its
    still-living pane. No ESC (a dead pane sits at a shell prompt, no modal). None when
    the pane/UUID can't be safely targeted.

    ``command`` is DATA, exactly like ``session`` on ``build_resurrect``: resolving it here
    would mean calling ``relaunch_command`` → ``live_cmdline`` → ``ps`` from inside a
    ``build_*``, breaking the module's purity contract (and tripping the suite's sandbox
    guard). The caller with I/O rights passes ``relaunch_command(pid, project_root)``.
    Empty falls back to the minimum that resumes a transcript.
    """
    cmd = _command_plan(
        terminal, (command or "").strip() or _FALLBACK_RELAUNCH_CMD, esc_first=False
    )
    if cmd is None:
        return None
    return {"rung": "relaunch", **cmd}


def build_force_restart(pid: int, terminal: dict, *, command: str = "") -> dict | None:
    """rung 6 — kill the hard-wedged `frozen` pid, then relaunch in its pane. The plan
    DESCRIBES the kill (``kill_pid``) + the relaunch; ``fire_restart`` performs the
    kill ONLY after ``is_killable`` passes. None when no pane resolves (then the caller
    escalates to resurrect). ``command`` is passed through to ``build_relaunch``."""
    relaunch = build_relaunch(terminal, command=command)
    if relaunch is None:
        return None
    return {"rung": "force_restart", "kill_pid": pid, "relaunch": relaunch}


def live_tmux_session() -> str:
    """The id of an existing tmux session to hang a resurrect window on, or "" if none.

    Session ID (``$3``) rather than name: a name may contain ``:``, which tmux parses as
    ``session:window`` in a ``-t`` target, so a user session called ``work:api`` would
    silently retarget. IDs have no such syntax. "" on any failure — the caller then falls
    back to creating its own session.
    """
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["tmux", "list-sessions", "-F", "#{session_id}"],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    for line in (proc.stdout or "").splitlines():
        sid = line.strip()
        if sid.startswith("$"):
            return sid
    return ""


def recorded_terminal(project_root: str | None) -> dict[str, str]:
    """The pane identity the SESSION recorded at start, or {} when there is none.

    THE POINT (owner directive 2026-07-29 — "restart in the same original tab"). Rungs 5
    and 6 already restart in place; rung 7 is the only one that creates a surface, and it
    fires exactly when no channel resolved. But ``fleet_scan`` resolves the terminal from
    the LIVE TTY and deliberately never from a recorded id — correct, because that is what
    lets it reach a zombie instance whose janitor predates ``terminal-identity.json``. The
    gap is that live resolution can fail on a pane that is perfectly reachable: the known
    case is iTerm automation denied by TCC, which the scanner itself flags
    (``fleet_scan.iterm_automation_blocked`` — "iTerm is UP but the osascript enumerated
    ZERO sessions"). Then a healthy tab reads as unreachable and we open one the user never
    needed.

    So: try live first (unchanged), and consult this only when live found nothing. Returns
    ONLY the two injection keys — ``term_program`` is recorded for diagnostics and is not an
    injection channel, so passing it through would put a non-channel key into a terminal
    dict that callers test for truthiness.

    Never raises: a missing/garbage file is simply "no recorded pane", and the caller
    escalates to rung 7 exactly as before.
    """
    if not project_root:
        return {}
    path = Path(project_root) / ".janitor" / "state" / "terminal-identity.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("iterm_session_id", "tmux_pane"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    return out


def recorded_argv(project_root: str | None) -> str:
    """The claude argv the SESSION recorded at start, or "" when there is none.

    Load-bearing for rung 5 (`dead`): the pid is already gone, so there is no live command
    line left to mirror. Only the session itself can capture this — `on-session-start.py`
    reads its own parent, which IS the claude process (verified: the hook's `getppid()`
    resolves to `claude …`, not to a shell wrapper).

    Same file as the pane identity, for the same reason: one artifact the session writes
    once, that a detached daemon can read later. Never raises.
    """
    if not project_root:
        return ""
    path = Path(project_root) / ".janitor" / "state" / "terminal-identity.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    argv = data.get("argv")
    return argv.strip() if isinstance(argv, str) else ""


def build_resurrect(
    pid: int, project_root: str | None, *, session: str = "", command: str = ""
) -> dict:
    """rung 7 — the pane is unreachable: spawn a background ``claude`` that, on launch,
    kills the stuck pid and resumes. The plan carries the kill target + the spawn argv;
    ``fire_restart`` runs it only when enabled AND ``is_killable`` passes. Always builds a
    plan (no pane needed) — it is the last resort precisely for the no-channel case.

    A WINDOW (i.e. a tab) in an existing session is preferred over a whole new session
    (owner directive 2026-07-29). A detached ``new-session`` is INVISIBLE: it does not
    appear in any tab bar, so a 3am resurrect leaves a running claude the user can only
    find by knowing to run ``tmux attach -t janitor-resurrect-<pid>``. As a tab it shows up
    where they are already looking, next to the session it replaced.

    ``-d`` on ``new-window`` creates the tab WITHOUT switching to it — visible, but it does
    not yank the user's current view away mid-task.

    ``new-session`` remains the fallback for when no session exists at all, because this
    rung must never fail to produce a plan.

    ``session`` and ``command`` are DATA, not lookups: this function stays PURE (the module
    contract — every ``build_*`` returns a plan you can inspect and dry-run). Resolving them
    here by shelling out to ``tmux``/``ps`` would put invisible machine-touching calls inside
    a builder, which is exactly what the suite's sandbox guard exists to surface. The caller
    with I/O rights (the daemon) passes ``live_tmux_session()`` and
    ``relaunch_command(pid, project_root)``.
    """
    cwd = project_root or os.path.expanduser("~")
    relaunch = (command or "").strip() or _FALLBACK_RELAUNCH_CMD
    # shlex-quoted so a crafted cwd cannot break out of the single command string.
    inner = f"kill {int(pid)} 2>/dev/null; cd {shlex.quote(cwd)} && {relaunch}"
    name = f"janitor-resurrect-{int(pid)}"
    # .strip(): a whitespace-only id is TRUTHY, so an unstripped value would build
    # `new-window -t "   "` — a target tmux cannot resolve, turning "no session" into a
    # silently failing spawn instead of the working fallback.
    target = (session or "").strip()
    if target:
        argv = ["tmux", "new-window", "-d", "-t", target, "-n", name, "sh", "-c", inner]
    else:
        argv = ["tmux", "new-session", "-d", "-s", name, "sh", "-c", inner]
    return {"rung": "resurrect", "kill_pid": pid, "cwd": cwd, "spawn": argv}


def live_cmdline(pid: int) -> str:
    """The pid's CURRENT command line, read fresh (`ps -p PID -o args=`, POSIX-portable).

    "" on any failure — and callers must treat "" as "cannot confirm", never as "safe".
    """
    if pid <= 0:
        return ""
    try:
        proc = subprocess.run(  # noqa: S603 - explicit args, no shell
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def fire_restart(
    plan: dict | None,
    *,
    enabled: bool,
    killable: bool,
    killer=os.kill,
    spawner=None,
    cmdline_reader=live_cmdline,
) -> str:
    """Execute a hard-restart plan — but ONLY when ``enabled`` (the opt-in) AND, for any
    rung that kills, ``killable`` (the ``is_killable`` verdict the caller computed) AND the
    pid is STILL a claude process at the instant we signal it.
    Returns a short status string for the daemon log; never raises.

    - not ``enabled`` → ``DRY_RUN:<rung>`` (build everything, execute nothing).
    - ``relaunch`` → fire the keystroke plan (no kill; ``killable`` not required).
    - ``force_restart``/``resurrect`` → refuse with ``REFUSED:not-killable`` unless
      ``killable``, and ``REFUSED:pid-recycled`` unless the live cmdline re-check passes;
      otherwise kill the pid (injectable ``killer``) then relaunch/spawn (injectable
      ``spawner``).

    THE RE-CHECK IS NOT REDUNDANT WITH ``is_killable``. That verdict is computed from a
    process-table SNAPSHOT taken during the fleet scan; the kill happens later, after a
    diagnosis, a cooldown gate and a plan build. In that window the wedged claude can exit
    and the OS can hand its pid number to something else — pids are recycled integers, not
    handles. Signalling on the stale verdict would then SIGTERM an innocent process that did
    nothing but inherit a number. So we re-read the pid's cmdline at the last possible moment
    and require it to still be a claude; if we cannot read it, we REFUSE rather than guess,
    because failing to restart a wedged session costs one more cooldown, while killing the
    user's editor or build costs their work.

    ``killer``/``spawner``/``cmdline_reader`` are injected so tests prove the control flow
    without touching a real process."""
    if not plan:
        return "NO_PLAN"
    rung = plan.get("rung", "?")
    if not enabled:
        return f"DRY_RUN:{rung}"
    if rung == "relaunch":
        return "FIRED:relaunch" if fleet_inject.fire(plan) else "FIRE_FAILED:relaunch"
    if rung in ("force_restart", "resurrect"):
        if not killable:
            return f"REFUSED:not-killable:{rung}"
        kill_pid = int(plan["kill_pid"])
        if "claude" not in cmdline_reader(kill_pid):
            # Either the pid is gone (nothing to kill — the wedge resolved itself) or it now
            # belongs to an unrelated process (recycled). Both mean: do NOT signal it.
            return f"REFUSED:pid-recycled:{rung}"
        try:
            killer(kill_pid, 15)  # SIGTERM the stuck pid
        except (OSError, ProcessLookupError):
            pass  # already gone is success for our purposes
        if rung == "force_restart":
            return "FIRED:force_restart" if fleet_inject.fire(plan["relaunch"]) else \
                "FIRE_FAILED:force_restart"
        # resurrect: spawn the detached background claude
        run = spawner if spawner is not None else _default_spawn
        return "FIRED:resurrect" if run(plan["spawn"]) else "FIRE_FAILED:resurrect"
    return f"UNKNOWN_RUNG:{rung}"


def _default_spawn(argv: list[str]) -> bool:
    """Spawn the resurrect argv fully detached; True iff launched. Best-effort."""
    try:
        subprocess.Popen(  # noqa: S603 - fixed argv (tmux new-window/new-session), no shell
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
