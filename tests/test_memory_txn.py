"""Tests for the wikimem memory-edit transaction core (TRDD-b92a9dd0).

Real fixtures, no mocks: each test builds a fake scope root of `.md` notes in a
tmp dir, isolates the machine-wide flock/state via JANITOR_GLOBAL_STATE_DIR, and
drives the transaction through commit / abort / resume / the stale-snapshot guard
/ the kill gate. Covers the acceptance criteria in TRDD-b92a9dd0: a clean commit
applies atomically, a crash mid-swap rolls forward, a concurrent writer aborts the
stale snapshot, and a held scope lock makes a second pass skip.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import memory_txn  # noqa: E402
from memory_txn import MemoryTxn, MemoryTxnError  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_global_state(tmp_path, monkeypatch):
    """Point the machine-wide flock + state dir at a per-test tmp dir."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_WIKIMEM_EDITOR_ENABLED", raising=False)


def _scope(tmp_path) -> Path:
    root = tmp_path / "memory"
    root.mkdir()
    (root / "a.md").write_text("---\nname: a\n---\n\nFact A.\n", encoding="utf-8")
    (root / "b.md").write_text("---\nname: b\n---\n\nFact B.\n", encoding="utf-8")
    return root


def test_clean_commit_applies_writes_and_deletes(tmp_path):
    """A clean merge (write C, delete A+B) lands atomically and cleans staging."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "merge", ["a.md", "b.md"])
    txn.stage_write("c.md", "---\nname: c\n---\n\nFact A. Fact B.\n")
    txn.stage_delete("a.md")
    txn.stage_delete("b.md")
    txn.commit()
    assert (scope / "c.md").read_text(encoding="utf-8").endswith("Fact A. Fact B.\n")
    assert not (scope / "a.md").exists()
    assert not (scope / "b.md").exists()
    assert not txn.staging_dir.exists()  # staging cleaned on done
    assert not txn.journal_path.exists()


def test_apply_atomic_happy_path_returns_txn_id(tmp_path):
    """apply_atomic stages + verifies + commits in one call and returns the id."""
    scope = _scope(tmp_path)
    tid = memory_txn.apply_atomic(
        scope, "split", ["a.md"],
        writes={"a.md": "---\nname: a\n---\n\nFact A (edited).\n"}, deletes=[],
    )
    assert isinstance(tid, str) and len(tid) == 32
    assert "edited" in (scope / "a.md").read_text(encoding="utf-8")


def test_verify_failure_aborts_and_leaves_live_untouched(tmp_path):
    """A verify callback that raises discards staging and never mutates the live tree."""
    scope = _scope(tmp_path)
    before = (scope / "a.md").read_text(encoding="utf-8")

    def _reject(_txn):
        raise MemoryTxnError("verify says no")

    with pytest.raises(MemoryTxnError):
        memory_txn.apply_atomic(
            scope, "merge", ["a.md"],
            writes={"a.md": "CLOBBERED"}, deletes=[], verify=_reject,
        )
    assert (scope / "a.md").read_text(encoding="utf-8") == before
    assert not list((scope / memory_txn._STAGING_DIRNAME).glob("*"))  # nothing left staged


def test_stale_snapshot_guard_aborts_on_concurrent_write(tmp_path):
    """A source changed between begin and commit (mtime is NOT the truth — SHA-256
    re-hash) aborts the commit so a concurrent memory-write is never clobbered."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "merge", ["a.md", "b.md"])
    txn.stage_write("c.md", "merged")
    txn.stage_delete("a.md")
    txn.stage_delete("b.md")
    # a concurrent user memory-write lands on a source AFTER begin:
    (scope / "a.md").write_text("---\nname: a\n---\n\nFact A — user just edited.\n", encoding="utf-8")
    with pytest.raises(MemoryTxnError, match="stale snapshot"):
        txn.commit()
    txn.abort()
    assert "user just edited" in (scope / "a.md").read_text(encoding="utf-8")  # preserved
    assert (scope / "b.md").exists()
    assert not (scope / "c.md").exists()  # the merge did NOT apply


def test_vanished_source_aborts_commit(tmp_path):
    """A source deleted out from under the txn aborts the commit, not a crash."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "merge", ["a.md"])
    txn.stage_write("c.md", "merged")
    (scope / "a.md").unlink()
    with pytest.raises(MemoryTxnError, match="vanished"):
        txn.commit()
    txn.abort()


def test_commit_skips_when_scope_lock_held(tmp_path):
    """A second pass commits only if it wins the per-scope flock; else it skips."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "merge", ["a.md"])
    txn.stage_write("a.md", "---\nname: a\n---\n\nedited\n")
    with memory_txn.commit_lock(scope) as got:
        assert got is True
        with pytest.raises(MemoryTxnError, match="commit lock"):
            txn.commit()
    txn.abort()
    assert "Fact A." in (scope / "a.md").read_text(encoding="utf-8")  # unchanged


def test_kill_switch_disables_commit(tmp_path):
    """The janitor kill-switch flag disables every editorial commit immediately."""
    scope = _scope(tmp_path)
    import global_state
    global_state.init_global_state()
    (global_state.global_state_dir() / "kill-switch.flag").write_text("stop", encoding="utf-8")
    assert memory_txn.editor_enabled() is False
    txn = MemoryTxn.begin(scope, "merge", ["a.md"])
    txn.stage_write("a.md", "edited")
    with pytest.raises(MemoryTxnError, match="disabled"):
        txn.commit()
    txn.abort()


def test_option_off_disables_editor(monkeypatch):
    """CLAUDE_PLUGIN_OPTION_WIKIMEM_EDITOR_ENABLED=off disables the editor."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_WIKIMEM_EDITOR_ENABLED", "off")
    assert memory_txn.editor_enabled() is False


def test_resume_rolls_forward_a_committing_txn(tmp_path):
    """A crash AFTER the source-rehash passed (phase=committing) rolls FORWARD to
    the intended end-state on the next heartbeat — idempotently."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "merge", ["a.md", "b.md"])
    txn.stage_write("c.md", "MERGED")
    txn.stage_delete("a.md")
    txn.stage_delete("b.md")
    txn.phase = "committing"  # simulate the crash window: guard passed, swap not done
    txn._persist()
    acted = memory_txn.resume_pending(scope)
    assert any("rolled-forward" in a for a in acted)
    assert (scope / "c.md").read_text(encoding="utf-8") == "MERGED"
    assert not (scope / "a.md").exists() and not (scope / "b.md").exists()
    assert not txn.staging_dir.exists()


def test_resume_cleans_a_done_txn(tmp_path):
    """A crash after apply but before cleanup (phase=done) is just cleaned up."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "merge", ["a.md"])
    txn.stage_write("a.md", "---\nname: a\n---\n\nedited\n")
    txn.phase = "done"
    txn._persist()
    acted = memory_txn.resume_pending(scope)
    assert any("cleaned" in a for a in acted)
    assert not txn.staging_dir.exists() and not txn.journal_path.exists()


def test_resume_discards_a_stale_staging_txn(tmp_path):
    """A staging-phase journal untouched past the stale window (journal MTIME —
    M-9) is a crashed pass — drop it WITHOUT touching the live tree (the merge
    never began applying)."""
    import os
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "merge", ["a.md"])
    txn.stage_write("c.md", "never applied")
    txn.started_at = 0  # ancient
    txn._persist()
    os.utime(txn.journal_path, (0, 0))  # journal untouched since the epoch
    acted = memory_txn.resume_pending(scope, stale_seconds=10)
    assert any("discarded stale" in a for a in acted)
    assert not txn.staging_dir.exists()
    assert (scope / "a.md").exists()  # live untouched
    assert not (scope / "c.md").exists()


def test_resume_keepalive_journal_touch_prevents_discard(tmp_path):
    """M-9 regression: an OLD txn whose journal was recently touched (the agent
    keepalive — or simply a recent stage_write's _persist) is a LIVE in-flight
    pass and must NOT be discarded, no matter how old started_at is. Pre-fix the
    check used started_at alone, so a >30-min agent pass was thrown away."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "merge", ["a.md"])
    txn.stage_write("c.md", "in flight for hours")
    txn.started_at = 0  # the pass began ages ago…
    txn._persist()      # …but the journal was JUST touched (the keepalive)
    acted = memory_txn.resume_pending(scope, stale_seconds=10)
    assert not any("discarded" in a for a in acted), acted
    assert txn.staging_dir.exists()
    txn.abort()


# M-7 regression (wikimem audit 2026-07-07): resume must isolate per-journal
# failures (one poisoned txn cannot wedge the rest) and SURFACE unreadable
# journals instead of silently skipping them.

def test_resume_surfaces_unreadable_journal(tmp_path):
    """A corrupt journal is left in place for a human — but resume now SAYS so
    (the silent continue meant nobody was ever told, and its staging leaked)."""
    scope = _scope(tmp_path)
    staging_root = MemoryTxn._staging_root(scope)
    staging_root.mkdir()
    (staging_root / "deadbeef.json").write_text("{not json", encoding="utf-8")
    acted = memory_txn.resume_pending(scope)
    assert any("unreadable journal deadbeef.json" in a for a in acted), acted
    assert (staging_root / "deadbeef.json").exists()  # left for a human


def test_resume_one_failing_txn_does_not_wedge_the_next(tmp_path):
    """Two committing txns; one fails its _apply with a REAL I/O error (its write
    target's parent is a regular file, so mkdir raises). Resume surfaces a FAILED
    line for it, keeps its journal (the roll-forward path survives), and still
    rolls the healthy txn forward."""
    scope = _scope(tmp_path)
    (scope / "sub").write_text("a FILE where the bad txn needs a directory", encoding="utf-8")

    bad = MemoryTxn.begin(scope, "repair", ["a.md"])
    bad.stage_write("sub/c.md", "cannot land: parent is a file")
    bad.phase = "committing"
    bad._persist()

    good = MemoryTxn.begin(scope, "repair", ["b.md"])
    good.stage_write("b.md", "---\nname: b\n---\n\nFact B (rolled forward).\n")
    good.phase = "committing"
    good._persist()

    acted = memory_txn.resume_pending(scope)
    assert any(a.startswith(f"FAILED {bad.txn_id}") for a in acted), acted
    assert any(f"rolled-forward {good.txn_id}" in a for a in acted), acted
    assert "rolled forward" in (scope / "b.md").read_text(encoding="utf-8")
    assert bad.journal_path.exists(), "the failing txn keeps its roll-forward journal"


# M-8 regression (wikimem audit 2026-07-07): a journal-less staging dir (crash
# between mkdir and the first _persist) must be swept once stale — it grew
# unbounded and its staged copies were memgrep-recall-visible.

def test_resume_sweeps_stale_orphan_staging_dir(tmp_path):
    """An old staging subdir with no matching journal is removed and surfaced."""
    import os
    scope = _scope(tmp_path)
    staging_root = MemoryTxn._staging_root(scope)
    orphan = staging_root / "0123456789abcdef0123456789abcdef"
    orphan.mkdir(parents=True)
    (orphan / "a.md").write_text("leaked staged copy", encoding="utf-8")
    os.utime(orphan, (0, 0))  # ancient
    acted = memory_txn.resume_pending(scope, stale_seconds=10)
    assert any("removed orphan staging dir" in a for a in acted), acted
    assert not orphan.exists()


def test_resume_leaves_fresh_orphan_staging_dir_alone(tmp_path):
    """A FRESH journal-less staging dir may belong to a begin() racing this very
    resume (journal not persisted yet) — never sweep it early."""
    scope = _scope(tmp_path)
    staging_root = MemoryTxn._staging_root(scope)
    orphan = staging_root / "fedcba9876543210fedcba9876543210"
    orphan.mkdir(parents=True)
    acted = memory_txn.resume_pending(scope, stale_seconds=1800)
    assert not any("orphan" in a for a in acted)
    assert orphan.exists()


def test_resume_leaves_a_fresh_staging_txn_alone(tmp_path):
    """A just-created staging journal may belong to a live in-flight pass — resume
    must NOT clobber it."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "merge", ["a.md"])  # started_at = now
    txn.stage_write("c.md", "in flight")
    acted = memory_txn.resume_pending(scope, stale_seconds=1800)
    assert acted == []
    assert txn.staging_dir.exists()
    txn.abort()


def test_resume_is_noop_without_a_staging_dir(tmp_path):
    """resume_pending on a scope that never ran a txn returns nothing, no crash."""
    scope = _scope(tmp_path)
    assert memory_txn.resume_pending(scope) == []


# M-10 regression (wikimem audit 2026-07-07): rel-paths must never escape the
# scope root — `Path / <absolute>` replaces the base entirely and `..` walks
# out, so an unvalidated rel was an arbitrary write/unlink primitive.

def test_begin_rejects_absolute_source_path(tmp_path):
    """An absolute source path is refused at begin (and staging is cleaned)."""
    scope = _scope(tmp_path)
    victim = tmp_path / "outside.md"
    victim.write_text("outside the scope", encoding="utf-8")
    with pytest.raises(MemoryTxnError, match="escapes the scope root"):
        MemoryTxn.begin(scope, "merge", [str(victim)])
    assert not list((scope / memory_txn._STAGING_DIRNAME).glob("*"))


def test_stage_write_rejects_dotdot_escape(tmp_path):
    """A `../` rel in stage_write is refused — nothing may land outside scope."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "repair", ["a.md"])
    with pytest.raises(MemoryTxnError, match="escapes the scope root"):
        txn.stage_write("../escape.md", "poison")
    txn.abort()
    assert not (tmp_path / "escape.md").exists()


def test_stage_delete_rejects_absolute_path(tmp_path):
    """An absolute rel in stage_delete is refused — no out-of-scope unlink."""
    scope = _scope(tmp_path)
    victim = tmp_path / "victim.md"
    victim.write_text("must survive", encoding="utf-8")
    txn = MemoryTxn.begin(scope, "repair", ["a.md"])
    with pytest.raises(MemoryTxnError, match="escapes the scope root"):
        txn.stage_delete(str(victim))
    txn.abort()
    assert victim.exists()


def test_resume_refuses_hostile_journal_with_escaping_delete(tmp_path):
    """A hand-crafted committing journal whose deletes target an ABSOLUTE path
    is refused at _load (surfaced as unreadable) — resume never unlinks it."""
    import json as _json
    scope = _scope(tmp_path)
    victim = tmp_path / "victim.md"
    victim.write_text("must survive", encoding="utf-8")
    staging_root = MemoryTxn._staging_root(scope)
    staging_root.mkdir()
    hostile_id = "aa" * 16
    (staging_root / hostile_id).mkdir()
    (staging_root / f"{hostile_id}.json").write_text(_json.dumps({
        "txn_id": hostile_id, "op": "merge", "scope_root": str(scope),
        "phase": "committing", "started_at": 0,
        "sources": {}, "writes": [], "deletes": [str(victim)],
    }), encoding="utf-8")
    acted = memory_txn.resume_pending(scope)
    assert any("unreadable journal" in a for a in acted), acted
    assert victim.exists(), "resume must never roll a scope-escaping txn forward"


# M-1 regression (wikimem audit 2026-07-07): a roll-forward runs minutes-to-hours
# after the crash; a user edit that landed on a SOURCE page in that window must
# be PRESERVED (skip the stale write/delete), never silently clobbered.

def test_roll_forward_preserves_concurrent_edit_over_stale_delete(tmp_path):
    """A merge crashed in phase=committing; the user then edits a to-be-deleted
    source page. Resume must apply the rest, SKIP that delete (the live content
    is newer than the journal snapshot), and surface the skip."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "merge", ["a.md", "b.md"])
    txn.stage_write("c.md", "MERGED")
    txn.stage_delete("a.md")
    txn.stage_delete("b.md")
    txn.phase = "committing"
    txn._persist()
    # The crash window: a user janitor-memory-write lands on source b.md.
    user_edit = "---\nname: b\n---\n\nFact B — user just edited.\n"
    (scope / "b.md").write_text(user_edit, encoding="utf-8")

    acted = memory_txn.resume_pending(scope)
    assert any("rolled-forward" in a for a in acted)
    assert any("skipped delete b.md" in a for a in acted), acted
    assert (scope / "c.md").read_text(encoding="utf-8") == "MERGED"   # rest applied
    assert not (scope / "a.md").exists()                              # unchanged source deleted
    assert (scope / "b.md").read_text(encoding="utf-8") == user_edit  # newer content preserved
    assert not txn.staging_dir.exists()


def test_roll_forward_preserves_concurrent_edit_over_stale_write(tmp_path):
    """An in-place repair crashed in phase=committing; the user then edits the
    page. Resume must NOT overwrite the newer user content with the stale staged
    result — skip the write and surface it."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "repair", ["a.md"])
    txn.stage_write("a.md", "---\nname: a\n---\n\nREPAIRED (stale).\n")
    txn.phase = "committing"
    txn._persist()
    user_edit = "---\nname: a\n---\n\nFact A — user just edited.\n"
    (scope / "a.md").write_text(user_edit, encoding="utf-8")

    acted = memory_txn.resume_pending(scope)
    assert any("skipped write a.md" in a for a in acted), acted
    assert (scope / "a.md").read_text(encoding="utf-8") == user_edit
    assert not txn.staging_dir.exists()  # txn still completes + cleans


# H-2 regression (wikimem audit 2026-07-07): a failure DURING the committing
# swap must NOT destroy the journal — abort() refuses past staging, so
# resume_pending can roll the half-applied txn forward.

def test_abort_refuses_once_committing(tmp_path):
    """abort() in the committing phase is a no-op: journal + staging survive."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "merge", ["a.md", "b.md"])
    txn.stage_write("c.md", "---\nname: c\n---\n\nFact A. Fact B.\n")
    txn.phase = memory_txn._PHASE_COMMITTING
    txn._persist()
    txn.abort()
    assert txn.journal_path.exists(), "committing journal must survive abort()"
    assert txn.staging_dir.exists()


def test_apply_atomic_failure_mid_swap_leaves_journal_and_resume_completes(
    tmp_path, monkeypatch
):
    """apply_atomic with an OSError on the SECOND os.replace (write #1 already
    landed): the exception propagates, but the journal survives — and the next
    resume_pending rolls the txn forward to a fully-consistent corpus. Pre-fix,
    abort() destroyed the journal here and the corpus stayed half-mutated forever."""
    scope = _scope(tmp_path)
    real_replace = memory_txn.os.replace

    # Patch fires ONLY on the second LIVE content swap (d.md landing outside the
    # staging tree) — a plain call counter would trip on the journal/staging
    # atomic_writes first (same global os module) and abort while still staging.
    def flaky_replace(src, dst):
        d = str(dst)
        if d.endswith("d.md") and ".maint-staging" not in d:
            raise OSError("disk full (injected)")
        return real_replace(src, dst)

    monkeypatch.setattr(memory_txn.os, "replace", flaky_replace)
    with pytest.raises(OSError, match="injected"):
        memory_txn.apply_atomic(
            scope, "merge", ["a.md", "b.md"],
            writes={
                "c.md": "---\nname: c\n---\n\nFact A. Fact B.\n",
                "d.md": "---\nname: d\n---\n\nSecond page.\n",
            },
            deletes=["a.md", "b.md"],
        )
    monkeypatch.setattr(memory_txn.os, "replace", real_replace)
    staging_root = MemoryTxn._staging_root(scope)
    journals = list(staging_root.glob("*.json"))
    assert journals, "the committing journal must survive the mid-swap failure"
    acted = memory_txn.resume_pending(scope)
    assert any("rolled-forward" in line or "forward" in line for line in acted) or acted
    assert (scope / "c.md").exists() and (scope / "d.md").exists()
    assert not (scope / "a.md").exists() and not (scope / "b.md").exists()
    assert not list(staging_root.glob("*.json")), "journal cleaned after roll-forward"
