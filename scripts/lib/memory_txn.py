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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional

import global_state
import memory_split_lineage
import state

_STAGING_DIRNAME = ".maint-staging"

# The `op` value that marks a transaction as a SPLIT — the one operation whose writes carry a
# lineage stamp (TRDD-3QIQ2E6J). Matches the `--op split` the split skill passes to
# `memory_txn_cli.py commit`.
_OP_SPLIT = "split"

# Journal phases — the ONLY values `phase` ever holds.
_PHASE_STAGING = "staging"        # building the txn; nothing applied yet
_PHASE_COMMITTING = "committing"  # source re-hash passed → swap in progress (roll FORWARD on resume)
_PHASE_DONE = "done"              # fully applied → only cleanup remains

# A staging-phase journal whose JOURNAL FILE has been untouched for this long is
# a CRASHED pass, safe to discard on resume. M-9 (wikimem audit 2026-07-07): the
# CLI contract is begin → agent semantic work → commit ACROSS PROCESSES, and a
# rate-limited / slow agent pass routinely exceeds 30 minutes — the old 1800 s
# window let any OTHER pass's resume discard a legitimately in-flight txn and
# throw away hours of editorial work. Staleness is measured on the journal file's
# MTIME (freshest liveness signal — every _persist bumps it, and a long-thinking
# agent may simply `touch` the journal as an explicit keepalive), with started_at
# as the floor for filesystems with unreliable mtimes. 6 h default.
_STALE_SECONDS_DEFAULT = 21600

# Issue #158: nothing discouraged a pass from BATCH-OPENING many transactions up
# front (a real incident opened 47 USER-scope transactions in 3.5s, then went off
# to edit each in turn) — any interruption of that pass orphans every one of them
# at once, and while they sit open the corpus looks mid-edit to every other
# reader. `begin -> stage -> commit` is meant to be short-lived and roughly
# one-at-a-time; refuse to grow a scope's open (staging-phase) transaction count
# past this cap rather than merely documenting the contract, so a runaway batch
# fails LOUD on transaction #(cap + 1) instead of silently fanning out orphans.
_MAX_CONCURRENT_TXNS_PER_SCOPE = 5


class MemoryTxnError(Exception):
    """A transaction precondition failed (stale source, vanished source, lock
    contention, or the editor kill-gate is engaged). Callers abort + re-surface."""


class MemoryTxnConflict(MemoryTxnError):
    """A roll-forward found a source page changed since the txn began, so the txn was
    ABANDONED with nothing mutated (F1, audit 2026-07-13).

    Distinct from its parent because the handling is different: an ordinary
    `MemoryTxnError` means the txn never started applying and should be discarded, while
    this one means the txn is still VALID but cannot be completed safely right now. Its
    live pages and its staging tree are BOTH intact, and the caller must therefore leave
    the journal alone — advancing the phase or cleaning the staging dir would throw away
    the very content this exception was raised to protect."""


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

# The ONE lock every out-of-scope write shares (TRDD-X4LI97IK). Deliberately NOT 16 hex chars so
# it can never collide with a real `memory-maint-<sha16>.lock`. Byte-identical with memgrep's
# `write_gate::OUT_OF_SCOPE_LOCK_NAME` — change both or neither.
_OUT_OF_SCOPE_LOCK_NAME = "memory-maint-out-of-scope.lock"


def _scope_lock_path(scope_root: Path) -> Path:
    # Machine-wide (under global_state_dir) but keyed by the scope root so two
    # passes on DIFFERENT scopes can commit in parallel while two passes on the
    # SAME scope serialize. 16 hex of sha256 is collision-free in practice.
    #
    # REALPATH first (TRDD-7YHT3FNK P3): memgrep's Rust write_gate canonicalizes
    # the scope root before hashing, so the Python side must hash the SAME string
    # or a symlinked invocation (e.g. /tmp vs /private/tmp on macOS, or a future
    # published-globally symlink) forks the lock and the two languages stop
    # excluding each other — the exact corruption class this lock exists to kill.
    # Path.resolve() is non-strict, so a not-yet-created root still resolves.
    #
    # A root that is NOT a scope shares ONE lock (TRDD-X4LI97IK). memgrep's `scope_root_for`
    # falls back to a page's own parent directory when the page has no `memory` ancestor, so
    # hashing it makes the lock key unbounded — 1,128 orphan lock files on this machine against
    # 9 real ones, +165 in one day. Python's callers only ever pass a real scope root today, but
    # the rule is applied on BOTH sides regardless: a discriminator that lives in one language
    # is the same cross-language divergence TRDD-7YHT3FNK exists to prevent. All three canonical
    # roots end in `.../memory`, so the basename is the discriminator; a `WIKIMEM_*_SCOPE_PATH`
    # relocation to another name over-serializes onto this lock, which is the safe direction.
    root = Path(scope_root).resolve()
    if root.name != "memory":
        return global_state.global_state_dir() / _OUT_OF_SCOPE_LOCK_NAME
    h = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
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


def _pid_is_alive(pid: int) -> bool:
    """True iff `pid` names a live process on this host (issue #158's owner-liveness
    reclaim). `os.kill(pid, 0)` sends no signal, only probes existence/permission.

    Conservative on purpose: an unreadable/ambiguous signal (any OSError other than
    "no such process") is treated as ALIVE, never as a green light to reclaim — the
    staleness window (`_STALE_SECONDS_DEFAULT`) remains the fallback for anything
    this probe cannot confidently call dead."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False  # definitely gone
    except PermissionError:
        return True  # exists, just not owned by us — still alive
    except OSError:
        return True  # ambiguous — do not reclaim on an uncertain signal
    return True


def _ensure_rel_inside(scope_root: Path, rel: str) -> None:
    """M-10 (wikimem audit 2026-07-07), defense-in-depth: reject any rel-path
    that escapes the scope root. ``Path / <absolute>`` REPLACES the base entirely
    and ``..`` segments walk out, so an absolute or dot-dot rel arriving via the
    API (`apply_atomic`, `stage_*`) or a hand-crafted journal (`_load` trusts
    `scope_root`+rel verbatim) could make commit/resume write or unlink arbitrary
    user-writable paths — in the one module allowed to delete memory files. The
    CLI's own reconstructed paths are already safe (derived via `relative_to`);
    this guards every other entry point. Raises MemoryTxnError on escape."""
    p = Path(rel)
    if p.is_absolute():
        raise MemoryTxnError(f"rel path escapes the scope root: {rel!r}")
    root = Path(scope_root).resolve()
    # resolve() also collapses symlink hops, so a rel that tunnels OUT of the
    # scope through an in-scope symlink is rejected too.
    if not (root / p).resolve().is_relative_to(root):
        raise MemoryTxnError(f"rel path escapes the scope root: {rel!r}")


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
    # rel_path -> sha256 of the STAGED content (F5). This is what makes "did this write
    # already apply?" a fail-CLOSED question — see _write_already_applied.
    write_hashes: dict = field(default_factory=dict)
    # The pid that called begin() (issue #158). 0 means "unknown" — a journal written
    # before this field existed, or a caller that could not resolve one; resume then
    # falls back to the staleness window exactly as it always did, never a NEW reclaim.
    owner_pid: int = 0

    # ---- construction / persistence ------------------------------------- #

    @staticmethod
    def _staging_root(scope_root: Path) -> Path:
        return Path(scope_root) / _STAGING_DIRNAME

    @classmethod
    def begin(cls, scope_root, op: str, source_rel_paths, owner_pid: int | None = None) -> "MemoryTxn":
        """Open a transaction: snapshot each source's content hash and copy it into
        the staging tree (so the agent edits the COPY, never the live page, until
        commit). `source_rel_paths` are paths relative to `scope_root`.

        `owner_pid` defaults to `os.getpid()` (in-process API, issue #158 dead-owner
        reaping applies as before). TRDD-0A8FN3W3: a short-lived CLI process (`begin`,
        exit, later `commit` in a different process) must pass `owner_pid=0` — the pid
        it would otherwise record dies the instant the CLI exits, so `resume_pending`
        would reap a live staging txn out from under a concurrent pass. `0` is the
        existing "owner unknown, staleness-only reclaim" contract (see resume_pending)."""
        scope_root = Path(scope_root).resolve()
        staging_root = cls._staging_root(scope_root)
        open_count = cls._staging_phase_count(staging_root)
        if open_count >= _MAX_CONCURRENT_TXNS_PER_SCOPE:
            raise MemoryTxnError(
                f"refusing to open transaction #{open_count + 1} on {scope_root}: "
                f"{_MAX_CONCURRENT_TXNS_PER_SCOPE} already open (issue #158 — begin -> "
                "stage -> commit is meant to be one transaction at a time; commit or "
                "abort an open one first, or run resume_pending to reclaim any orphans)"
            )
        txn_id = uuid.uuid4().hex
        staging_dir = staging_root / txn_id
        staging_dir.mkdir(parents=True, exist_ok=False)
        sources: dict = {}
        for rel in source_rel_paths:
            try:
                _ensure_rel_inside(scope_root, rel)  # M-10: no scope escape
            except MemoryTxnError:
                shutil.rmtree(staging_dir, ignore_errors=True)
                raise
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
            owner_pid=os.getpid() if owner_pid is None else owner_pid,
        )
        txn._persist()
        return txn

    @classmethod
    def _staging_phase_count(cls, staging_root: Path) -> int:
        """How many transactions under `staging_root` are currently in the STAGING
        phase (begun, not yet committed) — the concurrency `begin()` caps (issue
        #158). A journal that cannot be parsed is not counted as an open
        transaction — `resume_pending` (never `begin`) is responsible for those."""
        if not staging_root.is_dir():
            return 0
        count = 0
        for jp in staging_root.glob("*.json"):
            try:
                data = json.loads(jp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("phase") == _PHASE_STAGING:
                count += 1
        return count

    def _persist(self) -> None:
        data = {
            "txn_id": self.txn_id, "op": self.op, "scope_root": str(self.scope_root),
            "phase": self.phase, "started_at": self.started_at,
            "sources": self.sources, "writes": self.writes, "deletes": self.deletes,
            "write_hashes": self.write_hashes, "owner_pid": self.owner_pid,
        }
        # F12: DURABLE, not merely atomic. `state.atomic_write` (tmp + os.replace) is atomic
        # with respect to other PROCESSES, which covers process death — the page cache
        # survives that. It does not survive a power loss or a kernel panic, where the classic
        # outcome is "the rename is durable but the file contents are not" → a ZERO-LENGTH
        # journal. This journal is the ONLY roll-forward path for a half-applied live tree, so
        # it must be durable; fsync the file, then the directory (which is what makes the
        # RENAME itself durable). state.atomic_write stays as-is — it is used on hot
        # per-session paths where this cost is not worth paying.
        blob = json.dumps(data, indent=2, sort_keys=True)
        tmp = self.journal_path.with_name(f"{self.journal_path.name}.tmp.{os.getpid()}")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.journal_path)
        dir_fd = os.open(str(self.journal_path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    @classmethod
    def _load(cls, journal_path: Path) -> "MemoryTxn":
        data = json.loads(Path(journal_path).read_text(encoding="utf-8"))
        scope_root = Path(data["scope_root"])
        # M-10: a hand-crafted/corrupted journal must not become an arbitrary
        # file write/unlink primitive — validate every recorded rel BEFORE any
        # caller can _apply it. resume_pending treats the raise as an unreadable
        # journal (surfaced, left in place), never rolling a hostile txn forward.
        for rel in (*data["sources"], *data["writes"], *data["deletes"]):
            _ensure_rel_inside(scope_root, rel)
        return cls(
            scope_root=scope_root, txn_id=data["txn_id"], op=data["op"],
            staging_dir=cls._staging_root(scope_root) / data["txn_id"],
            journal_path=Path(journal_path), sources=data["sources"],
            writes=data["writes"], deletes=data["deletes"], phase=data["phase"],
            started_at=data.get("started_at", 0),
            write_hashes=data.get("write_hashes") or {},
            owner_pid=data.get("owner_pid", 0),
        )

    # ---- staging -------------------------------------------------------- #

    def stage_write(self, rel_path: str, content: str) -> None:
        """Stage the FULL new content of `rel_path` (created or overwritten on
        commit). Supersedes a pending delete of the same path.

        On a SPLIT, the pages this transaction PRODUCES are stamped with its `txn_id` as their
        `split-lineage:` (TRDD-3QIQ2E6J), so the librarian can later tell "one split emitted both
        of these" and stop re-litigating siblings that share vocabulary by construction. Stamping
        here rather than in the split SKILL is deliberate: a skill instruction is a request to an
        agent, and a lineage field that is merely usually present is worse than none — the pairs it
        silently fails to cover are exactly the ones that go on costing ~221k tokens per pass, with
        nothing to show that they were missed.

        NOT every write is stamped — see `is_split_child`. A split also rewrites OTHER pages'
        inbound `[[links]]`, and marking those as siblings would suppress genuine conflicts against
        unrelated pages.

        KNOWN, BOUNDED GAP — stated because it is real, not because it bites. `cmd_commit` runs
        `verify_split` on the RECONSTRUCTED write set and only then calls this method, so the
        oracle inspects the page one line SHORTER than what lands on disk. Every preservation
        check is body-level and so is unaffected; the one size-sensitive check,
        `split_converged`, could in principle pass at exactly the cap and then apply a page ~50 B
        over it. It cannot in practice: the split skill's headroom rule already refuses to emit a
        sibling within 10% of the cap (3 600 B at the 36 000 B default), which is ~70x the stamp.
        Stamping here rather than before verify is still the right trade — this is the ONE choke
        point every writer passes through, including `apply_atomic`, and a stamp that some future
        split path silently skipped would be worse than a 50-byte accounting gap.
        """
        _ensure_rel_inside(self.scope_root, rel_path)  # M-10: no scope escape
        if self.op == _OP_SPLIT and memory_split_lineage.is_split_child(
            rel_path,
            sources=self.sources,
            exists_in_live=(self.scope_root / rel_path).exists(),
        ):
            content = memory_split_lineage.stamp(content, self.txn_id)
        dst = self.staging_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")
        # F5: remember WHAT we staged, not just that we staged it. `os.replace` moving the
        # staged file is only a sound completion oracle if nothing else can remove staged
        # files — and several things can (see _write_already_applied).
        self.write_hashes[rel_path] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if rel_path not in self.writes:
            self.writes.append(rel_path)
        if rel_path in self.deletes:
            self.deletes.remove(rel_path)
        self._persist()

    def stage_delete(self, rel_path: str) -> None:
        """Stage the removal of `rel_path` from the live tree on commit.
        Supersedes a pending write of the same path."""
        _ensure_rel_inside(self.scope_root, rel_path)  # M-10: no scope escape
        if rel_path not in self.deletes:
            self.deletes.append(rel_path)
        if rel_path in self.writes:
            self.writes.remove(rel_path)
            (self.staging_dir / rel_path).unlink(missing_ok=True)
        self._persist()

    def staged_text(self, rel_path: str) -> str:
        """Read a staged page's current bytes (the copy the agent edits)."""
        return (self.staging_dir / rel_path).read_text(encoding="utf-8")

    def _write_already_applied(self, rel: str) -> bool:
        """Did this write ALREADY land? A vanished staged file is NOT the answer (F5).

        `_apply` used to infer "this write already applied" from the staged file being
        gone — sound ONLY if `os.replace` is the sole thing that can remove a staged file.
        It is not. `resume_pending`'s stale-staging discard rmtree's it, its orphan-staging
        sweep rmtree's it, and `.maint-staging/` lives INSIDE the memory scope root — which
        for PROJECT scope is inside a git repo, so a `git clean -fdx`, a disk cleaner, or a
        user tidying "that weird dot-dir in my memory folder" all take it too.

        When a staged write vanishes for any of those reasons, reading it as "applied" makes
        `_apply` skip the write and then RUN THE DELETES — sources retired, merged page never
        written. Exactly F1's terminal outcome, reached through a different door.

        So ask the fail-CLOSED question instead: is the live page the content we staged? Only
        then did our write land. Anything else is a destroyed staging tree, and the caller
        must abandon rather than delete.

        A journal written before this field existed has no hash, so it answers False and the
        txn is refused rather than half-applied — non-destructive, and such journals live at
        most `_STALE_SECONDS_DEFAULT` anyway."""
        want = self.write_hashes.get(rel)
        live = self.scope_root / rel
        return bool(want) and live.exists() and _sha256_file(live) == want

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
            # F3 (audit 2026-07-13): a write to a path that is NOT a declared source is
            # a NEW page by definition — every oracle in this txn treats it as one. If a
            # live page already sits there, NOTHING has looked at it: the stale-snapshot
            # re-hash above only iterates `sources`, `_apply`'s hash guard keys on
            # `sources`, and the CLI removes every write path from the "other live pages"
            # set before the LINK-LAW check — so the verifier is blinded to it too. The
            # swap below would `os.replace` that page (its body, its `[^N]` lessons, its
            # backlinks) out of existence without printing a word. The legitimate way to
            # edit an existing page IS to declare it a source at `begin`, so this refuses
            # only unintended collisions. The txn core is the last line of defence and
            # must not trust the caller's "brand-new" classification.
            for rel in self.writes:
                if rel not in self.sources and (self.scope_root / rel).exists():
                    raise MemoryTxnError(
                        f"write would clobber a live page not declared as a source: {rel} "
                        "— re-run `begin` with it as a source (an intentional overwrite), "
                        "or choose a free path"
                    )
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
        guards the live commit, so the roll-forward must re-check each source's
        live sha against the journal's begin-time hash.

        F1 (audit 2026-07-13) — THE CHECK IS PER-TRANSACTION, NOT PER-FILE. M-1
        originally decided each write and each delete independently, which tears a
        merge in half. A merge is ONE indivisible mutation — `write(survivor) ∧
        delete(retired)` — and the DELETE IS WHAT PAYS FOR THE WRITE. Skipping the
        write while still running the delete removes the retired page, and the merged
        page (which held the retired page's facts AND its `[^N]` lessons) then dies
        with the staging tree in `_cleanup()`. Net: content that existed nowhere else
        is gone, reported by a single line that does not even mention a page was
        destroyed. That is precisely the outcome the journal exists to prevent, in the
        one module whose charter is "never lose a memory".

        Worse, that is the LIKELIER direction: the survivor is the page a user is more
        apt to be editing, because it is the one that still exists and is recall-visible.

        So: decide everything first, mutate nothing until every target is proven
        current, and on ANY stale source ABANDON THE WHOLE TRANSACTION — mutating
        nothing, deleting nothing, and leaving the staging tree intact so the merged
        page remains recoverable. Completing a stale swap would destroy the user's
        newer edit; half-completing it destroys a page outright. Refusing costs one
        deferred merge, which the next pass redoes from current content.

        Raises `MemoryTxnConflict` (nothing mutated) when a source moved under us.
        Returns one line per no-op target otherwise."""
        # ---- PHASE 1 — DECIDE. No mutation may happen in this loop. ----
        conflicts: list[str] = []
        pending_writes: list[str] = []
        pending_deletes: list[str] = []

        for rel in self.writes:
            staged = self.staging_dir / rel
            live = self.scope_root / rel
            want = self.sources.get(rel)
            if not staged.exists():
                # F5: staged gone does NOT mean "applied". os.replace is atomic, so a
                # completed write does leave no staged file — but so does a racing
                # stale-discard, an orphan sweep, or a `git clean` on the scope root.
                # Verify the live page IS what we staged; if it is not, our staging tree was
                # destroyed under us, and skipping the write while still running the deletes
                # would retire the sources with nothing written (F1's outcome, F5's door).
                if self._write_already_applied(rel):
                    continue
                conflicts.append(
                    f"write {rel}: staged content is gone and the live page does not carry "
                    "it — the staging tree was destroyed mid-transaction"
                )
                continue
            if want is not None and live.exists() and _sha256_file(live) != want:
                conflicts.append(f"write {rel}: live page changed since the journal snapshot")
                continue
            if want is None and live.exists():
                # F3 (audit 2026-07-13) — the roll-forward half. `commit()` proved this
                # non-source path was FREE before flipping to `committing`, and a still-
                # staged file proves the swap never ran, so a live page here appeared
                # AFTER the crash: it is someone else's memory, unseen by every oracle
                # of this txn. Replacing it would delete it silently. (No legitimate
                # shape reaches this branch — an already-applied write has no staged
                # file and was skipped above.)
                conflicts.append(f"write {rel}: a live page now occupies this new-page path")
                continue
            pending_writes.append(rel)

        for rel in self.deletes:
            live = self.scope_root / rel
            if not live.exists():
                continue  # already deleted by a crashed commit — idempotent
            want = self.sources.get(rel)
            if want is not None and _sha256_file(live) != want:
                conflicts.append(f"delete {rel}: live page changed since the journal snapshot")
                continue
            pending_deletes.append(rel)

        if conflicts:
            # Abandon. The live tree and the staging tree are BOTH untouched, so no
            # knowledge is lost — the caller must NOT advance the phase and must NOT
            # clean the staging dir.
            raise MemoryTxnConflict(
                "roll-forward abandoned — the live tree moved under this txn, and applying "
                "it now would destroy a page: "
                + "; ".join(conflicts)
                + f". Nothing was mutated. The merged content is preserved in {self.staging_dir}."
            )

        # ---- PHASE 2 — MUTATE. Every target above was proven current. ----
        for rel in pending_writes:
            live = self.scope_root / rel
            live.parent.mkdir(parents=True, exist_ok=True)
            os.replace(self.staging_dir / rel, live)
        for rel in pending_deletes:
            (self.scope_root / rel).unlink()
        return []

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
    - `staging` → discard if the JOURNAL FILE is older than `stale_seconds`
      (mtime-based, M-9: every `_persist` bumps it and an in-flight agent may
      `touch` the journal as a keepalive — a fresh journal belongs to a
      legitimately in-flight pass between begin and commit; never clobber it),
      OR (issue #158) if its recorded `owner_pid` is a process that no longer
      exists — a FRESH journal whose owner is provably dead is not "in-flight",
      it is an orphan of a stopped pass, and does not need to wait out
      `stale_seconds` to be reclaimed. A stale/orphaned one never began applying
      → safe to drop.

    Returns one human-readable line per transaction acted on — including (M-7)
    a `FAILED <id>` line when one txn's handling raised (a poisoned journal must
    never wedge the rest of the resume) and an `unreadable journal` line for a
    journal that cannot even be parsed (left in place for a human, but SURFACED —
    the old silent `continue` meant nobody was ever told). Honors the same
    commit flock so a concurrent live commit and a resume never race a swap."""
    staging_root = MemoryTxn._staging_root(Path(scope_root))
    if not staging_root.is_dir():
        return []
    acted: list[str] = []
    now = int(time.time())
    for jp in sorted(staging_root.glob("*.json")):
        try:
            txn = MemoryTxn._load(jp)
        except (json.JSONDecodeError, KeyError, OSError, MemoryTxnError):
            # M-7: left in place for a human — but surfaced, never silently
            # skipped. MemoryTxnError covers M-10's scope-escape validation: a
            # hostile journal is refused here and NEVER rolled forward.
            acted.append(f"unreadable journal {jp.name}: left in place for a human")
            continue
        try:
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
                # Surface every no-op target (a step a crashed commit had already
                # applied) — a divergence from the intended end-state a human should see.
                acted.extend(f"{line} ({txn.txn_id})" for line in skipped)
            elif txn.phase == _PHASE_STAGING:
                try:
                    fresh_ts = int(jp.stat().st_mtime)
                except OSError:
                    fresh_ts = txn.started_at
                is_stale = now - max(fresh_ts, txn.started_at) > stale_seconds
                # Issue #158: a staging-phase txn whose OWNER PROCESS is provably dead
                # (the pass was stopped/killed mid-run) is reclaimable the moment we
                # notice — no live edit can still be in flight for it. Waiting out
                # `stale_seconds` (6h default) before reclaiming is exactly the 74-orphan
                # incident: 47 transactions began, stayed FRESH the whole time, and sat
                # unreclaimable while `resume` reported "nothing pending". `owner_pid == 0`
                # means an older journal (predates this field) or an unresolved pid — keep
                # the staleness-only behavior for those, never a new reclaim path.
                owner_dead = txn.owner_pid > 0 and not _pid_is_alive(txn.owner_pid)
                if is_stale or owner_dead:
                    # F5(b): this branch rmtree's another pass's staging tree, so it MUST
                    # hold the scope lock — the `committing` branch above already does. The
                    # CLI's contract is cross-process (begin in one turn, agent work, commit
                    # in a later turn) and `resume` runs at the start of every editorial
                    # pass, so two passes on the same scope (the USER scope is dispatched
                    # against by every project's heartbeat) overlap BY DESIGN. Without the
                    # lock, this could rmtree the staging dir out from under an in-flight
                    # `_apply`.
                    with commit_lock(txn.scope_root) as got:
                        if not got:
                            continue  # a live commit owns this scope right now — hands off
                        # ...and the lock alone is not enough, because `stage_write` does
                        # NOT hold it: the owner may have bumped the journal (or flipped it
                        # to `committing`) between our stat and our acquire. RE-READ under
                        # the lock — that is what actually closes the TOCTOU, for EITHER
                        # reclaim reason.
                        try:
                            fresh = MemoryTxn._load(jp)
                            unchanged = int(jp.stat().st_mtime) <= fresh_ts
                        except (json.JSONDecodeError, KeyError, OSError, MemoryTxnError):
                            continue
                        still_reclaimable = unchanged and (
                            is_stale
                            or (fresh.owner_pid > 0 and not _pid_is_alive(fresh.owner_pid))
                        )
                        if fresh.phase != _PHASE_STAGING or not still_reclaimable:
                            continue  # it woke up while we were acquiring — it is ALIVE
                        fresh._cleanup()
                    reason = "stale" if is_stale else "owner-dead"
                    acted.append(f"discarded {reason} {txn.txn_id}")
        except MemoryTxnConflict as exc:
            # F1: NOT a failure — a deliberate, safe refusal. `_apply` proved a source page
            # changed under us and abandoned BEFORE mutating anything, so the live tree and
            # the staging tree are both intact. We must therefore leave the journal in
            # `committing` (do NOT advance the phase, do NOT clean the staging dir): the txn
            # stays rollable-forward, and the merged content stays recoverable. Reported
            # distinctly from FAILED because "FAILED" reads as breakage, and an operator who
            # believes something broke may go "clean up" the very staging dir that is now the
            # only copy of the merged page.
            acted.append(f"CONFLICT {txn.txn_id}: {exc}")
        except Exception as exc:  # noqa: BLE001 — M-7: isolate per-journal failures
            # One poisoned txn (e.g. a permanent I/O error inside its _apply) must
            # not wedge every later journal — and the skills invoke resume at the
            # start of EVERY editorial pass, so an uncaught exception here would
            # silently no-op all future passes on this scope. The journal is left
            # in place: a committing txn keeps its roll-forward path for a later,
            # healthier resume.
            acted.append(f"FAILED {txn.txn_id}: {exc}")
    # M-8: a crash between staging-dir creation and the first journal persist
    # leaves a journal-LESS staging dir no journal-loop entry will ever clean —
    # unbounded growth, and its staged page copies are memgrep-recall-visible
    # (memgrep has no .maint-staging exclusion; only iter_note_files does).
    # Sweep any staging subdir with no matching journal once it is older than
    # the stale window (a FRESH one may belong to a begin() racing this resume).
    try:
        subdirs = sorted(p for p in staging_root.iterdir() if p.is_dir())
    except OSError:
        subdirs = []
    for sub in subdirs:
        if (staging_root / f"{sub.name}.json").exists():
            continue
        try:
            age = now - int(sub.stat().st_mtime)
        except OSError:
            continue
        if age > stale_seconds:
            shutil.rmtree(sub, ignore_errors=True)
            acted.append(f"removed orphan staging dir {sub.name} (no journal)")
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
