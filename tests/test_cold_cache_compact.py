"""Auto-compact policy + readers — the PREVENTIVE (warm) lever and the idle /clear.

The two cache-EXPIRED gates this file used to cover (`should_compact_on_resume`,
`should_compact_after_idle`) were REMOVED on 2026-08-04 by USER directive, along
with their tests, once their premise was verified false. They existed to avoid the
cache-creation write of a large cold context, on the belief that Claude Code
summarises with a cheaper model. It does not: Anthropic's compaction docs state it
"requires an additional sampling step, which contributes to rate limits and
billing", billed at the full pre-compaction context size. So a cold-cache /compact
pays exactly the cost it was meant to avoid, and on a session nobody resumes it
converts zero cost into one full-price sampling step over the whole context. No
threshold or cadence fixes that, so the gates are gone rather than retuned.

What is covered here is what SURVIVES that reasoning:
  * should_compact_proactively_idle — fires while the cache is still WARM and the
    user is absent, paying a ~0.1x read now so the next cold event reads ~30k
    instead of ~600k. A real saving, not a rearrangement of an unavoidable one.
  * should_clear_when_long_idle — the 6h abandoned-session lever, its own knob.
  * the harness-relative threshold, the floor machinery that makes the preventive
    trigger terminate, the cooldown, and the readers — all against real tmp files.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TypedDict

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import cold_cache_compact as ccc  # noqa: E402

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



def _write_transcript_with_usage(path: Path, tokens: int) -> None:
    """A minimal one-entry transcript whose sole assistant usage sums to `tokens`."""
    import json

    path.write_text(
        json.dumps(
            {
                "type": "assistant",
                "uuid": "u1",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"id": "m1", "usage": {"input_tokens": tokens}},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_context_tokens_for_resume_prefers_the_live_reading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the plain (tail-window) reading succeeds, the resume-lane fallback is never consulted."""
    import token_meter

    t = tmp_path / "s.jsonl"
    _write_transcript_with_usage(t, 55_000)

    def _boom(*a: object, **k: object) -> None:
        raise AssertionError("resolve_context must not be called when the live reading succeeds")

    monkeypatch.setattr(token_meter, "resolve_context", _boom)
    got = ccc.context_tokens_for_resume(t, project_dir=tmp_path, session_id="s1", now=1_000_000)
    assert got == 55_000


def test_context_tokens_for_resume_derives_from_the_statusline_snapshot_when_the_tail_read_misses(
    tmp_path: Path,
) -> None:
    """TRDD-L32WC0H7 card 1 follow-up item 1: a resumed session whose live tail reading is None
    (e.g. the last usage entry sits outside token_meter's tail window) is measured via
    token_meter.resolve_context's statusline-snapshot fallback instead of staying unmeasurable —
    this is the "derive from the transcript" fix the restart lane needs to be reachable at all."""
    import json

    t = tmp_path / "s.jsonl"
    t.write_text("", encoding="utf-8")  # empty file -> live reading is 0, not None; use a missing one instead
    missing = tmp_path / "does-not-exist.jsonl"

    snap_dir = tmp_path / ".claude" / "janitor"
    snap_dir.mkdir(parents=True)
    (snap_dir / "context-usage.s1.json").write_text(
        json.dumps({"pct": 40, "tokens": 400_000, "window": 1_000_000, "ts": 999_999}),
        encoding="utf-8",
    )
    got = ccc.context_tokens_for_resume(missing, project_dir=tmp_path, session_id="s1", now=1_000_000)
    assert got == 400_000


def test_context_tokens_for_resume_stays_none_when_neither_source_has_anything(
    tmp_path: Path,
) -> None:
    """No live reading and no statusline snapshot: genuinely unmeasurable, never guessed."""
    missing = tmp_path / "does-not-exist.jsonl"
    got = ccc.context_tokens_for_resume(missing, project_dir=tmp_path, session_id="no-such-session", now=1_000_000)
    assert got is None

def test_context_tokens_for_resume_discards_a_snapshot_the_transcript_has_outgrown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Post-review fix (TRDD-L32WC0H7 card 1 follow-up item 1 v2): staleness is an ORDERING
    check against the transcript, never wall-clock age against `now` -- a snapshot is only
    wrong once the transcript grew AFTER it was written. `snap_ts` here is recent by wall-clock
    terms (unlike the old, now-removed age-based test this replaces) to prove age plays no part:
    only the transcript's mtime landing after it matters.
    """
    import json
    import os

    t = tmp_path / "s.jsonl"
    t.write_text("some later activity\n", encoding="utf-8")

    snap_dir = tmp_path / ".claude" / "janitor"
    snap_dir.mkdir(parents=True)
    snap_ts = 1_000_000 - 5  # 5s old -- well inside token_meter's own 120s window
    (snap_dir / "context-usage.s1.json").write_text(
        json.dumps({"pct": 40, "tokens": 400_000, "window": 1_000_000, "ts": snap_ts}),
        encoding="utf-8",
    )
    os.utime(t, (snap_ts + 100, snap_ts + 100))  # transcript written AFTER the snapshot
    monkeypatch.setattr(ccc, "context_tokens_for", lambda _p: None)  # force the fallback branch

    got = ccc.context_tokens_for_resume(t, project_dir=tmp_path, session_id="s1", now=1_000_000)
    assert got is None


def test_context_tokens_for_resume_keeps_an_old_snapshot_the_transcript_has_not_outgrown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resume-lane bug this fix closes: a session idle for 26h has a snapshot that is, by
    wall-clock age, always "stale" -- but nothing ran on the transcript while it was idle, so
    the number is still exactly right and must NOT be discarded."""
    import json
    import os

    t = tmp_path / "s.jsonl"
    t.write_text("some earlier activity\n", encoding="utf-8")

    snap_dir = tmp_path / ".claude" / "janitor"
    snap_dir.mkdir(parents=True)
    now = 1_000_000
    snap_ts = now - 26 * 3600  # written 26h before the restart -- ordinary resume, not corruption
    (snap_dir / "context-usage.s1.json").write_text(
        json.dumps({"pct": 40, "tokens": 400_000, "window": 1_000_000, "ts": snap_ts}),
        encoding="utf-8",
    )
    os.utime(t, (snap_ts, snap_ts))  # transcript untouched since the snapshot was written
    monkeypatch.setattr(ccc, "context_tokens_for", lambda _p: None)  # force the fallback branch

    got = ccc.context_tokens_for_resume(t, project_dir=tmp_path, session_id="s1", now=now)
    assert got == 400_000


def test_context_tokens_for_resume_transcript_with_no_assistant_usage_is_none(tmp_path: Path) -> None:
    """No snapshot and a transcript big enough to force the tail-window branch, but with no
    usage-bearing assistant entry anywhere in it: genuinely unmeasurable, never guessed."""
    import json

    t = tmp_path / "s.jsonl"
    filler = json.dumps({"type": "user", "message": {"content": "x" * 200}}) + "\n"
    with t.open("w", encoding="utf-8") as fh:
        while fh.tell() < 600_000:  # exceed token_meter._TAIL_BYTES (512 KiB)
            fh.write(filler)

    got = ccc.context_tokens_for_resume(t, project_dir=tmp_path, session_id="no-such-session", now=1_000_000)
    assert got is None



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

class _ClearKwargs(TypedDict):
    """Shape of `should_clear_when_long_idle`'s bool/int kwargs (TypedDict, PEP 692) —
    a bare `dict(...)` mixing bool and int values infers one union value type, so `**kw`
    would broadcast that union against every keyword parameter (bool params included)."""

    user_present: bool
    active_waiting: bool
    min_idle_s: int
    context_tokens: int | None
    min_context_tokens: int


def _clear_kw(**over: bool | int | None) -> _ClearKwargs:
    kw: _ClearKwargs = {
        "user_present": False,
        "active_waiting": False,
        "min_idle_s": 3600,
        # Large enough to clear the reinstated floor by default — most tests below are about
        # idle time / vetoes, not size, so the size term should not have to be repeated everywhere.
        "context_tokens": 500_000,
        "min_context_tokens": 300_000,
    }
    kw.update(over)  # type: ignore[typeddict-item]  # `over` is a caller-supplied partial override
    return kw


def test_an_hour_of_nothing_but_heartbeats_is_cleared():
    """The case the directive names (owner 2026-08-04): *"if the project main agent is just
    running the janitor beats while doing nothing else for more than 1 hour, it MUST handoff
    and clear automatically"*. One hour, nobody present, nothing waiting, big enough context
    → clear."""
    assert ccc.should_clear_when_long_idle(3_601, **_clear_kw()) is True


def test_context_size_IS_a_gate_again_card1_item3():
    """SUPERSEDED 2026-09-22 (TRDD-L32WC0H7 card 1 item 3): size is back as a term, reusing the
    `*_MIN_CONTEXT_TOKENS` pattern. The 2026-08-04 directive this test used to pin ("size must
    not veto") answered a different question — WHETHER an abandoned session should ever clear —
    and the floor reinstated here is deliberately tiny: it exists only to skip a nothing-to-
    reclaim clear on a near-empty idle session, not to resurrect a bar high enough to never
    fire (the mistake that made the old compact path unreachable)."""
    assert ccc.should_clear_when_long_idle(
        3_601, **_clear_kw(context_tokens=100, min_context_tokens=300_000)
    ) is False, "a context too small to be worth reclaiming must not authorize a /clear"
    assert ccc.should_clear_when_long_idle(3_601, **_clear_kw()) is True  # big context still fires

    import inspect

    params = inspect.signature(ccc.should_clear_when_long_idle).parameters
    assert "context_tokens" in params and "min_context_tokens" in params, (
        "the size term must be an explicit input — card 1 item 3 reinstated it"
    )


def test_unmeasurable_context_never_satisfies_the_min_context_gate():
    """Card 1 item 1's invariant, applied to the reinstated clear-gate floor too: an unmeasurable
    transcript is not evidence there is something worth reclaiming, so it must refuse exactly
    like a too-small one — never silently skip the size clause and decide on idle time alone."""
    assert ccc.should_clear_when_long_idle(3_601, **_clear_kw(context_tokens=None)) is False


def test_every_remaining_veto_blocks_the_clear_independently():
    """Each surviving gate alone must stop a DESTRUCTIVE action — checked one at a time so a
    refactor cannot quietly make one redundant and leave the others carrying it. A `/clear` is
    irreversible; there is no partial credit for 'most gates held'."""
    assert ccc.should_clear_when_long_idle(30_000, **_clear_kw(user_present=True)) is False
    assert ccc.should_clear_when_long_idle(30_000, **_clear_kw(active_waiting=True)) is False
    assert ccc.should_clear_when_long_idle(100, **_clear_kw()) is False, "not idle long enough"
    assert ccc.should_clear_when_long_idle(3_599, **_clear_kw()) is False, "boundary: just under 1h"


def test_an_UNKNOWN_idle_age_never_authorizes_a_clear():
    """`None` is not zero and must not read as 'idle forever'. `transcript_activity` returns
    None when it cannot read the transcript — a fresh session, a moved checkout, a permissions
    error. Treating None as a satisfied gate would clear a session precisely when we know least
    about it, which is the worst possible moment for an irreversible action."""
    assert ccc.should_clear_when_long_idle(None, **_clear_kw()) is False


def test_the_idle_threshold_is_one_hour():
    """Pinned because it is a stated directive, not a taste — and because the value it replaced
    (6h) was chosen on the reasoning that an hour-idle session "may simply be between turns".
    That reasoning does not survive the measurement source: the idle age fed in here is
    SUBSTANTIVE (heartbeat enqueues discounted), so an hour of it is already an hour of nothing
    but beats."""
    assert ccc.DEFAULT_CLEAR_MIN_IDLE_SECONDS == 3600


def test_clear_is_gated_by_its_own_knob_not_the_compact_master(monkeypatch):
    """Turning cold-compact off must NOT silently disable the clear too — one knob disabling
    two unrelated levers is how a feature gets switched off without anyone noticing."""
    monkeypatch.setenv(ccc.ENABLED_ENV, "false")
    monkeypatch.delenv(ccc.CLEAR_ENABLED_ENV, raising=False)
    assert ccc.enabled() is False
    assert ccc.clear_enabled() is True
    monkeypatch.setenv(ccc.CLEAR_ENABLED_ENV, "false")
    assert ccc.clear_enabled() is False


def test_the_clear_cooldown_is_SHORT_because_min_context_is_the_real_guard(tmp_path):
    """Owner ruling 2026-08-23: 5 minutes, not 2 hours.

    The old 2h assumed the cooldown was what stopped a cleared session clearing again. It never
    was — `min_context` (300k) is, and a just-cleared session sits an order of magnitude below it,
    so a second clear is impossible on size alone. The cooldown only has to cover the gap between
    the chain firing and the context measurement catching up.

    2h was also ACTIVELY HARMFUL once the cache-expired trigger existed: a prompt cache can expire
    at any moment, so a session expiring 20 minutes after a clear had to pay a full
    cache-creation write and wait out 100 more minutes before the janitor could act — the
    cooldown suppressing exactly the fires the trigger exists to catch.

    Pinned as a VALUE, deliberately: the sibling test above uses the constant, so it would keep
    passing if someone restored 7200 and would prove nothing about the decision.
    """
    import time as _t

    assert ccc.DEFAULT_CLEAR_COOLDOWN_SECONDS == 300
    now = int(_t.time())
    ccc.mark_clear_fired(tmp_path, now=now)
    assert ccc.clear_in_cooldown(tmp_path, now=now + 301) is False, (
        "a cache expiring minutes after a clear must not be suppressed"
    )


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



# --------------------------------------------------------------------------- #
# harness_will_autocompact — GUARD 2 (TRDD-PH8SAQKS, issue 306)               #
#                                                                             #
# BAND semantics (round 2, coordinator correction): imminent only inside     #
# [effective_compact_point - margin, min_context_tokens()). Below the lower  #
# bound the harness genuinely isn't close yet; AT OR ABOVE the upper bound   #
# the harness has already missed its own turn-end compact point, so a send  #
# there is a BACKSTOP, not a race, and must proceed. Every test below reads  #
# the real `ccc.min_context_tokens()` / `token_meter.predict_auto_compact`  #
# for its expected boundary instead of hand-computing it, so the assertions #
# track the production formula rather than a second, possibly-wrong copy.  #
# --------------------------------------------------------------------------- #

def _write_settings(tmp_path: Path, payload: dict) -> Path:
    import json as _json

    p = tmp_path / "settings.json"
    p.write_text(_json.dumps(payload), encoding="utf-8")
    return p


def _band(monkeypatch: pytest.MonkeyPatch) -> tuple[int, int]:
    """The real (lower, upper) band edges for whatever env is currently set, computed the
    SAME way `harness_will_autocompact` computes them -- so a test asserting against this
    tracks the production formula instead of a second, possibly-drifted copy of it."""
    import token_meter

    pred = token_meter.predict_auto_compact(0)
    assert pred is not None, "test setup must set CLAUDE_CODE_AUTO_COMPACT_WINDOW"
    lower = pred.effective_compact_point - int(pred.effective_compact_point * ccc.GUARD2_MARGIN_FRACTION)
    upper = ccc.min_context_tokens()
    return lower, upper


@pytest.fixture
def guard2_env(monkeypatch: pytest.MonkeyPatch):
    """A small, deterministic CLAUDE_CODE_AUTO_COMPACT_WINDOW with no MIN_CONTEXT override, so
    `min_context_tokens()` falls to its own DEFAULT_MIN_CONTEXT_TOKENS floor (350_000) --
    comfortably above the small window's effective point, giving a real, wide band to place
    test context sizes inside/below/above."""
    monkeypatch.delenv(ccc.MIN_CONTEXT_ENV, raising=False)
    monkeypatch.delenv(ccc.HARNESS_BACKSTOP_MARGIN_ENV, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "100000")
    return monkeypatch


def test_guard2_inside_the_band_under_auto_compact_enabled_is_imminent(
    tmp_path: Path, guard2_env: pytest.MonkeyPatch
) -> None:
    """A context between the two edges -> imminent (True), the /compact send is suppressed."""
    settings = _write_settings(tmp_path, {"autoCompactEnabled": True})
    lower, upper = _band(guard2_env)
    mid = (lower + upper) // 2
    assert ccc.harness_will_autocompact(mid, settings_path=settings) is True


def test_guard2_below_the_band_lets_the_send_proceed(
    tmp_path: Path, guard2_env: pytest.MonkeyPatch
) -> None:
    """A context below the lower edge -> not imminent yet (False), the send proceeds."""
    settings = _write_settings(tmp_path, {"autoCompactEnabled": True})
    lower, _upper = _band(guard2_env)
    assert ccc.harness_will_autocompact(max(0, lower - 10_000), settings_path=settings) is False


def test_guard2_at_or_above_the_upper_edge_is_a_backstop_not_a_race(
    tmp_path: Path, guard2_env: pytest.MonkeyPatch
) -> None:
    """A context AT the upper edge (min_context_tokens()) -> the harness already missed its
    turn-end compact point; sending is now the BACKSTOP, so it proceeds (False = not guarded)."""
    settings = _write_settings(tmp_path, {"autoCompactEnabled": True})
    _lower, upper = _band(guard2_env)
    assert ccc.harness_will_autocompact(upper, settings_path=settings) is False
    assert ccc.harness_will_autocompact(upper + 50_000, settings_path=settings) is False


def test_guard2_inverted_band_fails_safe(tmp_path: Path, guard2_env: pytest.MonkeyPatch) -> None:
    """An operator override can push `min_context_tokens()` (the upper edge) BELOW the lower
    edge (`effective - margin`), inverting the band. The `>= upper` check must run before the
    `< lower` check so this degrades to "guard 2 never fires" (the safe direction) rather than
    to "guard 2 always fires" (which would silently re-disable the backstop, round 2's own bug,
    for any operator who tunes the override this way). Round-2 review finding 5c."""
    lower, upper = _band(guard2_env)
    assert upper > lower, "test setup must start from a normal, non-inverted band"
    # Force MIN_CONTEXT_ENV below the lower edge -> min_context_tokens() (the upper edge)
    # drops below `lower`, inverting the band.
    guard2_env.setenv(ccc.MIN_CONTEXT_ENV, str(lower - 10_000))
    inverted_lower, inverted_upper = _band(guard2_env)
    assert inverted_upper < inverted_lower, "test setup must actually invert the band"
    settings = _write_settings(tmp_path, {"autoCompactEnabled": True})
    # Every context in, around, and between the (now swapped) edges must fail safe (False).
    for ctx in (inverted_upper - 1, inverted_upper, inverted_lower, inverted_lower + 1):
        assert ccc.harness_will_autocompact(ctx, settings_path=settings) is False


def test_guard2_auto_compact_disabled_lets_the_send_proceed(
    tmp_path: Path, guard2_env: pytest.MonkeyPatch
) -> None:
    """autoCompactEnabled=false -> the harness will not compact, so the send proceeds unguarded,
    even for a context that would otherwise sit inside the band."""
    settings = _write_settings(tmp_path, {"autoCompactEnabled": False})
    lower, upper = _band(guard2_env)
    assert ccc.harness_will_autocompact((lower + upper) // 2, settings_path=settings) is False


def test_guard2_unreadable_settings_fails_open_send_proceeds(
    tmp_path: Path, guard2_env: pytest.MonkeyPatch
) -> None:
    """settings.json missing/unparseable -> fail OPEN (False), never suppress a decided send."""
    missing = tmp_path / "does-not-exist.json"
    lower, upper = _band(guard2_env)
    assert ccc.harness_will_autocompact((lower + upper) // 2, settings_path=missing) is False


def test_guard2_unresolvable_window_fails_open_send_proceeds(tmp_path: Path) -> None:
    """No CLAUDE_CODE_AUTO_COMPACT_WINDOW anywhere (env or settings' own env block) -> fail open."""
    settings = _write_settings(tmp_path, {"autoCompactEnabled": True})
    assert ccc.harness_will_autocompact(999_000, settings_path=settings, env={}) is False


def test_guard2_window_falls_back_to_settings_env_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLAUDE_CODE_AUTO_COMPACT_WINDOW absent from the real env but present in settings.json's
    own `env` block (the launchd case, TRDD-XCJFCJUX) -> still resolves the lower bound and
    still suppresses a context inside it (the real env's absence also leaves
    `min_context_tokens()` at its own DEFAULT_MIN_CONTEXT_TOKENS floor, comfortably above)."""
    monkeypatch.delenv(ccc.MIN_CONTEXT_ENV, raising=False)
    monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
    settings = _write_settings(
        tmp_path,
        {"autoCompactEnabled": True, "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "100000"}},
    )
    assert ccc.harness_will_autocompact(96_000, settings_path=settings, env={}) is True


def test_guard2_upper_edge_uses_the_settings_merged_window_not_the_bare_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The launchd case (TRDD-XCJFCJUX): with no CLAUDE_CODE_AUTO_COMPACT_WINDOW in the process
    env, guard 2's upper edge must come from min_context_tokens(env=<settings env block>), not
    the env-less min_context_tokens() -- reverting to the latter would leave a context strictly
    between the two edges wrongly classified as still-in-band (True) instead of past-the-real-
    upper-edge (False)."""
    monkeypatch.delenv(ccc.MIN_CONTEXT_ENV, raising=False)
    monkeypatch.delenv(ccc.HARNESS_BACKSTOP_MARGIN_ENV, raising=False)
    monkeypatch.delenv(ccc.CONTEXT_WINDOW_ENV, raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_COMPACT_SUMMARY_TOKENS", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
    monkeypatch.setattr(ccc.state, "_SETTINGS_OPTIONS", {}, raising=False)
    settings = _write_settings(
        tmp_path,
        {"autoCompactEnabled": True, "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "700000"}},
    )
    env_with_window = {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "700000"}
    upper_with_window = ccc.min_context_tokens(env=env_with_window)
    upper_env_less = ccc.min_context_tokens()
    context_tokens = upper_with_window + (upper_env_less - upper_with_window) // 2
    assert upper_with_window <= context_tokens < upper_env_less, (
        "test setup must place context strictly between the settings-merged upper edge and the "
        "env-less one -- that gap is what this test discriminates"
    )
    # Pin the expected False to the `>= upper` branch specifically (not the `< lower` branch,
    # which would also return False for the wrong reason and mask a regression in the upper-edge
    # check this test targets -- round-2 review finding).
    import token_meter

    pred = token_meter.predict_auto_compact(0, env=env_with_window)
    assert pred is not None
    lower = pred.effective_compact_point - int(pred.effective_compact_point * ccc.GUARD2_MARGIN_FRACTION)
    assert context_tokens >= lower, (
        "test setup must keep context_tokens at/above the band's lower edge too, so a False "
        "result can only come from the `>= upper` branch this test is about"
    )
    assert ccc.harness_will_autocompact(context_tokens, settings_path=settings, env={}) is False


def test_guard2_default_autocompact_enabled_when_key_absent(
    tmp_path: Path, guard2_env: pytest.MonkeyPatch
) -> None:
    """autoCompactEnabled key absent entirely -> defaults True (Claude Code's own default)."""
    settings = _write_settings(tmp_path, {})
    lower, upper = _band(guard2_env)
    assert ccc.harness_will_autocompact((lower + upper) // 2, settings_path=settings) is True
