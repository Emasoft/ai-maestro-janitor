"""File-integrity primitives for the resilient daemon (TRDD-7100178d, Pillar 2).

Backup-everything + corruption-recovery for the critical state files the daemon
depends on (the rotator's state.json, etc.). Every critical write keeps TWO redundant
copies of the SAME content:

  1. writes the content to a ``<path>.bak`` mirror (+ ``<path>.bak.sha256``) FIRST —
     a prepared-in-advance redundant copy, not a previous version;
  2. writes the same content to the primary ``path`` atomically (tmp in the same dir +
     ``os.replace``, owner-only perms) so a crash mid-write can never leave a
     half-written file, and the mirror-first ordering keeps the pair crash-consistent;
  3. records a ``<path>.sha256`` sidecar of the content for both copies.

Every critical read (``read_or_restore``) verifies the sidecar; on a missing or
mismatched primary it RESTORES from the verified ``.bak`` and re-heals the sidecar,
so a truncated/garbled state file self-heals instead of taking the daemon down. When
neither the primary nor the backup is intact it returns ``None`` — the caller then
rebuilds from the authoritative source (e.g. the keychain slots), never trusting
corrupt bytes (fail-safe, not silent-garbage).

This is the bytes+mode, backup-aware analogue of ``state.atomic_write`` (a string-only,
project-scoped per-session helper) — a distinct concern with a distinct home.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

_BAK_SUFFIX = ".bak"
_SHA_SUFFIX = ".sha256"


def sha256_bytes(data: bytes) -> str:
    """Hex sha256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Write ``data`` to ``path`` atomically: a uniquely-named tmp file in the SAME
    directory (so ``os.replace`` is a pure rename, never a cross-device copy) chmod-ed
    to ``mode`` (owner-only by default — these hold credential-adjacent state), then
    ``os.replace`` into place. ``os.replace`` is atomic on POSIX and Windows, so a
    crash leaves either the old file or the new file, never a partial one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("%s.tmp.%d" % (path.name, os.getpid()))
    tmp.write_bytes(data)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _sidecar_of(path: Path) -> Path:
    return path.with_name(path.name + _SHA_SUFFIX)


def _matches_sidecar(path: Path) -> bool:
    """True iff ``path`` exists, its ``.sha256`` sidecar exists, and they agree."""
    sidecar = _sidecar_of(path)
    if not (path.is_file() and sidecar.is_file()):
        return False
    want = sidecar.read_bytes().decode(errors="replace").strip()
    return want == sha256_bytes(path.read_bytes())


def backup_and_write(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Critical write with a REDUNDANT MIRROR. ``data`` is written to BOTH the primary
    ``path`` and a ``<path>.bak`` mirror, each with its own ``.sha256`` sidecar — two
    independent copies of the SAME content, so a later single-file corruption of either
    is recovered from the other (``read_or_restore``). This protects against corruption
    / torn writes, NOT logical error — there is no version rollback; the backup is the
    current value, not the previous one, so recovery never loses the latest committed
    state (and even the very first write is protected).

    Ordering matters for crash-consistency: the mirror (``.bak`` + its sidecar) is
    written and renamed into place FIRST, then the primary + its sidecar. A crash
    mid-save therefore leaves a fully-consistent state — either the older value (primary
    not yet updated) or, once the primary commits, the newer one — never a torn pair."""
    digest = sha256_bytes(data).encode()
    bak = path.with_name(path.name + _BAK_SUFFIX)
    atomic_write_bytes(bak, data, mode=mode)
    atomic_write_bytes(_sidecar_of(bak), digest, mode=mode)
    atomic_write_bytes(path, data, mode=mode)
    atomic_write_bytes(_sidecar_of(path), digest, mode=mode)


def read_or_restore(path: Path) -> bytes | None:
    """Read ``path`` with corruption recovery.

    - No sidecar at all => trust the primary as-is (a file written before this
      integrity layer wrapped it — e.g. a freshly migrated state.json).
    - Sidecar present and matches => return the primary.
    - Primary missing/corrupt (sidecar present but mismatched) => RESTORE from the
      ``.bak`` *only if the backup verifies against its own sidecar*, re-heal the
      primary's sidecar, and return the restored bytes.
    - Nothing recoverable => ``None`` (caller rebuilds from the authoritative source;
      never returns known-corrupt bytes)."""
    sidecar = _sidecar_of(path)
    if path.is_file() and not sidecar.is_file():
        return path.read_bytes()
    if _matches_sidecar(path):
        return path.read_bytes()
    bak = path.with_name(path.name + _BAK_SUFFIX)
    if _matches_sidecar(bak):
        restored = bak.read_bytes()
        atomic_write_bytes(path, restored)
        atomic_write_bytes(sidecar, sha256_bytes(restored).encode())
        return restored
    return None


def backup_is_consistent(path: Path) -> bool:
    """True iff ``path`` has a fully-established, self-consistent redundant mirror: the
    primary matches its ``.sha256`` sidecar AND the ``.bak`` matches its own sidecar. False
    for a pre-integrity file (no sidecar yet) or any torn / missing / corrupt copy — the
    caller should ``backup_and_write`` to (re-)establish the in-advance backup before relying
    on it. Lets a periodic repair pass cheaply answer "is the safety net already in place?"."""
    bak = path.with_name(path.name + _BAK_SUFFIX)
    return _matches_sidecar(path) and _matches_sidecar(bak)
