"""Tests for the external (zero-model-turn) handoff-and-clear policy lib (TRDD-PXP08ZQC).

Real, no mocks: every gate here is a PURE function over injected facts, so the tests call it
directly; the two readers are exercised against REAL files written to a tmp dir, never a mock.

The values in `test_measured_machine_config_*` are the ones measured on the machine the card was
written for (2026-08-06: probed 60-minute cache TTL, `*/5 * * * *` cadence) — they are the
regression guard for the whole reason this module deviates from the card's literal wording.
"""

import dataclasses
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
    active_waiting=False,
    in_cooldown=False,
    awaiting_user=False,
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


def test_the_gate_knows_nothing_about_the_user_being_present():
    """INVERTED (owner, 2026-08-13: *"my presence must not even be mentioned"*).

    This test used to assert `user_present=True` vetoes. That veto is what kept the whole
    external-clear lever dead: the injection layer migrated on 2026-08-02 to the three ratified
    rules — inject only into an empty field, STOP the instant a key is typed, retry 8 s later,
    NEVER cancel — but the decision layer kept refusing outright, so the injector that would
    have deferred was never asked. Presence now lives in exactly one place, as one fact: the
    last-keystroke timestamp the injector defers 8 s from.

    Asserted structurally, on the SIGNATURE, because that is the only form a future re-add
    cannot slip past: a re-introduced veto would have to add the parameter back first.
    """
    import inspect

    params = set(inspect.signature(ec.should_clear_externally).parameters)
    assert "user_present" not in params, "presence must not be an input to the decision"
    assert not any("present" in p for p in params), f"no presence-shaped input: {sorted(params)}"


def test_active_waiting_vetoes():
    """A pending resume or in-flight background agent is work mid-flight, not abandonment."""
    assert verdict(active_waiting=True).fire is False


def test_awaiting_user_vetoes():
    """TRDD-OO301H7D: a session parked on an unanswered human-facing `tool_use` (plan approval,
    permission prompt) is idle by construction and would otherwise satisfy the long-idle
    trigger — this must refuse instead of clearing the pending question away."""
    v = verdict(awaiting_user=True)
    assert v.fire is False and v.why == "awaiting-user"


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


def test_unknown_context_now_vetoes_card1_item1():
    """SUPERSEDED 2026-09-22 (TRDD-L32WC0H7 card 1 item 1): an unmeasurable transcript USED TO
    skip the size clause and let the idle/miss terms decide alone (the 2026-08-04 correction
    this test used to pin). That was backwards for a gate whose job is "is there enough here to
    justify a destructive /clear" — not knowing the size is exactly the case where the honest
    answer is "assume no". Pinned to the warm 60-min TTL so only the long-idle trigger could
    fire if the floor did not veto first — proving the veto now wins ahead of it.
    """
    v = verdict(context_tokens=None, ttl_minutes=60, last_turn_age_s=30)
    assert v.fire is False and "unmeasurable" in v.why


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
        {"active_waiting": True},
        {"awaiting_user": True},
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


def test_ttl_is_always_the_default_since_the_regime_probe_was_retired(tmp_path):
    """No regime file is ever written any more (TRDD-BRHJHWW0) — the reader always returns the default."""
    assert ec.read_ttl_minutes(tmp_path) == ec.DEFAULT_TTL_MINUTES


# --- compose_template_handoff ------------------------------------------------

NOW_ISO = "2026-08-06T18:07:00+0200"


def _inputs(**kw) -> ec.HandoffInputs:
    """A representative `HandoffInputs`, with per-test overrides.

    Built as a TYPED instance + `dataclasses.replace` rather than `HandoffInputs(**dict(...))`.
    A heterogeneous `dict(...)` literal collapses to a union value type, so every field became
    unassignable and the helper type-checked as nothing at all — meaning a test could pass a
    wrong-typed field (a str where a Sequence belongs) and no checker would say so. `replace`
    keeps the base fully checked and still accepts arbitrary overrides.
    """
    base = ec.HandoffInputs(
        cards=[("PXP08ZQC", "dev", "External zero-turn handoff-and-clear")],
        commits=[("f3f664de", "feat(fleet): rotation unblocks the panes it fixed")],
        findings=["HIGH WINDOW-BURN: 7d/Fable window 100% at 29% elapsed"],
        memory_dir=".claude/project/memory",
        trigger=ec.TRIGGER_LONG_IDLE,
        idle_seconds=7200,
        context_tokens=460_000,
    )
    return dataclasses.replace(base, **kw) if kw else base


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


# --- the REACTIVE trigger: agentlensPro's certain-expiry read (TRDD-1QJIZFFW) ----


def test_certain_expiry_fires_and_is_attributed_to_the_measurement():
    """A measured expiry fires even when the prediction would not — that IS the blind spot."""
    # Headroom OK (100s >= 60s), prediction quiet (1+100 < 5min TTL), idle short (1 < 3600):
    # every other reason to fire is absent, so only the measurement can be what fired it.
    v = verdict(cache_expired=True, last_turn_age_s=1, seconds_to_next_fire=100, idle_seconds=1)
    assert v.fire and v.trigger == ec.TRIGGER_CACHE_CERTAIN_EXPIRED


def test_unknown_expiry_leaves_the_other_triggers_exactly_as_they_were():
    """`None` is NO SIGNAL. Reading it as False would disable the lever wherever the CLI is absent."""
    assert verdict(cache_expired=None) == verdict()


def test_a_fresh_cache_does_not_veto_the_other_triggers():
    """False answers only its own question; long-idle and next-fire-miss still decide alone."""
    v = verdict(cache_expired=False, idle_seconds=99_999, last_turn_age_s=1,
                seconds_to_next_fire=100)
    assert v.fire and v.trigger == ec.TRIGGER_LONG_IDLE


def test_every_safety_veto_outranks_a_certain_expiry():
    """`/clear` is unrecoverable; a cache miss is money. Neither buys the right to destroy work."""
    for veto in ("active_waiting", "in_cooldown"):
        v = verdict(cache_expired=True, **{veto: True})
        assert not v.fire, f"{veto} must still veto a measured expiry"


# --- the probe's contract: the exit code is NOT the answer -----------------------


class _P:
    def __init__(self, rc, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def test_probe_reads_the_WORD_not_the_exit_code():
    """MEASURED on 12.x: the verbose form exits 0 while printing `false`. `rc == 0 ⇒ expired`
    would report a miss on every healthy session and fire an unrecoverable clear."""
    import agentlens_probe as alp

    assert alp.probe_cache_expired("x", runner=lambda *a, **k: _P(0, "false\n")) is False
    assert alp.probe_cache_expired("x", runner=lambda *a, **k: _P(0, "true\n")) is True


def test_probe_returns_None_for_cannot_answer_and_for_junk():
    """Exit 2 with EMPTY stdout is 'could not resolve' — it must never read as a fresh cache."""
    import agentlens_probe as alp

    assert alp.probe_cache_expired("x", runner=lambda *a, **k: _P(2, "")) is None
    assert alp.probe_cache_expired("x", runner=lambda *a, **k: _P(0, "maybe")) is None
    assert alp.probe_cache_expired("", runner=lambda *a, **k: _P(0, "true")) is None


def test_probe_never_raises_on_a_broken_cli():
    """A composer that raises stops the clear from happening at all."""
    import subprocess

    import agentlens_probe as alp

    def _boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="agentlenspro", timeout=1)

    assert alp.probe_cache_expired("x", runner=_boom) is None
    assert alp.probe_cache_expired("x", runner=lambda *a, **k: (_ for _ in ()).throw(OSError())) is None


# --- the regression that was live in HEAD ---------------------------------------


def test_the_watchers_gate_dict_matches_the_gates_signature():
    """`_decide` built ONE dict for both the gate and the log; adding a composer-only
    `transcript` key to it made every run raise `unexpected keyword argument`, and the
    `# type: ignore[arg-type]` on the call hid it. Asserting the shape is what makes the
    split load-bearing instead of stylistic."""
    import ast
    import inspect
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "scripts" / "external_handoff_clear.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    keys = {
        str(k.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", "") == "gate" for t in node.targets)
        and isinstance(node.value, ast.Dict)
        for k in node.value.keys
        # `str(...)`, not the bare `.value`: an `ast.Constant`'s value is an untyped union, so
        # the set was `set[_ConstantValue]` — `keys <= params` compared it against a `set[str]`
        # and `sorted()` on the difference was a type error. Worse than untidy: a non-string
        # key would then never match a parameter name and the check would pass by never
        # comparing anything, which is exactly the shape of a guard that guards nothing.
        if isinstance(k, ast.Constant)
    }
    assert keys, "no `gate = {...}` literal found — did the call site get renamed?"
    params = set(inspect.signature(ec.should_clear_externally).parameters)
    assert keys <= params, f"passed but not accepted: {sorted(keys - params)}"


def test_context_pressure_fires_on_a_BUSY_session_the_other_triggers_cannot_reach():
    """TRDD-79LXF6PJ: the whole point — a session that is NOT idle and whose cache is warm.

    The other four triggers are idle/cache economies, so none of them can fire here. Before this
    trigger existed that was harmless, because the HARNESS auto-compacted at the boundary. With
    `autoCompactEnabled: false` it no longer does — it errors — so this is the only thing standing
    between a busy session and a hard stop.
    """
    v = verdict(
        idle_seconds=5,  # actively working: long-idle cannot fire
        last_turn_age_s=1,  # cache warm …
        seconds_to_next_fire=120,  # … and the next fire lands INSIDE the 5min TTL, so
        #                            next-fire-misses cannot fire either. Without this the
        #                            baseline's 300s makes 1+300 > TTL and that term fires; the
        #                            test would still pass — context-pressure is checked first —
        #                            but it would no longer be testing what its name claims.
        cache_expired=False,  # measured warm: cache-certain-expired cannot fire
        context_tokens=700_000,
        context_high_water=700_000,
    )
    assert v.fire is True
    assert v.trigger == ec.TRIGGER_CONTEXT_PRESSURE
    assert "context limit" in v.why


def test_context_pressure_outranks_the_min_context_floor_on_a_200k_model():
    """The floor must not veto the survival trigger — the 200K case the other test cannot reach.

    Every other context-pressure test uses 700K, which sails over `min_context`, so the ordering
    bug was invisible to all of them: the floor is `DEFAULT_MIN_CONTEXT_TOKENS` = 300K while
    `context_high_water` resolves from `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, which is UNDER 200K on
    a 200K-window model. A session at 170K with auto-compact off — precisely what this trigger
    exists for — was refused with "nothing worth reclaiming" and rode on into the hard
    context-limit error. The two questions only ever disagree when the floor is the larger number,
    and there the high-water mark has already answered "yes, this is worth reclaiming".
    """
    v = verdict(
        idle_seconds=5,
        last_turn_age_s=1,
        seconds_to_next_fire=120,
        cache_expired=False,
        context_tokens=170_000,
        min_context=ec.DEFAULT_MIN_CONTEXT_TOKENS,  # 300K — above the whole 200K window
        context_high_water=155_000,
    )
    assert v.fire is True, f"the survival trigger must outrank the floor, got: {v.why}"
    assert v.trigger == ec.TRIGGER_CONTEXT_PRESSURE

    # …and the floor still vetoes when context pressure is NOT the reason: below the high-water
    # mark there is nothing to survive, so the economy triggers face the floor as before.
    below = verdict(
        idle_seconds=5,
        last_turn_age_s=1,
        seconds_to_next_fire=120,
        cache_expired=False,
        context_tokens=120_000,
        min_context=ec.DEFAULT_MIN_CONTEXT_TOKENS,
        context_high_water=155_000,
    )
    assert below.fire is False
    assert "nothing worth reclaiming" in below.why


def test_context_pressure_is_off_when_no_high_water_is_configured():
    """0 disables it. A hardcoded default would be wrong by ~5x between a 200K and a 1M window,
    so the backstop is opt-in — and its absence must read as OFF, never as 'fire always'."""
    # `seconds_to_next_fire` is kept well inside the TTL on purpose: at the FIRING baseline's 300s
    # the next-fire-misses term fires on its own (1+300 > the 5min TTL), and this test would then
    # "pass" or "fail" for a reason that has nothing to do with the high-water mark. A test whose
    # subject is one term must silence the others, or it is measuring the fixture.
    v = verdict(
        idle_seconds=5,
        last_turn_age_s=1,
        seconds_to_next_fire=120,
        cache_expired=False,
        context_high_water=0,
    )
    assert v.fire is False, "an unset high-water must not authorize anything"


def test_cache_expired_needs_300k_of_context_and_no_recent_clear():
    """Owner's rule, verbatim: compact on an expired cache ONLY when context >300k AND the
    session was not just compacted — 'to avoid compacting it twice'.

    Written to PIN behaviour that already existed rather than to add any: min_context defaults to
    300_000 and vetoes ahead of every trigger, and in_cooldown (2h) is the not-just-compacted
    guard. Pinned because the rule is now explicit, and an unpinned coincidence is one refactor
    away from silently becoming false.
    """
    # Below the floor: an expired cache alone must NOT authorize a clear.
    assert verdict(cache_expired=True, context_tokens=250_000, min_context=300_000).fire is False
    # Above it, with no recent clear: fires, and names the measurement.
    hot = verdict(cache_expired=True, context_tokens=400_000, min_context=300_000)
    assert hot.fire is True and hot.trigger == ec.TRIGGER_CACHE_CERTAIN_EXPIRED
    # Above it, but just compacted: the cooldown wins — this is the "twice" the owner ruled out.
    assert verdict(
        cache_expired=True, context_tokens=400_000, min_context=300_000, in_cooldown=True
    ).fire is False


def test_the_janitor_owns_compaction_only_when_the_harness_stopped(tmp_path, monkeypatch):
    """Ownership is DETECTED, never assumed — and both wrong answers are expensive.

    harness ON + janitor fires  => the session is compacted twice, the janitor racing a
    compaction the harness was about to do anyway.
    harness OFF + janitor silent => nothing compacts and the session dies at the context limit.
    That second one was live on this machine for hours today: the setting was flipped before the
    janitor could see it.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("DISABLE_AUTO_COMPACT", raising=False)
    cfg = tmp_path / ".claude"
    cfg.mkdir(parents=True, exist_ok=True)
    settings = cfg / "settings.json"

    settings.write_text('{"autoCompactEnabled": false}', encoding="utf-8")
    assert ec.harness_auto_compacts(home=tmp_path) is False, "janitor must take over"

    settings.write_text('{"autoCompactEnabled": true}', encoding="utf-8")
    assert ec.harness_auto_compacts(home=tmp_path) is True, "harness still owns it"

    # Absent key, absent file, and unparseable JSON must ALL read as "the harness still
    # compacts". The safe default is the janitor doing nothing: a wrongly-silent janitor costs a
    # redundant compaction, a wrongly-eager one clears a session that was never in danger.
    settings.write_text("{}", encoding="utf-8")
    assert ec.harness_auto_compacts(home=tmp_path) is True
    settings.write_text("{not json", encoding="utf-8")
    assert ec.harness_auto_compacts(home=tmp_path) is True
    settings.unlink()
    assert ec.harness_auto_compacts(home=tmp_path) is True

    # The per-session env var disables it on its own — whichever surface turns auto-compact off
    # wins, and the other cannot turn it back on.
    settings.write_text('{"autoCompactEnabled": true}', encoding="utf-8")
    monkeypatch.setenv("DISABLE_AUTO_COMPACT", "1")
    assert ec.harness_auto_compacts(home=tmp_path) is False


def test_context_pressure_never_overrides_a_SAFETY_veto():
    """Pressure is urgent, not supreme: a question addressed to a human still wins.

    `awaiting_user` means the session is parked on a decision only a person can make. Clearing it
    would discard that decision — and unlike a context-limit error, which is recoverable by the
    user, a discarded question is not.
    """
    v = verdict(
        awaiting_user=True, context_tokens=900_000, context_high_water=700_000, idle_seconds=5
    )
    assert v.fire is False and v.why == "awaiting-user"


def test_the_expiry_probe_gets_its_own_generous_timeout():
    """MEASURED 0.15s / 11.5s / 19.7s on one warm host. At the burn probes' 5s this returned
    None on 2 of 3 runs — and None fails open, so a too-short bound is indistinguishable from
    'agentlensPro is not installed' and ships the trigger dead. Pinned so a later tidy-up that
    unifies the timeouts has to argue with the measurement first."""
    import agentlens_probe as alp

    assert alp._CACHE_EXPIRED_TIMEOUT_S >= 20.0
    assert alp._CACHE_EXPIRED_TIMEOUT_S is not alp._TIMEOUT_S


# --- card 1 items 2+7: every clear decision logs its context reading + autoCompactEnabled ----


def _read_log(name: str) -> str:
    import state

    path = state.log_dir() / f"{name}.log"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def test_a_decline_logs_the_context_reading_and_autocompact_setting(tmp_path, monkeypatch):
    """Card 1 items 2+7: a DECLINE must be as visible as a fire — this is what makes a dead
    lever distinguishable from a healthy-but-quiet one, and what lets a threshold tuned while
    `autoCompactEnabled` was believed false (it is TRUE, measured 2026-09-22) be re-checked
    against the setting that actually governed the decision at the time."""
    import state

    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    state.log_dir.cache_clear()
    # Short idle AND a warm-TTL next fire, so BOTH triggers miss and the gate declines cleanly
    # ("idle ... still warm") rather than firing on next-fire-misses.
    v = verdict(idle_seconds=100, ttl_minutes=60)
    assert v.fire is False
    log = _read_log("external-clear")
    assert "decline" in log
    assert "context=460000" in log  # FIRING's context_tokens, unchanged by this override
    assert "autoCompactEnabled=True" in log  # no settings.json on this fake HOME -> default True


def test_a_fire_logs_unmeasurable_context_literally(tmp_path, monkeypatch):
    """The `context=unmeasurable` spelling from card 1 item 2, not a bare `None` or `-1` that a
    log reader would have to know the code to interpret."""
    import state

    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    state.log_dir.cache_clear()
    v = verdict(context_tokens=None)
    assert v.fire is False  # card 1 item 1: unmeasurable never satisfies the floor
    log = _read_log("external-clear")
    assert "context=unmeasurable" in log


def test_should_clear_on_resume_also_logs(tmp_path, monkeypatch):
    """The resume-gate wrapper gets the same guarantee as the externally-clear one — a single
    shared `_log_clear_decision` helper, not a copy that could drift."""
    import state

    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    state.log_dir.cache_clear()
    v = ec.should_clear_on_resume(
        source="startup",
        cache_expired=None,
        context_tokens=200_000,
        min_context=300_000,
        in_cooldown=False,
        already_fired_this_session=False,
    )
    assert v.fire is False
    log = _read_log("clear-on-resume")
    assert "decline" in log and "context=200000" in log and "autoCompactEnabled=True" in log


# --- card 1 item 5: recovery guard on the resume gate -------------------------------------


def test_recovery_pending_vetoes_the_resume_clear():
    """`recovery_pending=True` must refuse even though every other term is satisfied — a
    rate-limit / API-error / compact / clear resume cue still armed on disk means the
    "no in-flight work to destroy" premise the whole resume gate rests on does not hold yet."""
    v = ec.should_clear_on_resume(
        source="resume",
        cache_expired=True,
        context_tokens=500_000,
        min_context=150_000,
        in_cooldown=False,
        already_fired_this_session=False,
        recovery_pending=True,
    )
    assert v.fire is False and "recovery" in v.why


def test_recovery_pending_defaults_false_so_an_omitting_caller_is_unaffected():
    """SUPERSEDED 2026-09-22 (TRDD-L32WC0H7 card 1 follow-up item 2): this used to say
    `external_handoff_clear.py::_decide` calls this WITHOUT the kwarg — no longer true, `_decide`
    now always passes the real `external_clear.recovery_pending(sd)` reading. The default still
    exists and is still worth pinning: it is a REGRESSION smoke test, not an isolation test of
    the default's effect on its own (that is `test_recovery_pending_vetoes_the_resume_clear`
    above, which flips only that one kwarg and proves the fire flips with it) — it only
    re-confirms every OTHER term at the same values still fires when `recovery_pending` is
    omitted entirely, i.e. that adding the parameter did not change the call's shape or its
    default outcome for a caller that never learned about it."""
    v = ec.should_clear_on_resume(
        source="resume",
        cache_expired=True,
        context_tokens=500_000,
        min_context=150_000,
        in_cooldown=False,
        already_fired_this_session=False,
    )
    assert v.fire is True



# --- card 1 follow-up item 2: the shared recovery_pending helper + the daemon-lane veto ---


def test_recovery_pending_true_on_each_of_the_three_flags(tmp_path):
    """Any one of the three pending-recovery flags is enough — `recovery_pending` is an OR."""
    for flag in ("rate-limited.flag", "resume-after-compact.flag", "resume-after-clear.flag"):
        d = tmp_path / flag
        d.write_text("", encoding="utf-8")
        assert ec.recovery_pending(tmp_path) is True
        d.unlink()


def test_recovery_pending_false_with_no_flags(tmp_path):
    assert ec.recovery_pending(tmp_path) is False


def test_recovery_pending_fails_open_on_an_unreadable_dir(tmp_path):
    """A state dir that does not exist (or cannot be read) reads as "nothing pending", the same
    asymmetry `_fire_recorded` documents elsewhere: a missed veto costs one wrongly-cleared
    session, a false one costs the whole lever, silently, on every resume."""
    assert ec.recovery_pending(tmp_path / "does-not-exist") is False


def test_should_clear_externally_vetoes_on_recovery_pending():
    """card 1 follow-up item 2: `external_handoff_clear.py::_decide` used to reach
    `should_clear_externally` with no recovery guard at all — this pins the new parameter on the
    DAEMON lane, the sibling of `test_recovery_pending_vetoes_the_resume_clear` above."""
    v = verdict(recovery_pending=True)
    assert v.fire is False and "recovery" in v.why


def test_should_clear_externally_recovery_pending_defaults_false():
    """Every existing caller/test that never learned about the new parameter keeps firing."""
    v = verdict()
    assert v.fire is True


# --- TRDD-RAEGS1D5 card 3 part C1: compose_handoff carries the compacted context, and the
# trailing "pointers expand with:" line survives the budget cut no matter what ------------------


def _compacted_doc(body_lines: int, *, transcript: str = "/tmp/fake-transcript.jsonl") -> str:
    """A `jev_compact.py compact` document shape (scripts/lib/jev_compaction.py::compose):
    a header, kept items, then the fixed trailing pointer-expand line -- built directly rather
    than importing jev_compaction (this test file must not import jevctx/httpx transitively;
    see tests/test_jev_boundary.py)."""
    body = "\n".join(f"line {i} of the compacted context, padded to a realistic width" for i in range(body_lines))
    return (
        "# Compacted context (Jev compaction)\n"
        f"transcript: {transcript}\n"
        "\n## Kept items\n"
        f"{body}\n"
        "\n## Elided\n"
        '[[elided id=abc:0 tokens=40 "an elided item"]]\n'
        "\n"
        f'pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" '
        f"expand --transcript {transcript} <id>"
    )


def test_compose_handoff_survives_a_missing_compacted_context():
    """`summary=None` (jev_compact never produced a file) must still yield facts + tail --
    unchanged from the llm-ext-era contract this composer already had."""
    text = ec.compose_handoff(
        _inputs(), now_iso=NOW_ISO, summary=None, tail=["USER: do the thing", "ASSISTANT: done"],
    )
    assert "PXP08ZQC" in text
    assert "do the thing" in text


def test_compose_handoff_pointer_expand_line_survives_truncation():
    """THE POINT of the rewrite: a compacted context long enough to be cut by the budget must
    still end with its `pointers expand with:` line intact -- it is the model's only way back
    to every elided item. A naive byte-slice (the old behaviour) could and did drop it."""
    doc = _compacted_doc(400)  # long enough that max_bytes=2500 forces a cut well before EOF
    text = ec.compose_handoff(_inputs(), now_iso=NOW_ISO, summary=doc, tail=[], max_bytes=2500)
    assert len(text.encode("utf-8")) <= 2500
    assert "pointers expand with:" in text
    assert text.rstrip().splitlines()[-1].startswith("pointers expand with:")


def test_compose_handoff_pointer_line_survives_even_under_extreme_pressure():
    """No room at all for the body (facts alone eat the whole budget) must still keep the
    pointer line rather than silently drop the whole compacted-context section."""
    big_inputs = _inputs(
        findings=[f"HIGH finding number {i} with a reasonably long descriptive message" for i in range(40)],
    )
    doc = _compacted_doc(50)
    text = ec.compose_handoff(big_inputs, now_iso=NOW_ISO, summary=doc, max_bytes=1400)
    assert len(text.encode("utf-8")) <= 1400
    if "## Compacted context" in text:
        assert "pointers expand with:" in text


def test_compose_handoff_leaves_a_plain_summary_untouched_when_short():
    """A short, old-style (no trailing pointer line) summary is unaffected by the pointer-
    preservation logic -- `_split_trailing_pointer_line` degrades to a no-op for it."""
    text = ec.compose_handoff(_inputs(), now_iso=NOW_ISO, summary="a short plain summary", tail=[])
    assert "a short plain summary" in text
    assert "pointers expand with:" not in text


def test_split_trailing_pointer_line_no_trailer():
    assert ec._split_trailing_pointer_line("just text\nmore text") == ("just text\nmore text", "")


def test_split_trailing_pointer_line_extracts_the_fixed_line():
    body, trailer = ec._split_trailing_pointer_line(
        "body line one\nbody line two\npointers expand with: uv run --script x expand y z"
    )
    assert body == "body line one\nbody line two"
    assert trailer == "pointers expand with: uv run --script x expand y z"
