# Dedupe helper — Python port of scripts/lib/dedupe.sh.
#
# emit_once(): returns the message the FIRST time a given key is seen,
# returns None on repeats. Keys persist in a per-detector seen-file so
# dedupe survives session restarts.
#
# The /janitor-audit skill renames seen-files aside and restores them, and
# a cron fire may overlap that window. `os.mkdir` is an atomic POSIX
# primitive (it either succeeds or raises FileExistsError without leaving
# partial state), so we use it as a mutex around the read-then-append
# sequence — no `flock` dependency, works on macOS default userland.
#
# API differs slightly from the bash original: the bash emit_once helper
# printed the message to stdout; the Python version returns it (or None)
# so the caller has explicit control over routing. Detectors append to
# drift output via the regular print function.

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional


def _acquire_lock(lockdir: Path, retries: int = 50, sleep_s: float = 0.1) -> bool:
    """Acquire a lockdir mutex. Fail open after `retries` to avoid blocking dispatch.

    Returns True on success, False if lock contention exceeded the budget.
    The bash original also "fails open" — under contention, the caller
    treats the key as already-seen so worst case is one dropped nudge that
    the next fire re-emits.
    """
    for _ in range(retries):
        try:
            lockdir.mkdir()
            return True
        except FileExistsError:
            time.sleep(sleep_s)
    return False


def _release_lock(lockdir: Path) -> None:
    """Best-effort lock release. Never raises."""
    try:
        lockdir.rmdir()
    except (FileNotFoundError, OSError):
        pass


def emit_once(seen_file: Path | str, key: str, message: str) -> Optional[str]:
    """Return `message` the FIRST time `key` is seen, None on repeats.

    `seen_file` is created if missing. Keys are line-separated. The check
    is exact-string-match, line-oriented (`grep -qxF` semantics in bash).
    """
    seen = Path(seen_file)
    seen.parent.mkdir(parents=True, exist_ok=True)
    seen.touch()

    lockdir = Path(str(seen) + ".lockdir")
    if not _acquire_lock(lockdir):
        return None  # fail open — pretend already-seen

    try:
        existing = seen.read_text().splitlines()
        if key in existing:
            return None
        # Append the key. We open in append mode so concurrent readers see
        # an atomic write of the new line.
        with seen.open("a", encoding="utf-8") as f:
            f.write(key + "\n")
        return message
    finally:
        _release_lock(lockdir)


def emit_forget(seen_file: Path | str, key: str) -> None:
    """Forget a key so the next occurrence re-emits.

    Use when the underlying condition resolves (e.g. a stale stash gets
    popped — re-emit if it ever comes back). Idempotent: missing seen-file
    or missing key is a no-op.
    """
    seen = Path(seen_file)
    if not seen.exists():
        return

    lockdir = Path(str(seen) + ".lockdir")
    if not _acquire_lock(lockdir):
        return

    try:
        existing = seen.read_text().splitlines()
        if key not in existing:
            return
        kept = [line for line in existing if line != key]
        # Atomic rewrite via tmp + os.replace.
        tmp = seen.with_suffix(seen.suffix + f".tmp.{os.getpid()}")
        tmp.write_text("\n".join(kept) + ("\n" if kept else ""))
        os.replace(tmp, seen)
    finally:
        _release_lock(lockdir)
