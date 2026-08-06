"""Tests for the external (zero-model-turn) handoff-and-clear policy lib (TRDD-PXP08ZQC).

Real, no mocks: every gate here is a PURE function over injected facts, so the tests call it
directly; the two readers are exercised against REAL files written to a tmp dir, never a mock.

The values in `test_measured_machine_config_*` are the ones measured on the machine the card was
written for (2026-08-06: probed 60-minute cache TTL, `*/5 * * * *` cadence) — they are the
regression guard for the whole reason this module deviates from the card's literal wording.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import external_clear as ec  # noqa: E402

# The full set of runtime facts the gate needs, in its "abandoned session, safe to clear" shape.
# Each test overrides exactly the one fact it is about, so a failure names its own cause.
FIRING = dict(
    idle_seconds=7200,
    last_turn_age_s=30,
    ttl_minutes=5,
    seconds_to_next_fire=300,
    context_tokens=460_000,
    min_context=150_000,
    min_idle_s=3600,
    headroom_s=60,
    user_present=False,
    active_waiting=False,
    in_cooldown=False,
)


def verdict(**overrides):
    """Run the gate with the firing baseline plus the named overrides."""
    return ec.should_clear_externally(**{**FIRING, **overrides})


# --- seconds_until_next_fire -------------------------------------------------


def test_next_fire_is_computed_from_the_real_minute_of_hour_set():
    """`*/5` at HH:07:00 fires next at HH:10 — 180s away."""
    now = int(time.mktime(time.struct_time((2026, 8, 6, 14, 7, 0, 0, 0, -1))))
    assert ec.seconds_until_next_fire("*/5 * * * *", now) == 180


def test_next_fire_wraps_the_hour_without_inventing_a_step_that_cron_never_uses():
    """`*/7` at HH:56 wraps to the next hour's :00 in 4 min, not the 7 a naive step implies."""
    now = int(time.mktime(time.struct_time((2026, 8, 6, 14, 56, 0, 0, 0, -1))))
    assert ec.seconds_until_next_fire("*/7 * * * *", now) == 4 * 60


def test_next_fire_is_unknown_for_a_cron_shape_we_cannot_read():
    """A non-`*/N` cron returns None rather than a fabricated schedule."""
    now = int(time.time())
    assert ec.seconds_until_next_fire("0 * * * *", now) is None
    assert ec.seconds_until_next_fire("", now) is None
    assert ec.seconds_until_next_fire("*/abc * * * *", now) is None


# --- next_fire_misses_cache --------------------------------------------------


def test_next_fire_misses_when_the_gap_crosses_the_ttl():
    """Last turn 200s ago + 300s to the next fire exceeds a 5-min TTL, so that fire pays a miss."""
    assert ec.next_fire_misses_cache(
        last_turn_age_s=200, seconds_to_next_fire=300, ttl_minutes=5
    ) is True


def test_measured_machine_config_keeps_the_cache_warm_so_the_miss_trigger_stays_quiet():
    """MEASURED 2026-08-06 (60-min TTL, `*/5` cadence): the cache never expires between fires."""
    assert ec.next_fire_misses_cache(
        last_turn_age_s=30, seconds_to_next_fire=300, ttl_minutes=60
    ) is False


def test_next_fire_miss_is_false_on_unknown_inputs():
    """An unknown schedule or unmeasurable transcript is not evidence that a miss is coming."""
    assert ec.next_fire_misses_cache(
        last_turn_age_s=None, seconds_to_next_fire=300, ttl_minutes=5
    ) is False
    assert ec.next_fire_misses_cache(
        last_turn_age_s=200, seconds_to_next_fire=None, ttl_minutes=5
    ) is False


# --- should_clear_externally: the vetoes -------------------------------------


def test_cooldown_vetoes_so_the_two_levers_never_double_fire():
    """A recent clear (stamp shared with the in-model lever) stands this path down."""
    v = verdict(in_cooldown=True)
    assert v.fire is False and v.why == "cooldown"


def test_user_present_vetoes_an_unrecoverable_clear():
    """Somebody typing in this pane is not an abandoned session."""
    assert verdict(user_present=True).fire is False


def test_active_waiting_vetoes():
    """A pending resume or in-flight background agent is work mid-flight, not abandonment."""
    assert verdict(active_waiting=True).fire is False


def test_unknown_idle_vetoes_because_it_cannot_authorize_a_destructive_act():
    """`idle_seconds is None` must never reach a `/clear` — unlike unknown context."""
    v = verdict(idle_seconds=None)
    assert v.fire is False and v.why == "idle-unknown"


def test_imminent_fire_defers_to_the_next_idle_gap():
    """Less headroom than the chain needs means the fire would land mid-clear; wait."""
    v = verdict(seconds_to_next_fire=10)
    assert v.fire is False and "no-headroom" in v.why


def test_unreadable_cron_does_not_silently_disable_the_lever():
    """Unknown headroom must NOT veto — that is how an unreadable cron kills the feature."""
    v = verdict(seconds_to_next_fire=None)
    assert v.fire is True and v.trigger == ec.TRIGGER_LONG_IDLE


def test_small_context_is_not_worth_clearing():
    """Below the floor there is nothing measurable to reclaim, so leave the session alone."""
    v = verdict(context_tokens=50_000)
    assert v.fire is False and "nothing worth reclaiming" in v.why


def test_unknown_context_does_not_veto_the_2026_08_04_correction():
    """An unmeasurable transcript skips the size clause instead of disabling the lever.

    Pinned to the warm 60-min TTL so only the long-idle trigger can fire — otherwise the
    miss trigger would carry the test and it would pass without exercising the correction.
    """
    v = verdict(context_tokens=None, ttl_minutes=60, last_turn_age_s=30)
    assert v.fire is True and v.trigger == ec.TRIGGER_LONG_IDLE


# --- should_clear_externally: the two triggers -------------------------------


def test_long_idle_fires_even_while_the_cache_stays_warm():
    """The case the measured config produces: warm cache, but hours of nothing but beats."""
    v = verdict(ttl_minutes=60, last_turn_age_s=30)
    assert v.fire is True and v.trigger == ec.TRIGGER_LONG_IDLE


def test_next_fire_miss_fires_before_the_long_idle_threshold_is_reached():
    """A short-idle session still clears when the NEXT fire would pay a full cache miss."""
    v = verdict(idle_seconds=600, ttl_minutes=5, last_turn_age_s=200, seconds_to_next_fire=300)
    assert v.fire is True and v.trigger == ec.TRIGGER_NEXT_FIRE_MISSES


def test_a_warm_recently_active_session_is_left_alone():
    """Neither trigger holds: short idle and the next fire still lands inside the TTL."""
    v = verdict(idle_seconds=600, ttl_minutes=60, last_turn_age_s=30)
    assert v.fire is False and "still warm" in v.why


def test_every_refusal_explains_itself():
    """A gate that cannot say why it declined is indistinguishable from a dead one."""
    for override in (
        {"in_cooldown": True},
        {"user_present": True},
        {"active_waiting": True},
        {"idle_seconds": None},
        {"seconds_to_next_fire": 10},
        {"context_tokens": 50_000},
        {"idle_seconds": 600, "ttl_minutes": 60, "last_turn_age_s": 30},
    ):
        v = verdict(**override)
        assert v.fire is False
        assert v.why, f"silent refusal for {override}"


# --- terminal_from_record ----------------------------------------------------


def test_recorded_iterm_id_is_split_to_the_bare_uuid():
    """`ITERM_SESSION_ID` is `<tty>:<UUID>`; the whole string fails clear_trigger's `_UUID_RE`."""
    rec = {"iterm_session_id": "w0t1p0:ECEF0378-8D5D-4834-A8A9-371F0FDB3720"}
    assert ec.terminal_from_record(rec) == {
        "kind": "iterm",
        "session_id": "ECEF0378-8D5D-4834-A8A9-371F0FDB3720",
    }


def test_tmux_is_preferred_because_its_pane_can_be_read_back():
    """Read-back is what lets the chain VERIFY a command before submitting it."""
    rec = {"tmux_pane": "%3", "iterm_session_id": "w0t1p0:ABCDEF01-0000-0000-0000-000000000000"}
    assert ec.terminal_from_record(rec) == {"kind": "tmux", "pane": "%3"}


def test_an_empty_record_resolves_to_an_unsupported_channel():
    """No recorded pane must read as `unknown`, never as a truthy half-built dict."""
    assert ec.terminal_from_record({}) == {"kind": "unknown"}
    assert ec.terminal_from_record({"term_program": "iTerm.app"}) == {"kind": "unknown"}


# --- read_ttl_minutes --------------------------------------------------------


def test_ttl_is_read_from_the_dispatchers_own_cache(tmp_path):
    """The watcher reuses the heartbeat's probed TTL rather than spending its own subprocess."""
    (tmp_path / "ttl-regime.json").write_text(
        '{"minutes": 60, "probed_at": 1786027332, "source": "probe"}', encoding="utf-8"
    )
    assert ec.read_ttl_minutes(tmp_path) == 60


def test_missing_or_garbage_ttl_falls_back_to_the_short_side(tmp_path):
    """An unknown TTL biases toward 'the next fire will miss', i.e. toward acting."""
    assert ec.read_ttl_minutes(tmp_path) == ec.DEFAULT_TTL_MINUTES
    (tmp_path / "ttl-regime.json").write_text("not json", encoding="utf-8")
    assert ec.read_ttl_minutes(tmp_path) == ec.DEFAULT_TTL_MINUTES
    (tmp_path / "ttl-regime.json").write_text('{"minutes": 0}', encoding="utf-8")
    assert ec.read_ttl_minutes(tmp_path) == ec.DEFAULT_TTL_MINUTES


# --- compose_template_handoff ------------------------------------------------

NOW_ISO = "2026-08-06T18:07:00+0200"


def _inputs(**kw):
    base = dict(
        cards=[("PXP08ZQC", "dev", "External zero-turn handoff-and-clear")],
        commits=[("f3f664de", "feat(fleet): rotation unblocks the panes it fixed")],
        findings=["HIGH WINDOW-BURN: 7d/Fable window 100% at 29% elapsed"],
        memory_dir=".claude/project/memory",
        trigger=ec.TRIGGER_LONG_IDLE,
        idle_seconds=7200,
        context_tokens=460_000,
    )
    base.update(kw)
    return ec.HandoffInputs(**base)


def test_template_handoff_carries_the_pointers_it_promises():
    """Cards, commits and findings all appear, each as a link/reference rather than content."""
    text = ec.compose_template_handoff(_inputs(), now_iso=NOW_ISO)
    assert "TRDD-PXP08ZQC" in text
    assert "f3f664de" in text
    assert "WINDOW-BURN" in text
    assert "memgrep recall" in text


def test_template_handoff_always_carries_a_reference_even_when_empty():
    """An empty session still needs a pointer into the payload store, or it is not exhaustive."""
    text = ec.compose_template_handoff(
        _inputs(cards=[], commits=[], findings=[]), now_iso=NOW_ISO
    )
    assert "memgrep" in text


def test_template_handoff_never_inlines_a_fenced_block():
    """A fenced block is how content gets inlined instead of linked — the contract forbids it."""
    text = ec.compose_template_handoff(_inputs(), now_iso=NOW_ISO)
    assert "```" not in text


def test_template_handoff_trims_to_the_byte_budget_by_dropping_whole_items():
    """Over-budget input sheds tail ITEMS; a mid-line cut could leave a half-written TRDD id."""
    big = _inputs(
        cards=[(f"CARD{i:04d}", "dev", "x" * 90) for i in range(60)],
        commits=[(f"{i:08x}", "y" * 90) for i in range(60)],
        findings=["z" * 120 for _ in range(60)],
    )
    text = ec.compose_template_handoff(big, now_iso=NOW_ISO, max_bytes=4096)
    assert len(text.encode("utf-8")) <= 4096
    # Whatever survived is intact: every card line still ends with a full 90-char title.
    for line in text.splitlines():
        if line.startswith("- TRDD-CARD"):
            assert line.endswith("x" * 90)
    assert "memgrep" in text  # the recall pointer is never what gets trimmed


def test_template_handoff_keeps_at_least_one_card_when_everything_else_is_gone():
    """Cards are the only thing that says what was being worked on, so they are shed last."""
    big = _inputs(
        cards=[("PXP08ZQC", "dev", "t" * 200), ("AAAAAAAA", "todo", "u" * 200)],
        commits=[(f"{i:08x}", "y" * 120) for i in range(40)],
        findings=["z" * 150 for _ in range(40)],
    )
    text = ec.compose_template_handoff(big, now_iso=NOW_ISO, max_bytes=1200)
    assert "TRDD-PXP08ZQC" in text


def test_template_handoff_reports_unknown_facts_as_unknown():
    """Never render a missing measurement as `~0h` / `~0k` — that reads as a real reading."""
    text = ec.compose_template_handoff(
        _inputs(idle_seconds=None, context_tokens=None), now_iso=NOW_ISO
    )
    assert "idle unknown" in text and "context unknown" in text
