# Memory-edit transaction core (TRDD-b92a9dd0) — the safety substrate every
# wikimem editorial pass (merge / split / conflict-resolve) mutates pages through.
#
# WHY this exists (the load-bearing reason): a merge/split mutates MANY files at
# once — the merged/overview page, the deleted source pages, MEMORY.md, and the
# redirected backlinks in OTHER pages. POSIX has no multi-file atomic rename, so a
# crash / rate-limit / context-compaction mid-pass would leave the corpus
# inconsistent (duplicate pages, or deleted-source-without-merged-page data loss),
# and verify-AFTER-write cannot undo a partial mutation. This module makes the
# whole mutation a JOURNALED transaction: stage every new page in a sibling
# `.maint-staging/<txn-id>/` dir, record the intended end-state + the sources'
# content hashes in a journal, then apply via ORDERED per-file `os.replace` (each
# atomic). A crash leaves a journal a later heartbeat ROLLS FORWARD to the intended
# end-state — and because `os.replace` moves the staged file, "the staged file
# still exists" is itself the per-write completion oracle, so roll-forward is
# idempotent. A concurrent user `janitor-memory-write` between stage and commit is
# caught by re-hashing the sources right before the swap: mtime is NOT the truth
# (the wikimem model says so), a SHA-256 mismatch aborts the txn, and it
# re-surfaces next cycle on fresh content. The commit-time flock (cloned from
# global_state.marketplace_lock) serializes two passes' swaps machine-wide.

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

import global_state
import state

_STAGING_DIRNAME = ".maint-staging"

# Journal phases — the ONLY values `phase` ever holds.
_PHASE_STAGING = "staging"        # building the txn; nothing applied yet
_PHASE_COMMITTING = "committing"  # source re-hash passed → swap in progress (roll FORWARD on resume)
_PHASE_DONE = "done"              # fully applied → only cleanup remains

# A staging-phase journal older than this is a CRASHED pass (no real pass takes
# this long), safe to discard on resume. Kept generous so resume never clobbers a
# legitimately in-flight pass that is between begin() and commit().
_STALE_SECONDS_DEFAULT = 1800


class MemoryTxnError(Exception):
    """A transaction precondition failed (stale source, vanished source, lock
    contention, or the editor kill-gate is engaged). Callers abort + re-surface."""


# --------------------------------------------------------------------------- #
# kill gate
# --------------------------------------------------------------------------- #

def editor_enabled() -> bool:
    """Master kill gate for the entire wikimem editor.

    False when the janitor kill-switch is present (so a runaway pass is stoppable
    machine-wide, exactly like the daemon) OR when the option is a friendly-false
    spelling. Default ON — the user wants the editor automatic — but a single
    `kill-switch.flag` or `CLAUDE_PLUGIN_OPTION_WIKIMEM_EDITOR_ENABLED=off`
    disables every pass immediately.
    """
    if global_state.kill_switch_present():
        return False
    return state.is_truthy_env("CLAUDE_PLUGIN_OPTION_WIKIMEM_EDITOR_ENABLED", default=True)


# --------------------------------------------------------------------------- #
# per-scope commit flock (clone of global_state.marketplace_lock)
# --------------------------------------------------------------------------- #

def _scope_lock_path(scope_root: Path) -> Path:
    # Machine-wide (under global_state_dir) but keyed by the scope root so two
    # passes on DIFFERENT scopes can commit in parallel while two passes on the
    # SAME scope serialize. 16 hex of sha256 is collision-free in practice.
    h = hashlib.sha256(str(scope_root).encode("utf-8")).hexdigest()[:16]
    return global_state.global_state_dir() / f"memory-maint-{h}.lock"


def _acquire_commit_lock(scope_root: Path) -> Optional[int]:
    """Non-blocking exclusive flock for this scope's commit. fd on success, None
    when another process holds it (caller SKIPS and re-surfaces next cycle —
    never blocks, exactly like the marketplace/oauth locks)."""
    global_state.init_global_state()
    fd = os.open(str(_scope_lock_path(scope_root)), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (BlockingIOError, OSError) as exc:
        try:
            os.close(fd)
        finally:
            pass
        if isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in (errno.EAGAIN, errno.EWOULDBLOCK):
            return None
        raise


@contextlib.contextmanager
def commit_lock(scope_root: Path) -> Iterator[bool]:
    """Yield True iff this process holds the scope's commit lock. Releases on exit."""
    fd = _acquire_commit_lock(Path(scope_root))
    try:
        yield fd is not None
    finally:
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# hashing
# --------------------------------------------------------------------------- #

def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# the transaction
# --------------------------------------------------------------------------- #

@dataclass
class MemoryTxn:
    """One journaled, crash-resumable, hash-guarded edit of a memory scope root.

    Lifecycle: ``begin`` → ``stage_write`` / ``stage_delete`` (any number) →
    ``commit`` (or ``abort``). State lives in the on-disk journal after every
    mutation, so begin and commit may run in SEPARATE processes (the agent-driven
    case) or the same process (the in-process ``apply_atomic`` convenience).
    """

    scope_root: Path
    txn_id: str
    op: str
    staging_dir: Path
    journal_path: Path
    sources: dict           # rel_path -> sha256 captured at begin()
    writes: list            # rel_paths whose new content lives in staging_dir
    deletes: list           # rel_paths to unlink from the live tree on commit
    phase: str
    started_at: int = 0

    # ---- construction / persistence ------------------------------------- #

    @staticmethod
    def _staging_root(scope_root: Path) -> Path:
        return Path(scope_root) / _STAGING_DIRNAME

    @classmethod
    def begin(cls, scope_root, op: str, source_rel_paths) -> "MemoryTxn":
        """Open a transaction: snapshot each source's content hash and copy it into
        the staging tree (so the agent edits the COPY, never the live page, until
        commit). `source_rel_paths` are paths relative to `scope_root`."""
        scope_root = Path(scope_root).resolve()
        txn_id = uuid.uuid4().hex
        staging_root = cls._staging_root(scope_root)
        staging_dir = staging_root / txn_id
        staging_dir.mkdir(parents=True, exist_ok=False)
        sources: dict = {}
        for rel in source_rel_paths:
            live = scope_root / rel
            if not live.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
                raise MemoryTxnError(f"source does not exist at begin: {rel}")
            sources[rel] = _sha256_file(live)
            dst = staging_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(live, dst)
        txn = cls(
            scope_root=scope_root, txn_id=txn_id, op=op, staging_dir=staging_dir,
            journal_path=staging_root / f"{txn_id}.json", sources=sources,
            writes=[], deletes=[], phase=_PHASE_STAGING, started_at=int(time.time()),
        )
        txn._persist()
        return txn

    def _persist(self) -> None:
        data = {
            "txn_id": self.txn_id, "op": self.op, "scope_root": str(self.scope_root),
            "phase": self.phase, "started_at": self.started_at,
            "sources": self.sources, "writes": self.writes, "deletes": self.deletes,
        }
        state.atomic_write(self.journal_path, json.dumps(data, indent=2, sort_keys=True))

    @classmethod
    def _load(cls, journal_path: Path) -> "MemoryTxn":
        data = json.loads(Path(journal_path).read_text(encoding="utf-8"))
        scope_root = Path(data["scope_root"])
        return cls(
            scope_root=scope_root, txn_id=data["txn_id"], op=data["op"],
            staging_dir=cls._staging_root(scope_root) / data["txn_id"],
            journal_path=Path(journal_path), sources=data["sources"],
            writes=data["writes"], deletes=data["deletes"], phase=data["phase"],
            started_at=data.get("started_at", 0),
        )

    # ---- staging -------------------------------------------------------- #

    def stage_write(self, rel_path: str, content: str) -> None:
        """Stage the FULL new content of `rel_path` (created or overwritten on
        commit). Supersedes a pending delete of the same path."""
        dst = self.staging_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")
        if rel_path not in self.writes:
            self.writes.append(rel_path)
        if rel_path in self.deletes:
            self.deletes.remove(rel_path)
        self._persist()

    def stage_delete(self, rel_path: str) -> None:
        """Stage the removal of `rel_path` from the live tree on commit.
        Supersedes a pending write of the same path."""
        if rel_path not in self.deletes:
            self.deletes.append(rel_path)
        if rel_path in self.writes:
            self.writes.remove(rel_path)
            (self.staging_dir / rel_path).unlink(missing_ok=True)
        self._persist()

    def staged_text(self, rel_path: str) -> str:
        """Read a staged page's current bytes (the copy the agent edits)."""
        return (self.staging_dir / rel_path).read_text(encoding="utf-8")

    # ---- commit / abort / apply ----------------------------------------- #

    def commit(self) -> None:
        """Apply the transaction atomically-enough to be crash-recoverable.

        Order: kill-gate → acquire the scope flock → re-hash every source (the
        stale-snapshot guard; a concurrent writer aborts us) → flip the journal to
        `committing` (the point past which a crash ROLLS FORWARD, never back) →
        ordered per-file swap → `done` → clean. Raises MemoryTxnError on any
        precondition failure; the caller then aborts."""
        if not editor_enabled():
            raise MemoryTxnError("wikimem editor disabled (kill-switch or option)")
        with commit_lock(self.scope_root) as got:
            if not got:
                raise MemoryTxnError("another pass holds this scope's commit lock; retry next cycle")
            for rel, want in self.sources.items():
                live = self.scope_root / rel
                if not live.exists():
                    raise MemoryTxnError(f"source vanished since begin: {rel}")
                if _sha256_file(live) != want:
                    raise MemoryTxnError(f"source changed since begin (stale snapshot): {rel}")
            self.phase = _PHASE_COMMITTING
            self._persist()
            self._apply()
            self.phase = _PHASE_DONE
            self._persist()
        self._cleanup()

    def _apply(self) -> list[str]:
        """Idempotent end-state application (used by commit AND resume roll-forward).
        Writes first (survivors before deletions so content is never momentarily
        absent), deletes last. `os.replace` is atomic, so a staged file still
        present ⟺ that write has NOT applied — the resume completion oracle.

        M-1 (wikimem audit 2026-07-07): a roll-forward can run MINUTES TO HOURS
        after the crash (next heartbeat), and a user `janitor-memory-write` may
        have landed on a source page in that window. The commit-time re-hash only
        guards the live commit; here each write/delete whose target rel is a
        recorded SOURCE re-checks the live sha against the journal's begin-time
        hash and SKIPS on mismatch — the NEWER user content is preserved (the
        never-lose-a-memory charter beats completing the stale swap; a preserved
        duplicate re-surfaces on the next consolidate pass). Returns one line per
        skipped target so resume can surface the decision."""
        skipped: list[str] = []
        for rel in self.writes:
            staged = self.staging_dir / rel
            live = self.scope_root / rel
            if staged.exists():
                want = self.sources.get(rel)
                if want is not None and live.exists() and _sha256_file(live) != want:
                    skipped.append(f"skipped write {rel}: live content newer than the journal snapshot")
                    continue
                live.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, live)
            # staged gone ⇒ a prior (crashed) commit already applied this write → skip
        for rel in self.deletes:
            live = self.scope_root / rel
            if live.exists():
                want = self.sources.get(rel)
                if want is not None and _sha256_file(live) != want:
                    skipped.append(f"skipped delete {rel}: live content newer than the journal snapshot")
                    continue
                live.unlink()
        return skipped

    def abort(self) -> None:
        """Discard a not-yet-committed transaction. Safe to call any time before
        the `committing` phase; a no-op on a vanished staging tree.

        REFUSES (no-op) once the phase is past `staging` (H-2, wikimem audit
        2026-07-07): after commit() persists phase=committing, a partial _apply
        may already have mutated the live tree — the journal is then the ONLY
        roll-forward path for resume_pending, and destroying it would strand the
        corpus permanently half-mutated. Roll-forward, never roll-back, is the
        committing-phase contract; abort must not be able to break it."""
        if self.phase != _PHASE_STAGING:
            return
        self._cleanup()

    def _cleanup(self) -> None:
        shutil.rmtree(self.staging_dir, ignore_errors=True)
        self.journal_path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# resume (run at heartbeat start, BEFORE any new pass)
# --------------------------------------------------------------------------- #

def resume_pending(scope_root, stale_seconds: int = _STALE_SECONDS_DEFAULT) -> list[str]:
    """Roll forward / clean every interrupted transaction under `scope_root`.

    - `committing` → ROLL FORWARD (idempotent `_apply`) → done → clean. A crash
      after the source re-hash passed MUST complete; the staged content is the
      verified end-state.
    - `done` → just clean (the crash was after apply, before cleanup).
    - `staging` → discard ONLY if older than `stale_seconds` (a fresh staging
      journal may belong to a legitimately in-flight pass between begin and
      commit; never clobber it). A stale one is a crashed pass that never began
      applying → safe to drop.

    Returns one human-readable line per transaction acted on. Honors the same
    commit flock so a concurrent live commit and a resume never race a swap."""
    staging_root = MemoryTxn._staging_root(Path(scope_root))
    if not staging_root.is_dir():
        return []
    acted: list[str] = []
    now = int(time.time())
    for jp in sorted(staging_root.glob("*.json")):
        try:
            txn = MemoryTxn._load(jp)
        except (json.JSONDecodeError, KeyError, OSError):
            continue  # an unreadable journal is left for a human; never crash resume
        if txn.phase == _PHASE_DONE:
            txn._cleanup()
            acted.append(f"cleaned {txn.txn_id} (was done)")
        elif txn.phase == _PHASE_COMMITTING:
            with commit_lock(txn.scope_root) as got:
                if not got:
                    continue  # another process owns the swap right now
                skipped = txn._apply()
                txn.phase = _PHASE_DONE
                txn._persist()
            txn._cleanup()
            acted.append(f"rolled-forward {txn.txn_id}")
            # Surface every target the M-1 guard preserved (a concurrent edit
            # landed in the crash window) — silent data-preservation is still a
            # divergence from the txn's intended end-state; a human/agent should see it.
            acted.extend(f"{line} ({txn.txn_id})" for line in skipped)
        elif txn.phase == _PHASE_STAGING:
            if now - txn.started_at > stale_seconds:
                txn._cleanup()
                acted.append(f"discarded stale {txn.txn_id}")
    return acted


# --------------------------------------------------------------------------- #
# in-process convenience (tests + script-driven passes)
# --------------------------------------------------------------------------- #

def apply_atomic(
    scope_root,
    op: str,
    source_rel_paths,
    writes: dict,
    deletes,
    verify: Optional[Callable[["MemoryTxn"], None]] = None,
) -> str:
    """begin → stage `writes`/`deletes` → optional `verify(txn)` → commit, all in
    one process. `writes` is {rel_path: content}; `deletes` is an iterable of
    rel_paths; `verify` raises to abort. Returns the txn_id on success. On a
    failure BEFORE commit reaches the committing phase, the staging tree is
    discarded and the exception re-raised (live tree untouched); a failure
    DURING the committing swap leaves the journal in place — abort() refuses
    past staging — so the next resume_pending rolls the txn forward instead of
    stranding a half-applied live tree (H-2)."""
    txn = MemoryTxn.begin(scope_root, op, source_rel_paths)
    try:
        for rel, content in writes.items():
            txn.stage_write(rel, content)
        for rel in deletes:
            txn.stage_delete(rel)
        if verify is not None:
            verify(txn)
        txn.commit()
        return txn.txn_id
    except BaseException:
        txn.abort()
        raise
