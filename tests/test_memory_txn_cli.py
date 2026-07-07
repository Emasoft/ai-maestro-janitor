"""Tests for the wikimem memory-edit transaction CLI (TRDD-b92a9dd0, TRDD-A).

Real fixtures, no mocks: each test builds a fake memory scope of `.md` notes in a
tmp dir, isolates the machine-wide flock/state via JANITOR_GLOBAL_STATE_DIR, then
drives the CLI exactly as an agent would — `begin` to snapshot+copy sources into a
staging dir, edit the COPIES inside staging (overwrite/add = write, remove =
delete), then `commit` (which DIFFs staging vs the sources, verifies, and applies
atomically). Covers the acceptance: a clean merge/split commit applies; a
verify-fail aborts and leaves the live tree intact; and resume rolls a crashed txn
forward.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import memory_txn_cli as cli  # noqa: E402
from memory_txn import MemoryTxn  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_global_state(tmp_path, monkeypatch):
    """Point the machine-wide flock + state dir at a per-test tmp dir and keep the
    editor enabled (no kill-switch / option override leaking in from the host)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_WIKIMEM_EDITOR_ENABLED", raising=False)


def _run(*argv) -> int:
    """Invoke the CLI's main() with a synthetic argv (sys.argv[0] is the prog)."""
    import contextlib
    import io
    saved = sys.argv
    sys.argv = ["memory_txn_cli", *map(str, argv)]
    try:
        # Swallow stdout/stderr so the test output stays clean; the assertions read
        # the live filesystem (the real effect), not the printed text.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main()
    finally:
        sys.argv = saved


def _note(name, *, ocd="2026-06-01", lmd="2026-06-01", tier="component",
          typ="project", body="A fact.", lessons="") -> str:
    return (
        f"---\nname: {name}\ndescription: \"d\"\nocd: {ocd}\nlmd: {lmd}\n"
        f"metadata:\n  node_type: memory\n  type: {typ}\n  tier: {tier}\n---\n\n"
        f"{body}\n\n## Notes and lessons learned\n{lessons}\n"
    )


def _txn_id_from_begin(scope: Path, op: str, *sources: str) -> str:
    """Run `begin` via MemoryTxn directly (the CLI's begin just wraps it) and return
    the new txn_id. Driving begin through the API lets the test edit the staging dir
    deterministically before invoking the CLI's `commit`."""
    txn = MemoryTxn.begin(scope, op, list(sources))
    return txn.txn_id


def _staging(scope: Path, txn_id: str) -> Path:
    return MemoryTxn._staging_root(scope) / txn_id


# --------------------------------------------------------------------------- #
# begin → edit staging → commit  (the happy path: merge applies)
# --------------------------------------------------------------------------- #

def test_begin_edit_staging_commit_applies_merge(tmp_path):
    """A clean merge: begin copies A+B into staging; the agent removes the copies
    and adds C; commit reconstructs (write C, delete A+B), verifies, and applies."""
    scope = tmp_path / "memory"
    scope.mkdir()
    a = _note("a", ocd="2026-05-01", lmd="2026-05-10",
              body="Auth uses JWT.", lessons="[^1]: cap is 3, verified against source.\n")
    b = _note("b", ocd="2026-06-01", lmd="2026-06-09",
              body="Tokens expire in 30s.", lessons="[^1]: 30s timeout per config.\n")
    (scope / "a.md").write_text(a, encoding="utf-8")
    (scope / "b.md").write_text(b, encoding="utf-8")

    txn_id = _txn_id_from_begin(scope, "merge", "a.md", "b.md")
    staging = _staging(scope, txn_id)
    # Agent's editorial work, performed in staging: drop the two source copies and
    # write the merged survivor (lessons preserved, ocd=min, no dups).
    (staging / "a.md").unlink()
    (staging / "b.md").unlink()
    merged = _note("merged", ocd="2026-05-01", lmd="2026-06-18",
                   body="Auth uses JWT. Tokens expire in 30s.", lessons=(
                       "[^1]: cap is 3, verified against source.\n"
                       "[^2]: 30s timeout per config.\n"))
    (staging / "merged.md").write_text(merged, encoding="utf-8")

    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc == 0
    assert (scope / "merged.md").exists()
    assert not (scope / "a.md").exists() and not (scope / "b.md").exists()
    assert "Auth uses JWT. Tokens expire in 30s." in (scope / "merged.md").read_text(encoding="utf-8")
    assert not staging.exists()  # staging cleaned on commit
    assert not (MemoryTxn._staging_root(scope) / f"{txn_id}.json").exists()


def test_begin_edit_staging_commit_applies_repair(tmp_path):
    """A clean repair (TRDD-87935f21): begin copies a malformed page; the agent
    backfills the missing ocd/lmd/node_type/tier and adds the Notes section IN
    PLACE; commit reconstructs (1 write at the same path, 0 deletes) and applies."""
    scope = tmp_path / "memory"
    scope.mkdir()
    bad = ("---\nname: foo\ndescription: \"d\"\nmetadata:\n  type: project\n---\n\n"
           "A fact.\n[^1]: the cap is 3.\n")
    (scope / "foo.md").write_text(bad, encoding="utf-8")

    txn_id = _txn_id_from_begin(scope, "repair", "foo.md")
    staging = _staging(scope, txn_id)
    (staging / "foo.md").write_text(
        _note("foo", ocd="2026-06-19", lmd="2026-06-19", body="A fact.",
              lessons="[^1]: the cap is 3.\n"),
        encoding="utf-8",
    )

    rc = _run("commit", scope, txn_id, "--op", "repair")
    assert rc == 0
    applied = (scope / "foo.md").read_text(encoding="utf-8")
    assert "tier: component" in applied and "## Notes and lessons learned" in applied
    assert not staging.exists()


def test_repair_rejects_dropped_lesson(tmp_path):
    """A repair that loses a lesson FAILS verify; the live page is left untouched."""
    scope = tmp_path / "memory"
    scope.mkdir()
    src = _note("foo", body="A fact.", lessons="[^1]: the cap is 3, verified.\n")
    (scope / "foo.md").write_text(src, encoding="utf-8")
    txn_id = _txn_id_from_begin(scope, "repair", "foo.md")
    staging = _staging(scope, txn_id)
    (staging / "foo.md").write_text(_note("foo", lmd="2026-06-19", body="A fact."), encoding="utf-8")

    rc = _run("commit", scope, txn_id, "--op", "repair")
    assert rc == 1
    assert (scope / "foo.md").read_text(encoding="utf-8") == src  # live tree untouched


def test_repair_rejects_delete_shaped_changeset(tmp_path):
    """A 'repair' that deletes the source (a merge/split shape) is refused — repair
    is strictly a single-page in-place edit, so the live tree is untouched."""
    scope = tmp_path / "memory"
    scope.mkdir()
    (scope / "foo.md").write_text(_note("foo", body="A fact."), encoding="utf-8")
    txn_id = _txn_id_from_begin(scope, "repair", "foo.md")
    staging = _staging(scope, txn_id)
    (staging / "foo.md").unlink()
    (staging / "other.md").write_text(_note("other", body="x"), encoding="utf-8")

    rc = _run("commit", scope, txn_id, "--op", "repair")
    assert rc != 0
    assert (scope / "foo.md").exists()


def test_begin_edit_staging_commit_applies_split(tmp_path):
    """A clean hub split: begin copies the hub; the agent overwrites it as the
    overview and adds two sub-pages; commit reconstructs the writes, verifies the
    globs partition + lesson preservation, and applies."""
    scope = tmp_path / "memory"
    scope.mkdir()
    glist = '["src/a/**", "src/b/**"]'
    hub = (
        "---\nname: plat\ndescription: \"d\"\nocd: 2026-06-01\nlmd: 2026-06-01\n"
        f"metadata:\n  node_type: memory\n  type: project\n  tier: hub\n  globs: {glist}\n---\n\n"
        "## Frontend\nUI bits.\n## Backend\nServer bits.\n\n"
        "## Notes and lessons learned\n[^1]: the build flag is --release.\n"
    )
    (scope / "plat.md").write_text(hub, encoding="utf-8")

    txn_id = _txn_id_from_begin(scope, "split", "plat.md")
    staging = _staging(scope, txn_id)

    def _page(name, globs, body, lessons=""):
        gl = "[" + ", ".join(f'"{g}"' for g in globs) + "]"
        return (
            f"---\nname: {name}\ndescription: \"d\"\nocd: 2026-06-01\nlmd: 2026-06-18\n"
            f"metadata:\n  node_type: memory\n  type: project\n  tier: hub\n  globs: {gl}\n---\n\n"
            f"{body}\n\n## Notes and lessons learned\n{lessons}\n"
        )

    overview = _page("plat", ["src/a/**", "src/b/**"],
                     "Overview: see [[plat-frontend]] and [[plat-backend]].")
    sub1 = _page("plat-frontend", ["src/a/**"], "UI bits.",
                 lessons="[^1]: the build flag is --release.\n")
    sub2 = _page("plat-backend", ["src/b/**"], "Server bits.")
    (staging / "plat.md").write_text(overview, encoding="utf-8")          # overwrite source -> overview
    (staging / "plat-frontend.md").write_text(sub1, encoding="utf-8")     # new sub-page
    (staging / "plat-backend.md").write_text(sub2, encoding="utf-8")      # new sub-page

    rc = _run("commit", scope, txn_id, "--op", "split")
    assert rc == 0
    assert (scope / "plat-frontend.md").exists() and (scope / "plat-backend.md").exists()
    assert "Overview: see" in (scope / "plat.md").read_text(encoding="utf-8")  # source became overview
    assert not staging.exists()


# --------------------------------------------------------------------------- #
# verify-fail aborts and leaves the live tree intact
# --------------------------------------------------------------------------- #

def test_verify_fail_aborts_and_leaves_live_tree_intact(tmp_path):
    """A merge that DROPS a source lesson fails verify → commit returns non-zero,
    aborts the txn, and the live A/B pages are untouched (no C created)."""
    scope = tmp_path / "memory"
    scope.mkdir()
    a = _note("a", ocd="2026-05-01", lmd="2026-05-10",
              lessons="[^1]: cap is 3, verified against source.\n")
    b = _note("b", ocd="2026-06-01", lmd="2026-06-09",
              lessons="[^1]: 30s timeout per config.\n")
    (scope / "a.md").write_text(a, encoding="utf-8")
    (scope / "b.md").write_text(b, encoding="utf-8")

    txn_id = _txn_id_from_begin(scope, "merge", "a.md", "b.md")
    staging = _staging(scope, txn_id)
    (staging / "a.md").unlink()
    (staging / "b.md").unlink()
    # The merged page silently DROPS a's lesson — verify must catch it.
    bad = _note("merged", ocd="2026-05-01", lmd="2026-06-18",
                lessons="[^1]: 30s timeout per config.\n")
    (staging / "merged.md").write_text(bad, encoding="utf-8")

    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc == 1                                   # verify-fail exit code
    assert (scope / "a.md").read_text(encoding="utf-8") == a   # live tree untouched
    assert (scope / "b.md").read_text(encoding="utf-8") == b
    assert not (scope / "merged.md").exists()        # the merge did NOT apply
    assert not staging.exists()                      # txn aborted, staging discarded
    assert not list(MemoryTxn._staging_root(scope).glob("*.json"))


# --------------------------------------------------------------------------- #
# resume rolls a crashed (committing-phase) transaction forward
# --------------------------------------------------------------------------- #

def test_resume_rolls_forward_a_crashed_commit(tmp_path):
    """A txn that crashed AFTER the source re-hash passed (phase=committing) is
    rolled forward to its intended end-state by `resume`."""
    scope = tmp_path / "memory"
    scope.mkdir()
    (scope / "a.md").write_text(_note("a"), encoding="utf-8")
    (scope / "b.md").write_text(_note("b"), encoding="utf-8")

    txn = MemoryTxn.begin(scope, "merge", ["a.md", "b.md"])
    txn.stage_write("c.md", "---\nname: c\n---\n\nMERGED.\n")
    txn.stage_delete("a.md")
    txn.stage_delete("b.md")
    txn.phase = "committing"   # the crash window: guard passed, swap not yet done
    txn._persist()

    rc = _run("resume", scope)
    assert rc == 0
    assert (scope / "c.md").read_text(encoding="utf-8") == "---\nname: c\n---\n\nMERGED.\n"
    assert not (scope / "a.md").exists() and not (scope / "b.md").exists()
    assert not _staging(scope, txn.txn_id).exists()


def test_abort_discards_staging(tmp_path):
    """`abort` discards a not-yet-committed txn and never touches the live tree."""
    scope = tmp_path / "memory"
    scope.mkdir()
    (scope / "a.md").write_text(_note("a"), encoding="utf-8")
    txn_id = _txn_id_from_begin(scope, "merge", "a.md")
    staging = _staging(scope, txn_id)
    (staging / "a.md").write_text("CLOBBERED in staging", encoding="utf-8")

    rc = _run("abort", scope, txn_id)
    assert rc == 0
    assert not staging.exists()
    assert "A fact." in (scope / "a.md").read_text(encoding="utf-8")  # live untouched


def test_cli_begin_creates_staging_with_source_copies(tmp_path):
    """The CLI `begin` subcommand opens a txn and copies the named sources into a
    fresh staging dir (the agent then edits those copies)."""
    import contextlib
    import io
    scope = tmp_path / "memory"
    scope.mkdir()
    (scope / "a.md").write_text(_note("a"), encoding="utf-8")
    (scope / "b.md").write_text(_note("b"), encoding="utf-8")

    saved = sys.argv
    sys.argv = ["memory_txn_cli", "begin", str(scope), "merge", "a.md", "b.md"]
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = cli.main()
    finally:
        sys.argv = saved
    assert rc == 0
    printed = out.getvalue()
    assert "txn_id=" in printed and "staging=" in printed
    txn_id = next(ln.split("=", 1)[1] for ln in printed.splitlines() if ln.startswith("txn_id="))
    staging = _staging(scope, txn_id)
    assert (staging / "a.md").exists() and (staging / "b.md").exists()  # source copies staged


def test_commit_with_no_staged_changes_errors(tmp_path):
    """A commit that diffs to ZERO writes and ZERO deletes (agent did nothing) is a
    no-op error, not a silent empty commit."""
    scope = tmp_path / "memory"
    scope.mkdir()
    (scope / "a.md").write_text(_note("a"), encoding="utf-8")
    txn_id = _txn_id_from_begin(scope, "merge", "a.md")
    # Leave staging exactly as begin made it (the unchanged a.md copy).
    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc == 2
    assert not _staging(scope, txn_id).exists()  # aborted
    assert "A fact." in (scope / "a.md").read_text(encoding="utf-8")


# H-1 regression (wikimem audit 2026-07-07): the merge-INTO-SURVIVOR shape
# (overwrite a.md, delete b.md) must feed the SURVIVOR's begin-time content to
# the verifier too — dropping the survivor's own lesson used to commit clean.

def _survivor_merge_txn(tmp_path, survivor_text: str):
    """Build the merge-into-survivor shape: a.md is overwritten with
    `survivor_text`, b.md is deleted. Returns (scope, txn_id)."""
    scope = tmp_path / "memory"
    scope.mkdir()
    a = _note("a", ocd="2026-05-01", lmd="2026-05-10",
              body="Auth uses JWT.", lessons="[^1]: cap is 3, verified against source.\n")
    b = _note("b", ocd="2026-06-01", lmd="2026-06-09",
              body="Tokens expire in 30s.", lessons="[^1]: 30s timeout per config.\n")
    (scope / "a.md").write_text(a, encoding="utf-8")
    (scope / "b.md").write_text(b, encoding="utf-8")
    txn_id = _txn_id_from_begin(scope, "merge", "a.md", "b.md")
    staging = _staging(scope, txn_id)
    (staging / "b.md").unlink()
    (staging / "a.md").write_text(survivor_text, encoding="utf-8")
    return scope, txn_id


def test_merge_into_survivor_dropping_survivors_lesson_fails(tmp_path):
    """The exact H-1 hole: the survivor keeps B's content but LOSES its own
    lesson + fact — the verifier must now refuse (it used to pass)."""
    bad = _note("a", ocd="2026-05-01", lmd="2026-06-18",
                body="Tokens expire in 30s.",
                lessons="[^1]: 30s timeout per config.\n")  # A's lesson + fact GONE
    scope, txn_id = _survivor_merge_txn(tmp_path, bad)
    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc != 0, "a merge that loses the survivor's own lesson must not commit"
    assert "cap is 3" in (scope / "a.md").read_text(encoding="utf-8")  # live tree intact
    assert (scope / "b.md").exists()


def test_merge_into_survivor_preserving_everything_commits(tmp_path):
    """The correct merge-into-survivor: both pages' lessons + facts survive and
    the survivor keeps its own OLDER ocd — must pass (the pre-fix gate perversely
    REJECTED the older ocd because it only saw the deleted page's sources)."""
    good = _note("a", ocd="2026-05-01", lmd="2026-06-18",
                 body="Auth uses JWT. Tokens expire in 30s.", lessons=(
                     "[^1]: cap is 3, verified against source.\n"
                     "[^2]: 30s timeout per config.\n"))
    scope, txn_id = _survivor_merge_txn(tmp_path, good)
    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc == 0
    merged = (scope / "a.md").read_text(encoding="utf-8")
    assert "cap is 3" in merged and "30s timeout" in merged
    assert not (scope / "b.md").exists()
