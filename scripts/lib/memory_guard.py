"""Tier-1 OOM memory-guard primitives (TRDD-7100178d, Pillar 4 / Phase 5).

The daemon's `memory-guard` Task calls into this module each beat: when system
free memory drops below a threshold, snapshot the process table TO A FILE (never
pipe `ps` into a live grep — the scanning process would self-match), parse it,
and kill the single largest JANITOR-OWNED runaway. Decision 1 (user, 2026-05-31)
fixed the aggressiveness at **Tier 1**:

  * ONLY processes whose command line matches an explicit janitor-workload
    signature (a stuck `claude plugin marketplace update`, an orphaned
    `rotator.py` / `reauth.py` / `slot_capture_browser.py`, …) are killable.
  * A hard SAFELIST protects everything else BY CONSTRUCTION — an interactive
    `claude` session, the daemon itself, the calling process, and every system
    process simply never match a signature, and `claude`-anything that is not
    one of the plugin-CLI shapes is explicitly rejected.
  * Tier 2 ("kill the biggest non-interactive process at critical pressure")
    is deliberately NOT implemented — the flag name is reserved in the design
    but there is no code path; building it requires a fresh user sign-off.

Everything decision-shaped here is PURE (text in → value out) so the truth
table is testable without spawning processes; the only I/O lives in
`free_memory_mb` / `snapshot_processes` / `kill_process`.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from typing import NamedTuple, Optional

# Free-memory floor (MB). Below this the guard looks for a runaway to kill.
# Sized so a healthy laptop never trips it, while a true runaway (a leaking
# subprocess eating tens of GB) does. Env-tunable per host.
DEFAULT_MIN_FREE_MB = 1024

# A janitor workload only counts as RUNAWAY once it has lived this long.
# 2x the daemon's per-workload wall clock (1800 s): anything matching a
# signature AND older than this has outlived every legitimate execution
# path (the daemon kills its own children at 1800 s — so a survivor is an
# orphan from a dead daemon or a detached leak).
DEFAULT_RUNAWAY_ETIME_S = 3600

# Tier-1 killable signatures — the ONLY shapes the guard may ever kill.
# Each is a janitor-spawned workload; nothing else can match. Keep this
# list tight: adding a pattern widens the kill surface.
JANITOR_WORKLOAD_SIGNATURES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bclaude\s+plugin\s+marketplace\s+update\b"),
    re.compile(r"\bclaude\s+plugin\s+update\b"),
    re.compile(r"\bclaude\s+plugin\s+list\b"),
    re.compile(r"\boauth_rotator/rotator\.py\b"),
    re.compile(r"\boauth_rotator/reauth\.py\b"),
    re.compile(r"\boauth_rotator/slot_capture_browser\.py\b"),
)

# Anything whose command mentions `claude` but does NOT match a signature is
# treated as the USER'S interactive session (bare `claude`, `claude --resume`,
# `claude --continue`, the IDE helper, …) and is NEVER killable. This is the
# Tier-1 safety contract's load-bearing clause.
_CLAUDE_ANYTHING = re.compile(r"(?:^|/|\s)claude(?:\s|$)")


class ProcRow(NamedTuple):
    """One parsed `ps -axo pid,ppid,rss,etime,command` row."""

    pid: int
    ppid: int
    rss_kb: int
    etime_s: int
    command: str


# ---------- pure parsers ---------------------------------------------------

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
            continue  # header line or junk
        rows.append(ProcRow(
            pid=int(pid_s), ppid=int(ppid_s), rss_kb=int(rss_s),
            etime_s=parse_etime(etime_s_raw), command=command.strip(),
        ))
    return rows


def parse_vm_stat(text: str, page_size: int) -> Optional[int]:
    """Free MB from macOS `vm_stat` output: (free + speculative) pages.

    Returns None when the expected lines are absent (never guess).
    """
    free = spec = None
    for line in text.splitlines():
        if line.startswith("Pages free:"):
            free = _vm_stat_pages(line)
        elif line.startswith("Pages speculative:"):
            spec = _vm_stat_pages(line)
    if free is None:
        return None
    total_pages = free + (spec or 0)
    return (total_pages * page_size) // (1024 * 1024)


def _vm_stat_pages(line: str) -> Optional[int]:
    m = re.search(r"(\d+)\.?\s*$", line)
    return int(m.group(1)) if m else None


def parse_meminfo(text: str) -> Optional[int]:
    """Free MB from Linux /proc/meminfo's MemAvailable (kB). None if absent."""
    for line in text.splitlines():
        if line.startswith("MemAvailable:"):
            m = re.search(r"(\d+)", line)
            return int(m.group(1)) // 1024 if m else None
    return None


# ---------- the Tier-1 decision (pure) -------------------------------------

def is_tier1_killable(row: ProcRow, *, protected_pids: frozenset[int],
                      min_etime_s: int) -> bool:
    """The Tier-1 truth: may this row EVER be killed by the guard?

    Every clause must pass:
      1. not a protected pid (the caller, its parent, the daemon itself);
      2. the command matches a janitor-workload signature — the allowlist of
         killable shapes; nothing outside it is ever a candidate;
      3. the `claude`-but-not-a-plugin-subcommand rejection (defense in depth —
         an interactive session can't match a signature anyway, but a future
         signature edit must not be able to widen onto user sessions silently);
      4. older than the runaway age gate (a legitimately-running workload that
         is merely slow stays under the daemon's own 1800 s management).
    """
    if row.pid in protected_pids:
        return False
    if not any(sig.search(row.command) for sig in JANITOR_WORKLOAD_SIGNATURES):
        return False
    if _CLAUDE_ANYTHING.search(row.command) and not any(
        sig.search(row.command) for sig in JANITOR_WORKLOAD_SIGNATURES[:3]
    ):
        # A `claude` invocation may only be killed via the three plugin-CLI
        # signatures; any other claude-shaped command is the user's session.
        return False
    if row.etime_s < min_etime_s:
        return False
    return True


def select_victim(rows: list[ProcRow], *, protected_pids: frozenset[int],
                  min_etime_s: int = DEFAULT_RUNAWAY_ETIME_S) -> Optional[ProcRow]:
    """Pick the single largest-RSS Tier-1-killable row, or None.

    One victim per call — the guard kills at most one process per beat and
    re-evaluates pressure on the next beat, so a transient mis-read can never
    cascade into a kill spree.
    """
    candidates = [r for r in rows
                  if is_tier1_killable(r, protected_pids=protected_pids,
                                       min_etime_s=min_etime_s)]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.rss_kb)


# ---------- I/O edges -------------------------------------------------------

def free_memory_mb() -> Optional[int]:
    """System free memory in MB (macOS vm_stat / Linux meminfo). None = unknown.

    None makes the guard a NO-OP for the beat — never kill on missing data.
    """
    try:
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", encoding="utf-8") as fh:
                return parse_meminfo(fh.read())
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
        return parse_vm_stat(out.stdout, page_size)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def snapshot_processes(snapshot_path: str) -> list[ProcRow]:
    """`ps -axo pid,ppid,rss,etime,command` -> FILE -> parsed rows.

    The file hop is deliberate (the no-self-match discipline): the snapshot is
    complete before any matching happens, and the file doubles as the forensic
    record of what the guard saw when it acted.
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


def kill_process(pid: int, *, term_grace_s: float = 2.0) -> bool:
    """SIGTERM -> grace -> SIGKILL. True iff the process is gone afterwards."""
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


def _alive(pid: int) -> bool:
    """Alive AND not a zombie. `kill(pid, 0)` succeeds on zombies, but a zombie
    has already released its memory — for an OOM guard it counts as GONE (and
    without this, killing one of our OWN children would mis-report failure
    while the corpse waits to be reaped)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # exists under another uid — fall through to the state check
    except OSError:
        return False
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["ps", "-p", str(pid), "-o", "stat="],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True  # can't tell -> assume alive (conservative for kill-verification)
    if proc.returncode != 0:
        return False  # ps can't see it -> gone
    return not (proc.stdout or "").strip().upper().startswith("Z")
