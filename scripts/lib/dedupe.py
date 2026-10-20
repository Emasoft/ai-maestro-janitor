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


def _acquire_lock(lockdir: Path, retries: int = 50, sleep_s: float = 0.1, stale_s: float = 60.0) -> bool:
    """Acquire a lockdir mutex. Fail open after `retries` to avoid blocking dispatch.

    Returns True on success, False if lock contention exceeded the budget.
    The bash original also "fails open" — under contention, the caller
    treats the key as already-seen so worst case is one dropped nudge that
    the next fire re-emits.

    STALE-LOCK BREAK: a holder SIGKILLed mid-emit (e.g. a detector killed by dispatch's
    timeout) leaves the lockdir forever; without expiry every later emit_once on that
    seen-file spins the full retry budget and then drops its finding as "already seen" —
    permanently suppressing real drift alerts. A legitimate hold lasts milliseconds, so a
    lockdir older than `stale_s` is provably orphaned: break it and retry. rmdir on an
    empty dir is race-safe — concurrent breakers get FileNotFoundError (ignored) and
    exactly one subsequent mkdir wins.
    """
    for _ in range(retries):
        try:
            lockdir.mkdir()
            return True
        except FileExistsError:
            try:
                if time.time() - lockdir.stat().st_mtime > stale_s:
                    lockdir.rmdir()
                    continue  # broke a stale lock — retry mkdir immediately
            except (FileNotFoundError, OSError):
                continue  # holder released (or a peer broke it) — retry immediately
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
        # A corrupt seen-file must NOT raise out of emit_once. Every caller
        # treats an exception as "the write failed" and un-latches its
        # episode, so one undecodable file turns a single finding into an
        # unbounded repeat-and-write-amplification loop: the finding re-fires
        # on every fire and the durable record grows without bound.
        # `_read_seen_lines` handles the corrupt case by REWRITING the file
        # empty, so the next read is clean — one re-emit, then a clean file.
        existing = _read_seen_lines(seen)
        if existing is None:
            return None  # unreadable — fail open, pretend already-seen
        if key in existing:
            return None
        # Append the key. We open in append mode so concurrent readers see
        # an atomic write of the new line.
        with seen.open("a", encoding="utf-8") as f:
            f.write(key + "\n")
        return message
    finally:
        _release_lock(lockdir)

def _read_seen_lines(seen: Path) -> list[str] | None:
    """The seen-file's key lines, or None when the file cannot be decoded.

    A seen-file that is not valid UTF-8 is a CORRUPT seen-file, and the
    honest response is to treat it as the EMPTY key set — every key is
    treated as "never seen" — and to REWRITE IT so the corruption does not
    persist.

    WHY REWRITE, AND WHY NOT `errors="replace"`. Decoding with
    errors="replace" does not raise, so the caller proceeds, but it reads
    the file as a set of WRONG keys: the undecodable bytes become one
    replacement character, the real keys that were stored as text are still
    there, and the ones stored as undecodable bytes are gone. The
    consequence is that `emit_forget` finds its key absent and returns
    WITHOUT rewriting, so the corrupt file survives; and every later
    `emit_once` reads the same wrong set, so the same findings re-emit on
    every fire and the file keeps growing. Rewriting the file empty turns
    that into a CLEAN FILE, which is what the caller actually wants, and
    what the comment claiming to prevent an "unbounded
    repeat-and-write-amplification loop" describes.

    EVERY KEY RE-EMITS ONCE, NOT ONE. A wiped file holds no keys, so every
    key is treated as "never seen" and re-emits on the next fire. That is
    BROADER than the single corrupt episode, and it is the right behaviour:
    the file's stamps were unreadable, so nothing can be claimed to have
    been seen. The alternative — reading the corrupt file as a set of
    partial keys — is what produced the unbounded repeat.

    THIS DIFFERS FROM `findings_ledger`, DELIBERATELY. The ledger's
    seen-file records "we told the human about this finding", and it is a
    DURABLE record: it answers "never-reported" on a corrupt file but does
    NOT rewrite it, because wiping it would discard the fact that the
    human was notified. This file is an EPISODE LATCH — a transient
    "already said this" marker whose only job is to stop a repeat — so a
    corrupt one is discarded and rebuilt. The two are different kinds of
    record and take different actions on corruption.

    Returns None only when the file cannot be READ at all (an OSError), so
    the caller can distinguish "unreadable" from "corrupt".
    """
    try:
        raw = seen.read_bytes()
    except OSError:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        # Corrupt: rewrite it empty, atomically, so the next read is clean.
        _rewrite_seen(seen, [])
        return []
    return text.splitlines()


def _rewrite_seen(seen: Path, lines: list[str]) -> None:
    """Replace the seen-file's contents with `lines`, atomically."""
    tmp = seen.with_suffix(seen.suffix + f".tmp.{os.getpid()}")
    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    os.replace(tmp, seen)


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
        # Same reason as emit_once: a corrupt seen-file must not raise. A
        # caller that un-latches a failed write does so from an exception
        # handler, so a raise HERE would escape the handler that called it
        # and take the whole detector down instead of un-latching.
        # `_read_seen_lines` handles the corrupt case by rewriting the file
        # empty, so the corruption does not survive to the next fire.
        existing = _read_seen_lines(seen)
        if existing is None:
            return
        if key not in existing:
            return
        kept = [line for line in existing if line != key]
        _rewrite_seen(seen, kept)
    finally:
        _release_lock(lockdir)
