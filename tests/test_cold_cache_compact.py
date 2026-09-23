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


