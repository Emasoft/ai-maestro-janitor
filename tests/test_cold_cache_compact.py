"""Cold-cache auto-compact policy + readers (TRDD-EUWIHP0G).

Two PURE gates decide WHEN the janitor self-fires /compact so a resumed large
context whose 1h prompt cache has gone cold does not drag a ~600k cache-creation
write across the whole 5h window:

  * should_compact_on_resume   — SessionStart (startup/resume): context-size only.
  * should_compact_after_idle  — heartbeat rate-limit path: cold AND large.

Each gate is tested as an explicit truth-table PLUS a falsification: removing
either condition of should_compact_after_idle (idle OR size) must flip the
verdict, and the >= boundary of should_compact_on_resume must hold exactly. The
readers/cooldown/knobs are covered against real tmp files (never mocked).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import cold_cache_compact as ccc  # noqa: E402

# --------------------------------------------------------------------------- #
# should_compact_on_resume — the SessionStart gate (context-size only)          #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("ctx", "expected"),
    [
        (None, False),        # unknown context (bad/empty transcript) → never fire
        (0, False),           # empty context
        (269_999, False),     # just below the 270k threshold
        (270_000, True),      # exactly at threshold (>=) — the boundary
        (600_000, True),      # a real cold resume
    ],
)
def test_should_compact_on_resume_truth_table(ctx, expected) -> None:
    """Fires iff the resumed context is known AND >= the threshold."""
    assert ccc.should_compact_on_resume(ctx, min_context_tokens=270_000) is expected


def test_should_compact_on_resume_boundary_is_inclusive() -> None:
    """FALSIFICATION of the boundary: at exactly the threshold it MUST fire (>=, not >).
    269_999 must NOT and 270_000 MUST — proving the comparison is inclusive."""
    assert ccc.should_compact_on_resume(269_999, min_context_tokens=270_000) is False
    assert ccc.should_compact_on_resume(270_000, min_context_tokens=270_000) is True


# --------------------------------------------------------------------------- #
# should_compact_after_idle — the heartbeat rate-limit gate (cold AND large)    #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("idle", "ctx", "expected"),
    [
        (4_000, 300_000, True),    # cold (idle>=3600) AND large (ctx>=270k) → fire
        (4_000, 100_000, False),   # cold but SMALL → no fire (nothing to save)
        (600, 300_000, False),     # large but WARM (idle<3600) → no fire (wasted write)
        (600, 100_000, False),     # warm and small → no fire
        (4_000, None, False),      # cold but context unknown → no fire (can't judge)
        (3_600, 270_000, True),    # both exactly at their thresholds → fire
        (3_599, 270_000, False),   # idle one second under → no fire
    ],
)
def test_should_compact_after_idle_truth_table(idle, ctx, expected) -> None:
    """Requires BOTH: the gap outlived the cache TTL AND the context is large."""
    assert (
        ccc.should_compact_after_idle(
            idle, ctx, min_idle_s=3_600, min_context_tokens=270_000
        )
        is expected
    )


def test_should_compact_after_idle_needs_both_conditions() -> None:
    """FALSIFICATION: neither condition alone suffices. Start from a firing case and
    remove ONE condition at a time — each removal must flip the verdict to False."""
    assert ccc.should_compact_after_idle(4_000, 300_000, min_idle_s=3_600, min_context_tokens=270_000) is True
    # drop the idle condition only → False
    assert ccc.should_compact_after_idle(600, 300_000, min_idle_s=3_600, min_context_tokens=270_000) is False
    # drop the size condition only → False
    assert ccc.should_compact_after_idle(4_000, 100_000, min_idle_s=3_600, min_context_tokens=270_000) is False


# --------------------------------------------------------------------------- #
# knobs — defaults + env overrides                                             #
# --------------------------------------------------------------------------- #

def test_enabled_default_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ccc.ENABLED_ENV, raising=False)
    assert ccc.enabled() is True


def test_enabled_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ccc.ENABLED_ENV, "false")
    assert ccc.enabled() is False


def test_min_context_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ccc.MIN_CONTEXT_ENV, raising=False)
    assert ccc.min_context_tokens() == ccc.DEFAULT_MIN_CONTEXT_TOKENS == 270_000
    monkeypatch.setenv(ccc.MIN_CONTEXT_ENV, "500000")
    assert ccc.min_context_tokens() == 500_000


def test_min_idle_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ccc.MIN_IDLE_ENV, raising=False)
    assert ccc.min_idle_seconds() == ccc.DEFAULT_MIN_IDLE_SECONDS == 3_600
    monkeypatch.setenv(ccc.MIN_IDLE_ENV, "7200")
    assert ccc.min_idle_seconds() == 7_200


def test_cooldown_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ccc.COOLDOWN_ENV, raising=False)
    assert ccc.cooldown_seconds() == ccc.DEFAULT_COOLDOWN_SECONDS == 600
    monkeypatch.setenv(ccc.COOLDOWN_ENV, "120")
    assert ccc.cooldown_seconds() == 120


# --------------------------------------------------------------------------- #
# cooldown — shared by both trigger points                                     #
# --------------------------------------------------------------------------- #

def test_cooldown_absent_when_never_fired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No stamp → not in cooldown (so a first cold resume is allowed to fire)."""
    monkeypatch.delenv(ccc.COOLDOWN_ENV, raising=False)
    assert ccc.in_cooldown(tmp_path, now=1_000_000) is False


def test_cooldown_active_right_after_fire_then_expires(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After mark_fired, in_cooldown is True within the window and False once it elapses."""
    monkeypatch.setenv(ccc.COOLDOWN_ENV, "600")
    ccc.mark_fired(tmp_path, now=1_000_000)
    assert ccc.in_cooldown(tmp_path, now=1_000_000) is True          # same instant
    assert ccc.in_cooldown(tmp_path, now=1_000_000 + 599) is True    # within window
    assert ccc.in_cooldown(tmp_path, now=1_000_000 + 600) is False   # window elapsed
    assert ccc.in_cooldown(tmp_path, now=1_000_000 + 10_000) is False


def test_cooldown_reads_as_false_on_garbage_stamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A corrupt stamp reads as 'not in cooldown' — fail toward acting (missing a needed
    compact is the failure this feature exists to fix)."""
    monkeypatch.setenv(ccc.COOLDOWN_ENV, "600")
    (tmp_path / ccc._FIRED_STAMP).write_text("not-an-int", encoding="utf-8")
    assert ccc.in_cooldown(tmp_path, now=1_000_000) is False


# --------------------------------------------------------------------------- #
# readers — best-effort, never raise                                           #
# --------------------------------------------------------------------------- #

def test_context_tokens_for_none_on_empty_path() -> None:
    assert ccc.context_tokens_for("") is None
    assert ccc.context_tokens_for(None) is None


def test_context_tokens_for_none_on_bad_path(tmp_path: Path) -> None:
    """A non-existent / unparsable transcript returns None, never raises."""
    assert ccc.context_tokens_for(tmp_path / "does-not-exist.jsonl") is None


def test_transcript_idle_seconds_from_mtime(tmp_path: Path) -> None:
    """idle == now - mtime; a missing/empty path is treated as 'just active' (0)."""
    t = tmp_path / "session.jsonl"
    t.write_text("{}\n", encoding="utf-8")
    import os

    os.utime(t, (1_000_000, 1_000_000))
    assert ccc.transcript_idle_seconds(t, now=1_000_000 + 4_200) == 4_200
    assert ccc.transcript_idle_seconds("", now=1_000_000) == 0
    assert ccc.transcript_idle_seconds(tmp_path / "nope.jsonl", now=1_000_000) == 0


def test_newest_transcript_picks_latest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """newest_transcript returns the most-recently-written *.jsonl for a project."""
    import os

    import memory_scopes

    monkeypatch.setenv("HOME", str(tmp_path))
    project = "/Users/x/Code/demo-project"
    slug = memory_scopes.project_slug(project)
    tdir = tmp_path / ".claude" / "projects" / slug
    tdir.mkdir(parents=True)
    old = tdir / "aaa.jsonl"
    new = tdir / "bbb.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    new.write_text("{}\n", encoding="utf-8")
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))
    assert ccc.newest_transcript(project) == new


def test_newest_transcript_none_when_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert ccc.newest_transcript("/Users/x/Code/no-transcripts-here") is None
    assert ccc.newest_transcript(None) is None
