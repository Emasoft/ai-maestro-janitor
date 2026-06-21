"""Nuclear recovery rungs (TRDD-56d24c02 / TRDD-324223a6 A5) — the rungs that
KILL and RESPAWN a claude process when the gentle command-typing rungs
(rearm/reload/update) cannot revive a session.

THREE rungs, escalating:

- **relaunch** — the pid is GONE (`dead`) but the pane lives → type
  ``claude --continue`` into the pane to resume the session IN PLACE. No kill;
  ``--continue`` preserves the transcript, so this is not data loss.
- **force_restart** — the pid is alive but HARD-WEDGED (`frozen`, gentle ladder
  exhausted) → ``os.kill`` the stuck pid, then ``claude --continue`` in the pane.
- **resurrect** — the pane itself is unreachable → spawn a DETACHED background
  ``claude`` (``tmux new-session -d``) that kills + relaunches the stuck one. The
  "launch a background claude to kill+restart a stuck one" the user demanded.

THE SAFETY MODEL (this module kills processes, so it is gated three ways):

1. **DEFAULT-OFF.** ``nuclear_enabled()`` is false unless the user opts in with
   ``CLAUDE_PLUGIN_OPTION_FLEET_NUCLEAR_ENABLED=1``. Until then ``fire_nuclear``
   builds + returns a ``DRY_RUN`` marker and executes NOTHING.
2. **NEVER the user's working session.** ``is_killable`` refuses unless the pid is a
   real ``claude`` process, the instance is NOT ``active`` (transcript advancing),
   the diagnosis is the genuinely-wedged ``frozen``, and the pid is neither this
   process nor the daemon. ``diagnose_instance`` upstream already guarantees an
   active session is ``healthy`` (never ``frozen``/``dead``), so this is the second
   independent gate, not the only one.
3. **BOUNDED.** The caller wraps every nuclear attempt in the crash-loop guard
   (``session_liveness.crash_loop_tripped``) so a persistent fault pages a human
   instead of entering a kill/respawn storm.

PURE where it can be: every ``build_*`` returns a plan dict you can inspect/dry-run;
``fire_nuclear`` takes injectable ``killer``/``spawner`` so tests never touch a real
process. This module is INTENTIONALLY not yet wired into the daemon's live loop
(TRDD-56d24c02 increment 2 does that, behind the opt-in) — it ships tested + inert.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fleet_inject  # noqa: E402  (bare sibling import; lib/ is on sys.path)
import terminal_trigger  # noqa: E402

# The shell command that resumes a claude session in a pane that dropped to a shell.
_RELAUNCH_CMD = "claude --continue"


def nuclear_enabled() -> bool:
    """Master opt-in for the process-killing rungs. DEFAULT-OFF — these rungs kill and
    respawn processes, so they stay dry-run-only until the user deliberately enables
    them with CLAUDE_PLUGIN_OPTION_FLEET_NUCLEAR_ENABLED=1 (the documented true
    spellings). Unlike the gentle rungs (idempotent, on by default), the irreversible
    rungs are opt-in."""
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_FLEET_NUCLEAR_ENABLED", "0").strip().lower()
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
    """Build a keystroke plan that types ``command`` into a resolved terminal, reusing
    the SAME gated channel logic as fleet_inject (tmux pane validated, iTerm UUID
    validated) so a tampered identity can never reach the argv/osascript. None when no
    safe channel resolves."""
    pane = terminal.get("tmux_pane", "").strip()
    if pane and terminal_trigger.valid_tmux_pane(pane):
        # build_tmux_steps always leads with ESC; harmless at a shell prompt (it just
        # clears the line), so the esc_first distinction only matters for iTerm below.
        steps = terminal_trigger.build_tmux_steps(pane, command)
        return {"channel": "tmux", "command": command, "delay_s": 2.0, "steps": steps}
    sid = terminal.get("iterm_session_id", "").strip().split(":")[-1].strip()
    if sid and fleet_inject.valid_session_id(sid):
        return {
            "channel": "iterm", "command": command, "delay_s": 2.0,
            "osascript": fleet_inject.iterm_osascript(sid, command, esc_first=esc_first),
        }
    return None


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
    DESCRIBES the kill (``kill_pid``) + the relaunch; ``fire_nuclear`` performs the
    kill ONLY after ``is_killable`` passes. None when no pane resolves (then the caller
    escalates to resurrect)."""
    relaunch = build_relaunch(terminal)
    if relaunch is None:
        return None
    return {"rung": "force_restart", "kill_pid": pid, "relaunch": relaunch}


def build_resurrect(pid: int, project_root: str | None) -> dict:
    """rung 7 — the pane is unreachable: spawn a DETACHED background ``claude`` (a new
    tmux session) that, on launch, kills the stuck pid and resumes. The plan carries
    the kill target + the detached-spawn argv; ``fire_nuclear`` runs it only when
    enabled AND ``is_killable`` passes. Always builds a plan (no pane needed) — it is
    the last resort precisely for the no-channel case."""
    cwd = project_root or os.path.expanduser("~")
    # A detached tmux session that kills the stuck pid then starts a fresh claude that
    # resumes the transcript. shlex-quoted so a crafted cwd cannot break out of the
    # single command string.
    inner = f"kill {int(pid)} 2>/dev/null; cd {shlex.quote(cwd)} && {_RELAUNCH_CMD}"
    argv = ["tmux", "new-session", "-d", "-s", f"janitor-resurrect-{int(pid)}", "sh", "-c", inner]
    return {"rung": "resurrect", "kill_pid": pid, "cwd": cwd, "spawn": argv}


def fire_nuclear(
    plan: dict | None,
    *,
    enabled: bool,
    killable: bool,
    killer=os.kill,
    spawner=None,
) -> str:
    """Execute a nuclear plan — but ONLY when ``enabled`` (the opt-in) AND, for any
    rung that kills, ``killable`` (the ``is_killable`` verdict the caller computed).
    Returns a short status string for the daemon log; never raises.

    - not ``enabled`` → ``DRY_RUN:<rung>`` (build everything, execute nothing).
    - ``relaunch`` → fire the keystroke plan (no kill; ``killable`` not required).
    - ``force_restart``/``resurrect`` → refuse with ``REFUSED:not-killable`` unless
      ``killable``; otherwise kill the pid (injectable ``killer``) then relaunch/spawn
      (injectable ``spawner``).

    ``killer``/``spawner`` are injected so tests prove the control flow without
    touching a real process."""
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
        try:
            killer(int(plan["kill_pid"]), 15)  # SIGTERM the stuck pid
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
        subprocess.Popen(  # noqa: S603 - fixed argv (tmux new-session), no shell
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
