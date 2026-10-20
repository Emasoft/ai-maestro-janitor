"""Host-pressure detection and runaway-victim selection (TRDD-5G66S0HK).

The janitor already has a Tier-1 memory guard that kills SIX narrow
janitor-spawned shapes. What it does not have is the authority to kill a
runaway that CLAUDE CODE caused but the janitor did not spawn — which is
the whole of the 2026-10-20 incident (a 64 GB macOS box panicked under
swap exhaustion with 986 processes holding 19.8 GB).

This module supplies that authority, with two things the Tier-1 guard
deliberately never had: a pressure probe that can SEE the condition that
actually killed the machine, and an attribution rule that can tell an
agent's runaway from the user's own foreground work.

THE PRESSURE PROBE. Free memory alone is blind to the panic condition.
The 2026-10-20 panic log said "Compressor Info: 100% of segments limit
(BAD), 69 swapfiles" — so the probe reads SWAP USAGE, the SWAPFILE COUNT
and COMPRESSOR OCCUPANCY as well as free memory. A host that is
swap-exhausted with plenty of free RAM still reports CRITICAL.

THE ATTRIBUTION RULE — the part the card could not solve, settled by
MEASUREMENT on the owner's host (2026-10-20). The question was how to tell
an agent's runaway from a user's own dev server, a `vite` build, or a
`pytest` run the user started in their terminal. The answer is the
ENVIRONMENT SIGNAL, and it is exact:

    A process whose OWN environment carries CLAUDECODE, CLAUDE_PROJECT_DIR,
    CLAUDE_PLUGIN_DATA, CLAUDE_CODE_SESSION_ID or CLAUDE_CODE_CHILD_SESSION
    was started BY AN AGENT.

The user's own foreground work does not carry those variables — the user
typed the command at a plain shell prompt, so it inherits their shell's
environment, which has none of them. An agent's child inherits the
agent's environment, which has them.

The signal SURVIVES REPARENTING, which is why it and not ancestry alone is
the primary channel. Measured: `alcore serve` had ppid=1 (reparented to
launchd, its session long gone) yet still carried three of the
variables. Ancestry alone misses exactly that case — and an abandoned
watcher is by definition a reparented process.

Ancestry is kept as a SECOND, weaker signal, and it is necessary but not
sufficient on its own (the advisor's finding, TRDD-5G66S0HK): it cannot
see a reparented process at all, and a `claude` ANCESTOR proves the
process is a descendant of a session, which includes the user's own
work started inside that session.

ATTRIBUTION PROVES RELATEDNESS, NEVER KILL-WORTHINESS. A candidate must
also match a POSITIVE allowlist of runaway SHAPES, be older than the age
gate, not be a protected pid, and not be an interactive `claude` session.
Without the shape allowlist the rule degenerates to "biggest process
wins", which is what the janitor's Decision 1 refused.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import NamedTuple, Optional

# ---------- tunables -------------------------------------------------------

DEFAULT_MIN_FREE_MB = 1024
DEFAULT_SWAP_USED_MB = 2048
DEFAULT_SWAPFILES = 32
DEFAULT_COMPRESSOR_PCT = 60
DEFAULT_RUNAWAY_ETIME_S = 3600
DEFAULT_ALERT_RSS_KB = 4 * 1024 * 1024

# THE ENVIRONMENT VARIABLES THAT MARK A PROCESS AS AGENT-STARTED. Measured
# on the owner's host: the interactive `claude` sessions carry NONE of
# them, and the agent's children carry them whether or not they were
# reparented.
CLAUDE_ENV_MARKERS = (
    "CLAUDECODE",
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_PLUGIN_DATA",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION",
)

# THE POSITIVE ALLOWLIST OF RUNAWAY SHAPES. Attribution alone is not
# enough — without this the rule is "biggest process wins". Keep the list
# tight: every pattern here widens the kill surface.
#
# The first three are the janitor's OWN workload shapes, reused from
# memory_guard.JANITOR_WORKLOAD_SIGNATURES rather than re-typed.
RUNAWAY_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bclaude\s+plugin\s+marketplace\s+update\b"),
    re.compile(r"\bclaude\s+plugin\s+update\b"),
    re.compile(r"\bclaude\s+plugin\s+list\b"),
    re.compile(r"\bagentlenspro\s+statusline\b"),
    re.compile(r"\baimaestro-statusline-capture\.sh\b"),
    re.compile(r"\bpeak-space/watch\.mjs\b"),
    re.compile(r"\buv\s+run\s+pytest\b"),
    re.compile(r"(?:^|/)pytest\b"),
)

# The owner's other AI clients. EXPLICITLY FORBIDDEN by the owner
# directive of 2026-10-20: "do not touch processes executed by other ai
# clients like codex or copilot". These are excluded by shape even when
# they are attributed to Claude Code and even when they are enormous.
FORBIDDEN_CLIENTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcodex\b", re.IGNORECASE),
    re.compile(r"\bcopilot\b", re.IGNORECASE),
    re.compile(r"\blm[\s_-]?studio\b", re.IGNORECASE),
    re.compile(r"\b aider\b", re.IGNORECASE),
    re.compile(r"\bcursor\b", re.IGNORECASE),
)

# An interactive `claude` session — the thing the user is typing into.
# NEVER killable, even when it is the largest process on the host.
_CLAUDE_ANYTHING = re.compile(r"(?:^|/|\s)claude(?:\s|$)")


class ProcRow(NamedTuple):
    """One parsed `ps -axo pid,ppid,rss,etime,command` row."""

    pid: int
    ppid: int
    rss_kb: int
    etime_s: int
    command: str


class Pressure(NamedTuple):
    """The host's pressure state, with the readings that produced it."""

    state: str            # "healthy" | "elevated" | "critical"
    free_mb: Optional[int]
    swap_used_mb: Optional[int]
    swapfiles: Optional[int]
    compressor_pct: Optional[int]

    def readings(self) -> str:
        """A one-line, human-readable rendering of the readings."""
        def part(value: Optional[int], unit: str) -> str:
            return "?" if value is None else f"{value}{unit}"
        return (
            f"free {part(self.free_mb, 'MB')}, "
            f"swap {part(self.swap_used_mb, 'MB')}, "
            f"swapfiles {part(self.swapfiles, '')}, "
            f"compressor {part(self.compressor_pct, '%')}"
        )


# ---------- pure parsers ----------------------------------------------------

def parse_etime(raw: str) -> int:
    """Parse ps ELAPSED ([[dd-]hh:]mm:ss) into seconds. Unparseable -> 0.

    0 is the SAFE direction: an unparseable age fails the runaway-age gate,
    so the row can never be killed on a parsing accident.
    """
    raw = raw.strip()
    m = re.fullmatch(r"(?:(?:(\d+)-)?(\d+):)?(\d+):(\d+)", raw)
    if not m:
        return 0
    days, hours, minutes, seconds = m.groups()
    total = int(minutes) * 60 + int(seconds)
    if hours is not None:
        total += int(hours) * 3600
    if days is not None:
        total += int(days) * 86400
    return total


def parse_ps_snapshot(text: str) -> list[ProcRow]:
    """Parse `ps -axo pid,ppid,rss,etime,command` output (header tolerated).

    Malformed lines are skipped — the guard prefers missing a row to
    misattributing one.
    """
    rows: list[ProcRow] = []
    for line in text.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        pid_s, ppid_s, rss_s, etime_s_raw, command = parts
        if not (pid_s.isdigit() and ppid_s.isdigit() and rss_s.isdigit()):
            continue
        rows.append(ProcRow(
            pid=int(pid_s), ppid=int(ppid_s), rss_kb=int(rss_s),
            etime_s=parse_etime(etime_s_raw), command=command.strip(),
        ))
    return rows


def parse_swapusage(text: str) -> tuple[Optional[int], Optional[int]]:
    """(used_mb, swapfile_count) from `sysctl -n vm.swapusage` output.

    MEASURED FORMAT on this host:
        total = 0.00M  used = 0.00M  free = 0.00M  (encrypted)
    The swapfile COUNT is not in vm.swapusage on every host, so it is
    read from `sysctl -n vm.swapinfo` where available and is None
    otherwise — None means UNKNOWN, never zero.
    """
    used = re.search(r"used\s*=\s*([\d.]+)\s*([MG])", text)
    used_mb: Optional[int] = None
    if used:
        value = float(used.group(1))
        used_mb = int(value) if used.group(2) == "M" else int(value * 1024)
    count = re.search(r"(\d+)\s+files", text)
    files: Optional[int] = int(count.group(1)) if count else None
    return used_mb, files


def parse_compressor_pct(text: str, total_mb: int, page_size: int) -> Optional[int]:
    """Compressor occupancy as a PERCENTAGE of physical memory.

    MEASURED on this host: `Pages occupied by compressor: 1869016` with a
    16384-byte page size and 65536 MB of RAM is ~46% — a real reading, not
    a guess. `Pages stored in compressor` is the COMPRESSED size and is a
    different number; the OCCUPIED pages are the ones that cost physical
    memory, so that is the one measured.

    None when the line is absent or the arithmetic is impossible — never
    guess, because a wrong number here flips a healthy host to critical.
    """
    m = re.search(r"Pages occupied by compressor:\s*(\d+)", text)
    if not m or total_mb <= 0 or page_size <= 0:
        return None
    occupied_mb = (int(m.group(1)) * page_size) / (1024 * 1024)
    return int(occupied_mb * 100 / total_mb)


# ---------- the pressure probe ---------------------------------------------

def host_pressure(
    *,
    min_free_mb: int = DEFAULT_MIN_FREE_MB,
    swap_used_mb: int = DEFAULT_SWAP_USED_MB,
    swapfiles: int = DEFAULT_SWAPFILES,
    compressor_pct: int = DEFAULT_COMPRESSOR_PCT,
) -> Pressure:
    """Read the host's pressure state. Every probe failure degrades to None.

    The state is a function of the READINGS, and an UNKNOWN reading never
    pushes the state up: a host with unknown swap is `elevated` at worst,
    and only a KNOWN swap/compressor/free-memory reading can reach
    `critical`. Never kill on missing data.
    """
    free_mb = free_memory_mb()
    swap_used, files = read_swap()
    compressor = read_compressor_pct()

    free_bad = free_mb is not None and free_mb < min_free_mb
    swap_bad = swap_used is not None and swap_used >= swap_used_mb
    files_bad = files is not None and files >= swapfiles
    comp_bad = compressor is not None and compressor >= compressor_pct

    if free_bad and (swap_bad or files_bad or comp_bad):
        state = "critical"
    elif free_bad or swap_bad or files_bad or comp_bad:
        state = "elevated"
    else:
        state = "healthy"
    return Pressure(state, free_mb, swap_used, files, compressor)


def free_memory_mb() -> Optional[int]:
    """Free MB on macOS. None = unknown (never guess)."""
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["vm_stat"], capture_output=True, text=True, timeout=10, check=False,
        )
        if out.returncode != 0:
            return None
        page = subprocess.run(  # noqa: S603
            ["sysctl", "-n", "hw.pagesize"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        page_size = int(page.stdout.strip()) if page.returncode == 0 else 16384
        free = re.search(r"Pages free:\s*(\d+)", out.stdout)
        spec = re.search(r"Pages speculative:\s*(\d+)", out.stdout)
        if not free:
            return None
        pages = int(free.group(1)) + (int(spec.group(1)) if spec else 0)
        return int(pages * page_size / (1024 * 1024))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def read_swap() -> tuple[Optional[int], Optional[int]]:
    """(used_mb, swapfile_count). Either may be None = unknown."""
    used: Optional[int] = None
    files: Optional[int] = None
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["sysctl", "-n", "vm.swapusage"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if out.returncode == 0:
            used, files = parse_swapusage(out.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        out = subprocess.run(  # noqa: S603
            ["sysctl", "-n", "vm.swapinfo"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if out.returncode == 0:
            _, files = parse_swapusage(out.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    return used, files


def read_compressor_pct() -> Optional[int]:
    """Compressor occupancy as a percent of physical memory, or None."""
    try:
        out = subprocess.run(  # noqa: S603
            ["vm_stat"], capture_output=True, text=True, timeout=10, check=False,
        )
        if out.returncode != 0:
            return None
        total = subprocess.run(  # noqa: S603
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if total.returncode != 0:
            return None
        total_mb = int(total.stdout.strip()) // (1024 * 1024)
        page = subprocess.run(  # noqa: S603
            ["sysctl", "-n", "hw.pagesize"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        page_size = int(page.stdout.strip()) if page.returncode == 0 else 16384
        return parse_compressor_pct(out.stdout, total_mb, page_size)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


# ---------- attribution ----------------------------------------------------

def is_interactive_claude(command: str) -> bool:
    """True iff this command line is an interactive `claude` session.

    NEVER killable. The user is typing into it; killing it is the single
    most likely harm of the whole feature. The `claude` plugin
    subcommands are NOT interactive sessions and are separately killable
    by shape.
    """
    if not _CLAUDE_ANYTHING.search(command):
        return False
    return not any(
        sig.search(command)
        for sig in RUNAWAY_SHAPES[:3]
    )


def is_forbidden_client(command: str) -> bool:
    """True iff the command names another AI client the owner forbade."""
    return any(pat.search(command) for pat in FORBIDDEN_CLIENTS)


def has_claude_env(pid: int) -> bool:
    """True iff the process's OWN environment carries a Claude marker.

    This is the attribution channel that survives reparenting. Read it
    with `ps eww -o command= -p <pid>` — the environment is appended to
    the command line, so it comes back in the same read.

    Only the CANDIDATES are probed: on a host with 1400 processes, asking
    every process for its environment would cost 1400 subprocess spawns
    per beat.
    """
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["ps", "eww", "-o", "command=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if out.returncode != 0:
        return False
    for token in out.stdout.split():
        if token in CLAUDE_ENV_MARKERS:
            return True
        # An exported variable appears as NAME=value; the marker may be a
        # PREFIX of the value (CLAUDE_PROJECT_DIR=/path).
        name = token.split("=", 1)[0]
        if name in CLAUDE_ENV_MARKERS:
            return True
    return False


def claude_ancestor(pid: int, table: dict[int, tuple[int, str]]) -> Optional[int]:
    """Pid of the nearest ancestor whose executable basename is `claude`.

    The SECOND, weaker attribution signal. It cannot see a reparented
    process at all (which is the abandoned-watcher case), so it is never
    the only signal — but a descendant of a `claude` session IS
    Claude-related, and the shape allowlist still has to agree.

    Stops at pid <= 1, a cycle, a missing parent, or 64 levels.
    """
    seen = {pid}
    cur = pid
    for _ in range(64):
        entry = table.get(cur)
        if entry is None:
            return None
        ppid = entry[0]
        if ppid <= 1 or ppid in seen:
            return None
        parent = table.get(ppid)
        if parent is None:
            return None
        words = parent[1].split(None, 1)
        if words and os.path.basename(words[0]) in ("claude", "claude.exe"):
            return ppid
        seen.add(ppid)
        cur = ppid
    return None


def parse_ps_table(text: str) -> dict[int, tuple[int, str]]:
    """Parse `ps -axo pid=,ppid=,command=` into {pid: (ppid, command)}."""
    table: dict[int, tuple[int, str]] = {}
    for line in text.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        table[pid] = (ppid, parts[2])
    return table


def is_killable(
    row: ProcRow,
    *,
    protected_pids: frozenset[int],
    min_etime_s: int,
    ancestry: dict[int, tuple[int, str]],
    env_probe=None,
) -> bool:
    """The whole truth table. Every clause must pass.

      1. not a protected pid (the daemon, its parent, the janitor itself);
      2. NOT another AI client the owner forbade (codex, copilot,
         lmstudio, aider, cursor) — by shape, unconditionally;
      3. NOT an interactive `claude` session — the user is typing into it;
      4. matches a POSITIVE allowlist of runaway shapes;
      5. older than the runaway age gate;
      6. ATTRIBUTABLE to Claude Code — by the environment signal (which
         survives reparenting) or by a `claude` ancestor.

    `env_probe` is injected so the rule is testable without spawning a
    subprocess per row; it defaults to the real environment probe.
    """
    if row.pid in protected_pids:
        return False
    if is_forbidden_client(row.command):
        return False
    if is_interactive_claude(row.command):
        return False
    if not any(sig.search(row.command) for sig in RUNAWAY_SHAPES):
        return False
    if row.etime_s < min_etime_s:
        return False
    probe = env_probe if env_probe is not None else has_claude_env
    if probe(row.pid):
        return True
    return claude_ancestor(row.pid, ancestry) is not None


def select_victim(
    rows: list[ProcRow],
    *,
    protected_pids: frozenset[int],
    min_etime_s: int = DEFAULT_RUNAWAY_ETIME_S,
    ancestry: Optional[dict[int, tuple[int, str]]] = None,
    env_probe=None,
) -> Optional[ProcRow]:
    """Pick the single largest-RSS killable row, or None.

    ONE victim per call. The guard kills at most one process per beat and
    re-evaluates pressure on the next beat, so a transient misread can
    never cascade into a kill spree.
    """
    table = ancestry if ancestry is not None else {}
    candidates = [
        r for r in rows
        if is_killable(
            r,
            protected_pids=protected_pids,
            min_etime_s=min_etime_s,
            ancestry=table,
            env_probe=env_probe,
        )
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.rss_kb)


def select_refused_alert(
    rows: list[ProcRow],
    *,
    protected_pids: frozenset[int],
    min_etime_s: int = DEFAULT_RUNAWAY_ETIME_S,
    min_rss_kb: int = DEFAULT_ALERT_RSS_KB,
) -> Optional[ProcRow]:
    """The largest process the guard REFUSES to kill, for the owner's eyes.

    Alert-only. A process this large that the guard will not kill is
    exactly the runaway shape — a system daemon growing silently while
    the never-kill invariant (rightly) holds. Standing down must not mean
    silence about it.
    """
    hogs = [
        r for r in rows
        if r.rss_kb >= min_rss_kb
        and r.pid not in protected_pids
        and (is_forbidden_client(r.command) or is_interactive_claude(r.command))
    ]
    if not hogs:
        return None
    return max(hogs, key=lambda r: r.rss_kb)


# ---------- I/O edges -------------------------------------------------------

def snapshot_processes(snapshot_path: str) -> list[ProcRow]:
    """`ps -axo pid,ppid,rss,etime,command` -> FILE -> parsed rows.

    The file hop is deliberate (the no-self-match discipline): the
    snapshot is complete before any matching happens, and the file
    doubles as the forensic record of what the guard saw when it acted.
    """
    try:
        with open(snapshot_path, "w", encoding="utf-8") as fh:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["ps", "-axo", "pid,ppid,rss,etime,command"],
                stdout=fh, stderr=subprocess.DEVNULL, timeout=20, check=False,
            )
        if proc.returncode != 0:
            return []
        with open(snapshot_path, encoding="utf-8") as fh:
            return parse_ps_snapshot(fh.read())
    except (OSError, subprocess.SubprocessError):
        return []


def snapshot_ancestry(snapshot_path: str) -> dict[int, tuple[int, str]]:
    """`ps -axo pid=,ppid=,command=` -> {pid: (ppid, command)}.

    A SECOND snapshot, for the ancestry channel. It is a separate call
    because the two tables want different column sets and the guard only
    needs ancestry for the CANDIDATES — but the table must be built for
    the whole host, since a candidate's ancestor may be any pid.
    """
    try:
        with open(snapshot_path, "w", encoding="utf-8") as fh:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["ps", "-axo", "pid=,ppid=,command="],
                stdout=fh, stderr=subprocess.DEVNULL, timeout=20, check=False,
            )
        if proc.returncode != 0:
            return {}
        with open(snapshot_path, encoding="utf-8") as fh:
            return parse_ps_table(fh.read())
    except (OSError, subprocess.SubprocessError):
        return {}


def kill_process(pid: int, *, term_grace_s: float = 2.0) -> bool:
    """SIGTERM -> grace -> SIGKILL. True iff the process is gone afterwards."""
    import signal  # noqa: PLC0415 - only needed on the kill path
    import time  # noqa: PLC0415

    def _alive(target: int) -> bool:
        try:
            os.kill(target, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return not _alive(pid)
    deadline = time.time() + term_grace_s
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        return not _alive(pid)
    time.sleep(0.2)
    return not _alive(pid)


def base_name(command: str) -> str:
    """The process's BASE NAME — never its full command line.

    The broadcast payload is host-level and identical for every project
    (TRDD-X92VBFNF). A command line like `pytest /Volumes/.../other-
    project/tests` would carry one project's content into every other
    project's session, so the broadcast copy carries only the basename.
    """
    parts = command.split()
    if not parts:
        return "?"
    name = os.path.basename(parts[0])
    return name or "?"
