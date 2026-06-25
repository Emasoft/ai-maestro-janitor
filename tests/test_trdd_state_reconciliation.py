"""Integration tests for the trdd-state-reconciliation detector (TRDD-15ECPBSA).

Real I/O, no mocks: each case builds a temp GIT repo (so `git tag --contains`
is real), writes fixture TRDDs under design/tasks/, commits them with a
`TRDD-<id>` subject (the commit-discipline path the keystone relies on), tags a
release, and runs the detector as a SUBPROCESS with CLAUDE_PROJECT_DIR pointed
at it. The pure check LOGIC is covered exhaustively in test_trdd_common.py with
a fake tag map; here we prove the detector wires the git seams + report +
surface-only contract correctly end-to-end.

Load-bearing cases:
  * shipped-and-clean → 'closeable-candidate' in the drift line + report.
  * shipped-but-BLOCKED → 'partially-shipped-review', NOT 'closeable' (the exact
    over-claim the detector exists to prevent).
  * genuinely-in-progress-unshipped → NOTHING fires.
  * surface-only → every fixture TRDD's `column:` is byte-identical after a run.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

DETECTOR = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "detectors"
    / "trdd-state-reconciliation.py"
)

_TS = "20260101_000000+0000"


def _git(args: list[str], cwd: Path) -> None:
    env = dict(os.environ)
    env["GIT_AUTHOR_NAME"] = "T"
    env["GIT_AUTHOR_EMAIL"] = "t@example.com"
    env["GIT_COMMITTER_NAME"] = "T"
    env["GIT_COMMITTER_EMAIL"] = "t@example.com"
    subprocess.run(["git", *args], cwd=str(cwd), env=env, check=True,
                   capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    (root / "design" / "tasks").mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], root)


def _trdd_path(root: Path, uid: str) -> Path:
    return root / "design" / "tasks" / f"TRDD-{_TS}-{uid}-slug.md"


def _write_trdd(
    root: Path,
    uid: str,
    *,
    column: str,
    blocked_by: str = "[]",
    impl: str = "[]",
    body: str = "\n# body\nx\n",
) -> Path:
    text = textwrap.dedent(
        f"""\
        ---
        trdd-id: {uid}
        title: T
        column: {column}
        blocked-by: {blocked_by}
        implementation-commits: {impl}
        ---
        """
    ) + body
    p = _trdd_path(root, uid)
    p.write_text(text)
    return p


def _commit_all(root: Path, subject: str) -> str:
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", subject], root)
    res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root),
                         capture_output=True, text=True, check=True)
    return res.stdout.strip()


def _tag(root: Path, tag: str) -> None:
    _git(["tag", tag], root)


def _run(root: Path, session: str = "sess") -> str:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    env["CLAUDE_SESSION_ID"] = session
    # The temp project isn't an ai-maestro-plugins member; force the context gate
    # ON (the gate itself is tested separately, below).
    env["JANITOR_FORCE_AI_MAESTRO"] = "1"
    for k in ("CLAUDE_PLUGIN_OPTION_TRDD_PATH",):
        env.pop(k, None)
    res = subprocess.run(
        [sys.executable, str(DETECTOR)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert res.returncode == 0, res.stderr
    return res.stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    _init_repo(root)
    return root


# ── keystone: shipped-and-clean → closeable ──────────────────────────────────


def test_shipped_and_clean_is_closeable_candidate(repo: Path):
    """A non-terminal TRDD whose `TRDD-<id>`-subject commit is in a released tag,
    with NO remaining work, surfaces as a closeable-candidate."""
    uid = "aaaaaaaa"
    _write_trdd(repo, uid, column="dev", body="\n# body\nall shipped.\n")
    _commit_all(repo, f"feat: ship it (TRDD-{uid})")
    _tag(repo, "v0.1.0")

    out = _run(repo)
    assert "[trdd-state-reconciliation]" in out
    assert f"TRDD-{uid}" in out
    assert "closeable-candidate" in out
    assert "partially-shipped-review" not in out


def test_shipped_via_implementation_commits_field(repo: Path):
    """The keystone also resolves commits from the `implementation-commits:`
    frontmatter, not only the subject grep."""
    uid = "bbbbbbbb"
    # First commit lands the TRDD with a NEUTRAL subject (no TRDD ref), then we
    # record its SHA into implementation-commits and amend the file.
    _write_trdd(repo, uid, column="dev")
    sha = _commit_all(repo, "chore: unrelated subject")
    _write_trdd(repo, uid, column="dev", impl=f"[{sha}]", body="\n# body\nall shipped.\n")
    _commit_all(repo, "chore: record impl commit")
    _tag(repo, "v0.2.0")

    out = _run(repo)
    assert f"TRDD-{uid}" in out
    assert "closeable-candidate" in out


# ── the load-bearing regression: shipped-but-blocked → review, NOT closeable ──


def test_shipped_but_blocked_is_review_not_closeable(repo: Path):
    """THE regression: a TRDD whose commits SHIPPED but whose column is `blocked`
    (remaining in-scope work) must surface as partially-shipped-review, NEVER as
    closeable-candidate. This is the exact 3b9b2040 over-claim the detector
    prevents."""
    uid = "cccccccc"
    _write_trdd(repo, uid, column="blocked",
                body="\n## STATE\npublish BLOCKED on GROUP B\n")
    _commit_all(repo, f"feat: most of it (TRDD-{uid})")
    _tag(repo, "v0.3.0")

    out = _run(repo)
    assert f"TRDD-{uid}" in out
    assert "partially-shipped-review" in out
    assert "closeable-candidate" not in out


# ── no false positives ───────────────────────────────────────────────────────


def test_genuinely_unshipped_in_progress_fires_nothing(repo: Path):
    """A genuinely in-progress TRDD whose commit is NOT in any release tag, with
    frontmatter & prose in agreement and no stale blocker, fires nothing."""
    uid = "dddddddd"
    _write_trdd(repo, uid, column="dev", body="\n# body\nstill working.\n")
    _commit_all(repo, f"wip: in progress (TRDD-{uid})")
    # NO tag created → the commit is in no release.

    out = _run(repo)
    assert out.strip() == ""


def test_terminal_trdd_never_flagged(repo: Path):
    """A published TRDD whose commits are in a tag is already closed — silent."""
    uid = "eeeeeeee"
    _write_trdd(repo, uid, column="published")
    _commit_all(repo, f"feat: shipped + closed (TRDD-{uid})")
    _tag(repo, "v0.4.0")

    out = _run(repo)
    assert out.strip() == ""


# ── surface-only safety contract ─────────────────────────────────────────────


def test_surface_only_mutates_zero_trdd_files(repo: Path):
    """After a run on a fixture board, EVERY TRDD file is byte-identical — the
    detector mutated nothing (it only writes its own report + a drift line)."""
    closeable = _write_trdd(repo, "aaaaaaaa", column="dev", body="\n# body\nshipped.\n")
    blocked = _write_trdd(repo, "cccccccc", column="blocked",
                          body="\n## STATE\nBLOCKED on X\n")
    unshipped = _write_trdd(repo, "dddddddd", column="dev", body="\n# body\nwip.\n")
    _commit_all(repo, "feat: board (TRDD-aaaaaaaa) (TRDD-cccccccc) (TRDD-dddddddd)")
    _tag(repo, "v0.5.0")

    before = {p: p.read_bytes() for p in (closeable, blocked, unshipped)}
    out = _run(repo)
    # Something fired (so we know the detector actually ran its checks)...
    assert "[trdd-state-reconciliation]" in out
    # ...but every TRDD file is unchanged.
    for p, content in before.items():
        assert p.read_bytes() == content, f"{p.name} was mutated — must be surface-only"


def test_writes_a_candidate_report(repo: Path):
    """A run with at least one candidate writes a board report under
    reports/trdd-reconciliation/ naming the flagged TRDD + its verdict."""
    uid = "aaaaaaaa"
    _write_trdd(repo, uid, column="dev", body="\n# body\nshipped.\n")
    _commit_all(repo, f"feat: ship (TRDD-{uid})")
    _tag(repo, "v0.6.0")

    _run(repo)
    report_dir = repo / "reports" / "trdd-reconciliation"
    reports = list(report_dir.glob("*-board.md"))
    assert reports, "a candidate report must be written"
    text = reports[0].read_text()
    assert f"TRDD-{uid}" in text
    assert "closeable-candidate" in text
    assert "SURFACE-ONLY" in text


# ── dedupe + check 3 + check 4 + context gate ────────────────────────────────


def test_seen_file_dedupe_no_renag_same_verdict(repo: Path):
    """A second run with the SAME board (same verdicts) is silent — the
    per-(TRDD,verdict) seen-file suppresses the re-nag."""
    uid = "aaaaaaaa"
    _write_trdd(repo, uid, column="dev", body="\n# body\nshipped.\n")
    _commit_all(repo, f"feat: ship (TRDD-{uid})")
    _tag(repo, "v0.7.0")

    first = _run(repo)
    assert f"TRDD-{uid}" in first
    second = _run(repo)
    assert second.strip() == "", "same verdict must not re-nag"


def test_prose_frontmatter_mismatch_surfaces(repo: Path):
    """Check 3: STATE prose says blocked but frontmatter column != blocked &
    blocked-by: [] — surfaces even with nothing shipped (no tag)."""
    uid = "ffffffff"
    _write_trdd(repo, uid, column="dev", blocked_by="[]",
                body="\n## STATE\nwe are BLOCKED on the upstream API\n")
    _commit_all(repo, f"wip (TRDD-{uid})")  # no tag → nothing shipped

    out = _run(repo)
    assert f"TRDD-{uid}" in out
    assert "prose-frontmatter-mismatch" in out


def test_stale_blocker_surfaces(repo: Path):
    """Check 4: a `blocked` TRDD whose blocker is now `published` surfaces as a
    stale-blocker candidate (re-evaluate / unblock)."""
    blocker = "11111111"
    dependent = "22222222"
    _write_trdd(repo, blocker, column="published")
    _write_trdd(repo, dependent, column="blocked", blocked_by=f"[TRDD-{blocker}]")
    _commit_all(repo, "feat: board")  # no tag needed — Check 4 is column-based

    out = _run(repo)
    assert f"TRDD-{dependent}" in out
    assert "stale-blocker" in out


def test_context_gate_off_outside_ai_maestro(repo: Path):
    """Without JANITOR_FORCE_AI_MAESTRO, the detector self-deactivates in a
    non-ai-maestro project (the TRDD-db169d9e gate)."""
    uid = "aaaaaaaa"
    _write_trdd(repo, uid, column="dev", body="\n# body\nshipped.\n")
    _commit_all(repo, f"feat: ship (TRDD-{uid})")
    _tag(repo, "v0.8.0")

    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    env.pop("JANITOR_FORCE_AI_MAESTRO", None)
    res = subprocess.run(
        [sys.executable, str(DETECTOR)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "", "gate OFF → silent outside ai-maestro"
