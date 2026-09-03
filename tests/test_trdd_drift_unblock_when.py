"""`unblock-when:` — machine-checkable wait conditions that clear `column: blocked` on their
own (TRDD-RTRS704K / janitor#288 / ai-maestro TRDD-2UPK4XZG).

One test per predicate kind (`trdd:`, `issue:`, `file:`, `log:`, `date:`, `decision:`), plus
the two load-bearing guardrails: a malformed predicate must NEVER auto-unblock (fail OPEN
toward "stay blocked" — the inverse of `review_after_epoch`'s stance), and `decision:` is the
one kind that never auto-clears no matter how it's phrased.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

_DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "trdd-drift.py"


@pytest.fixture()
def drift():
    spec = importlib.util.spec_from_file_location("trdd_drift_under_test_unblock", _DETECTOR)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _eval(drift, predicates, **kw):
    defaults = dict(
        column_by_uid={},
        project_repo_slug="Emasoft/ai-maestro-janitor",
        open_issue_numbers=set(),
        project_root=Path("/tmp/does-not-matter"),
        now=int(time.time()),
    )
    defaults.update(kw)
    return drift.evaluate_unblock_when(predicates, **defaults)


# ── trdd: <id> terminal ──────────────────────────────────────────────────────


def test_trdd_predicate_satisfied_when_blocker_is_terminal(drift):
    ok, malformed = _eval(
        drift, ["trdd:ABCD1234 terminal"], column_by_uid={"ABCD1234": "complete"}
    )
    assert (ok, malformed) == (True, [])


def test_trdd_predicate_not_satisfied_while_blocker_is_open(drift):
    ok, _ = _eval(drift, ["trdd:ABCD1234 terminal"], column_by_uid={"ABCD1234": "dev"})
    assert ok is False


def test_trdd_predicate_not_satisfied_when_blocker_unknown(drift):
    """An id the board has never seen is NOT terminal — never guess it shipped."""
    ok, malformed = _eval(drift, ["trdd:ZZZZZZZZ terminal"], column_by_uid={})
    assert (ok, malformed) == (False, [])


# ── issue: <owner/repo#N> closed ─────────────────────────────────────────────


def test_issue_predicate_satisfied_when_not_in_the_open_snapshot(drift):
    ok, malformed = _eval(
        drift,
        ["issue:Emasoft/ai-maestro-janitor#42 closed"],
        open_issue_numbers={7, 9},
    )
    assert (ok, malformed) == (True, [])


def test_issue_predicate_not_satisfied_while_still_in_the_open_snapshot(drift):
    ok, _ = _eval(
        drift,
        ["issue:Emasoft/ai-maestro-janitor#42 closed"],
        open_issue_numbers={42},
    )
    assert ok is False


def test_issue_predicate_on_another_repo_never_auto_clears(drift):
    """No cross-repo snapshot exists — treated as decision-needed, never malformed."""
    ok, malformed = _eval(
        drift,
        ["issue:Emasoft/ai-maestro#5 closed"],
        project_repo_slug="Emasoft/ai-maestro-janitor",
        open_issue_numbers=set(),
    )
    assert (ok, malformed) == (False, [])


def test_issue_predicate_missing_snapshot_never_auto_unblocks(drift):
    """`None` (no readable snapshot yet) must NOT read as "zero open issues" — collapsing the
    two used to satisfy every `issue:` predicate on the project's own repo the moment the
    watcher snapshot was absent (`num not in set()` is always True). Advisor finding B1."""
    ok, malformed = _eval(
        drift,
        ["issue:Emasoft/ai-maestro-janitor#42 closed"],
        open_issue_numbers=None,
    )
    assert (ok, malformed) == (False, [])


def test_issue_predicate_empty_snapshot_still_satisfies(drift):
    """An empty-but-PRESENT snapshot (watcher ran, zero issues open) is a real signal and must
    still satisfy — distinguishing this from `None` is the whole point of B1's fix."""
    ok, malformed = _eval(
        drift,
        ["issue:Emasoft/ai-maestro-janitor#42 closed"],
        open_issue_numbers=set(),
    )
    assert (ok, malformed) == (True, [])


# ── file: <repo-relative path> exists ────────────────────────────────────────


def test_file_predicate_satisfied_when_the_file_exists(drift, tmp_path):
    (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
    ok, malformed = _eval(drift, ["file:marker.txt exists"], project_root=tmp_path)
    assert (ok, malformed) == (True, [])


def test_file_predicate_not_satisfied_when_absent(drift, tmp_path):
    ok, _ = _eval(drift, ["file:nope.txt exists"], project_root=tmp_path)
    assert ok is False


def test_file_predicate_with_absolute_path_is_malformed(drift, tmp_path):
    """A scope-leak vector (advisor constraint) — an absolute path is refused, not evaluated."""
    ok, malformed = _eval(drift, ["file:/etc/passwd exists"], project_root=tmp_path)
    assert (ok, malformed) == (False, ["file:/etc/passwd exists"])


def test_file_predicate_climbing_out_of_the_repo_is_malformed(drift, tmp_path):
    ok, malformed = _eval(drift, ["file:../secret exists"], project_root=tmp_path)
    assert (ok, malformed) == (False, ["file:../secret exists"])


# ── log: <repo-relative path> matches <regex> ────────────────────────────────


def test_log_predicate_satisfied_on_a_matching_line(drift, tmp_path):
    (tmp_path / "out.log").write_text("boot ok\nrelease v1.2.3 shipped\n", encoding="utf-8")
    ok, malformed = _eval(drift, [r"log:out.log matches ^release v1\.2\.3"], project_root=tmp_path)
    assert (ok, malformed) == (True, [])


def test_log_predicate_not_satisfied_without_a_match(drift, tmp_path):
    (tmp_path / "out.log").write_text("boot ok\n", encoding="utf-8")
    ok, _ = _eval(drift, ["log:out.log matches nope"], project_root=tmp_path)
    assert ok is False


def test_log_predicate_missing_file_not_satisfied_not_malformed(drift, tmp_path):
    ok, malformed = _eval(drift, ["log:missing.log matches x"], project_root=tmp_path)
    assert (ok, malformed) == (False, [])


def test_log_predicate_matches_within_the_bounded_tail(drift, tmp_path):
    """A match sitting in the last bytes of a >1MiB log is still found — the tail bound
    doesn't just truncate to nothing. The filler is newline-terminated lines, as a real log
    is: the truncated window drops its first (cut) line, so a single 1 MiB line would be
    dropped whole — that is the documented ceiling, not a bug."""
    filler = ("x" * 79 + "\n") * (1024 * 1024 // 80)
    (tmp_path / "big.log").write_text(filler + "release v9 shipped\n", encoding="utf-8")
    ok, malformed = _eval(drift, ["log:big.log matches release v9"], project_root=tmp_path)
    assert (ok, malformed) == (True, [])


def test_log_predicate_misses_a_match_outside_the_bounded_tail(drift, tmp_path):
    """A match sitting only in the first bytes of a >1MiB log, far outside the tail window,
    is correctly NOT found — the whole point of bounding the read."""
    (tmp_path / "big.log").write_text(
        "release v9 shipped\n" + "x" * (1024 * 1024), encoding="utf-8"
    )
    ok, _ = _eval(drift, ["log:big.log matches release v9"], project_root=tmp_path)
    assert ok is False


def test_log_predicate_invalid_regex_is_malformed(drift, tmp_path):
    (tmp_path / "out.log").write_text("boot ok\n", encoding="utf-8")
    ok, malformed = _eval(drift, ["log:out.log matches [unclosed"], project_root=tmp_path)
    assert ok is False
    assert malformed == ["log:out.log matches [unclosed"]


def test_log_predicate_tail_boundary_does_not_false_match_a_cut_line(drift, tmp_path):
    """The seek can land mid-line: the real line is `PREneedle body\\n` but the tail window
    starts 3 bytes in, at `needle body\\n`. With `re.MULTILINE`, `^` matches index 0 of ANY
    string, so `^needle` would spuriously match a fragment that never actually started a line
    in the source file — RTRS704K #3. Sized so the window boundary lands exactly there.
    `^.*needle` is the hole a sentinel byte at index 0 left open (the wildcard swallowed the
    sentinel): the cut line must be dropped, not prefixed."""
    tail_bytes = drift._LOG_PRED_TAIL_BYTES
    line = "PREneedle body text\n"
    filler_len = tail_bytes - len(line) + 3  # window_start (= size-TAIL) lands 3 bytes into `line`
    (tmp_path / "boundary.log").write_text(line + ("b" * filler_len), encoding="utf-8")
    ok, _ = _eval(drift, [r"log:boundary.log matches ^needle"], project_root=tmp_path)
    assert ok is False  # the real line started with "PRE", never with "needle"
    ok, _ = _eval(drift, [r"log:boundary.log matches ^.*needle"], project_root=tmp_path)
    assert ok is False  # a wildcard after the anchor must not reach the fragment either


def test_log_predicate_tail_boundary_still_matches_a_real_line_start(drift, tmp_path):
    """A genuine `^`-anchored match, on a line that starts well inside the tail window (a real
    `\\n` precedes it, not the truncation boundary), must still fire."""
    tail_bytes = drift._LOG_PRED_TAIL_BYTES
    filler = "x" * tail_bytes  # entirely before the window boundary except its own tail slice
    (tmp_path / "boundary2.log").write_text(filler + "\nneedle body text\n", encoding="utf-8")
    ok, _ = _eval(drift, [r"log:boundary2.log matches ^needle"], project_root=tmp_path)
    assert ok is True


# ── date: >=YYYY-MM-DD ────────────────────────────────────────────────────────


def test_date_predicate_satisfied_once_past(drift):
    ok, malformed = _eval(drift, ["date:>=2020-01-01"], now=int(time.time()))
    assert (ok, malformed) == (True, [])


def test_date_predicate_not_satisfied_while_future(drift):
    ok, _ = _eval(drift, ["date:>=2099-01-01"], now=int(time.time()))
    assert ok is False


def test_date_predicate_malformed_never_unblocks(drift):
    ok, malformed = _eval(drift, ["date:>=2026-02-31"])  # 31 Feb doesn't exist
    assert (ok, malformed) == (False, ["date:>=2026-02-31"])


# ── decision: <who> — the ONLY human-only kind ───────────────────────────────


def test_decision_predicate_never_auto_clears(drift):
    ok, malformed = _eval(drift, ["decision:owner"])
    assert (ok, malformed) == (False, [])


# ── malformed / unknown predicate shapes ─────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-known-predicate",
        "trdd:short terminal",  # not 8 chars
        "issue:closed",  # missing owner/repo#N
        "date:2026-01-01",  # missing >=
    ],
)
def test_unknown_predicate_shape_is_malformed_and_never_unblocks(drift, bad):
    ok, malformed = _eval(drift, [bad])
    assert (ok, malformed) == (False, [bad])


def test_a_mix_of_satisfied_and_malformed_never_unblocks(drift):
    """ALL predicates must hold — one malformed token among otherwise-true ones still blocks."""
    ok, malformed = _eval(
        drift,
        ["trdd:ABCD1234 terminal", "garbage"],
        column_by_uid={"ABCD1234": "complete"},
    )
    assert (ok, malformed) == (False, ["garbage"])


def test_no_predicates_is_vacuously_true_but_try_unblock_guards_it(drift):
    """`evaluate_unblock_when([])` is vacuously True (no predicate failed) — the real guard
    against "a card with no field auto-unblocks" lives in `_try_unblock`, which returns before
    ever calling this on an empty list (see `test_try_unblock_...` below)."""
    assert _eval(drift, []) == (True, [])


# ── `_restore_column_text` — the actual on-disk rewrite ──────────────────────


def _card(column="blocked", updated="2026-01-01T00:00:00+0000"):
    return "\n".join(
        [
            "---",
            "trdd-id: ABCDEFGH",
            "title: a blocked card",
            f"column: {column}",
            f"updated: {updated}",
            "---",
            "",
            "# body",
        ]
    )


def test_restore_column_text_rewrites_column_and_updated(drift):
    out = drift._restore_column_text(_card(), "todo", "2026-09-03T10:00:00+0200")
    assert "column: todo" in out
    assert "updated: 2026-09-03T10:00:00+0200" in out
    assert "column: blocked" not in out


def test_restore_column_text_only_touches_the_frontmatter_block(drift):
    """A body that happens to mention `column: blocked` must not be rewritten."""
    text = _card() + "\n\nSee `column: blocked` in the example above.\n"
    out = drift._restore_column_text(text, "todo", "2026-09-03T10:00:00+0200")
    assert out.count("column: blocked") == 1  # only the body mention survives
    assert "column: todo" in out


def test_restore_column_text_none_when_not_actually_blocked(drift):
    """Defensive: refuses to rewrite a card whose column isn't `blocked` at all."""
    assert drift._restore_column_text(_card(column="dev"), "todo", "2026-09-03T10:00:00+0200") is None


# ── `_try_unblock` — the end-to-end write path ───────────────────────────────


def _blocked_card_with(*extra: str) -> str:
    return "\n".join(
        [
            "---",
            "trdd-id: ABCDEFGH",
            "title: a blocked card",
            "column: blocked",
            "updated: 2026-01-01T00:00:00+0000",
            *extra,
            "---",
            "",
            "# body",
        ]
    )


def test_try_unblock_restores_pre_block_column_when_satisfied(drift, tmp_path, capsys):
    f = tmp_path / "TRDD-20260101_000000+0000-ABCDEFGH-x.md"
    f.write_text(
        _blocked_card_with("unblock-when: [trdd:ZZZZZZZZ terminal]", "pre-block-column: dev"),
        encoding="utf-8",
    )
    drift._try_unblock(
        f,
        f.read_text(encoding="utf-8"),
        column_by_uid={"ZZZZZZZZ": "complete"},
        project_repo_slug=None,
        open_issue_numbers=set(),
        project_root=tmp_path,
        now=int(time.time()),
        seen=tmp_path / "seen.txt",
    )
    out = f.read_text(encoding="utf-8")
    assert "column: dev" in out
    assert "column: blocked" not in out
    assert "TRDD-ABCDEFGH" in capsys.readouterr().out


def test_try_unblock_defaults_to_todo_without_pre_block_column(drift, tmp_path):
    f = tmp_path / "TRDD-20260101_000000+0000-ABCDEFGH-x.md"
    f.write_text(_blocked_card_with("unblock-when: [trdd:ZZZZZZZZ terminal]"), encoding="utf-8")
    drift._try_unblock(
        f,
        f.read_text(encoding="utf-8"),
        column_by_uid={"ZZZZZZZZ": "complete"},
        project_repo_slug=None,
        open_issue_numbers=set(),
        project_root=tmp_path,
        now=int(time.time()),
        seen=tmp_path / "seen.txt",
    )
    assert "column: todo" in f.read_text(encoding="utf-8")


def test_try_unblock_is_a_noop_without_the_field(drift, tmp_path):
    """A `blocked` card with no `unblock-when:` is untouched — `blocked-by:` alone stays a
    human-only read (rule §6); nothing here ever guesses at it."""
    f = tmp_path / "TRDD-20260101_000000+0000-ABCDEFGH-x.md"
    text = _blocked_card_with()
    f.write_text(text, encoding="utf-8")
    drift._try_unblock(
        f,
        text,
        column_by_uid={},
        project_repo_slug=None,
        open_issue_numbers=set(),
        project_root=tmp_path,
        now=int(time.time()),
        seen=tmp_path / "seen.txt",
    )
    assert f.read_text(encoding="utf-8") == text


def test_try_unblock_leaves_the_card_blocked_on_a_malformed_predicate(drift, tmp_path):
    f = tmp_path / "TRDD-20260101_000000+0000-ABCDEFGH-x.md"
    text = _blocked_card_with("unblock-when: [garbage]")
    f.write_text(text, encoding="utf-8")
    drift._try_unblock(
        f,
        text,
        column_by_uid={},
        project_repo_slug=None,
        open_issue_numbers=set(),
        project_root=tmp_path,
        now=int(time.time()),
        seen=tmp_path / "seen.txt",
    )
    assert f.read_text(encoding="utf-8") == text  # never auto-unblocked on a parse error


def test_try_unblock_holds_when_blocked_by_is_still_open(drift, tmp_path):
    """`unblock-when:` satisfied but `blocked-by:` names a still-open card — don't restore
    past a live blocker the two fields track independently."""
    f = tmp_path / "TRDD-20260101_000000+0000-ABCDEFGH-x.md"
    text = _blocked_card_with(
        "unblock-when: [trdd:ZZZZZZZZ terminal]",
        "blocked-by: [TRDD-YYYYYYYY]",
        "pre-block-column: dev",
    )
    f.write_text(text, encoding="utf-8")
    drift._try_unblock(
        f,
        text,
        column_by_uid={"ZZZZZZZZ": "complete", "YYYYYYYY": "dev"},
        project_repo_slug=None,
        open_issue_numbers=set(),
        project_root=tmp_path,
        now=int(time.time()),
        seen=tmp_path / "seen.txt",
    )
    assert f.read_text(encoding="utf-8") == text  # blocked-by still open — held


def test_try_unblock_holds_when_blocked_by_is_unresolvable(drift, tmp_path):
    """A `blocked-by:` id that resolves NOWHERE (typo, or unindexed) is a hold too — mirrors
    dispatch.py's `_blocked_reason` classifying it decision-needed, not cleared."""
    f = tmp_path / "TRDD-20260101_000000+0000-ABCDEFGH-x.md"
    text = _blocked_card_with(
        "unblock-when: [trdd:ZZZZZZZZ terminal]",
        "blocked-by: [TRDD-NOSUCH12]",
        "pre-block-column: dev",
    )
    f.write_text(text, encoding="utf-8")
    drift._try_unblock(
        f,
        text,
        column_by_uid={"ZZZZZZZZ": "complete"},
        project_repo_slug=None,
        open_issue_numbers=set(),
        project_root=tmp_path,
        now=int(time.time()),
        seen=tmp_path / "seen.txt",
    )
    assert f.read_text(encoding="utf-8") == text  # unresolvable blocked-by — held


def test_try_unblock_restores_when_blocked_by_is_terminal(drift, tmp_path):
    """Same shape, but the named blocker has reached a terminal column — restore proceeds."""
    f = tmp_path / "TRDD-20260101_000000+0000-ABCDEFGH-x.md"
    text = _blocked_card_with(
        "unblock-when: [trdd:ZZZZZZZZ terminal]",
        "blocked-by: [TRDD-YYYYYYYY]",
        "pre-block-column: dev",
    )
    f.write_text(text, encoding="utf-8")
    drift._try_unblock(
        f,
        text,
        column_by_uid={"ZZZZZZZZ": "complete", "YYYYYYYY": "complete"},
        project_repo_slug=None,
        open_issue_numbers=set(),
        project_root=tmp_path,
        now=int(time.time()),
        seen=tmp_path / "seen.txt",
    )
    out = f.read_text(encoding="utf-8")
    assert "column: dev" in out
    # B2: `blocked-by:` empties and `pre-block-column:` is dropped on restore — otherwise
    # `check4_stale_blockers` re-flags TRDD-YYYYYYYY as a "cleared blocker" every fire even
    # though this card already left `blocked` (rule §6: "blocked-by: empties; restore
    # previous column").
    assert "blocked-by: []" in out
    assert "blocked-by: [TRDD-YYYYYYYY]" not in out
    assert "pre-block-column:" not in out


def test_try_unblock_holds_on_an_illegal_pre_block_column(drift, tmp_path):
    """A corrupted/typo'd `pre-block-column:` must never be written verbatim as `column:` —
    advisor finding B4."""
    f = tmp_path / "TRDD-20260101_000000+0000-ABCDEFGH-x.md"
    text = _blocked_card_with(
        "unblock-when: [trdd:ZZZZZZZZ terminal]",
        "pre-block-column: not-a-real-column",
    )
    f.write_text(text, encoding="utf-8")
    drift._try_unblock(
        f,
        text,
        column_by_uid={"ZZZZZZZZ": "complete"},
        project_repo_slug=None,
        open_issue_numbers=set(),
        project_root=tmp_path,
        now=int(time.time()),
        seen=tmp_path / "seen.txt",
    )
    assert f.read_text(encoding="utf-8") == text  # never rewrote an illegal target


def test_column_by_uid_spans_all_design_folders(drift, tmp_path):
    """The `main()` board-build loop walks `trdd_common.DESIGN_FOLDERS` (tasks + archived +
    proposals + refused), not just `tasks/` — a blocker that shipped is ARCHIVED and would be
    invisible (and its dependent held forever) if the board were built from `tasks/` alone
    (RTRS704K #1; mirrors dispatch.py's `_all_folders_columns`)."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))
    import trdd_common

    project = tmp_path / "proj"
    tasks_dir = project / "design" / "tasks"
    archived_dir = project / "design" / "archived"
    tasks_dir.mkdir(parents=True)
    archived_dir.mkdir(parents=True)
    (archived_dir / "TRDD-20260101_000000+0000-YYYYYYYY-y.md").write_text(
        "\n".join(["---", "trdd-id: YYYYYYYY", "title: t", "column: complete", "---", "", "#"]),
        encoding="utf-8",
    )

    column_by_uid: dict[str, str] = {}
    for folder in trdd_common.DESIGN_FOLDERS:
        for _scope, f in trdd_common.trdd_files(folder, str(project)):
            uid = trdd_common.extract_uid(f.name)
            if uid is not None and uid not in column_by_uid:
                _, col = trdd_common.parse_trdd_state(f)
                column_by_uid[uid] = col

    assert column_by_uid.get("YYYYYYYY") == "complete"
    assert trdd_common.is_done_column(column_by_uid["YYYYYYYY"]) is True


def test_try_unblock_leaves_the_card_blocked_on_a_decision_predicate(drift, tmp_path):
    """`decision:` is the ONE kind that never auto-clears — end to end, not just at eval time."""
    f = tmp_path / "TRDD-20260101_000000+0000-ABCDEFGH-x.md"
    text = _blocked_card_with("unblock-when: [decision:owner]")
    f.write_text(text, encoding="utf-8")
    drift._try_unblock(
        f,
        text,
        column_by_uid={},
        project_repo_slug=None,
        open_issue_numbers=set(),
        project_root=tmp_path,
        now=int(time.time()),
        seen=tmp_path / "seen.txt",
    )
    assert f.read_text(encoding="utf-8") == text
