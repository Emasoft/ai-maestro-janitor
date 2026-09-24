"""Tests for scripts/lib/jev_shadow_log.py (TRDD-N9LDHF7N card 7).

`state.project_root`/`janitor_root`/`state_dir` are `lru_cache`d for the process lifetime
(see scripts/lib/state.py), and tests/conftest.py's session-wide isolation already points
`CLAUDE_PROJECT_DIR` at one SHARED fake project for the whole test session -- so every test
here that cares about *where* the shadow log lands points `CLAUDE_PROJECT_DIR` at its own
`tmp_path` and clears those three caches before and after, exactly like
tests/test_state_log_dir.py's own `_clear()` helper.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import jev_shadow_log as jsl  # noqa: E402
import state  # noqa: E402
from jevctx.shadow import ShadowLog  # noqa: E402


def _clear_state_caches() -> None:
    state.project_root.cache_clear()
    state.janitor_root.cache_clear()
    state.state_dir.cache_clear()


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point CLAUDE_PROJECT_DIR at an isolated tmp_path for one test, and restore the caches
    afterward so later tests in the same session don't inherit this test's fake project."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    _clear_state_caches()
    yield tmp_path
    _clear_state_caches()


def _item(id_: str, kind: str = "assistant", text: str = "hello", tokens: int = 5, turn: int = 1) -> Any:
    return SimpleNamespace(id=id_, kind=kind, text=text, tokens=tokens, turn=turn)


def _score(
    relevance: float = 0.9, decision: float = 0.0, oversized: bool = False,
    kept: bool = True, decision_passed: bool = False, blocked: bool = False,
) -> Any:
    return SimpleNamespace(
        relevance=relevance, decision=decision, oversized=oversized, kept=kept,
        decision_passed=decision_passed, blocked=blocked,
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --- file location (never the repo tree) --------------------------------------------------- #


def test_shadow_log_path_lands_in_state_dir_not_repo_tree(project_dir: Path) -> None:
    path = jsl.shadow_log_path()
    assert path == project_dir / ".janitor" / "state" / "jev-shadow.jsonl"
    # never anywhere under the real checkout this test suite itself lives in
    assert _PROJECT_ROOT not in path.parents


def test_log_decisions_writes_under_the_state_dir(project_dir: Path) -> None:
    items = [_item("u-1:0", kind="user")]
    scores = {"u-1:0": _score()}
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)
    path = jsl.shadow_log_path()
    assert path.exists()
    assert path.parent == project_dir / ".janitor" / "state"


# --- per-item, per-question logging shape -------------------------------------------------- #


def test_log_decisions_logs_admit_for_every_item_and_retrieve_only_for_user(project_dir: Path) -> None:
    items = [
        _item("u-1:0", kind="user", text="a decision the user made"),
        _item("a-1:1", kind="assistant", text="an assistant reply"),
    ]
    scores = {
        "u-1:0": _score(relevance=0.9, decision=0.8, kept=True, decision_passed=True),
        "a-1:1": _score(relevance=0.1, decision=0.0, kept=False, decision_passed=False),
    }
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    rows = _read_jsonl(jsl.shadow_log_path())
    admit_rows = [r for r in rows if r["kind"] == "admit"]
    retrieve_rows = [r for r in rows if r["kind"] == "retrieve"]
    assert {r["item_id"] for r in admit_rows} == {"u-1:0", "a-1:1"}
    # suffixed, never the bare id -- see jsl._RETRIEVE_ROW_ID_SUFFIX's own comment: sharing
    # the admit row's bare item_id here would collide in ShadowLog.stats()'s/.replay()'s
    # internal per-item action map (keyed by item_id alone), silently discarding the admit
    # row's real "kept"/"elided" action for this item.
    assert {r["item_id"] for r in retrieve_rows} == {"u-1:0#decision"}  # only the "user" item

    by_id = {r["item_id"]: r for r in admit_rows}
    assert by_id["u-1:0"]["action"] == "kept"
    assert by_id["a-1:1"]["action"] == "elided"
    assert retrieve_rows[0]["action"] == "injected"
    # previews are transcript content -- capped at 200 chars (jevctx.shadow.PREVIEW_CHARS)
    assert len(by_id["u-1:0"]["text_preview"]) <= 200


def test_log_decisions_skips_blocked_and_oversized_items(project_dir: Path) -> None:
    items = [_item("b-1:0"), _item("o-1:0")]
    scores = {
        "b-1:0": _score(blocked=True),
        "o-1:0": _score(oversized=True),
    }
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)
    path = jsl.shadow_log_path()
    # never scored for real -- logging the sentinel Scores would corrupt replay, so nothing
    # is written and the file is never even created.
    assert not path.exists()


# --- expand outcome / false negative ------------------------------------------------------- #


def test_expand_of_elided_id_counts_as_a_false_negative(project_dir: Path) -> None:
    items = [_item("a-1:1", kind="assistant")]
    scores = {"a-1:1": _score(relevance=0.1, kept=False)}
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    jsl.log_expand_outcome("a-1:1")

    log = ShadowLog.load(jsl.shadow_log_path())
    stats = log.stats()
    assert stats.false_negatives == 1
    assert stats.false_negative_rate == 1.0


def test_expand_of_a_kept_id_is_not_a_false_negative(project_dir: Path) -> None:
    items = [_item("a-1:1", kind="assistant")]
    scores = {"a-1:1": _score(relevance=0.9, kept=True)}
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    jsl.log_expand_outcome("a-1:1")  # expanding a KEPT item is not evidence of over-elision

    log = ShadowLog.load(jsl.shadow_log_path())
    assert log.stats().false_negatives == 0


def test_expand_of_an_elided_user_item_is_still_a_false_negative_via_vendored_stats(
    project_dir: Path,
) -> None:
    """Regression test for a post-write review finding (TRDD-N9LDHF7N card 7): a "user" item
    gets TWO rows (admit + retrieve). ShadowLog.stats() builds its internal per-item action
    map as `{item_id: action ...}` -- a plain dict keyed ONLY by item_id, with no `kind` --
    so two rows sharing one item_id collapse to one slot (last write wins). Before this was
    fixed by suffixing the retrieve row's item_id (jsl._RETRIEVE_ROW_ID_SUFFIX), an elided
    "user" item's admit row was silently overwritten by its own retrieve row in that map, and
    `ShadowLog.load(path).stats().false_negatives` never counted its expand -- even though
    the SAME item's admit row, read directly off disk, plainly says action="elided". This
    test reads the raw file through the VENDORED module's own public `.stats()`, not this
    module's kind-filtered `replay_stats` wrapper (which was never affected)."""
    items = [_item("u-1:0", kind="user")]
    # relevance alone would elide it, and the decision gate does NOT rescue it either --
    # both rows exist, and the admit row's real action must still be "elided".
    scores = {"u-1:0": _score(relevance=0.1, decision=0.2, kept=False, decision_passed=False)}
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    rows = _read_jsonl(jsl.shadow_log_path())
    admit_row = next(r for r in rows if r["kind"] == "admit")
    assert admit_row["action"] == "elided"  # the row on disk is correct on its own

    jsl.log_expand_outcome("u-1:0")  # the bare id -- matches the admit row only

    log = ShadowLog.load(jsl.shadow_log_path())
    assert log.stats().false_negatives == 1, (
        "the admit row's 'elided' action must survive being read through ShadowLog.stats(), "
        "not get silently overwritten by the retrieve row sharing its item_id"
    )


# --- replay: monotonic in the threshold, filtered by question ------------------------------- #


def test_replay_is_monotonic_in_threshold(project_dir: Path) -> None:
    items = [_item(f"i-{i}:0", kind="assistant") for i in range(5)]
    scores = {
        it.id: _score(relevance=score, kept=score >= 0.5)
        for it, score in zip(items, [0.1, 0.3, 0.5, 0.7, 0.9])
    }
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    low = jsl.replay_stats(0.0, question="relevance")
    mid = jsl.replay_stats(0.5, question="relevance")
    high = jsl.replay_stats(1.0, question="relevance")

    # raising the threshold can only ever keep FEWER items and elide MORE, never the reverse
    assert low.by_action["kept"] >= mid.by_action["kept"] >= high.by_action["kept"]
    assert low.by_action["elided"] <= mid.by_action["elided"] <= high.by_action["elided"]
    assert high.by_action["kept"] == 0  # nothing scores >= 1.0 except a perfect 1.0
    assert low.by_action["elided"] == 0  # everything scores >= 0.0


def test_replay_question_filters_to_that_questions_own_rows(project_dir: Path) -> None:
    """A "decision"-question replay must never be perturbed by the (unrelated) relevance
    rows sharing the same file -- proven by giving the two questions scores that would
    disagree if the filter leaked."""
    items = [_item("u-1:0", kind="user")]
    scores = {"u-1:0": _score(relevance=0.9, decision=0.1, kept=True, decision_passed=False)}
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    relevance_stats = jsl.replay_stats(0.5, question="relevance")
    decision_stats = jsl.replay_stats(0.5, question="decision")

    assert relevance_stats.total == 1  # only the admit row
    assert relevance_stats.by_action["kept"] == 1
    assert decision_stats.total == 1  # only the retrieve row
    assert decision_stats.by_action["skipped"] == 1


def test_replay_stats_on_a_missing_log_is_empty(project_dir: Path) -> None:
    assert not jsl.shadow_log_path().exists()
    stats = jsl.replay_stats(0.5, question="relevance")
    assert stats.total == 0
    assert stats.false_negative_rate == 0.0


def test_replay_stats_rejects_an_unknown_question(project_dir: Path) -> None:
    with pytest.raises(ValueError):
        jsl.replay_stats(0.5, question="bogus")


# --- size bound -------------------------------------------------------------------------- #


def test_shadow_log_rotates_once_oversized(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jsl, "MAX_SHADOW_LOG_BYTES", 50)  # tiny, so one write already crosses it
    path = jsl.shadow_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * 200 + "\n", encoding="utf-8")  # already over the (tiny) cap

    items = [_item("new-1:0")]
    scores = {"new-1:0": _score()}
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    backup = path.with_name(path.name + ".1")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8").startswith("x" * 200)
    # the live file now holds only what THIS call wrote, not the old oversized content
    assert "x" * 200 not in path.read_text(encoding="utf-8")
    rows = _read_jsonl(path)
    assert len(rows) == 1
    assert rows[0]["item_id"] == "new-1:0"


# --- write failure never breaks the caller -------------------------------------------------- #


def test_log_decisions_write_failure_reports_stderr_and_does_not_raise(
    project_dir: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    janitor_dir = project_dir / ".janitor"
    janitor_dir.mkdir()
    janitor_dir.chmod(0o500)  # read+execute only -- ".janitor/state" can never be mkdir'd
    try:
        items = [_item("u-1:0")]
        scores = {"u-1:0": _score()}
        jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)  # must not raise
    finally:
        janitor_dir.chmod(0o700)  # restore so tmp_path cleanup can remove it

    err = capsys.readouterr().err
    assert "jev-shadow" in err
    assert "decision log write failed" in err


def test_log_expand_outcome_write_failure_reports_stderr_and_does_not_raise(
    project_dir: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    janitor_dir = project_dir / ".janitor"
    janitor_dir.mkdir()
    janitor_dir.chmod(0o500)
    try:
        jsl.log_expand_outcome("u-1:0")  # must not raise
    finally:
        janitor_dir.chmod(0o700)

    err = capsys.readouterr().err
    assert "jev-shadow" in err
    assert "outcome log write failed" in err
