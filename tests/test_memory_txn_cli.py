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
from typing import cast

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import memory_txn  # noqa: E402
import memory_txn_cli as cli  # noqa: E402
from memory_txn import MemoryTxn  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_global_state(tmp_path, monkeypatch):
    """Point the machine-wide flock + state dir at a per-test tmp dir and keep the
    editor enabled (no kill-switch / option override leaking in from the host)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_WIKIMEM_EDITOR_ENABLED", raising=False)


def _run_err(*argv) -> tuple[int, str]:
    """`_run`, but also returning stderr.

    A bare `rc != 0` assertion passes when the CLI refuses for ANY reason, so a test written that
    way keeps passing after the refusal it was written to pin has been replaced by a different one
    — the vacuous-test failure mode. Use this whenever WHICH refusal fired is the point.
    """
    import contextlib
    import io

    saved = sys.argv
    sys.argv = ["memory_txn_cli", *map(str, argv)]
    err = io.StringIO()
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            return cli.main(), err.getvalue()
    finally:
        sys.argv = saved


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


def _note(name, *, ocd="2026-06-01", lmd="2026-06-01", tier="component", typ="project", body="A fact.", lessons="") -> str:
    return f'---\nname: {name}\ndescription: "d"\nocd: {ocd}\nlmd: {lmd}\nmetadata:\n  node_type: memory\n  type: {typ}\n  tier: {tier}\n---\n\n{body}\n\n## Notes and lessons learned\n{lessons}\n'


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
    a = _note("a", ocd="2026-05-01", lmd="2026-05-10", body="Auth uses JWT.", lessons="[^1]: cap is 3, verified against source.\n")
    b = _note("b", ocd="2026-06-01", lmd="2026-06-09", body="Tokens expire in 30s.", lessons="[^1]: 30s timeout per config.\n")
    (scope / "a.md").write_text(a, encoding="utf-8")
    (scope / "b.md").write_text(b, encoding="utf-8")

    txn_id = _txn_id_from_begin(scope, "merge", "a.md", "b.md")
    staging = _staging(scope, txn_id)
    # Agent's editorial work, performed in staging: drop the two source copies and
    # write the merged survivor (lessons preserved, ocd=min, no dups).
    (staging / "a.md").unlink()
    (staging / "b.md").unlink()
    merged = _note("merged", ocd="2026-05-01", lmd="2026-06-18", body="Auth uses JWT. Tokens expire in 30s.", lessons=("[^1]: cap is 3, verified against source.\n[^2]: 30s timeout per config.\n"))
    (staging / "merged.md").write_text(merged, encoding="utf-8")

    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc == 0
    assert (scope / "merged.md").exists()
    assert not (scope / "a.md").exists() and not (scope / "b.md").exists()
    assert "Auth uses JWT. Tokens expire in 30s." in (scope / "merged.md").read_text(encoding="utf-8")
    assert not staging.exists()  # staging cleaned on commit
    assert not (MemoryTxn._staging_root(scope) / f"{txn_id}.json").exists()


def test_merge_refused_when_memory_md_still_points_at_the_retired_page(tmp_path):
    """issue #182 (CLI-wiring gap): `verify_merge`'s `memory_md_text` param is
    opt-in and `_verify_merge` never supplied it, so a merge that retired a page
    committed clean even while the harness's SECOND index (MEMORY.md) still
    pointed at the now-deleted file. Read the live MEMORY.md and refuse."""
    scope = tmp_path / "memory"
    scope.mkdir()
    a = _note("a", body="Auth uses JWT.")
    b = _note("b", body="Tokens expire in 30s.")
    (scope / "a.md").write_text(a, encoding="utf-8")
    (scope / "b.md").write_text(b, encoding="utf-8")
    (scope / "MEMORY.md").write_text(
        "# MEMORY\n\n- [B fact](b.md) — tokens expire.\n", encoding="utf-8",
    )

    txn_id = _txn_id_from_begin(scope, "merge", "a.md", "b.md")
    staging = _staging(scope, txn_id)
    (staging / "a.md").unlink()
    (staging / "b.md").unlink()
    merged = _note("merged", body="Auth uses JWT. Tokens expire in 30s.")
    (staging / "merged.md").write_text(merged, encoding="utf-8")

    rc, err = _run_err("commit", scope, txn_id, "--op", "merge")
    assert rc == 1
    assert "MEMORY.md" in err, err
    assert (scope / "a.md").exists() and (scope / "b.md").exists()  # untouched
    assert not (scope / "merged.md").exists()


def test_merge_commits_when_memory_md_was_already_redirected(tmp_path):
    """The green path: MEMORY.md was repointed by a PRIOR `--op repair` pass (the
    documented two-transaction holder sequence, merge-protocol.md), so its link
    already names the survivor — the merge commits clean."""
    scope = tmp_path / "memory"
    scope.mkdir()
    a = _note("a", body="Auth uses JWT.")
    b = _note("b", body="Tokens expire in 30s.")
    (scope / "a.md").write_text(a, encoding="utf-8")
    (scope / "b.md").write_text(b, encoding="utf-8")
    (scope / "MEMORY.md").write_text(
        "# MEMORY\n\n- [B fact](merged.md) — tokens expire.\n", encoding="utf-8",
    )

    txn_id = _txn_id_from_begin(scope, "merge", "a.md", "b.md")
    staging = _staging(scope, txn_id)
    (staging / "a.md").unlink()
    (staging / "b.md").unlink()
    merged = _note("merged", body="Auth uses JWT. Tokens expire in 30s.")
    (staging / "merged.md").write_text(merged, encoding="utf-8")

    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc == 0
    assert (scope / "merged.md").exists()


def test_merge_commits_when_memory_md_is_absent(tmp_path):
    """No MEMORY.md at all (a scope root without the harness index) must not be
    misread as a dangling pointer — absence stays silent, matching
    `verify_merge`'s opt-in contract."""
    scope = tmp_path / "memory"
    scope.mkdir()
    a = _note("a", body="Auth uses JWT.")
    b = _note("b", body="Tokens expire in 30s.")
    (scope / "a.md").write_text(a, encoding="utf-8")
    (scope / "b.md").write_text(b, encoding="utf-8")

    txn_id = _txn_id_from_begin(scope, "merge", "a.md", "b.md")
    staging = _staging(scope, txn_id)
    (staging / "a.md").unlink()
    (staging / "b.md").unlink()
    merged = _note("merged", body="Auth uses JWT. Tokens expire in 30s.")
    (staging / "merged.md").write_text(merged, encoding="utf-8")

    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc == 0
    assert (scope / "merged.md").exists()


def test_begin_edit_staging_commit_applies_repair(tmp_path):
    """A clean repair (TRDD-87935f21): begin copies a malformed page; the agent
    backfills the missing ocd/lmd/node_type/tier and adds the Notes section IN
    PLACE; commit reconstructs (1 write at the same path, 0 deletes) and applies."""
    scope = tmp_path / "memory"
    scope.mkdir()
    bad = '---\nname: foo\ndescription: "d"\nmetadata:\n  type: project\n---\n\nA fact.\n[^1]: the cap is 3.\n'
    (scope / "foo.md").write_text(bad, encoding="utf-8")

    txn_id = _txn_id_from_begin(scope, "repair", "foo.md")
    staging = _staging(scope, txn_id)
    (staging / "foo.md").write_text(
        _note("foo", ocd="2026-06-19", lmd="2026-06-19", body="A fact.", lessons="[^1]: the cap is 3.\n"),
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
    hub = f'---\nname: plat\ndescription: "d"\nocd: 2026-06-01\nlmd: 2026-06-01\nmetadata:\n  node_type: memory\n  type: project\n  tier: hub\n  globs: {glist}\n---\n\n## Frontend\nUI bits.\n## Backend\nServer bits.\n\n## Notes and lessons learned\n[^1]: the build flag is --release.\n'
    (scope / "plat.md").write_text(hub, encoding="utf-8")

    txn_id = _txn_id_from_begin(scope, "split", "plat.md")
    staging = _staging(scope, txn_id)

    def _page(name, globs, body, lessons=""):
        gl = "[" + ", ".join(f'"{g}"' for g in globs) + "]"
        return f'---\nname: {name}\ndescription: "d"\nocd: 2026-06-01\nlmd: 2026-06-18\nmetadata:\n  node_type: memory\n  type: project\n  tier: hub\n  globs: {gl}\n---\n\n{body}\n\n## Notes and lessons learned\n{lessons}\n'

    overview = _page("plat", ["src/a/**", "src/b/**"], "Overview: see [[plat-frontend]] and [[plat-backend]].")
    sub1 = _page("plat-frontend", ["src/a/**"], "UI bits.", lessons="[^1]: the build flag is --release.\n")
    sub2 = _page("plat-backend", ["src/b/**"], "Server bits.")
    (staging / "plat.md").write_text(overview, encoding="utf-8")  # overwrite source -> overview
    (staging / "plat-frontend.md").write_text(sub1, encoding="utf-8")  # new sub-page
    (staging / "plat-backend.md").write_text(sub2, encoding="utf-8")  # new sub-page

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
    a = _note("a", ocd="2026-05-01", lmd="2026-05-10", lessons="[^1]: cap is 3, verified against source.\n")
    b = _note("b", ocd="2026-06-01", lmd="2026-06-09", lessons="[^1]: 30s timeout per config.\n")
    (scope / "a.md").write_text(a, encoding="utf-8")
    (scope / "b.md").write_text(b, encoding="utf-8")

    txn_id = _txn_id_from_begin(scope, "merge", "a.md", "b.md")
    staging = _staging(scope, txn_id)
    (staging / "a.md").unlink()
    (staging / "b.md").unlink()
    # The merged page silently DROPS a's lesson — verify must catch it.
    bad = _note("merged", ocd="2026-05-01", lmd="2026-06-18", lessons="[^1]: 30s timeout per config.\n")
    (staging / "merged.md").write_text(bad, encoding="utf-8")

    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc == 1  # verify-fail exit code
    assert (scope / "a.md").read_text(encoding="utf-8") == a  # live tree untouched
    assert (scope / "b.md").read_text(encoding="utf-8") == b
    assert not (scope / "merged.md").exists()  # the merge did NOT apply
    assert not staging.exists()  # txn aborted, staging discarded
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
    txn.phase = "committing"  # the crash window: guard passed, swap not yet done
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


def test_cli_begin_owner_pid_survives_resume_from_a_live_process(tmp_path, monkeypatch):
    """TRDD-0A8FN3W3: `begin` run as a REAL subprocess (as an agent invokes it) exits
    immediately, so os.getpid() would record a pid that is already dead by the time
    anyone looks at the journal. A `resume_pending` run right after must NOT reclaim
    the fresh staging txn it just created."""
    import subprocess

    scope = tmp_path / "memory"
    scope.mkdir()
    (scope / "a.md").write_text(_note("a"), encoding="utf-8")

    env = dict(**{"JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gstate")})
    import os as _os
    full_env = {**_os.environ, **env}
    full_env.pop("CLAUDE_PLUGIN_OPTION_WIKIMEM_EDITOR_ENABLED", None)
    cli_path = _PROJECT_ROOT / "scripts" / "memory_txn_cli.py"
    proc = subprocess.run(
        [sys.executable, str(cli_path), "begin", str(scope), "merge", "a.md"],
        capture_output=True, text=True, env=full_env,
    )
    assert proc.returncode == 0, proc.stderr
    txn_id = next(ln.split("=", 1)[1] for ln in proc.stdout.splitlines() if ln.startswith("txn_id="))

    journal = MemoryTxn._staging_root(scope) / f"{txn_id}.json"
    reloaded = MemoryTxn._load(journal)
    assert reloaded.owner_pid == 0  # never a dead pid from the exited CLI process

    acted = memory_txn.resume_pending(scope, stale_seconds=99999)
    assert acted == []  # a live/fresh CLI-begun txn must survive a concurrent resume
    assert journal.exists()


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
    a = _note("a", ocd="2026-05-01", lmd="2026-05-10", body="Auth uses JWT.", lessons="[^1]: cap is 3, verified against source.\n")
    b = _note("b", ocd="2026-06-01", lmd="2026-06-09", body="Tokens expire in 30s.", lessons="[^1]: 30s timeout per config.\n")
    (scope / "a.md").write_text(a, encoding="utf-8")
    (scope / "b.md").write_text(b, encoding="utf-8")
    txn_id = _txn_id_from_begin(scope, "merge", "a.md", "b.md")
    staging = _staging(scope, txn_id)
    (staging / "b.md").unlink()
    (staging / "a.md").write_text(survivor_text, encoding="utf-8")
    return scope, txn_id


def test_merge_refuses_a_second_write_even_for_a_backlink_holder(tmp_path):
    """A backlink HOLDER cannot ride along in the merge transaction.

    The consolidate skill's reference doc claimed holder rewrites were "fine and expected" as
    additional writes. They never were — `len(writes) != 1` counts every staged write with no
    exemption — and a real CONSOLIDATE pass hit the refusal. Nothing exercised the path, so the
    doc and the code drifted unnoticed; this pins the behaviour so the doc can only be wrong
    loudly. (The doc now prescribes two transactions, holder-repair FIRST.)

    The one-write rule is deliberate, not a limitation: `verify_merge` proves knowledge
    preservation between the SOURCES and the SURVIVOR and says nothing about an unrelated holder
    edit, so admitting that write would let an UNVERIFIED edit ride inside a verified transaction.
    """
    scope, txn_id = _survivor_merge_txn(
        tmp_path,
        _note(
            "a",
            ocd="2026-05-01",
            lmd="2026-06-18",
            body="Auth uses JWT.\nTokens expire in 30s.",
            lessons="[^1]: cap is 3, verified against source.\n[^2]: 30s timeout per config.\n",
        ),
    )
    # A third page that links the retiring slug, edited IN THE SAME staging dir — the shape the
    # doc used to bless.
    (_staging(scope, txn_id) / "holder.md").write_text(
        _note("holder", ocd="2026-05-01", lmd="2026-06-18", body="See [[a]] for the details."),
        encoding="utf-8",
    )
    rc, err = _run_err("commit", scope, txn_id, "--op", "merge")
    assert rc != 0, "a merge carrying a holder write must be refused, not silently accepted"
    assert "exactly ONE surviving page" in err, f"…and refused by the WRITE-COUNT rule specifically, not incidentally: {err!r}"
    # And the live tree is untouched — a refused transaction changes nothing.
    assert (scope / "b.md").exists(), "the refused merge must not have applied its delete"
    assert not (scope / "holder.md").exists(), "nor written the holder into the live tree"


def test_merge_refusal_names_the_two_transaction_workaround(tmp_path):
    """Issue #145: the reference doc and this check used to disagree (the doc
    promised holder rewrites "ride along fine"; the code has always refused
    them), so every agent hitting the refusal had to re-derive the same
    two-transaction workaround from scratch. The refusal message now carries
    that guidance itself, so it can no longer drift out of sync with a
    reference doc the way the prose did.
    """
    scope, txn_id = _survivor_merge_txn(
        tmp_path,
        _note(
            "a", ocd="2026-05-01", lmd="2026-06-18",
            body="Auth uses JWT.\nTokens expire in 30s.",
            lessons="[^1]: cap is 3, verified against source.\n[^2]: 30s timeout per config.\n",
        ),
    )
    (_staging(scope, txn_id) / "holder.md").write_text(
        _note("holder", ocd="2026-05-01", lmd="2026-06-18", body="See [[a]] for the details."),
        encoding="utf-8",
    )
    rc, err = _run_err("commit", scope, txn_id, "--op", "merge")
    assert rc != 0
    assert "--op repair" in err, f"the refusal must name the holder-first workaround: {err!r}"
    assert "FIRST" in err, f"the ORDER (holder before merge) must be explicit: {err!r}"


def test_merge_into_survivor_dropping_survivors_lesson_fails(tmp_path):
    """The exact H-1 hole: the survivor keeps B's content but LOSES its own
    lesson + fact — the verifier must now refuse (it used to pass)."""
    bad = _note("a", ocd="2026-05-01", lmd="2026-06-18", body="Tokens expire in 30s.", lessons="[^1]: 30s timeout per config.\n")  # A's lesson + fact GONE
    scope, txn_id = _survivor_merge_txn(tmp_path, bad)
    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc != 0, "a merge that loses the survivor's own lesson must not commit"
    assert "cap is 3" in (scope / "a.md").read_text(encoding="utf-8")  # live tree intact
    assert (scope / "b.md").exists()


# M-2 regression (wikimem audit 2026-07-07): structural legality is enforced AT
# COMMIT TIME for merge and split — the agent-side pre-flight is convention, not
# enforcement. A txn begun with op "conflict" is the ONE sanctioned exemption
# (the conflict pass's loss-preserving pair-retirement is legal across tiers).


def _pair_merge_txn(tmp_path, *, begin_op: str, a_extra: dict, b_extra: dict):
    """Build a delete-both-write-merged merge shape with per-page tier/type
    overrides. The merged result preserves BOTH pages' facts + lessons and keeps
    ocd=min, so ONLY the legality gate can refuse it."""
    scope = tmp_path / "memory"
    scope.mkdir()
    a = _note("a", ocd="2026-05-01", lmd="2026-05-10", body="Auth uses JWT.", lessons="[^1]: cap is 3, verified against source.\n", **a_extra)
    b = _note("b", ocd="2026-06-01", lmd="2026-06-09", body="Tokens expire in 30s.", lessons="[^1]: 30s timeout per config.\n", **b_extra)
    (scope / "a.md").write_text(a, encoding="utf-8")
    (scope / "b.md").write_text(b, encoding="utf-8")
    txn_id = _txn_id_from_begin(scope, begin_op, "a.md", "b.md")
    staging = _staging(scope, txn_id)
    (staging / "a.md").unlink()
    (staging / "b.md").unlink()
    merged = _note("merged", ocd="2026-05-01", lmd="2026-06-18", tier=a_extra.get("tier", "component"), typ=a_extra.get("typ", "project"), body="Auth uses JWT.\n\nTokens expire in 30s.", lessons=("[^1]: cap is 3, verified against source.\n[^2]: 30s timeout per config.\n"))
    (staging / "merged.md").write_text(merged, encoding="utf-8")
    return scope, txn_id


def test_cross_type_merge_refused_at_commit(tmp_path):
    """A merge of a `project` page with a `reference` page must be refused by the
    commit gate even when it loses nothing — cross-type is structurally illegal."""
    scope, txn_id = _pair_merge_txn(tmp_path, begin_op="merge", a_extra={"typ": "project"}, b_extra={"typ": "reference"})
    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc == 1, "cross-type merge must fail commit-time legality"
    assert (scope / "a.md").exists() and (scope / "b.md").exists()  # live intact
    assert not (scope / "merged.md").exists()


def test_cross_tier_merge_refused_at_commit(tmp_path):
    """A merge of an `aspect` page with a `component` page must be refused by the
    commit gate — cross-tier is structurally illegal (never mix a radiating rule
    with a terminal element)."""
    scope, txn_id = _pair_merge_txn(tmp_path, begin_op="merge", a_extra={"tier": "aspect"}, b_extra={"tier": "component"})
    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc == 1
    assert (scope / "a.md").exists() and (scope / "b.md").exists()
    assert not (scope / "merged.md").exists()


def test_conflict_op_txn_exempt_from_merge_legality(tmp_path):
    """A txn begun with op `conflict` (the conflict pass's pair-retirement) rides
    `commit --op merge` across tiers WITHOUT the legality screen — the sanctioned
    exemption (conflict-protocol.md): the demoted fact survives as a lesson."""
    scope, txn_id = _pair_merge_txn(tmp_path, begin_op="conflict", a_extra={"tier": "aspect"}, b_extra={"tier": "component"})
    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc == 0, "the conflict pass's cross-tier pair-retirement must stay legal"
    assert (scope / "merged.md").exists()
    assert not (scope / "a.md").exists() and not (scope / "b.md").exists()


def test_component_split_refused_at_commit(tmp_path):
    """Splitting a `component` page is refused at commit — one element = one page;
    a component is never fragmented, no matter how well the sub-pages preserve it."""
    scope = tmp_path / "memory"
    scope.mkdir()
    comp = _note("comp", body="## First\nFact one.\n## Second\nFact two.", lessons="[^1]: the cap is 3.\n")
    (scope / "comp.md").write_text(comp, encoding="utf-8")
    txn_id = _txn_id_from_begin(scope, "split", "comp.md")
    staging = _staging(scope, txn_id)
    (staging / "comp.md").write_text(_note("comp", lmd="2026-06-18", body="Overview: see [[comp-first]] and [[comp-second]]."), encoding="utf-8")
    (staging / "comp-first.md").write_text(_note("comp-first", body="## First\nFact one.", lessons="[^1]: the cap is 3.\n"), encoding="utf-8")
    (staging / "comp-second.md").write_text(_note("comp-second", body="## Second\nFact two."), encoding="utf-8")

    rc = _run("commit", scope, txn_id, "--op", "split")
    assert rc == 1, "a component split must fail commit-time legality"
    assert (scope / "comp.md").read_text(encoding="utf-8") == comp  # live intact
    assert not (scope / "comp-first.md").exists()


def test_merge_into_survivor_preserving_everything_commits(tmp_path):
    """The correct merge-into-survivor: both pages' lessons + facts survive and
    the survivor keeps its own OLDER ocd — must pass (the pre-fix gate perversely
    REJECTED the older ocd because it only saw the deleted page's sources)."""
    good = _note("a", ocd="2026-05-01", lmd="2026-06-18", body="Auth uses JWT. Tokens expire in 30s.", lessons=("[^1]: cap is 3, verified against source.\n[^2]: 30s timeout per config.\n"))
    scope, txn_id = _survivor_merge_txn(tmp_path, good)
    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc == 0
    merged = (scope / "a.md").read_text(encoding="utf-8")
    assert "cap is 3" in merged and "30s timeout" in merged
    assert not (scope / "b.md").exists()


# --------------------------------------------------------------------------- #
# F2 (audit 2026-07-13) — a CONFLICT verdict must be COMMITTABLE
# --------------------------------------------------------------------------- #


def test_conflict_demote_verdict_commits(tmp_path):
    """END-TO-END F2: the conflict pass's DEMOTE verdict — retire the obsolete page, keep
    the survivor's body at the CURRENT truth, demote the superseded claim to a `[^N]`
    lesson — must COMMIT. Before the fix, the body-fact oracle demanded the retired page's
    (deliberately superseded, deliberately reworded) claim still appear verbatim in the
    survivor's body, so BOTH conflict verdicts were structurally un-committable and every
    cadence threw its whole adversarial fan-out away at this gate."""
    scope = tmp_path / "memory"
    scope.mkdir()
    obsolete = _note("obsolete", ocd="2026-05-01", lmd="2026-05-02", body="The rotator retries a failed refresh up to five times before failing over.")
    current = _note("current", ocd="2026-04-01", lmd="2026-06-01", body="The rotator retries a failed refresh three times before failing over.")
    (scope / "obsolete.md").write_text(obsolete, encoding="utf-8")
    (scope / "current.md").write_text(current, encoding="utf-8")

    txn_id = _txn_id_from_begin(scope, "conflict", "obsolete.md", "current.md")
    staging = _staging(scope, txn_id)
    (staging / "obsolete.md").unlink()  # retire the obsolete page
    resolved = _note(
        "current",
        ocd="2026-04-01",
        lmd="2026-07-13",
        body="The rotator retries a failed refresh three times before failing over.",
        lessons="[^1]: DO NOT assert the rotator retries 5x, as page obsolete did, BECAUSE 8f960ed capped it at 3. DO use 3 instead.\n",
    )
    (staging / "current.md").write_text(resolved, encoding="utf-8")

    rc = _run("commit", scope, txn_id, "--op", "merge")  # conflict commits AS a merge
    assert rc == 0
    assert not (scope / "obsolete.md").exists()  # the contradiction is gone
    live = (scope / "current.md").read_text(encoding="utf-8")
    assert "three times" in live
    assert "DO NOT assert the rotator retries 5x" in live  # the WHY survives as a lesson


def test_conflict_verdict_that_corrupts_the_survivor_is_still_refused(tmp_path):
    """F2's narrowing is not a blanket exemption: a conflict that drops the SURVIVOR's own
    body fact is refused and the live tree is untouched."""
    scope = tmp_path / "memory"
    scope.mkdir()
    obsolete = _note("obsolete", body="The rotator retries a failed refresh up to five times.")
    current = _note("current", body="The rotator signs every refresh with the stored session key.")
    (scope / "obsolete.md").write_text(obsolete, encoding="utf-8")
    (scope / "current.md").write_text(current, encoding="utf-8")

    txn_id = _txn_id_from_begin(scope, "conflict", "obsolete.md", "current.md")
    staging = _staging(scope, txn_id)
    (staging / "obsolete.md").unlink()
    (staging / "current.md").write_text(
        _note(
            "current",
            body="The rotator refreshes tokens.",  # the survivor's own fact: GONE
            lessons="[^1]: DO NOT assert 5x, BECAUSE it is 3. DO use 3 instead.\n",
        ),
        encoding="utf-8",
    )

    rc = _run("commit", scope, txn_id, "--op", "merge")
    assert rc != 0
    assert (scope / "obsolete.md").exists()  # nothing applied
    assert "session key" in (scope / "current.md").read_text(encoding="utf-8")


# ─────────────── authoring-integrity DELTA gate (TRDD-4ZTNMQL3) ───────────────


def test_authoring_gate_blocks_a_newly_introduced_body_less_lesson(tmp_path):
    """A hand-edit that INTRODUCES a body-less lesson must be refused by the delta gate."""
    import shutil
    import types

    if shutil.which("memgrep") is None:
        pytest.skip("memgrep not installed")
    scope = tmp_path / "scope"
    scope.mkdir()
    rel = "n.md"
    good = '---\nname: n\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: "d"\n---\nbody.[^1]\n\n## Notes and lessons learned\n[^1]: a real lesson body.\n'
    (scope / rel).write_text(good, encoding="utf-8")
    bad = '---\nname: n\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: "d"\n---\nbody.[^1]\n\n## Notes and lessons learned\n[^1]: [id:ATOM-AAAA-BBBB, status:valid, keywords:"k", ocd:2026-01-01, lmd:2026-01-01]\n'
    # A real MemoryTxn needs a live transaction; _authoring_gate only reads .scope_root,
    # so a minimal stand-in is cast to the real type rather than built end-to-end.
    fake_txn = cast(MemoryTxn, types.SimpleNamespace(scope_root=scope))
    ok, reasons, _ = cli._authoring_gate(fake_txn, {rel: bad})
    assert not ok
    assert any("empty-lesson-body" in r for r in reasons), reasons


def test_authoring_gate_ignores_a_preexisting_violation_carried_forward(tmp_path):
    """A pre-existing body-less lesson the edit does NOT touch must not block (delta = 0)."""
    import shutil
    import types

    if shutil.which("memgrep") is None:
        pytest.skip("memgrep not installed")
    scope = tmp_path / "scope"
    scope.mkdir()
    rel = "n.md"
    bad = '---\nname: n\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: "d"\n---\nbody.[^1]\n\n## Notes and lessons learned\n[^1]: [id:ATOM-AAAA-BBBB, status:valid, keywords:"k", ocd:2026-01-01, lmd:2026-01-01]\n'
    (scope / rel).write_text(bad, encoding="utf-8")
    after = bad.replace("body.[^1]", "body edited.[^1]")  # same pre-existing bad lesson; count unchanged
    fake_txn = cast(MemoryTxn, types.SimpleNamespace(scope_root=scope))
    ok, reasons, _ = cli._authoring_gate(fake_txn, {rel: after})
    assert ok, reasons  # delta is 0 → not blocked
