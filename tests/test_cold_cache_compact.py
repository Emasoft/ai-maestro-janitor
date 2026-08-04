"""Cold-cache auto-compact policy + readers (TRDD-EUWIHP0G).

Two PURE gates decide WHEN the janitor self-fires /compact so a resumed large
context whose 1h prompt cache has gone cold does not drag a ~600k cache-creation
write across the whole 5h window:

  * should_compact_on_resume   — SessionStart (startup/resume).
  * should_compact_after_idle  — heartbeat rate-limit path.

Both now decide on ONE thing: IS THE LAST TURN OLDER THAN THE PROMPT-CACHE TTL
(USER directive 2026-08-04 — "simply check the last turn datetime. if it is
older than 55 minutes, it should inject the compact command. no matter the value
of the context"). The context-size clause these tests used to pin is GONE; the
tests that pinned it are rewritten below rather than adapted, because they
encoded the defect: the size bar was derived from CLAUDE_CODE_AUTO_COMPACT_WINDOW
and so sat ABOVE the point where the harness itself auto-compacts (measured live:
716,000 vs 666,000), making both gates unreachable — a resumed 500-600k session
was never compacted and paid a full cold cache-write on its first turn.

Each gate is tested as a truth-table PLUS the exact >= boundary, and the
absence-of-evidence case (no readable transcript → no fire) is pinned. The
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
# should_compact_on_resume — the SessionStart gate (last-turn age ONLY)         #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (None, False),        # no readable transcript ⇒ no last-turn time → never fire
        (0, False),           # the last turn was just now — cache is warm
        (3_299, False),       # one second under the 55-min TTL
        (3_300, True),        # exactly at the TTL (>=) — the boundary
        (86_400, True),       # idle since yesterday — the USER's reported case
    ],
)
def test_should_compact_on_resume_truth_table(age, expected) -> None:
    """Fires iff the last turn's age is known AND >= the TTL. Size is not consulted."""
    assert ccc.should_compact_on_resume(age, min_idle_s=3_300) is expected


def test_should_compact_on_resume_boundary_is_inclusive() -> None:
    """FALSIFICATION of the boundary: at exactly the TTL it MUST fire (>=, not >)."""
    assert ccc.should_compact_on_resume(3_299, min_idle_s=3_300) is False
    assert ccc.should_compact_on_resume(3_300, min_idle_s=3_300) is True


def test_resume_ignores_context_size_entirely() -> None:
    """FALSIFICATION of the retired size clause (the actual bug the USER reported).

    A tiny context that is COLD must fire, and a huge context that is WARM must not.
    Under the old size-gated shape the first case was the one that silently did
    nothing on a 500-600k session, because the size bar (716,000, derived from the
    auto-compact window) sat above where the harness already compacts (666,000).
    The gate takes no size argument at all now, so the only way to reintroduce the
    defect is to change the signature — which this call would then fail to make.
    """
    assert ccc.should_compact_on_resume(86_400, min_idle_s=3_300) is True   # cold, size irrelevant
    assert ccc.should_compact_on_resume(60, min_idle_s=3_300) is False      # warm, size irrelevant


# --------------------------------------------------------------------------- #
# should_compact_after_idle — the heartbeat rate-limit gate (same one rule)     #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("idle", "expected"),
    [
        (4_000, True),     # cold (>= TTL) → fire
        (600, False),      # warm → no fire (a compact would waste a write)
        (3_300, True),     # exactly at the TTL → fire
        (3_299, False),    # one second under → no fire
    ],
)
def test_should_compact_after_idle_truth_table(idle, expected) -> None:
    """Requires exactly one thing: the gap outlived the prompt-cache TTL."""
    assert ccc.should_compact_after_idle(idle, min_idle_s=3_300) is expected


def test_recompact_guard_blocks_a_compaction_from_any_route(tmp_path: Path) -> None:
    """USER directive 2026-08-04: don't compact if one already happened in the last 65 min —
    "the user may have run the compact itself, or a janitor cron may have executed a planned
    compact". Both routes land in `last-compact.ts` (the PostCompact hook stamps it for a manual
    /compact, our injected one, AND the harness's native auto-compact), so checking that stamp is
    what makes the guard cover compactions the janitor never fired.
    """
    sd = tmp_path / "state"
    sd.mkdir()
    now = 1_800_000_000

    assert ccc.recently_compacted(sd, now=now) is False  # nothing stamped → free to compact

    # A compaction someone ELSE performed, 10 minutes ago.
    ccc.mark_compacted(sd, now=now - 600)
    assert ccc.recently_compacted(sd, now=now) is True

    # …still blocking at 64 min, released at 66.
    assert ccc.recently_compacted(sd, now=now - 600 + 3_840) is True
    assert ccc.recently_compacted(sd, now=now - 600 + 3_960) is False


def test_recompact_guard_also_covers_a_fire_that_has_not_landed(tmp_path: Path) -> None:
    """Our own fire counts too: between injecting /compact and the compaction landing there is
    no `last-compact.ts` yet, and without this the next heartbeat would fire a second one."""
    sd = tmp_path / "state"
    sd.mkdir()
    now = 1_800_000_000
    ccc.mark_fired(sd, now=now - 30)  # injected half a minute ago, not landed
    assert ccc.recently_compacted(sd, now=now) is True


def test_the_guard_window_exceeds_the_trigger_window() -> None:
    """THE ANTI-LOOP INVARIANT, asserted as an inequality rather than trusted.

    The trigger fires when the last turn is older than 55 min; the guard blocks a repeat for 65.
    If the guard were ever made SHORTER than the trigger, a permanently idle session would clear
    the guard while still satisfying the trigger and compact forever on a cycle. Guard > trigger
    is what bounds an idle stretch to a single compaction.
    """
    assert ccc.DEFAULT_RECOMPACT_GUARD_SECONDS > ccc.DEFAULT_MIN_IDLE_SECONDS


def test_recompact_guard_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ccc.RECOMPACT_GUARD_ENV, raising=False)
    assert ccc.recompact_guard_seconds() == ccc.DEFAULT_RECOMPACT_GUARD_SECONDS == 3_900
    monkeypatch.setenv(ccc.RECOMPACT_GUARD_ENV, "600")
    assert ccc.recompact_guard_seconds() == 600


def test_both_cold_gates_agree_on_every_age() -> None:
    """The two paths differ only in WHERE the age comes from, never in what makes a
    compaction due — so for any known age they must return the same verdict. Pins the
    unification; a future edit that re-adds a condition to one path breaks this."""
    for age in (0, 60, 3_299, 3_300, 3_301, 86_400):
        assert ccc.should_compact_on_resume(age, min_idle_s=3_300) is ccc.should_compact_after_idle(
            age, min_idle_s=3_300
        )


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


def test_min_idle_default_is_55_minutes_not_the_full_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """55 min, deliberately UNDER the 1h prompt-cache TTL (USER directive 2026-08-04).

    The age we measure is the age at CHECK time, but the compact turn runs later and the
    TTL boundary is not observable from here — waiting the full hour lets the common
    near-boundary session go cold before we act. Firing 5 min early costs nothing (the
    session is idle by construction). Pinned as a NUMBER because that margin is the point:
    a silent drift back to 3600 would reintroduce the miss.
    """
    monkeypatch.delenv(ccc.MIN_IDLE_ENV, raising=False)
    assert ccc.min_idle_seconds() == ccc.DEFAULT_MIN_IDLE_SECONDS == 3_300
    assert ccc.DEFAULT_MIN_IDLE_SECONDS < 3_600  # the margin, stated as an assertion
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


# --- long-idle CLEAR (owner directive 2026-08-02) --------------------------------------

def _clear_kw(**over):
    kw = dict(
        user_present=False, active_waiting=False,
        min_idle_s=21600, min_context_tokens=350_000,
    )
    kw.update(over)
    return kw


def test_long_idle_fat_session_is_cleared():
    """The case the directive names: left alone a long time, big context, nobody waiting."""
    assert ccc.should_clear_when_long_idle(500_000, 30_000, **_clear_kw()) is True


def test_every_veto_blocks_the_clear_independently():
    """Each gate alone must be sufficient to stop a DESTRUCTIVE action — checked one at a time
    so a later refactor cannot quietly make one of them redundant and leave the others carrying
    it. A `/clear` is irreversible; there is no partial credit for 'most gates held'."""
    assert ccc.should_clear_when_long_idle(500_000, 30_000, **_clear_kw(user_present=True)) is False
    assert ccc.should_clear_when_long_idle(500_000, 30_000, **_clear_kw(active_waiting=True)) is False
    assert ccc.should_clear_when_long_idle(500_000, 100, **_clear_kw()) is False, "not idle long enough"
    assert ccc.should_clear_when_long_idle(10_000, 30_000, **_clear_kw()) is False, "context too small"


def test_an_UNKNOWN_measurement_never_authorizes_a_clear():
    """`None` is not zero and must not read as 'small' or 'idle forever'.

    `context_tokens_for` and `transcript_activity` both return None when they cannot read the
    transcript — a fresh session, a moved checkout, a permissions error. Treating None as a
    satisfied gate would clear a session precisely when we know least about it, which is the
    worst possible moment for an irreversible action."""
    assert ccc.should_clear_when_long_idle(None, 30_000, **_clear_kw()) is False
    assert ccc.should_clear_when_long_idle(500_000, None, **_clear_kw()) is False
    assert ccc.should_clear_when_long_idle(None, None, **_clear_kw()) is False


def test_the_clear_threshold_sits_ABOVE_the_compaction_floor():
    """Load-bearing relationship, not a taste. `refresh_floor` measured a real compaction at
    343,007 -> 308,644: the base install plus the summary reload every time, so that floor is a
    property of the install. Below it `/clear` reclaims nothing `/compact` did not already, so
    firing the destructive lever there would buy nothing. The default must stay above it."""
    assert ccc.DEFAULT_CLEAR_MIN_CONTEXT_TOKENS > 308_644


def test_clear_is_gated_by_its_own_knob_not_the_compact_master(monkeypatch):
    """Turning cold-compact off must NOT silently disable the clear too — one knob disabling
    two unrelated levers is how a feature gets switched off without anyone noticing."""
    monkeypatch.setenv(ccc.ENABLED_ENV, "false")
    monkeypatch.delenv(ccc.CLEAR_ENABLED_ENV, raising=False)
    assert ccc.enabled() is False
    assert ccc.clear_enabled() is True
    monkeypatch.setenv(ccc.CLEAR_ENABLED_ENV, "false")
    assert ccc.clear_enabled() is False


def test_clear_cooldown_suppresses_a_repeat(tmp_path):
    import time as _t
    now = int(_t.time())
    sd = tmp_path
    assert ccc.clear_in_cooldown(sd, now=now) is False
    ccc.mark_clear_fired(sd, now=now)
    assert ccc.clear_in_cooldown(sd, now=now) is True
    assert ccc.clear_in_cooldown(
        sd, now=now + ccc.DEFAULT_CLEAR_COOLDOWN_SECONDS + 1
    ) is False
