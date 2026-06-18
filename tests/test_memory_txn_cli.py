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
