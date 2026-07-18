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


def test_min_context_is_harness_relative(monkeypatch: pytest.MonkeyPatch) -> None:
    """Owner directive 2026-07-18: the janitor NEVER competes with the harness auto-compact — it
    fires only ABOVE the harness's own effective compact point (`CLAUDE_CODE_AUTO_COMPACT_WINDOW -
    overhead`) plus the backstop margin. The old fixed 350k default compacted the user out from
    under a 488k (49%) context, well below the 666k the harness owns."""
    monkeypatch.delenv(ccc.MIN_CONTEXT_ENV, raising=False)
    monkeypatch.delenv(ccc.HARNESS_BACKSTOP_MARGIN_ENV, raising=False)
    # 1) user's real setting: harness compacts at 700000-34000=666000 → janitor at 666000+50000.
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "700000")
    assert ccc.min_context_tokens() == 716_000
    # 2) env unset: harness compacts near the full window → janitor threshold sits just below it,
    #    so the context can never reach it and the harness owns compaction entirely.
    monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
    monkeypatch.setenv(ccc.CONTEXT_WINDOW_ENV, "1000000")
    assert ccc.min_context_tokens() == 1_016_000
    # 3) an explicit operator override always wins verbatim.
    monkeypatch.setenv(ccc.MIN_CONTEXT_ENV, "500000")
    assert ccc.min_context_tokens() == 500_000


def test_min_context_never_below_the_floor_on_a_tiny_auto_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pathologically small CLAUDE_CODE_AUTO_COMPACT_WINDOW must not push the threshold below the
    post-compaction floor (nothing to reclaim there) — it clamps to DEFAULT_MIN_CONTEXT_TOKENS."""
    monkeypatch.delenv(ccc.MIN_CONTEXT_ENV, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "100000")  # effective 66k + 50k = 116k
    assert ccc.min_context_tokens() == ccc.DEFAULT_MIN_CONTEXT_TOKENS == 350_000


def test_default_threshold_sits_above_the_measured_post_compaction_floor() -> None:
    """The default threshold is only meaningful RELATIVE to the post-compaction floor — a
    threshold below it can never close once compacted (see refresh_floor). 308,644 is the real
    floor measured in this repo on 2026-07-17. This pins the invariant so a future 'let's lower
    it to 200k for more savings' cannot silently re-open the infinite-compact loop."""
    MEASURED_FLOOR = 308_644
    assert ccc.DEFAULT_MIN_CONTEXT_TOKENS > MEASURED_FLOOR, (
        f"threshold {ccc.DEFAULT_MIN_CONTEXT_TOKENS} is at/below the measured post-compaction "
        f"floor {MEASURED_FLOOR}: the size gate could never close after a compaction"
    )


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


# --------------------------------------------------------------------------- #
# TRDD-D3PROACT — the PREVENTIVE proactive-idle gate                           #
# --------------------------------------------------------------------------- #

def test_should_compact_proactively_idle_all_three_gates() -> None:
    """PURE. Fires ONLY when the user is absent AND nothing is pending AND the context is large.
    Each gate alone must veto — compaction is lossy, so a present user or pending work blocks it."""
    import cold_cache_compact as ccc

    MIN = 270_000
    # The one firing case: absent + idle + large. No floor learned yet → judged on size alone.
    assert ccc.should_compact_proactively_idle(
        300_000, user_present=False, active_waiting=False, min_context_tokens=MIN,
        floor_tokens=None, min_gain=150_000) is True

    # Present user vetoes (never compact out from under active work).
    assert ccc.should_compact_proactively_idle(
        300_000, user_present=True, active_waiting=False, min_context_tokens=MIN,
        floor_tokens=None, min_gain=150_000) is False
    # Active-waiting vetoes (a resume / keep-going / directive / agent is pending).
    assert ccc.should_compact_proactively_idle(
        300_000, user_present=False, active_waiting=True, min_context_tokens=MIN,
        floor_tokens=None, min_gain=150_000) is False
    # Small context saves nothing (and would be a pointless lossy compaction).
    assert ccc.should_compact_proactively_idle(
        100_000, user_present=False, active_waiting=False, min_context_tokens=MIN,
        floor_tokens=None, min_gain=150_000) is False
    # Unknown context size → never fire (can't prove it's worth it).
    assert ccc.should_compact_proactively_idle(
        None, user_present=False, active_waiting=False, min_context_tokens=MIN,
        floor_tokens=None, min_gain=150_000) is False


def test_floor_gate_closes_the_infinite_compact_loop() -> None:
    """THE REGRESSION THAT MATTERS — pins the REAL numbers measured in this repo 2026-07-17.

    A compaction took the context 343,007 -> 308,644 (only 10%: the base — CLAUDE.md, ~10
    plugins, rules, skills, MCP schemas, the summary — reloads every time and cannot be compacted
    away). 308,644 is ABOVE the 270,000 threshold, so a SIZE-ONLY gate never closes and the
    trigger re-fires every cooldown forever, destroying context each time. The floor gate is the
    only thing that stops it: at the floor there is nothing left to reclaim.
    """
    import cold_cache_compact as ccc

    MIN, GAIN = 270_000, 150_000
    PRE_COMPACT, FLOOR = 343_007, 308_644

    # Sanity: this scenario is exactly the one a size-only gate CANNOT stop.
    assert FLOOR >= MIN, "if the floor were under the threshold the size gate alone would suffice"

    # At the floor: still over the threshold, but a compaction would reclaim NOTHING → no fire.
    # Without this the loop is infinite.
    assert ccc.should_compact_proactively_idle(
        FLOOR, user_present=False, active_waiting=False, min_context_tokens=MIN,
        floor_tokens=FLOOR, min_gain=GAIN) is False
    # The pre-compact size that legitimately fired ONCE must not fire again once the floor is
    # known — reclaiming 34,363 is not worth a lossy compaction, which is why it looped.
    assert ccc.should_compact_proactively_idle(
        PRE_COMPACT, user_present=False, active_waiting=False, min_context_tokens=MIN,
        floor_tokens=FLOOR, min_gain=GAIN) is False
    # Real work HAS piled up above the floor → firing reclaims ~291k → fire. The gate must not be
    # a permanent latch; a session that grows large again still gets its compaction.
    assert ccc.should_compact_proactively_idle(
        600_000, user_present=False, active_waiting=False, min_context_tokens=MIN,
        floor_tokens=FLOOR, min_gain=GAIN) is True
    # Exactly at the boundary fires (>= min_gain), one token under does not.
    assert ccc.should_compact_proactively_idle(
        FLOOR + GAIN, user_present=False, active_waiting=False, min_context_tokens=MIN,
        floor_tokens=FLOOR, min_gain=GAIN) is True
    assert ccc.should_compact_proactively_idle(
        FLOOR + GAIN - 1, user_present=False, active_waiting=False, min_context_tokens=MIN,
        floor_tokens=FLOOR, min_gain=GAIN) is False


def test_refresh_floor_learns_only_after_a_compaction(tmp_path: Path) -> None:
    """The floor is (re)measured EXACTLY when a compaction has happened since the last
    measurement — never otherwise, or ordinary context growth would be mistaken for a floor and
    permanently wedge the trigger off."""
    import cold_cache_compact as ccc

    sd = tmp_path / "state"
    sd.mkdir()

    # No compaction ever → no floor. The first fire is judged on size alone.
    assert ccc.refresh_floor(sd, 600_000) is None
    assert ccc.read_floor(sd) == (None, 0)

    # A compaction happens; the next observed context IS the floor.
    ccc.mark_compacted(sd, now=1000)
    assert ccc.refresh_floor(sd, 308_644) == 308_644
    assert ccc.read_floor(sd) == (308_644, 1000)

    # Context grows with ordinary work — NOT a new floor (no compaction since).
    assert ccc.refresh_floor(sd, 500_000) == 308_644
    assert ccc.read_floor(sd) == (308_644, 1000)

    # A second compaction re-measures it.
    ccc.mark_compacted(sd, now=2000)
    assert ccc.refresh_floor(sd, 312_000) == 312_000

    # An unreadable context size must not disturb a known floor.
    assert ccc.refresh_floor(sd, None) == 312_000


def test_floor_needs_learning_tracks_unobserved_compactions(tmp_path: Path) -> None:
    """The cheap pre-gate the call sites check BEFORE their action gates (TRDD-28XF77X6):
    True exactly while a landed compaction has no floor measurement yet. This is what lets the
    measurement run through a closed cooldown / resume-recency / keep-going — the v0.49.0 bug
    was measuring only after those gates, which the compaction itself stamps shut."""
    import cold_cache_compact as ccc

    sd = tmp_path / "state"
    sd.mkdir()

    # No compaction ever → nothing to observe.
    assert ccc.floor_needs_learning(sd) is False

    # A compaction lands → an observation is due, and STAYS due until one succeeds.
    ccc.mark_compacted(sd, now=1000)
    assert ccc.floor_needs_learning(sd) is True
    assert ccc.refresh_floor(sd, None) is None  # unreadable context → not observed yet
    assert ccc.floor_needs_learning(sd) is True

    # The observation succeeds → nothing pending.
    assert ccc.refresh_floor(sd, 308_644) == 308_644
    assert ccc.floor_needs_learning(sd) is False

    # A LATER compaction re-arms it; the earlier floor does not satisfy the new one.
    ccc.mark_compacted(sd, now=2000)
    assert ccc.floor_needs_learning(sd) is True
    assert ccc.refresh_floor(sd, 312_000) == 312_000
    assert ccc.floor_needs_learning(sd) is False


def test_proactive_idle_enabled_requires_master_switch(monkeypatch) -> None:
    """The preventive path is gated by BOTH the master cold-compact switch AND its own knob."""
    import cold_cache_compact as ccc

    for var in ("CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_ENABLED",
                "CLAUDE_PLUGIN_OPTION_PROACTIVE_IDLE_COMPACT_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    assert ccc.proactive_idle_enabled() is True                       # both default ON

    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_PROACTIVE_IDLE_COMPACT_ENABLED", "false")
    assert ccc.proactive_idle_enabled() is False                      # own knob off

    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_PROACTIVE_IDLE_COMPACT_ENABLED")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_ENABLED", "false")
    assert ccc.proactive_idle_enabled() is False                      # master off disables it too
