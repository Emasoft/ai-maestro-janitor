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
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fleet_inject  # noqa: E402  (bare sibling import; lib/ is on sys.path)


def _temp_dirs() -> list[str]:
    """The temp directories a relaunched session must be allowed to touch, per-OS.

    Two answers exist and they differ: POSIX `/tmp`, and the platform's own temp dir
    (`$TMPDIR` on macOS — `/var/folders/…/T` — and `%TEMP%` on Windows). Scratch files get
    written to BOTH depending on who created them, so an unattended session that can reach
    only one still stalls on the other. `/tmp` is skipped where it does not exist (Windows),
    which is also what keeps this list platform-correct without branching on the OS name.

    Deduped by real path: on macOS `/tmp` is a symlink to `/private/tmp`, so the resolved
    form is included too — a path handed to the session as `/private/tmp/…` (which is what
    a resolved scratchpad path looks like) would otherwise fall outside the allowance.
    """
    seen: set[str] = set()
    out: list[str] = []
    for cand in ("/tmp", os.path.realpath("/tmp"), tempfile.gettempdir()):
        if not cand or not os.path.isdir(cand) or cand in seen:
            continue
        seen.add(cand)
        out.append(cand)
    return out


# The shell command that resumes a claude session in a pane that dropped to a shell.
#
# WHY THE BYPASS FLAG (owner directive 2026-07-29). Every rung here fires at a session that
# is ALREADY unattended and wedged — that is the precondition for reaching a hard-restart
# rung at all. A relaunch that comes back up and then parks on a permission prompt has not
# recovered it: the process is running again, so the fleet scanner reads it as healthy while
# the session is as stuck as before, and now invisible. Recovery has to leave the session
# able to PROCEED, not merely alive.
#
# ONE flag, not two. `--dangerously-skip-permissions` performs the bypass.
# `--allow-dangerously-skip-permissions` only makes the bypass AVAILABLE "without it being
# enabled by default" (its own help text) — strictly weaker, and a no-op once the bypass is
# already on, so passing it would be cargo cult. `--permission-mode bypassPermissions` is
# likewise redundant here. Both are deliberately omitted.
#
# Blast radius is bounded by `hard_restart_enabled()` — DEFAULT-OFF, so no permission gate is
# dropped anywhere until the user deliberately opts the killing rungs in.
_TEMP_DIRS = _temp_dirs()
# shlex.quote: this string is both TYPED into a pane and embedded in an `sh -c` (rung 7),
# and a temp path can legally contain spaces on some platforms. The empty-list guard matters
# — a bare trailing `--add-dir` with no values would swallow the next token or error out.
_RELAUNCH_CMD = " ".join(
    [
        "claude --continue --dangerously-skip-permissions",
        *(["--add-dir", *(shlex.quote(d) for d in _TEMP_DIRS)] if _TEMP_DIRS else []),
    ]
)


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


def build_relaunch(terminal: dict) -> dict | None:
    """rung 5 — resume a `dead` (pid-gone) session by typing ``claude --continue`` into
    its still-living pane. No ESC (a dead pane sits at a shell prompt, no modal). None
    when the pane/UUID can't be safely targeted."""
    cmd = _command_plan(terminal, _RELAUNCH_CMD, esc_first=False)
    if cmd is None:
        return None
    return {"rung": "relaunch", **cmd}


def build_force_restart(pid: int, terminal: dict) -> dict | None:
    """rung 6 — kill the hard-wedged `frozen` pid, then relaunch in its pane. The plan
    DESCRIBES the kill (``kill_pid``) + the relaunch; ``fire_restart`` performs the
    kill ONLY after ``is_killable`` passes. None when no pane resolves (then the caller
    escalates to resurrect)."""
    relaunch = build_relaunch(terminal)
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


def build_resurrect(pid: int, project_root: str | None, *, session: str = "") -> dict:
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

    ``session`` is DATA, not a lookup: this function stays PURE (the module contract — every
    ``build_*`` returns a plan you can inspect and dry-run). Resolving it here by shelling
    out to ``tmux`` would put an invisible machine-touching call inside a builder, which is
    exactly what the suite's sandbox guard exists to surface. The caller with I/O rights
    (the daemon) passes ``live_tmux_session()``.
    """
    cwd = project_root or os.path.expanduser("~")
    # shlex-quoted so a crafted cwd cannot break out of the single command string.
    inner = f"kill {int(pid)} 2>/dev/null; cd {shlex.quote(cwd)} && {_RELAUNCH_CMD}"
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
