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


def _commit_all(root: Path, subject: str, *, spec_only: bool = False) -> str:
    # By default a fixture commit represents REAL IMPLEMENTATION, so it must
    # touch code — the detector excludes commits that touch ONLY design/tasks/
    # from the shipped check (TRDD-7C787DUS), since a TRDD's own `docs: add`
    # spec commit is authoring, not implementation. `spec_only=True` opts OUT
    # (used to test that a spec-only authoring commit does NOT read as shipped).
    # Content varies by subject so every implementation commit makes a real diff.
    if not spec_only:
        (root / "scripts").mkdir(exist_ok=True)
        (root / "scripts" / "impl.py").write_text(f"# {subject}\n", encoding="utf-8")
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


def test_spec_only_authoring_commit_does_not_read_as_shipped(repo: Path):
    """TRDD-7C787DUS regression: a backburner TRDD whose ONLY `TRDD-<id>`-subject
    commit touches just its own spec under design/tasks/ (its `docs: add` authoring
    commit) must NOT read as shipped — even in a released tag. A genuinely-shipped
    sibling (a real code commit) proves the detector ran and emitted."""
    real = "11111111"
    spec = "22222222"
    # genuine implementation — touches code (default), in the tag → shipped.
    _write_trdd(repo, real, column="dev", body="\n# body\nall shipped.\n")
    _commit_all(repo, f"feat: real code (TRDD-{real})")
    # backburner design doc — its ONLY commit touches only its own spec.
    _write_trdd(repo, spec, column="backburner", body="\n# body\nplan only, no code.\n")
    _commit_all(repo, f"docs: add TRDD-{spec} -- spec only", spec_only=True)
    _tag(repo, "v0.9.0")

    out = _run(repo)
    assert f"TRDD-{real}" in out            # genuine implementation surfaces
    assert "closeable-candidate" in out
    assert f"TRDD-{spec}" not in out        # spec-only authoring commit excluded


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


# ── Check 5 — STATE block cites a symbol the tree no longer has (TRDD-FDV1RQEB) ──
#
# Real git end-to-end (the pure predicate itself is exhaustively covered in
# test_trdd_common.py with a fake `token_is_dead`): a symbol that existed in
# `scripts/` history but was DELETED before the current HEAD must surface
# through the findings ledger, at HIGH severity when cited in the NEXT-ACTION
# paragraph, at LOW elsewhere.


def _write_and_delete_symbol(repo: Path, name: str) -> None:
    """Commit `scripts/impl.py` DEFINING `name`, then a second commit REMOVING it —
    the exact 'existed once, gone at HEAD' shape Check 5's history condition needs.
    """
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / "state_check5.py").write_text(f"def {name}():\n    pass\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", f"feat: add {name}"], repo)
    (scripts_dir / "state_check5.py").write_text("# removed\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", f"refactor: delete {name}"], repo)


def test_dead_symbol_in_next_action_is_high_severity(repo: Path):
    """A STATE block whose NEXT ACTION cites a symbol `git log -S` proves was
    deleted must surface as a HIGH-severity finding through the findings ledger."""
    uid = "12121212"
    _write_and_delete_symbol(repo, "should_emit_renew")
    _write_trdd(
        repo,
        uid,
        column="dev",
        body=(
            "\n## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-08-12\n\n"
            "Progress so far.\n\n"
            "NEXT ACTION: raise `should_emit_renew`'s threshold once measured.\n"
        ),
    )
    _commit_all(repo, f"wip (TRDD-{uid})")

    out = _run(repo)
    assert "TRDD-DEAD-SYMBOL" in out
    assert "HIGH" in out
    assert "should_emit_renew" in out
    assert f"TRDD-{uid}" in out


def test_dead_symbol_outside_next_action_is_low_severity(repo: Path):
    """The same dead symbol cited OUTSIDE the NEXT-ACTION paragraph is LOW
    severity — it misleads a reader but does not block the card."""
    uid = "13131313"
    _write_and_delete_symbol(repo, "resolve_ttl_minutes")
    _write_trdd(
        repo,
        uid,
        column="dev",
        body=(
            "\n## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-08-12\n\n"
            "Historical note: like `resolve_ttl_minutes` used to do.\n\n"
            "NEXT ACTION: write the missing unit test.\n"
        ),
    )
    _commit_all(repo, f"wip (TRDD-{uid})")

    out = _run(repo)
    assert "TRDD-DEAD-SYMBOL" in out
    assert "LOW" in out
    assert "resolve_ttl_minutes" in out


def test_symbol_still_at_head_is_not_flagged(repo: Path):
    """A symbol that is STILL present in scripts/ at HEAD must never be flagged —
    citing live code in a STATE block is normal, not drift."""
    uid = "14141414"
    (repo / "scripts").mkdir(exist_ok=True)
    (repo / "scripts" / "state_check5.py").write_text("def still_here_symbol():\n    pass\n",
                                                     encoding="utf-8")
    _write_trdd(
        repo,
        uid,
        column="dev",
        body=(
            "\n## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-08-12\n\n"
            "NEXT ACTION: extend `still_here_symbol` with a new branch.\n"
        ),
    )
    _commit_all(repo, f"wip (TRDD-{uid})")

    out = _run(repo)
    assert "TRDD-DEAD-SYMBOL" not in out


# ── the two probes form ONE predicate: they must agree on corpus + matching ───
# Both cases below FAILED before 2026-08-12: the HEAD probe used `git grep -w`
# over `scripts`+`tests` while the history probe used a substring `git log -S`
# over `scripts` alone. Each spelling was defensible on its own, which is why the
# asymmetry survived review — it only ever showed up as inexplicable findings.


def test_symbol_surviving_only_as_a_suffix_is_not_flagged(repo: Path):
    """A knob cited in prose by its unprefixed name, while the code holds the
    prefixed spelling, is ALIVE — flagging it is a false alarm.

    `_` is a word character, so a word-bounded HEAD probe can never match
    `FLEET_…` inside `CLAUDE_PLUGIN_OPTION_FLEET_…` — yet the substring history
    probe finds it, so the pair reported 'existed once, gone now' for a symbol
    that never went anywhere. Real instance: TRDD-G4BCRUP7, 2026-08-12."""
    uid = "15151515"
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    # History carries the BARE token, so `git log -S` says "existed once" — this
    # is what makes the test sharp: only the HEAD probe can save us here.
    (scripts_dir / "knobs.py").write_text('FLEET_AWAITING_ESC_IDLE_S = 5\n', encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "feat: add the knob"], repo)
    # ...then it is RENAMED to the prefixed spelling — still live, new name.
    (scripts_dir / "knobs.py").write_text(
        'CLAUDE_PLUGIN_OPTION_FLEET_AWAITING_ESC_IDLE_S = 5\n', encoding="utf-8"
    )
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "refactor: prefix the knob"], repo)

    _write_trdd(
        repo,
        uid,
        column="dev",
        body=(
            "\n## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-08-12\n\n"
            "NEXT ACTION: raise `FLEET_AWAITING_ESC_IDLE_S` once measured.\n"
        ),
    )
    _commit_all(repo, f"wip (TRDD-{uid})")

    out = _run(repo)
    assert "TRDD-DEAD-SYMBOL" not in out


def test_dead_symbol_quoted_in_a_test_fixture_is_still_flagged(repo: Path):
    """A symbol deleted from `scripts/` stays DEAD even though a fixture in
    `tests/` quotes it — a fixture is evidence of the bug, never evidence the
    symbol lives.

    With `tests/` inside the searched corpus this check went blind to exactly the
    symbols it was built to catch: its own fixtures name them, so the proof that
    it works was what stopped it working."""
    uid = "16161616"
    _write_and_delete_symbol(repo, "masked_by_fixture")
    tests_dir = repo / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_fixture.py").write_text(
        'STATE_BLOCK = "NEXT ACTION: raise `masked_by_fixture` threshold."\n', encoding="utf-8"
    )
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "test: pin the dead-symbol check"], repo)

    _write_trdd(
        repo,
        uid,
        column="dev",
        body=(
            "\n## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-08-12\n\n"
            "NEXT ACTION: raise `masked_by_fixture` once measured.\n"
        ),
    )
    _commit_all(repo, f"wip (TRDD-{uid})")

    out = _run(repo)
    assert "TRDD-DEAD-SYMBOL" in out
    assert "masked_by_fixture" in out


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


# ── issue #65: three remaining false-positive classes ────────────────────────
#
# The advisory observed on the core plugin flagged 4 verified false positives.
# The design-doc-commit class (a TRDD's own `docs: add` authoring commit read as
# shipped) was fixed in v0.24.10 (`_commit_touches_impl`); the cases below cover
# the two REMAINING classes: (a) terminal-column TRDDs flagged at all, and (b)
# a code-tag / script-name / embedded-id token mis-read as a current block or as
# a shipping commit attribution.


def test_terminal_column_with_blocked_prose_and_shipped_commit_never_flagged(repo: Path):
    """issue #65 class (a): a TERMINAL TRDD (`published`/`complete`) is done — its
    body is frozen by the TRDD rules and it is NEVER a reconciliation candidate,
    even when its STATE prose mentions a (historical) block AND a real shipping
    commit referencing it is in a released tag. TRDD-90c8ad35 / TRDD-fabb5c42
    (published) and TRDD-P83T33EN (complete) were all flagged as
    prose-frontmatter-mismatch; a terminal TRDD must surface nothing. A genuinely
    open, shipped sibling proves the detector still ran and emitted."""
    published = "90c8ad35"
    complete = "p83t33en"
    open_uid = "aaaaaaaa"
    # Terminal TRDDs whose STATE prose carries past-tense "blocked" narrative.
    _write_trdd(repo, published, column="published",
                body="\n## STATE\nColumn -> blocked (ai-maestro#36); now shipped.\n")
    _write_trdd(repo, complete, column="complete",
                body="\n## STATE\nThe work-loop reports done/blocked status.\n")
    # An OPEN, shipped, clean sibling so the run isn't trivially empty.
    _write_trdd(repo, open_uid, column="dev", body="\n# body\nall shipped.\n")
    _commit_all(repo, f"feat: real ship (TRDD-{open_uid}) "
                      f"(TRDD-{published}) (TRDD-{complete})")
    _tag(repo, "v0.10.0")

    out = _run(repo)
    assert f"TRDD-{open_uid}" in out          # the open sibling surfaces
    assert "closeable-candidate" in out
    assert f"TRDD-{published}" not in out      # terminal → never flagged
    assert f"TRDD-{complete}" not in out


def test_prose_block_inside_code_tag_or_script_name_not_flagged(repo: Path):
    """issue #65 class (b), prose half: on a NON-terminal TRDD the
    `prose-frontmatter-mismatch` check must not fire merely because 'block'
    appears INSIDE a code-tag (`DECOUPLE-BLOCKED`), a script/file name
    (`amp-task-blocked.sh`), or a slashed token (`done/blocked`). Those are code
    identifiers, not a current-state declaration. A sibling whose prose carries a
    genuine 'BLOCKED on X' declaration proves the check still fires on real
    blocks."""
    code_uid = "bbbbbbbb"
    real_uid = "cccccccc"
    _write_trdd(
        repo, code_uid, column="dev", blocked_by="[]",
        body=(
            "\n## STATE\n"
            "The DECOUPLE-BLOCKED code-tag is referenced; runs "
            "amp-task-blocked.sh which reports done/blocked status. "
            "Nothing is actually blocked-by anything.\n"
        ),
    )
    # Genuine current-state block declaration in plain prose.
    _write_trdd(repo, real_uid, column="dev", blocked_by="[]",
                body="\n## STATE\npublish is BLOCKED on GROUP B\n")
    _commit_all(repo, "feat: board")  # no tag — Check 3 is prose-based, not git

    out = _run(repo)
    # the genuine block surfaces...
    assert f"TRDD-{real_uid}" in out
    assert "prose-frontmatter-mismatch" in out
    # ...but the code-token-only TRDD does NOT.
    assert f"TRDD-{code_uid}" not in out


def test_commit_subject_embedded_id_token_not_attributed_as_shipped(repo: Path):
    """issue #65 class (b), commit half: the commit-subject→uid resolution must
    require the canonical `TRDD-<id8>` / `#<id8>` CITATION shape, not a bare
    8-char run that collides with a code identifier or filename. A never-shipped
    TRDD whose id only appears glued inside a code token (`fix_TRDD-<id>_path`,
    `<id>.bak`) in a released-tag commit must NOT read as shipped. A sibling with
    a real `(TRDD-<id>)` citation proves canonical citations are still attributed."""
    embedded_uid = "a1b2c3d4"
    cited_uid = "e5f6a7b8"
    # Both TRDDs are non-terminal with no implementation-commits of their own.
    _write_trdd(repo, embedded_uid, column="dev", body="\n# body\nnot yet shipped.\n")
    _write_trdd(repo, cited_uid, column="dev", body="\n# body\nshipped.\n")
    # ONE real code commit whose subject mentions the embedded uid ONLY inside a
    # code identifier / filename (no canonical citation), and the cited uid as a
    # proper parenthesized citation.
    _commit_all(
        repo,
        f"refactor: rename fix_TRDD-{embedded_uid}_path, dump to "
        f"trdd-{embedded_uid}.bak (TRDD-{cited_uid})",
    )
    _tag(repo, "v0.11.0")

    out = _run(repo)
    assert f"TRDD-{cited_uid}" in out          # real citation → attributed → shipped
    assert "closeable-candidate" in out
    assert f"TRDD-{embedded_uid}" not in out    # embedded-in-code token → not attributed


def test_casual_hash_citation_in_commit_subject_is_attributed(repo: Path):
    """issue #65 class (b) guard: the canonical-citation tightening must KEEP the
    casual `#<id8>` commit-subject citation shape (a documented TRDD reference
    form), not only `TRDD-<id8>`. A TRDD whose shipping commit cites it as
    `#<id8>` in a released tag surfaces as a closeable-candidate."""
    uid = "d4c3b2a1"
    _write_trdd(repo, uid, column="dev", body="\n# body\nall shipped.\n")
    _commit_all(repo, f"feat: ship the thing for #{uid} fully")
    _tag(repo, "v0.12.0")

    out = _run(repo)
    assert f"TRDD-{uid}" in out
    assert "closeable-candidate" in out


# --- janitor#255: the deadness predicate was "substring appeared in a diff" --------


def _sym_in_history():
    """The detector's real predicate, loaded the way the module does."""
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "trdd-state-reconciliation.py"
    spec = importlib.util.spec_from_file_location("tsr_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ordinary_words_are_not_symbols(tmp_path):
    """The reported failure: `queue` (another system's AMP verb) and `modified` (a memory
    frontmatter field) were both flagged as deleted symbols, because `git log -S` matches a
    substring anywhere in any changed line. Governance TRDDs quote other systems' vocabulary
    constantly, so the check fired hardest on the cards it understands least."""
    mod = _sym_in_history()
    root = Path(__file__).resolve().parent.parent
    for word in ("queue", "modified", "context", "result", "data", "value"):
        assert not mod._symbol_in_history(word, root), f"{word!r} is prose, not a symbol"


def test_real_deleted_symbols_are_still_found(tmp_path):
    """The fix must not buy a zero FP rate by making the check never fire — the failure mode
    this repo keeps hitting. These are real definitions in this repo's own history."""
    mod = _sym_in_history()
    root = Path(__file__).resolve().parent.parent
    for sym in ("_phase_self_budget", "_symbol_in_history", "emit_once"):
        assert mod._symbol_in_history(sym, root), f"{sym!r} was defined here and must be found"


def test_the_regex_uses_no_construct_git_silently_ignores():
    """`\\b` and `\\s` are unsupported in git's POSIX ERE: they match NOTHING and exit 0, so a
    regex using them makes the check silently dead rather than loudly broken. Pinned because
    that is invisible in every test that only asserts 'no findings'."""
    mod = _sym_in_history()
    assert "\\b" not in mod._DEFINITION_RE
    assert "\\s" not in mod._DEFINITION_RE
