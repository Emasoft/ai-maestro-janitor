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
import os
import sys
import threading
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
    # defect 1 (review): the rotated backup is locked down exactly like the live file.
    assert (backup.stat().st_mode & 0o777) == 0o600


# --- review follow-up defects 1-4 (TRDD-N9LDHF7N card 7 follow-up) -------------------------- #


def test_log_decisions_redacts_a_literal_secret_in_the_preview_and_locks_file_mode(
    project_dir: Path,
) -> None:
    """Defect 1: a preview containing an sk-style token or an AWS-key-shaped string must be
    written redacted, and the log file must be created 0600 (owner-only) -- not the previous
    default-permissions file carrying raw transcript/tool-output text verbatim."""
    fake_openai_key = "sk-proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    fake_aws_key = "AKIAIOSFODNN7EXAMPLE"
    text = f"tool output leaked a key {fake_openai_key} and also {fake_aws_key} in the env dump"
    items = [_item("u-1:0", kind="assistant", text=text)]
    # relevance == threshold -> |score - threshold| == 0, well within the far-from-threshold
    # margin, so the preview is kept (and therefore actually exercises redaction).
    scores = {"u-1:0": _score(relevance=0.5, kept=True)}
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    path = jsl.shadow_log_path()
    rows = _read_jsonl(path)
    preview = rows[0]["text_preview"]
    assert fake_openai_key not in preview
    assert fake_aws_key not in preview
    assert "[REDACTED]" in preview
    assert (path.stat().st_mode & 0o777) == 0o600


def test_log_decisions_redacts_a_secret_cut_at_the_truncation_boundary(project_dir: Path) -> None:
    """Coordinator, second follow-up (post-e904477d review): `_redact_preview` used to run on
    the ALREADY-truncated 200-char preview -- a real secret straddling that cut kept only its
    surviving prefix, which no longer completes the "known prefix + minimum length" shape any
    pattern requires, so the fragment leaked unredacted. Places a full 20-char AWS-shaped key
    starting at index 190 (so a naive truncate-then-redact keeps only its first 10 characters,
    "AKIAIOSFOD" -- ten characters alone never match `AKIA[0-9A-Z]{16}`) -- the fix redacts the
    FULL text first, so no raw fragment of the key can survive truncation."""
    aws_key = "AKIAIOSFODNN7EXAMPLE"
    text = "x" * 190 + aws_key + "y" * 50
    items = [_item("u-1:0", kind="assistant", text=text)]
    scores = {"u-1:0": _score(relevance=0.5, kept=True)}  # close to threshold -> preview kept
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    preview = _read_jsonl(jsl.shadow_log_path())[0]["text_preview"]
    assert aws_key[:10] not in preview  # the fragment a truncate-first order used to leak
    assert aws_key not in preview
    assert "[REDACTED]" in preview


@pytest.mark.parametrize(
    ("text", "forbidden"),
    [
        pytest.param(
            "config dump: password=TopSecretValue123 continue", "TopSecretValue123", id="password=",
        ),
        pytest.param("creds:\n  passwd: TopSecretValue123\n", "TopSecretValue123", id="passwd:"),
        pytest.param("export secret=TopSecretValue123 done", "TopSecretValue123", id="secret="),
        pytest.param("auth header token=TopSecretValue123 end", "TopSecretValue123", id="token="),
        # Review fork, third pass: the first draft's unquoted-only value class missed a
        # human-pasted password with a space/punctuation before its first 6 alnum characters.
        pytest.param(
            'password: "hi there! 9x"', "hi there! 9x", id="password-quoted-with-space-and-punct",
        ),
        pytest.param(
            "Authorization: Bearer abcDEF123456.ghiJKL7890tokenvalue", "abcDEF123456", id="bearer",
        ),
        pytest.param(
            # Fragmented per tests/README.md (fixture-hygiene gate): the BEGIN
            # marker is split across a `+` so no contiguous "-----BEGIN ...
            # PRIVATE KEY-----" literal sits in source; the runtime string is
            # byte-identical to the un-fragmented form.
            ("-----BEGIN RSA " + "PRIVATE KEY-----")
            + "\nMIIEowIBAAKCAQEAmorebase64keydata\n"
            + "-----END RSA PRIVATE KEY-----",
            "MIIEowIBAAKCAQEA",
            id="private-key-block",
        ),
        # Coordinator, fourth follow-up: four more shapes.
        pytest.param(
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fw",
            "SflKxwRJSMeKKF2QT4fw",
            id="jwt",
        ),
        pytest.param(
            "found this in env: api_key=TopSecretValue123 (not password/secret/token)",
            "TopSecretValue123",
            id="key-name-substring-api_key=",
        ),
        pytest.param(
            "cfg apikey:TopSecretValue123zz here", "TopSecretValue123zz", id="key-name-substring-apikey:",
        ),
        pytest.param(
            "export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY",
            "wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY",
            id="key-name-substring-AWS_SECRET_ACCESS_KEY=",
        ),
        pytest.param(
            "blob dump: " + "Qk7xZ9mP2vT8wL4nR1sV6yB3dF0hJ5kM9pS2uX7zA4cE8g" + " end",
            "Qk7xZ9mP2vT8wL4nR1sV6yB3dF0hJ5kM9pS2uX7zA4cE8g",
            id="high-entropy-blob-no-prefix",
        ),
        # Review fork, fourth pass: a hex-shaped secret (digit + one letter case -- 2 classes,
        # not 3) was invisible to the original all-3-classes gate.
        pytest.param(
            "sha ref: " + "a3f9c2b8e1d4567890abcdef1234567890abcdef" + " end",
            "a3f9c2b8e1d4567890abcdef1234567890abcdef",
            id="high-entropy-blob-hex-shaped",
        ),
        # Review fork, fourth pass: a JSON credential dump's closing key-quote used to sit
        # between the keyword and the separator, breaking the match entirely.
        pytest.param(
            '{"api_key": "TopSecretValue123456"}', "TopSecretValue123456", id="json-quoted-key",
        ),
    ],
)
def test_log_decisions_redacts_generic_secret_shapes(
    project_dir: Path, text: str, forbidden: str,
) -> None:
    """Coordinator, second follow-up: `_KNOWN_SECRET_RE` only matches vendor-PREFIXED tokens
    -- these four generic (unprefixed) shapes were added next to that reuse (see the module's
    own comment on why scripts/hooks/post-edit-safety.py and pre-bash-safety.py had nothing
    further to reuse) and must each come out redacted."""
    items = [_item("u-1:0", kind="assistant", text=text)]
    scores = {"u-1:0": _score(relevance=0.5, kept=True)}
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    preview = _read_jsonl(jsl.shadow_log_path())[0]["text_preview"]
    assert forbidden not in preview
    assert "[REDACTED]" in preview


def test_log_decisions_redacts_url_credentials_keeping_scheme_and_host(project_dir: Path) -> None:
    """Coordinator, fourth follow-up: `://user:pass@host` becomes `://[REDACTED]@host` --
    the exact worked example -- not a blanket whole-match wipe of the scheme/host too."""
    # Fragmented per tests/README.md (fixture-hygiene gate): the user:pass@host
    # run is split across `+` so no contiguous credential literal sits in
    # source; the runtime string is byte-identical to the un-fragmented form.
    text = (
        "clone with postgres://dbadmin:" + "hunter2VerySecret"
        + "@db.internal.example:5432/app"
    )
    items = [_item("u-1:0", kind="assistant", text=text)]
    scores = {"u-1:0": _score(relevance=0.5, kept=True)}
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    preview = _read_jsonl(jsl.shadow_log_path())[0]["text_preview"]
    assert "dbadmin" not in preview
    assert "hunter2VerySecret" not in preview
    assert "://[REDACTED]@db.internal.example:5432/app" in preview  # scheme + host preserved


def test_safe_preview_boundary_mask_keeps_earlier_path_segments_intact(project_dir: Path) -> None:
    """Coordinator: "a path cut mid-segment at the 200-character boundary keeps its earlier
    segments" -- `_PARTIAL_TOKEN_TAIL_RE` only matches a run of alnum/dash/underscore
    characters ending at the cut, and `/` is not in that character class, so an earlier
    `/`-delimited segment survives even when the final segment is left unfinished by the cut."""
    prefix = "/opt/service/config/release-branch/"
    tail = "very-long-directory-segment-name-that-keeps-going-" * 4  # crosses the 200-char cut
    items = [_item("u-1:0", kind="assistant", text=prefix + tail)]
    scores = {"u-1:0": _score(relevance=0.5, kept=True)}
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    preview = _read_jsonl(jsl.shadow_log_path())[0]["text_preview"]
    assert prefix in preview  # every earlier "/"-delimited segment survives, untouched
    assert preview.endswith("[TRUNC]")  # the unfinished LAST segment is masked


def test_log_decisions_opens_the_shadow_log_exactly_once_regardless_of_item_count(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defect 2 (review): the vendored `ShadowLog.decision()` opens the file for append on
    EVERY call when disk-backed -- ~45,000 opens scoring a full transcript. This is the
    architectural regression test for the fix (batch through an in-memory ShadowLog, one real
    `os.open` for the whole call): wraps the real `os.open` to count calls without faking its
    behaviour, so the file is still genuinely written."""
    calls: list[str] = []
    real_open = os.open

    def counting_open(path: object, flags: int, mode: int = 0o777) -> int:
        calls.append(str(path))
        return real_open(path, flags, mode)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", counting_open)

    items = [_item(f"i-{i}:0", kind="user" if i % 2 == 0 else "assistant") for i in range(50)]
    scores = {it.id: _score() for it in items}
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    assert len(calls) == 1, "one os.open per log_decisions() call, not one per record"
    rows = _read_jsonl(jsl.shadow_log_path())
    assert len(rows) == 50 + 25  # 50 admit rows + 25 retrieve rows (the "user"-kind half)


def test_log_decisions_dedupes_a_rerun_of_the_same_session_and_transcript_size(
    project_dir: Path, tmp_path: Path,
) -> None:
    """Defect 3: the sync and detached lanes can both `compact` the same just-closed session's
    transcript -- a second `log_decisions` call keyed by the same (session_key, transcript
    size) must be a no-op, not a duplicate set of rows."""
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("x" * 100, encoding="utf-8")
    items = [_item("u-1:0", kind="user")]
    scores = {"u-1:0": _score()}

    jsl.log_decisions(
        items, scores, relevance_threshold=0.5, decision_threshold=0.5,
        session_key="sess-1", transcript_path=transcript,
    )
    jsl.log_decisions(  # the "other lane", same session, same transcript size
        items, scores, relevance_threshold=0.5, decision_threshold=0.5,
        session_key="sess-1", transcript_path=transcript,
    )

    rows = _read_jsonl(jsl.shadow_log_path())
    assert len(rows) == 2  # one admit + one retrieve -- from the FIRST call only


def test_log_decisions_does_not_dedupe_a_genuinely_grown_transcript(
    project_dir: Path, tmp_path: Path,
) -> None:
    """A session that is still open keeps calling `compact` as its transcript grows -- those
    are genuinely different runs (different transcript byte size) and must both be logged."""
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("x" * 100, encoding="utf-8")
    items = [_item("u-1:0", kind="user")]
    scores = {"u-1:0": _score()}

    jsl.log_decisions(
        items, scores, relevance_threshold=0.5, decision_threshold=0.5,
        session_key="sess-1", transcript_path=transcript,
    )
    transcript.write_text("x" * 200, encoding="utf-8")  # the session grew
    jsl.log_decisions(
        items, scores, relevance_threshold=0.5, decision_threshold=0.5,
        session_key="sess-1", transcript_path=transcript,
    )

    rows = _read_jsonl(jsl.shadow_log_path())
    assert len(rows) == 4  # both runs logged -- not the same (session_key, size) key


def test_log_decisions_lock_prevents_a_true_concurrent_race(
    project_dir: Path, tmp_path: Path,
) -> None:
    """Post-write review follow-up: a plain read-then-write on the seen-set is racy if the
    sync and detached lanes genuinely overlap -- both could read "not seen" before either
    marks it. Two real threads calling `log_decisions` synchronized to start at the same
    instant (a `Barrier`) each do their own `os.open` of the lock file -- `flock` is scoped to
    the open file description, not the process, so this exercises the same serialization a
    second OS process racing the first would hit. The result must still be exactly ONE run's
    rows, never two."""
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("x" * 100, encoding="utf-8")
    items = [_item("u-1:0", kind="user")]
    scores = {"u-1:0": _score()}
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            barrier.wait(timeout=5)
            jsl.log_decisions(
                items, scores, relevance_threshold=0.5, decision_threshold=0.5,
                session_key="sess-race", transcript_path=transcript,
            )
        except BaseException as exc:  # pragma: no cover - surfaced via the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors
    rows = _read_jsonl(jsl.shadow_log_path())
    assert len(rows) == 2  # one admit + one retrieve -- only ONE thread's run landed, not both


def test_log_decisions_drops_preview_far_from_threshold_but_keeps_it_close(
    project_dir: Path,
) -> None:
    """Defect 4's fallback: a record whose score sits more than 0.3 from the threshold it was
    logged against can't flip under any plausible replay threshold, so its preview is dropped
    (not just redacted) to fit the retention budget -- a record close to the threshold, the
    one a replay could actually move, keeps its preview."""
    items = [
        _item("close:0", kind="assistant", text="close-to-threshold transcript text"),
        _item("far:0", kind="assistant", text="far-from-threshold transcript text"),
    ]
    scores = {
        "close:0": _score(relevance=0.55, kept=True),  # |0.55 - 0.5| = 0.05 <= 0.3
        "far:0": _score(relevance=0.95, kept=True),  # |0.95 - 0.5| = 0.45 > 0.3
    }
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    rows = {r["item_id"]: r for r in _read_jsonl(jsl.shadow_log_path())}
    assert rows["close:0"]["text_preview"] != ""
    assert rows["far:0"]["text_preview"] == ""
    # the hash is NOT part of the drop -- only the preview (the review's literal fallback)
    assert rows["far:0"]["text_sha256"] != ""


def test_batched_records_round_trip_through_vendored_load_and_replay(project_dir: Path) -> None:
    """Defect 2's schema-compatibility requirement: `log_decisions` now builds every record
    through the vendored `ShadowLog.decision()` in memory and serializes them itself instead
    of letting the vendored `_append` write to disk -- this proves the resulting JSONL is
    byte-for-byte what `ShadowLog.load()`/`.replay()` expect, not just superficially similar
    (a schema drift would silently show up as fewer parsed rows, not an exception -- see
    `ShadowLog.load`'s own `except (ValueError, TypeError): continue`)."""
    items = [_item(f"i-{i}:0", kind="user" if i % 3 == 0 else "assistant") for i in range(10)]
    scores = {
        it.id: _score(relevance=0.9, kept=True, decision=0.9, decision_passed=True)
        for it in items
    }
    jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    log = ShadowLog.load(jsl.shadow_log_path())
    # 10 admit rows + 4 retrieve rows (i=0,3,6,9 are "user"-kind) -- every line parsed, none
    # silently dropped as malformed.
    assert log.stats().total == 14
    replayed = log.replay(0.5)
    assert replayed.total == 14


def test_log_decisions_record_text_count_mismatch_raises_not_drops_silently(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coordinator, fourth follow-up: "the zip-mismatch guard raises; it never drops records
    silently" -- supersedes the previous round's print-and-return. Forces a length mismatch
    (monkeypatching `ShadowLog.entries` to return one extra row) and asserts `log_decisions`
    RAISES `ValueError` (from `zip(..., strict=True)`, deliberately left uncaught by this
    function's own `except OSError`) rather than silently skipping the batch -- and that
    nothing is written either way (never fall back to writing the vendor's own unredacted
    preview)."""
    real_entries = ShadowLog.entries

    def entries_with_one_extra(self: ShadowLog) -> list[dict[str, Any]]:
        rows = real_entries(self)
        return [*rows, dict(rows[0])] if rows else rows

    monkeypatch.setattr(ShadowLog, "entries", entries_with_one_extra)

    items = [_item("u-1:0", kind="assistant", text="hello")]
    scores = {"u-1:0": _score()}
    with pytest.raises(ValueError, match="zip"):
        jsl.log_decisions(items, scores, relevance_threshold=0.5, decision_threshold=0.5)

    assert not jsl.shadow_log_path().exists()  # nothing written, not even a partial batch


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
