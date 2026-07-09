"""Daemon-side fleet scanner (TRDD-324223a6) — find EVERY running claude instance
and diagnose its janitor's health from OUTSIDE it.

The 2026-06-20→21 freeze was not one session — a live scan found 23 running
claude instances on this host, 15 with a broken janitor (frozen, or a dead
heartbeat stale for up to 23h). The mandate: the janitor must guard the whole
fleet — re-arm a dead cron, reload a version-mismatch, run the freeze ladder —
from outside, regardless of terminal env, leaving only deliberately-unarmed
instances alone.

This module is the daemon's eyes. The PARSERS are pure (tested against captured
tool output, no mocks); ``gather_fleet`` runs the subprocesses (ps / lsof / tmux
/ osascript) and composes them with the pure decision functions in
``session_liveness``. Crucially it resolves each instance's terminal by its live
TTY — NOT by a recorded id — so it can reach even an OLD/zombie instance whose
janitor predates ``terminal-identity.json``. The daemon (which has no session
env of its own) could never do this from inside a session.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass

import session_liveness
import state
import terminal_trigger

# A session whose transcript has NOT advanced in this window is treated as stuck
# (dead heartbeat / frozen). A live heartbeat fires a turn every ~5 min and every
# turn is appended to the transcript, so 3× the cadence tolerates two missed fires
# (a slow tick / a brief throttle) before we ever flag it. This — NOT dispatch.log
# (silent on quiet fires) and NOT a new heartbeat stamp (legacy instances lack it)
# — is the reliable liveness signal that also works on old instances.
STALE_S = 15 * 60

# A transcript advanced this recently means the session is BUSY working (continuous
# tool-call appends) — a display nuance over the merely-alive idle-but-cron-firing
# case. Both are "fresh" (< STALE_S) and never flagged; this just distinguishes
# "ending a turn now" from "idle but its heartbeat is keeping it alive".
ACTIVE_FRESH_S = 5 * 60

# Read each iTerm session's controlling TTY + stable session id. Read-only — it
# never brings a window to front and never relaunches iTerm (the caller only runs
# it when iTerm is already in the process table). The id is the UUID that the
# daemon's inject filter matches (`if (id of s) is "<uuid>"`).
#
# The delimiter is a literal "|", NOT the AppleScript `tab` constant: empirically
# (od -c) `osascript -e '… & tab & …'` emits the THREE LETTERS "tab", not a tab
# byte, so a "\t"-split silently matched nothing and every instance read
# UNREACHABLE. A literal "|" round-trips correctly (neither a TTY path nor a UUID
# contains it), resolving 20/21 live instances on the real host.
_ITERM_TTY_OSASCRIPT = (
    'tell application "iTerm2"\n'
    "  set out to \"\"\n"
    "  repeat with w in windows\n"
    "    repeat with t in tabs of w\n"
    "      repeat with s in sessions of t\n"
    '        set out to out & (tty of s) & "|" & (id of s) & linefeed\n'
    "      end repeat\n"
    "    end repeat\n"
    "  end repeat\n"
    "  return out\n"
    "end tell"
)


@dataclass(frozen=True)
class Instance:
    """One running claude instance + its diagnosed janitor health. ``terminal`` is the
    injection identity, resolved from the live TTY and then extended by the taggers:
    ``{tmux_pane?, iterm_session_id?, aimaestro_session?+aimaestro_cli?,
    linux_gui_channel?}``. ``fleet_inject.build_command_plan`` consumes it in that
    fallback order (tmux -> iterm -> aimaestro -> linux-gui). EMPTY means the daemon
    cannot reach this pane by keystroke at all — an armed instance with an empty
    identity is genuinely unreachable, not merely on an unusual terminal."""

    pid: int
    command: str
    tty: str
    project_root: str | None
    terminal: dict[str, str]
    diagnosis: str
    recovery: str | None
    dispatch_age_s: int | None
    active: bool
    transcript_age_s: int | None


def parse_ps_claude(ps_text: str) -> list[tuple[int, str, str]]:
    """``(pid, normalized_tty, command)`` for every claude process in
    ``ps -eo pid=,tty=,command=`` output. A claude process = argv[0] basename
    ``claude`` OR a ``/share/claude/versions/`` launcher path in the cmdline
    (the two shapes the real install presents). Malformed rows are skipped."""
    out: list[tuple[int, str, str]] = []
    for ln in ps_text.splitlines():
        if not ln.strip():
            continue
        parts = ln.split(None, 2)  # pid, tty, command (command keeps its spaces)
        if len(parts) < 3:
            continue
        pid_s, tty_s, cmd = parts
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        toks = cmd.split()
        first = toks[0] if toks else ""
        if os.path.basename(first) == "claude" or "/share/claude/versions/" in cmd:
            out.append((pid, session_liveness.normalize_tty(tty_s), cmd))
    return out


def parse_iterm_sessions(text: str) -> dict[str, str]:
    """``{normalized_tty: iterm_session_id}`` from the osascript dump of
    ``tty|session_id`` lines (see _ITERM_TTY_OSASCRIPT for why the delimiter is a
    literal ``|``, not a tab). Rows without both fields are skipped."""
    out: dict[str, str] = {}
    for ln in text.splitlines():
        if "|" not in ln:
            continue
        tty_s, sid = ln.split("|", 1)
        tty = session_liveness.normalize_tty(tty_s.strip())
        sid = sid.strip()
        if tty and sid:
            out[tty] = sid
    return out


def parse_tmux_panes(text: str) -> dict[str, str]:
    """``{normalized_tty: pane_id}`` from
    ``tmux list-panes -a -F '#{pane_tty} #{pane_id}'``."""
    out: dict[str, str] = {}
    for ln in text.splitlines():
        toks = ln.split()
        if len(toks) < 2:
            continue
        tty = session_liveness.normalize_tty(toks[0])
        if tty and toks[1]:
            out[tty] = toks[1]
    return out


def find_janitor_root(cwd: str | None) -> str | None:
    """Walk up from ``cwd`` to the nearest dir containing ``.janitor/`` (the
    project where the janitor is/was active). ``None`` if ``cwd`` is unset or no
    ancestor qualifies — a claude running where the janitor never ran is not our
    concern (its SessionStart hook will set it up)."""
    if not cwd:
        return None
    d = os.path.realpath(cwd)
    for _ in range(8):  # bounded walk — never loop on a pathological tree
        if os.path.isdir(os.path.join(d, ".janitor")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _age(path: str, now: int) -> int | None:
    """Seconds since ``path`` was last modified, or ``None`` if it does not exist."""
    try:
        return now - int(os.path.getmtime(path))
    except OSError:
        return None


def transcript_age(root: str, now: int) -> int | None:
    """Seconds since this project's NEWEST session transcript was written, or
    ``None`` if no transcript exists. A fresh transcript = the agent is actively
    working — the signal that gates every disruptive recovery. The transcript
    lives outside ``.janitor`` (``~/.claude/projects/<dashed-cwd>/*.jsonl``), so
    this maps the project root to its harness slug the same way the memory scopes
    do (the absolute path with every separator replaced by a dash)."""
    # SSOT slug (memory_scopes.project_slug): the harness dashes EVERY non-alphanumeric
    # char, not just "/" — a separators-only replace returned None for any dotted or
    # underscored project path, so the fleet guardian never saw those sessions' activity.
    import memory_scopes

    slug = memory_scopes.project_slug(os.path.realpath(root))
    tdir = os.path.join(os.path.expanduser("~"), ".claude", "projects", slug)
    youngest: int | None = None
    try:
        for name in os.listdir(tdir):
            if name.endswith(".jsonl"):
                age = _age(os.path.join(tdir, name), now)
                if age is not None and (youngest is None or age < youngest):
                    youngest = age
    except OSError:
        return None
    return youngest


def sweep_stale_rate_limit(root: str, *, now: int, max_age_s: int) -> bool:
    """Delete `<root>/.janitor/state/rate-limited.flag` if it is stale. Returns True if swept.

    The daemon is the ONLY actor that can do this (janitor#77 item C). The flag is cleared
    by `dispatch.py`, which runs only from a live heartbeat cron — so the project that most
    needs its flag cleared (the one whose cron died) is precisely the one that can never
    clear it. The daemon is alive when the cron is not, which is what breaks the circle.

    A `disarmed.flag` project is sacrosanct and is skipped: the user opted out, its diagnosis
    is `unarmed` regardless of the rate-limit flag, and we do not touch its files.

    Never raises. A missing flag, an unreadable mtime, or a losing unlink race are all
    "nothing to do" — the sweep is idempotent and bounded (one stat, at most one unlink).
    """
    sdir = os.path.join(root, ".janitor", "state")
    if os.path.isfile(os.path.join(sdir, state.DISARMED_FLAG)):
        return False
    flag = os.path.join(sdir, state.RATE_LIMITED_FLAG)
    try:
        mtime: int | None = int(os.stat(flag).st_mtime)
    except OSError:
        return False  # absent or unreadable — never delete what we cannot assess
    if not session_liveness.rate_limit_flag_is_stale(mtime, now, max_age_s):
        return False
    try:
        os.unlink(flag)
    except OSError:
        return False  # lost a race with dispatch.py clearing it — the same outcome
    return True


def diagnose_root(
    root: str,
    *,
    now: int,
    transcript_age: int | None,
    stale_s: int = STALE_S,
) -> tuple[str, str | None, int | None]:
    """Read a project's ``.janitor`` state + the session's ``transcript_age`` and
    diagnose its janitor health. Returns ``(diagnosis, recovery, dispatch_age_s)``
    — ``dispatch_age_s`` is INFORMATIONAL ONLY (dispatch.log logs notable events,
    not liveness); the diagnosis runs entirely on the transcript.

    A transcript that advanced within ``stale_s`` means the session is working OR
    its heartbeat is firing — either way alive, never flagged. A stale transcript
    means neither: stuck. An unknown transcript age (cannot locate the file) is
    treated as NOT stale — we never flag what we cannot actually assess. The
    opt-out is POSITIVE: only a ``disarmed.flag`` (written by ``/janitor-disarm``)
    makes an instance sacrosanct; a merely-absent ``heartbeat-armed-at.ts`` is a
    lapsed arm to restore, which is exactly what the user wants guarded.
    """
    sdir = os.path.join(root, ".janitor", "state")
    ldir = os.path.join(root, ".janitor", "logs")
    deliberately_unarmed = os.path.isfile(os.path.join(sdir, state.DISARMED_FLAG))
    rate_limited = os.path.isfile(os.path.join(sdir, state.RATE_LIMITED_FLAG))
    transcript_stale = transcript_age is not None and transcript_age >= stale_s
    diagnosis = session_liveness.diagnose_instance(
        deliberately_unarmed=deliberately_unarmed,
        pane_alive=True,  # the caller only diagnoses processes found alive in ps
        transcript_stale=transcript_stale,
        rate_limited=rate_limited,
        version_stale=False,  # v1: cross-process version compare deferred (Group C)
    )
    dispatch_age = _age(os.path.join(ldir, "dispatch.log"), now)
    return diagnosis, session_liveness.recovery_for_diagnosis(diagnosis), dispatch_age


def _run(cmd: list[str], *, timeout: int = 10) -> str:
    """Run a read-only probe; never raise. Empty string on any failure/timeout."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        ).stdout
    except Exception:  # noqa: BLE001 -- a probe failure must never break the scan
        return ""


def _cwd_of(pid: int) -> str | None:
    """The working directory of ``pid`` via ``lsof`` (macOS-friendly), or None."""
    for line in _run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], timeout=8
    ).splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def _aimaestro_agents(env: Mapping[str, str] | None = None) -> tuple[str | None, list]:
    """Resolve the ai-maestro CLI and fetch its agent list ONCE per ``gather_fleet()``
    call — never per-instance, an N-instance scan must not shell out N times.
    Best-effort: returns ``(None, [])`` on ANY failure (CLI absent, server down,
    malformed JSON) so a host without ai-maestro installed/running never breaks the
    fleet scan. Reuses ``terminal_trigger``'s resolver/runner — the SAME ones
    self-trigger's ``_try_ai_maestro_send`` uses — instead of re-implementing CLI
    discovery. (TRDD-ME8V2YJF follow-up)
    """
    e = env if env is not None else os.environ
    cli = terminal_trigger._resolve_aimaestro_cli(e)
    if not cli:
        return None, []
    proc = terminal_trigger._run_aimaestro_cli(cli, ["list", "--json"], env=e, timeout=5.0)
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return cli, []
    try:
        agents = json.loads(proc.stdout)
    except ValueError:
        return cli, []
    if isinstance(agents, dict) and isinstance(agents.get("agents"), list):
        agents = agents["agents"]
    return cli, (agents if isinstance(agents, list) else [])


def tag_aimaestro_identity(
    terminal: dict[str, str], *, agents: list, cli: str | None, root: str | None
) -> None:
    """Extend a resolved ``terminal`` identity dict IN PLACE with the ai-maestro CLI
    channel when this instance's ``root`` matches an ai-maestro agent's
    ``workingDirectory``. Pure — ``agents``/``cli`` are the values ``_aimaestro_agents``
    already fetched ONCE for the whole scan; this just does the per-instance match via
    ``terminal_trigger.match_agent_tmux`` (the SAME pure matcher self-trigger uses,
    keyed on this instance's project root instead of ``os.getcwd()``). Stores
    ``aimaestro_session`` — an ai-maestro TMUX SESSION NAME (e.g. ``agent-foo``), NOT
    a ``tmux_pane`` id — alongside the resolved CLI path, so ``fleet_restart._command_plan``
    has both pieces it needs to build the CLI argv. No-op (leaves ``terminal``
    untouched) when ``cli``/``agents``/``root`` are falsy or nothing matches, so a host
    without ai-maestro running never grows a dangling identity key. (TRDD-ME8V2YJF follow-up)
    """
    if not cli or not agents or not root:
        return
    session = terminal_trigger.match_agent_tmux(agents, [root])
    if session:
        terminal["aimaestro_session"] = session
        terminal["aimaestro_cli"] = cli


def tag_linux_gui_identity(terminal: dict[str, str], *, channel: str | None) -> None:
    """Extend a resolved ``terminal`` identity dict IN PLACE with the Linux
    GUI-terminal channel (``wtype``/``xdotool``) — but ONLY when neither tmux nor
    iTerm already resolved a channel for this instance. ``wtype``/``xdotool`` have no
    per-window target (they type into whichever window has focus — see
    ``terminal_trigger.build_wtype_steps``), so this is deliberately the LAST-RESORT
    tag, mirroring ``fleet_restart._command_plan``'s fallback order
    (tmux -> iterm -> aimaestro -> linux-gui): tagging it unconditionally would
    misrepresent an already-reachable instance as needing the imprecise
    focused-window channel. No-op when ``channel`` is falsy or a channel already
    resolved. (TRDD-ME8V2YJF follow-up)
    """
    if channel and "tmux_pane" not in terminal and "iterm_session_id" not in terminal:
        terminal["linux_gui_channel"] = channel


def gather_fleet(*, now: int, sweep_stale_rate_limit_s: int | None = None) -> list[Instance]:
    """Scan the whole host: every running claude instance whose cwd resolves to a
    ``.janitor`` project, with its terminal (by TTY) and diagnosed janitor health.

    Pure-ish I/O: one ``ps``, one ``tmux``, at most one ``osascript`` (only if
    iTerm is actually running — so we NEVER relaunch a closed iTerm), at most one
    ai-maestro CLI ``list --json`` (only if the CLI resolves), and one ``lsof`` per
    claude pid. Instances outside a janitor project are skipped. The ai-maestro
    agent list and the Linux GUI channel are each resolved ONCE for the whole scan
    (never per-instance) and then tagged onto every matching instance's terminal
    identity — the same fan-out shape as ``iterm_by_tty``/``tmux_by_tty`` below.
    (TRDD-ME8V2YJF follow-up)

    ``sweep_stale_rate_limit_s`` is the ONLY way this function writes to disk, and it
    defaults to None (read-only). Pass a window and each root's stale ``rate-limited.flag``
    is deleted BEFORE it is diagnosed, so the same beat sees the corrected `cron_dead`
    instead of a false `frozen` (janitor#77 item C). The daemon passes it; ``fleet_status``
    must not — a status table that mutates the thing it reports on is a status table nobody
    can trust.
    """
    ps_text = _run(["ps", "-eo", "pid=,tty=,command="])
    claude = parse_ps_claude(ps_text)
    tmux_by_tty = parse_tmux_panes(
        _run(["tmux", "list-panes", "-a", "-F", "#{pane_tty} #{pane_id}"])
    )
    iterm_by_tty: dict[str, str] = {}
    if "iTerm" in ps_text:  # only drive osascript when iTerm is already up
        iterm_by_tty = parse_iterm_sessions(
            _run(["osascript", "-e", _ITERM_TTY_OSASCRIPT], timeout=15)
        )
    aimaestro_cli, aimaestro_agents = _aimaestro_agents()
    linux_gui_channel = (
        terminal_trigger._resolve_linux_gui_channel(os.environ)
        if sys.platform.startswith("linux")
        else None
    )

    fleet: list[Instance] = []
    for pid, tty, cmd in claude:
        root = find_janitor_root(_cwd_of(pid))
        if not root:
            continue
        tr_age = transcript_age(root, now)
        active = tr_age is not None and tr_age < ACTIVE_FRESH_S
        if sweep_stale_rate_limit_s is not None and sweep_stale_rate_limit(
            root, now=now, max_age_s=sweep_stale_rate_limit_s
        ):
            # BEFORE diagnose_root, so this beat already sees the honest diagnosis.
            state.log_line(
                "daemon",
                f"session-liveness: swept stale rate-limited.flag in {root} "
                f"(older than {sweep_stale_rate_limit_s}s) — restores cron_dead over frozen",
            )
        diagnosis, recovery, dispatch_age = diagnose_root(
            root, now=now, transcript_age=tr_age
        )
        terminal = session_liveness.resolve_terminal_for_tty(
            tty, iterm_by_tty=iterm_by_tty, tmux_by_tty=tmux_by_tty
        )
        tag_aimaestro_identity(terminal, agents=aimaestro_agents, cli=aimaestro_cli, root=root)
        tag_linux_gui_identity(terminal, channel=linux_gui_channel)
        fleet.append(
            Instance(
                pid=pid,
                command=cmd,
                tty=tty,
                project_root=root,
                terminal=terminal,
                diagnosis=diagnosis,
                recovery=recovery,
                dispatch_age_s=dispatch_age,
                active=active,
                transcript_age_s=tr_age,
            )
        )
    return fleet


def _main() -> int:
    """Live diagnostic: print the fleet, one line per instance. Read-only."""
    import time

    fleet = gather_fleet(now=int(time.time()))
    broken = [i for i in fleet if i.recovery is not None]
    print(f"fleet: {len(fleet)} janitor-project claude instance(s), {len(broken)} need recovery\n")
    for inst in fleet:
        chan = (
            "tmux:" + inst.terminal["tmux_pane"]
            if "tmux_pane" in inst.terminal
            else "iterm:" + inst.terminal["iterm_session_id"]
            if "iterm_session_id" in inst.terminal
            else "UNREACHABLE"
        )
        age = f"{inst.dispatch_age_s // 60}m" if inst.dispatch_age_s is not None else "none"
        rec = inst.recovery or "—"
        print(f"  pid {inst.pid:>6}  {inst.diagnosis:<16} → {rec:<9} [{chan}]  dispatch {age}")
        print(f"          {inst.project_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
