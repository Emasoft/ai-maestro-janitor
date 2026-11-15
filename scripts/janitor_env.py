#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Print the environment of ONE process with every value hidden except the names you allow (issue #354).

The legitimate need behind `ps eww -p N` or `cat /proc/N/environ`: see a few variables of a stuck process.
The Bash guard denies those commands because their output lands in a file or in the conversation, and both
end up in a transcript on disk. This helper reads the environment in memory, never through a file or a shell
pipeline, and prints `NAME=value` only for a name that matches an --allow pattern AND is not secret-named by
the shared name test (scripts/lib/secret_names.py). Every other variable prints as
`NAME=<hidden, N characters>`. A secret-named variable stays hidden even when a pattern allows it, so this
helper cannot be used to get around the guard.

    uv run <this file> --pid 4242 --allow 'PYTHON*,NODE_*'

Reads processes of the same user only. macOS: sysctl KERN_PROCARGS2. Linux: /proc/<pid>/environ.
A process that the system does not report an environment for (an Apple-signed binary) prints no variable.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import errno
import fnmatch
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import secret_names  # noqa: E402

_CTL_KERN = 1
_KERN_ARGMAX = 8
_KERN_PROCARGS2 = 49


def _read_macos(pid: int) -> list[bytes]:
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    argmax = ctypes.c_int()
    size = ctypes.c_size_t(ctypes.sizeof(argmax))
    if libc.sysctl((ctypes.c_int * 2)(_CTL_KERN, _KERN_ARGMAX), 2, ctypes.byref(argmax), ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), "sysctl kern.argmax failed")
    buf = ctypes.create_string_buffer(argmax.value)
    size = ctypes.c_size_t(argmax.value)
    if libc.sysctl((ctypes.c_int * 3)(_CTL_KERN, _KERN_PROCARGS2, pid), 3, buf, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), f"sysctl KERN_PROCARGS2 failed for pid {pid}")
    return parse_procargs2(buf.raw[: size.value])


def parse_procargs2(data: bytes) -> list[bytes]:
    """The NAME=value entries of a KERN_PROCARGS2 buffer: argc, the executable path, the arguments, the environment.

    A buffer that is too short or whose argc runs past its strings (a process that exited between the two sysctl calls,
    or one that rewrote its argv area, as nginx and redis do) raises OSError, which main() reports; it used to escape
    as a struct.error or ValueError traceback."""
    try:
        (argc,) = struct.unpack_from("i", data, 0)
        pos = data.index(b"\0", 4)  # end of the executable path
        while pos < len(data) and data[pos] == 0:  # padding
            pos += 1
        for _ in range(argc):  # the arguments
            pos = data.index(b"\0", pos) + 1
    except (struct.error, ValueError) as exc:
        raise OSError(errno.EINVAL, "malformed KERN_PROCARGS2 buffer") from exc
    entries = []
    while pos < len(data):
        end = data.find(b"\0", pos)
        if end == -1:
            end = len(data)
        if end == pos:  # an empty string ends the environment block; what follows is loader data, not environment
            break
        entries.append(data[pos:end])
        pos = end + 1
    return entries


def _read_linux(pid: int) -> list[bytes]:
    return [entry for entry in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if entry]


def read_environment(pid: int) -> list[bytes]:
    """Raw NAME=value entries of process `pid`. Raises OSError when the system refuses."""
    return _read_macos(pid) if sys.platform == "darwin" else _read_linux(pid)


# user:password@ in a URL: DATABASE_URL, REDIS_URL and the like are not secret-named (the shared name test excludes *_URL) yet carry one.
_URL_CREDENTIALS = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/\s:@]*:\S*@")  # \S*: a password may hold a slash; over-hiding `host:80/a@b` is harmless


def render(entries: list[bytes], patterns: list[str]) -> list[str]:
    """One line per variable: the value only for an allowed name that is not secret-named."""
    lines = []
    for entry in sorted(entries):
        name_bytes, _, value_bytes = entry.partition(b"=")
        name = name_bytes.decode("utf-8", "replace")
        value = value_bytes.decode("utf-8", "replace")
        allowed = any(fnmatch.fnmatchcase(name, p) for p in patterns)
        if allowed and not secret_names.is_secret_env_name(name) and not _URL_CREDENTIALS.search(value):
            lines.append(f"{name}={value}")
        else:
            lines.append(f"{name}=<hidden, {len(value)} characters>")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print one process's environment with values hidden except allowed names.")
    parser.add_argument("--pid", type=int, required=True, help="process id (same user)")
    parser.add_argument("--allow", default="", help="comma-separated name patterns whose value may be printed, e.g. 'PYTHON*,NODE_*'")
    args = parser.parse_args(argv)
    patterns = [p.strip() for p in args.allow.split(",") if p.strip()]
    try:
        entries = read_environment(args.pid)
    except OSError as exc:
        print(f"janitor-env: cannot read the environment of pid {args.pid}: {exc}", file=sys.stderr)
        return 1
    if not entries:
        print(f"janitor-env: the system reports no environment for pid {args.pid} (a system-signed binary hides it)", file=sys.stderr)
        return 0
    print("\n".join(render(entries, patterns)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
