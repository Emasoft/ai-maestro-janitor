"""Hard-restart recovery rung (TRDD-56d24c02 / TRDD-324223a6 A5) — the rung that
resumes a claude process in place when the gentle command-typing rungs
(rearm/reload/update) cannot revive a session.

ONE rung remains:

- **relaunch** — the pid is GONE (`dead`) but the pane lives → type
  ``claude --continue`` into the pane to resume the session IN PLACE. No kill;
  ``--continue`` preserves the transcript, so this is not data loss.

The two former kill rungs — **force_restart** (kill a hard-wedged `frozen` pid,
then relaunch) and **resurrect** (spawn a background claude to kill+relaunch an
unreachable one) — were RETIRED (TRDD-56d24c02, executed by TRDD-V07NFXS9):
TRDD-L32WC0H7 F1 capped the `frozen` diagnosis at `esc_nudge` unconditionally, so
nothing could ever route to them; a capability nothing can reach is dead code
with a safety story attached. ``hard_restart_enabled()`` and ``is_killable`` are
KEPT as-is per that decision (their own guard value, independent of the retired
rungs) even though this module no longer calls ``is_killable`` itself.

THE SAFETY MODEL for the remaining rung:

1. **DEFAULT-OFF.** ``hard_restart_enabled()`` is false unless the user opts in with
   ``CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED=1``. Until then ``fire_restart``
   builds + returns a ``DRY_RUN`` marker and executes NOTHING.
2. **NEVER the user's working session.** ``diagnose_instance`` upstream already
   guarantees an active (transcript-advancing) session is ``healthy``, never `dead`,
   so relaunch is never typed into a session the user is actively working in.
3. **BOUNDED.** The caller wraps every hard-restart attempt in the crash-loop guard
   (``session_liveness.crash_loop_tripped``) so a persistent fault pages a human
   instead of retrying forever.

PURE where it can be: ``build_relaunch`` returns a plan dict you can inspect/dry-run;
``fire_restart`` is the only thing here that touches a pane. The daemon wires exactly
one path — `dead` → relaunch (TRDD-56d24c02 increment 2) — behind the opt-in above.
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

    The replay is guarded so it can only ever relaunch something that IS claude (the
    `argv_is_claude` filter here), so a recycled pid cannot make this replay an unrelated
    command line.
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
    """Master opt-in for the hard-restart rung (relaunch). DEFAULT-OFF — it types a
    relaunch line into another session's pane, so it stays dry-run-only until the user
    deliberately enables it with CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED=1 (the
    documented true spellings). Unlike the gentle rungs (idempotent, on by default),
    typing into a pane the scanner called dead is opt-in. One of the three invariants
    TRDD-56d24c02 named; kept as the gate when the kill rungs were retired
    (TRDD-V07NFXS9)."""
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED", "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_killable(
    *, pid: int, command: str, active: bool, diagnosis: str, self_pid: int, daemon_pid: int | None
) -> bool:
    """The hard gate before any ``os.kill``. UNCALLED since TRDD-V07NFXS9 retired the two
    kill rungs (nothing under ``scripts/`` signals a pid any more); kept because it is one
    of the three invariants TRDD-56d24c02 named — its fate is TRDD-PP4YS4GQ, not a quiet
    deletion. True ONLY when killing this pid is safe:

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

    ``command`` is DATA: resolving it here would mean calling ``relaunch_command`` →
    ``live_cmdline`` → ``ps`` from inside a ``build_*``, breaking the module's purity
    contract (and tripping the suite's sandbox guard). The caller with I/O rights passes
    ``relaunch_command(pid, project_root)``. Empty falls back to the minimum that resumes
    a transcript.
    """
    cmd = _command_plan(
        terminal, (command or "").strip() or _FALLBACK_RELAUNCH_CMD, esc_first=False
    )
    if cmd is None:
        return None
    return {"rung": "relaunch", **cmd}


def recorded_terminal(project_root: str | None) -> dict[str, str]:
    """The pane identity the SESSION recorded at start, or {} when there is none.

    THE POINT (owner directive 2026-07-29 — "restart in the same original tab"). The
    surviving relaunch rung already restarts in place. But ``fleet_scan`` resolves the
    terminal from the LIVE TTY and deliberately never from a recorded id — correct,
    because that is what lets it reach a zombie instance whose janitor predates
    ``terminal-identity.json``. The gap is that live resolution can fail on a pane that is
    perfectly reachable: the known case is iTerm automation denied by TCC, which the
    scanner itself flags (``fleet_scan.iterm_automation_blocked`` — "iTerm is UP but the
    osascript enumerated ZERO sessions"). Then a healthy tab reads as unreachable and a
    relaunch attempt would find no channel where one existed.

    So: try live first (unchanged), and consult this only when live found nothing. Returns
    ONLY the two injection keys — ``term_program`` is recorded for diagnostics and is not an
    injection channel, so passing it through would put a non-channel key into a terminal
    dict that callers test for truthiness.

    Never raises: a missing/garbage file is simply "no recorded pane", and the caller
    falls back to logging the instance as unreachable exactly as before.
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


def _fire_relaunch(plan: dict, terminal: dict | None, project_dir: str | None) -> bool:
    """Type the relaunch line through the policy table (TRDD-N954KWUC P3), never a bare
    `fleet_inject.fire`. Returns True iff it landed.

    Always reads the pane first: the relaunch target is a pid that died on its own, so its
    frame carries no Claude chrome and classifies ``UNKNOWN``, which is exactly what the
    ``RELAUNCH`` row expects. That read buys a check this rung would not otherwise have — if
    the pane in fact shows a LIVE claude (the human restarted it, or the scan raced), the
    table refuses instead of typing ``claude --continue`` into that session's input field.
    """
    import pane_actuate  # noqa: PLC0415 -- local: fleet_inject/pane_state cycle at module load

    outcome = pane_actuate.act(
        terminal or {},
        pane_actuate.Event.RELAUNCH,
        read_pane=terminal is not None,
        command=str(plan.get("command") or ""),
        command_plan=plan,
        project_dir=project_dir,
    )
    return outcome.status is pane_actuate.OutcomeStatus.DONE


def fire_restart(
    plan: dict | None,
    *,
    enabled: bool,
    terminal: dict | None = None,
    project_dir: str | None = None,
) -> str:
    """Execute a hard-restart plan — but ONLY when ``enabled`` (the opt-in). Returns a short
    status string for the daemon log; never raises.

    - not ``enabled`` → ``DRY_RUN:<rung>`` (build everything, execute nothing).
    - ``relaunch`` → fire the keystroke plan. No kill involved — a `dead` pid has nothing
      left to signal, it types ``claude --continue`` into the surviving pane.
    - anything else → ``UNKNOWN_RUNG:<rung>`` (defensive; ``relaunch`` is the only rung a
      caller can currently build a plan for).
    """
    if not plan:
        return "NO_PLAN"
    rung = plan.get("rung", "?")
    if not enabled:
        return f"DRY_RUN:{rung}"
    if rung == "relaunch":
        return (
            "FIRED:relaunch"
            if _fire_relaunch(plan, terminal, project_dir)
            else "FIRE_FAILED:relaunch"
        )
    return f"UNKNOWN_RUNG:{rung}"
