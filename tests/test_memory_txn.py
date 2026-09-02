"""Tests for the wikimem memory-edit transaction core (TRDD-b92a9dd0).

Real fixtures, no mocks: each test builds a fake scope root of `.md` notes in a
tmp dir, isolates the machine-wide flock/state via JANITOR_GLOBAL_STATE_DIR, and
drives the transaction through commit / abort / resume / the stale-snapshot guard
/ the kill gate. Covers the acceptance criteria in TRDD-b92a9dd0: a clean commit
applies atomically, a crash mid-swap rolls forward, a concurrent writer aborts the
stale snapshot, and a held scope lock makes a second pass skip.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
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


def test_begin_records_the_owner_pid(tmp_path):
    """issue #158: begin() stamps the calling process's pid so a later resume can
    tell a live in-flight owner from a stopped one."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "merge", ["a.md"])
    assert txn.owner_pid == os.getpid()
    reloaded = memory_txn.MemoryTxn._load(txn.journal_path)
    assert reloaded.owner_pid == os.getpid()
    txn.abort()


def test_resume_reclaims_a_fresh_orphan_whose_owner_process_died(tmp_path):
    """issue #158: a stopped memory-agent pass leaves FRESH (nowhere near the
    multi-hour staleness window) staging transactions behind — the real incident
    was 47 of them, all begun seconds apart, none stale, none reclaimable until
    the window elapsed. The owner pid recorded at begin() lets resume reclaim as
    soon as the owning process is provably dead, regardless of the journal's age."""
    import subprocess

    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "repair", ["a.md"])
    txn.stage_write("c.md", "never applied — the agent was stopped")
    proc = subprocess.Popen(["true"])
    proc.wait()  # the pid is now free of any live process
    txn.owner_pid = proc.pid
    txn._persist()  # journal stays FRESH — mtime is "now"
    acted = memory_txn.resume_pending(scope, stale_seconds=99999)
    assert any(a == f"discarded owner-dead {txn.txn_id}" for a in acted), acted
    assert not txn.staging_dir.exists()
    assert (scope / "a.md").exists()  # live untouched
    assert not (scope / "c.md").exists()


def test_begin_owner_pid_kwarg_still_reclaims_a_dead_owner(tmp_path):
    """TRDD-0A8FN3W3 regression guard for issue #158: passing an explicit dead
    owner_pid at begin() (as the CLI now does via 0, or as any other caller that
    resolves its own pid) must still be reclaimed on sight by resume_pending — the
    new kwarg must not silently disable the dead-owner fast path for a real pid."""
    import subprocess

    scope = _scope(tmp_path)
    proc = subprocess.Popen(["true"])
    proc.wait()  # pid is now free of any live process
    txn = MemoryTxn.begin(scope, "repair", ["a.md"], owner_pid=proc.pid)
    txn.stage_write("c.md", "never applied")
    acted = memory_txn.resume_pending(scope, stale_seconds=99999)
    assert any(a == f"discarded owner-dead {txn.txn_id}" for a in acted), acted
    assert not txn.staging_dir.exists()


def test_begin_owner_pid_zero_is_staleness_only(tmp_path):
    """TRDD-0A8FN3W3: owner_pid=0 (what the CLI now passes) is the pre-existing
    'owner unknown' contract — a fresh journal is left alone, and only elapsing
    stale_seconds reclaims it. Guards against the CLI fix accidentally reviving
    the dead-owner fast path for pid 0."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "repair", ["a.md"], owner_pid=0)
    assert txn.owner_pid == 0
    fresh_acted = memory_txn.resume_pending(scope, stale_seconds=99999)
    assert fresh_acted == []
    assert txn.staging_dir.exists()  # still alive — not reclaimed while fresh

    # Age the journal past stale_seconds and confirm the staleness path still fires.
    # `is_stale` is computed against max(journal mtime, started_at) — both must be aged.
    old = time.time() - 10000
    txn.started_at = int(old)
    txn._persist()
    os.utime(txn.journal_path, (old, old))
    stale_acted = memory_txn.resume_pending(scope, stale_seconds=1)
    assert any(a == f"discarded stale {txn.txn_id}" for a in stale_acted), stale_acted
    assert not txn.staging_dir.exists()


def test_resume_leaves_a_fresh_orphan_whose_owner_is_alive(tmp_path):
    """The other half: a fresh staging txn whose owner pid IS this (alive) test
    process must not be reclaimed — only a provably-dead owner is a green light."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "repair", ["a.md"])  # owner_pid == os.getpid()
    txn.stage_write("c.md", "still being edited")
    acted = memory_txn.resume_pending(scope, stale_seconds=99999)
    assert acted == []
    assert txn.staging_dir.exists()
    txn.abort()


def test_begin_refuses_past_the_concurrency_cap(tmp_path):
    """issue #158: nothing discouraged a pass from batch-opening many transactions
    up front (47 opened in 3.5s in the reported incident) — any interruption then
    orphans all of them at once. begin() now refuses transaction #(cap + 1)."""
    scope = _scope(tmp_path)
    cap = memory_txn._MAX_CONCURRENT_TXNS_PER_SCOPE
    txns = [MemoryTxn.begin(scope, "repair", []) for _ in range(cap)]
    with pytest.raises(MemoryTxnError, match="already open"):
        MemoryTxn.begin(scope, "repair", [])
    for t in txns:
        t.abort()


def test_committing_one_txn_frees_a_concurrency_slot(tmp_path):
    """Closing (not just merely existing) a transaction is what frees the cap —
    abort()'s cleanup removes its journal, so the STAGING count drops and a new
    begin() succeeds again."""
    scope = _scope(tmp_path)
    cap = memory_txn._MAX_CONCURRENT_TXNS_PER_SCOPE
    txns = [MemoryTxn.begin(scope, "repair", []) for _ in range(cap)]
    txns[0].abort()
    fresh = MemoryTxn.begin(scope, "repair", [])  # no longer refused
    for t in txns[1:]:
        t.abort()
    fresh.abort()


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

def test_roll_forward_abandons_whole_txn_when_a_delete_source_was_edited(tmp_path):
    """A merge crashed in phase=committing; the user then edits a to-be-deleted source.
    The txn is ABANDONED WHOLE (F1): nothing mutated, both live pages intact, staging
    kept. Applying "the rest" would write a c.md merged from the STALE b.md while ALSO
    keeping the user's new b.md — a merged page carrying outdated content. Re-merging
    from current content on the next pass is both safe and more correct."""
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
    assert any("CONFLICT" in a for a in acted), acted
    assert not (scope / "c.md").exists()                              # nothing written
    assert (scope / "a.md").exists()                                  # nothing deleted
    assert (scope / "b.md").read_text(encoding="utf-8") == user_edit  # newer content preserved
    assert txn.staging_dir.exists(), "staging must survive — it holds the merged page"
    assert txn.journal_path.exists(), "the txn stays rollable-forward"


def test_roll_forward_abandons_whole_txn_when_the_write_target_was_edited(tmp_path):
    """An in-place repair crashed in phase=committing; the user then edits the page.
    Resume must NOT overwrite the newer user content with the stale staged result."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "repair", ["a.md"])
    txn.stage_write("a.md", "---\nname: a\n---\n\nREPAIRED (stale).\n")
    txn.phase = "committing"
    txn._persist()
    user_edit = "---\nname: a\n---\n\nFact A — user just edited.\n"
    (scope / "a.md").write_text(user_edit, encoding="utf-8")

    acted = memory_txn.resume_pending(scope)
    assert any("CONFLICT" in a for a in acted), acted
    assert (scope / "a.md").read_text(encoding="utf-8") == user_edit
    assert txn.staging_dir.exists()


def test_roll_forward_never_deletes_a_page_whose_merged_survivor_was_skipped(tmp_path):
    """F1 REGRESSION — the CRITICAL one. THE data-loss path.

    A merge is ONE indivisible mutation: write(survivor) ∧ delete(retired), where the
    DELETE PAYS FOR THE WRITE. The old code decided the two loops independently, so when
    the survivor's write was skipped (the user edited it in the crash window) the delete
    of the retired page RAN ANYWAY — and `_cleanup()` then rmtree'd the staging dir that
    held the only copy of the merged page. Result: b.md's facts and its `[^N]` lessons
    existed NOWHERE, reported by a line that never mentioned a page was destroyed.

    This is the likelier direction, too: the survivor is the page a user is more apt to be
    editing, because it is the one that still exists and is recall-visible.

    Falsification: revert `_apply` to the per-file skip and this test fails on the
    `b.md` assertion — it is the whole point."""
    scope = _scope(tmp_path)
    # a.md is the SURVIVOR (merged into, in place); b.md is RETIRED (its facts fold in).
    txn = MemoryTxn.begin(scope, "merge", ["a.md", "b.md"])
    txn.stage_write("a.md", "---\nname: a\n---\n\nFact A. Fact B (folded in).\n")
    txn.stage_delete("b.md")
    txn.phase = "committing"
    txn._persist()

    # The crash window: the user edits the SURVIVOR — an entirely ordinary thing to do.
    user_edit = "---\nname: a\n---\n\nFact A — user just edited.\n"
    (scope / "a.md").write_text(user_edit, encoding="utf-8")

    acted = memory_txn.resume_pending(scope)

    # THE assertion: the retired page must still exist. Its content lives nowhere else.
    assert (scope / "b.md").exists(), (
        "b.md was DELETED while the merged survivor that absorbed it was skipped — "
        "its facts and lessons now exist nowhere. This is F1."
    )
    assert (scope / "b.md").read_text(encoding="utf-8") == "---\nname: b\n---\n\nFact B.\n"
    assert (scope / "a.md").read_text(encoding="utf-8") == user_edit  # user's edit intact
    assert any("CONFLICT" in a for a in acted), acted
    assert txn.staging_dir.exists(), "the merged page must remain recoverable"


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


# --------------------------------------------------------------------------- #
# F3 (audit 2026-07-13) — a "new page" write may not clobber a live page
# --------------------------------------------------------------------------- #

def test_commit_refuses_to_clobber_a_live_page_not_declared_as_a_source(tmp_path):
    """A staged page that is NOT a declared source is a NEW page by definition — every
    oracle in the txn treats it as one (the stale-snapshot re-hash and _apply's hash guard
    both key on `sources`, and the CLI even removes write paths from the LINK-LAW "other
    live pages" set). So if a live page already occupies that path, NOTHING has looked at
    it, and the swap would os.replace its body, its lessons and its backlinks out of
    existence silently. The txn core refuses instead."""
    scope = _scope(tmp_path)
    victim = "---\nname: victim\n---\n\nA page nobody in this txn declared.\n"
    (scope / "victim.md").write_text(victim, encoding="utf-8")

    txn = MemoryTxn.begin(scope, "split", ["a.md"])
    txn.stage_write("victim.md", "---\nname: victim\n---\n\nthe sub-page I just carved out\n")

    with pytest.raises(MemoryTxnError, match="clobber"):
        txn.commit()
    assert (scope / "victim.md").read_text(encoding="utf-8") == victim   # untouched
    assert (scope / "a.md").exists()                                     # nothing applied
    assert txn.staging_dir.exists()                                      # recoverable


def test_commit_allows_overwriting_a_page_declared_as_a_source(tmp_path):
    """The guard rejects only UNINTENDED collisions: declaring the page as a source at
    `begin` is the sanctioned way to overwrite it (the verifier then sees its content),
    and that still commits."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "repair", ["a.md"])
    txn.stage_write("a.md", "---\nname: a\n---\n\nFact A, repaired.\n")
    txn.commit()
    assert "repaired" in (scope / "a.md").read_text(encoding="utf-8")


def test_roll_forward_refuses_to_clobber_a_page_that_appeared_after_the_crash(tmp_path):
    """The roll-forward half of F3. commit() proved the path was free before flipping to
    `committing`, and a still-staged file proves the swap never ran — so a live page here
    was created AFTER the crash, by someone else. Rolling forward would delete it. Abandon
    instead: nothing mutated, staging intact, and the conflict is SURFACED."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "split", ["a.md"])
    txn.stage_write("new.md", "---\nname: new\n---\n\nthe sub-page from the crashed split\n")
    txn.phase = "committing"     # crash window: guard passed, swap not done
    txn._persist()

    # ...and in that window a user writes their own page at the very same path.
    users_page = "---\nname: new\n---\n\nA memory the user wrote while we were down.\n"
    (scope / "new.md").write_text(users_page, encoding="utf-8")

    acted = memory_txn.resume_pending(scope)
    assert any("CONFLICT" in a for a in acted), acted
    assert (scope / "new.md").read_text(encoding="utf-8") == users_page  # NOT destroyed
    assert txn.staging_dir.exists()                                      # still recoverable


# --------------------------------------------------------------------------- #
# F5 (audit 2026-07-13) — a destroyed staging tree must never read as "applied"
# --------------------------------------------------------------------------- #

def test_roll_forward_refuses_when_the_staging_tree_was_destroyed(tmp_path):
    """`_apply` used to infer "this write already applied" from the staged file being GONE.
    That is sound only if os.replace is the sole thing that can remove a staged file — and it
    is not: resume's own stale-discard and orphan sweep rmtree it, and `.maint-staging/` sits
    INSIDE the memory scope root, which for PROJECT scope is inside a git repo (a `git clean
    -fdx`, a disk cleaner, or a user tidying "that weird dot-dir" all take it).

    When the staged write vanishes that way, treating it as applied made `_apply` skip the
    write and then RUN THE DELETES — sources retired, merged page never written. F1's
    terminal outcome through a different door. It must ABANDON instead."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "merge", ["a.md", "b.md"])
    txn.stage_write("c.md", "---\nname: c\n---\n\nFact A. Fact B.\n")
    txn.stage_delete("a.md")
    txn.stage_delete("b.md")
    txn.phase = "committing"          # crash window: guard passed, swap not done
    txn._persist()

    # A `git clean` / racing discard / orphan sweep takes the staging tree.
    shutil.rmtree(txn.staging_dir)

    acted = memory_txn.resume_pending(scope)
    assert any("CONFLICT" in a for a in acted), acted
    assert (scope / "a.md").exists() and (scope / "b.md").exists()   # sources NOT retired
    assert not (scope / "c.md").exists()


def test_roll_forward_still_completes_a_genuinely_applied_write(tmp_path):
    """The oracle must stay useful: a write that REALLY landed (os.replace moved the staged
    file, and the live page carries exactly that content) is recognised as applied, and the
    roll-forward finishes the remaining deletes."""
    scope = _scope(tmp_path)
    merged = "---\nname: c\n---\n\nFact A. Fact B.\n"
    txn = MemoryTxn.begin(scope, "merge", ["a.md", "b.md"])
    txn.stage_write("c.md", merged)
    txn.stage_delete("a.md")
    txn.stage_delete("b.md")
    txn.phase = "committing"
    txn._persist()

    # Simulate the crash landing AFTER the write's os.replace but BEFORE the deletes.
    os.replace(txn.staging_dir / "c.md", scope / "c.md")

    acted = memory_txn.resume_pending(scope)
    assert any("rolled-forward" in a for a in acted), acted
    assert (scope / "c.md").read_text(encoding="utf-8") == merged
    assert not (scope / "a.md").exists() and not (scope / "b.md").exists()


def test_stale_discard_does_not_rmtree_a_txn_that_woke_up(tmp_path):
    """F5(b): the stale-staging discard rmtree's another pass's staging tree, so it must hold
    the scope lock AND re-read the journal under it. `stage_write` does not take the lock, so
    the owner can bump the journal between our stat and our acquire — discarding then would
    destroy an in-flight transaction's only copy of the merged page."""
    scope = _scope(tmp_path)
    txn = MemoryTxn.begin(scope, "merge", ["a.md", "b.md"])
    txn.stage_write("c.md", "---\nname: c\n---\n\nthe merged page\n")

    # Backdate the txn so the discard branch is entered at all (started_at floors the
    # staleness check, so it must be backdated too — then the journal file's mtime, since
    # _persist rewrites it).
    old = int(time.time()) - 100_000
    txn.started_at = old
    txn._persist()
    os.utime(txn.journal_path, (old, old))

    # ...but the owner WAKES UP and stages more work in the window before we acquire.
    def _wake_up(*_a, **_k):
        txn.stage_write("c.md", "---\nname: c\n---\n\nthe merged page, revised\n")
        return commit_lock_real(scope)

    commit_lock_real = memory_txn.commit_lock
    import unittest.mock as _mock
    with _mock.patch.object(memory_txn, "commit_lock", _wake_up):
        acted = memory_txn.resume_pending(scope, stale_seconds=1)

    assert not any("discarded" in a for a in acted), acted
    assert txn.staging_dir.exists()                                  # NOT destroyed
    assert "revised" in (txn.staging_dir / "c.md").read_text(encoding="utf-8")
