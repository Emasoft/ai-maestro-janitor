"""Same-user process size scan (macOS, ctypes + libproc, no subprocess).

WHY (incident 2026-10-05): a runaway process of the owner's own user grew to many GB and the
daemon only knew how to look at janitor-owned processes via `ps`, so nothing saw it. This
module only MEASURES; it never stops, signals or slows anything.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import stat
import struct
import sys
import time
from typing import NamedTuple

import state

_BSDINFO_SIZE = 136  # struct proc_bsdinfo (PROC_PIDTBSDINFO)
_PPID_OFF, _UID_OFF, _START_OFF = 16, 20, 120
_RUSAGE_RESIDENT_OFF, _RUSAGE_FOOTPRINT_OFF = 64, 72  # rusage_info_v2
_RUSAGE_BUF = 512
_LABEL_MAX = 60


class ProcRow(NamedTuple):
    pid: int
    ppid: int
    start_s: int
    resident_b: int
    footprint_b: int
    exe: str


def _libs() -> tuple[ctypes.CDLL, ctypes.CDLL]:
    lp = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    lc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    lp.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
    lp.proc_listpids.restype = ctypes.c_int
    lp.proc_pidinfo.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int,
    ]
    lp.proc_pidinfo.restype = ctypes.c_int
    lp.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    lp.proc_pid_rusage.restype = ctypes.c_int
    lp.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    lp.proc_pidpath.restype = ctypes.c_int
    lc.sysctl.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_size_t,
    ]
    lc.sysctl.restype = ctypes.c_int
    lc.sysctlbyname.argtypes = [
        ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
    ]
    lc.sysctlbyname.restype = ctypes.c_int
    return lp, lc


def _list_pids(lp: ctypes.CDLL) -> list[int]:
    need = lp.proc_listpids(1, 0, None, 0)
    if need <= 0:
        return []
    buf = (ctypes.c_int * (need // 4 + 64))()
    got = lp.proc_listpids(1, 0, buf, ctypes.sizeof(buf))
    if got <= 0:
        return []
    return [p for p in buf[: got // 4] if p > 0]


def _read_row(lp: ctypes.CDLL, pid: int, uid: int) -> ProcRow | None:
    info = ctypes.create_string_buffer(_BSDINFO_SIZE)
    # A size mismatch means the process exited mid-scan or the layout is not the one these
    # offsets were measured on: skip the row rather than feed garbage downstream.
    if lp.proc_pidinfo(pid, 3, 0, info, _BSDINFO_SIZE) != _BSDINFO_SIZE:
        return None
    if struct.unpack_from("I", info.raw, _UID_OFF)[0] != uid:
        return None
    ru = ctypes.create_string_buffer(_RUSAGE_BUF)
    if lp.proc_pid_rusage(pid, 2, ru) != 0:
        return None
    path = ctypes.create_string_buffer(4096)
    n = lp.proc_pidpath(pid, path, 4096)
    exe = os.path.basename(path.value.decode("utf-8", "replace")) if n > 0 else "?"
    return ProcRow(
        pid=pid,
        ppid=struct.unpack_from("I", info.raw, _PPID_OFF)[0],
        start_s=struct.unpack_from("Q", info.raw, _START_OFF)[0],
        resident_b=struct.unpack_from("Q", ru.raw, _RUSAGE_RESIDENT_OFF)[0],
        footprint_b=struct.unpack_from("Q", ru.raw, _RUSAGE_FOOTPRINT_OFF)[0],
        exe=exe,
    )


def scan_same_user() -> list[ProcRow]:
    """Every process of this uid that could be read in full; unreadable ones are skipped."""
    if sys.platform != "darwin":
        return []
    lp, _ = _libs()
    uid = os.getuid()
    rows = (_read_row(lp, pid, uid) for pid in _list_pids(lp))
    return [r for r in rows if r is not None]


def read_row(pid: int) -> ProcRow | None:
    """One process of this uid, or None when it is gone, foreign, or unreadable."""
    if sys.platform != "darwin":
        return None
    return _read_row(_libs()[0], pid, os.getuid())


def alert_summary(pid: int, label: str, start_s: int) -> str:
    """Notification text: pid, label, start as local date and time; no size, no ceiling.

    notify.push dedupes on the message text, so nothing that changes between passes
    (sizes, the ceiling) may appear here or the same runaway would re-alert every pass.
    """
    started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_s))
    return f"process {pid} ({label}) started {started} is above the size ceiling"


def argv_of(pid: int) -> list[str]:
    """KERN_PROCARGS2 argv of `pid`; [] on any failure (the process may be gone)."""
    if sys.platform != "darwin":
        return []
    try:
        _, lc = _libs()
        mib = (ctypes.c_int * 3)(1, 49, pid)
        size = ctypes.c_size_t(0)
        if lc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0 or size.value < 4:
            return []
        buf = ctypes.create_string_buffer(size.value)
        if lc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0 or size.value < 4:
            return []
        raw = buf.raw[: size.value]
        argc = struct.unpack("i", raw[:4])[0]
        rest = raw[4:]
        rest = rest[rest.index(b"\0"):].lstrip(b"\0")
        return [a.decode("utf-8", "replace") for a in rest.split(b"\0")[:argc]]
    except (OSError, ValueError, struct.error):
        return []



def largest_arg_file_kb(args: list[str]) -> int | None:
    """Size in whole kB of the largest existing regular file among the absolute-path args.

    The caller decides which arguments count (argv[0] and an interpreter's script are not
    inputs). An argument `--flag=/abs/path` counts as that path.

    SIZE ONLY: no argument text and no file name is returned, because arguments can hold
    secrets (same reason `label_from_argv` shows none). The new field adds no name; the
    script name `label_from_argv` already shows for an interpreter run is unchanged.
    None when no argument qualifies.
    """
    # shortcut: a relative-path argument is not seen (the process cwd is not read) and a
    # file passed on stdin is not seen; upgrade when a field detection shows `none` for a
    # process known to edit a file. Symlinks are followed; any absolute-path argument counts,
    # so a model or config file passed by absolute path can be the figure. os.stat runs on the
    # watch thread once per detection, so an argument on a hung network mount would stall the
    # 5 s watch for that call; upgrade to a stat with a timeout if a watch stall is ever
    # traced here.
    sizes: list[int] = []
    for arg in args:
        if not arg.startswith("/") and "=" in arg:
            arg = arg.split("=", 1)[1]
        if not arg.startswith("/"):
            continue
        try:
            st = os.stat(arg)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            sizes.append(st.st_size)
    return max(sizes) // 1024 if sizes else None


def label_from_argv(exe: str, argv: list[str]) -> str:
    """Executable name, plus the script name for an interpreter run on a script file.

    No other argument ever appears: arguments can hold secrets, so the `-c` / `-m` forms
    show the executable alone.
    """
    label = exe
    if is_script_run(exe, argv):
        label = f"{exe} {os.path.basename(argv[1])}"
    return state.sanitize_for_drift_line(label[:_LABEL_MAX])



def is_script_run(exe: str, argv: list[str]) -> bool:
    """True when argv is an interpreter (python, node) run on a script file in argv[1]."""
    # lower(): the Homebrew framework interpreter is named "Python" with a capital P.
    return exe.lower().startswith(("python", "node")) and len(argv) > 1 and not argv[1].startswith("-")


def over_ceiling(
    rows: list[ProcRow], ceiling_b: int, protected: frozenset[int] | set[int]
) -> list[ProcRow]:
    """Rows at or above the ceiling, largest first, never a protected pid.

    max() of the two fields because which of footprint and resident tracked the
    2026-10-05 runaway was never determined; trusting either alone could miss it.
    """
    hits = [
        r for r in rows
        if max(r.footprint_b, r.resident_b) >= ceiling_b and r.pid not in protected
    ]
    return sorted(hits, key=lambda r: max(r.footprint_b, r.resident_b), reverse=True)


def default_ceiling_b() -> int:
    """A quarter of physical memory; 0 off macOS or when the sysctl fails."""
    if sys.platform != "darwin":
        return 0
    _, lc = _libs()
    val = ctypes.c_uint64(0)
    n = ctypes.c_size_t(8)
    if lc.sysctlbyname(b"hw.memsize", ctypes.byref(val), ctypes.byref(n), None, 0) != 0:
        return 0
    return val.value // 4
