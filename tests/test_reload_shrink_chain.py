"""Shrink-before-reload: `/janitor-reload-plugins` clears first so the cache-prefix break
lands on a near-floor context (owner directive 2026-08-14).

WHY these tests and not others. `/reload-plugins` breaks the prompt-cache prefix, so on a
500k session the next turn re-caches everything at ~1.25x instead of reading it at ~0.1x
(measured; `token_meter.RELOAD_GUARD_DEFAULT_THRESHOLD`). Three properties carry the whole
design, and each is asserted here rather than trusted:

  1. WHEN we shrink — shrinking is destructive (`/clear` is unrecoverable), so every
     refusal direction must fail toward the RECOVERABLE outcome.
  2. THE ORDER of the post-clear bootstrap — the reload must come FIRST, before
     `/janitor-arm`. Between `/clear` and the first API turn no cache has been written, so
     the reload there is FREE; after arm it re-bills the fresh base at 1.25x. An edit that
     reorders this list silently destroys the entire saving, and nothing else would notice.
  3. THAT THE SETTLE IS REAL — `/reload-plugins` fires no hook, so a mid-swap registry can
     swallow the `/janitor-arm` that follows and leave the session cleared AND unwakeable.

SAFETY: nothing here fires a real `/clear` or `/reload-plugins`. The pure predicates are
called directly and the chain is exercised with injected fakes.
"""

from __future__ import annotations

import importlib.util as _u
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))


def _load(name: str, relpath: str):
    spec = _u.spec_from_file_location(name, str(_PROJECT_ROOT / relpath))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rt = _load("reload_trigger_shrink_uut", "scripts/reload_trigger.py")
ct = _load("clear_trigger_shrink_uut", "scripts/clear_trigger.py")
import terminal_trigger  # noqa: E402
import token_meter as tm  # noqa: E402

# --- 1. WHEN do we shrink -----------------------------------------------------------

@pytest.mark.parametrize(
    ("mode", "ctx", "hard", "expected", "why"),
    [
        ("auto", 500_000, False, True, "above threshold — the expensive case this exists for"),
        ("auto", 350_000, False, True, "exactly at the threshold counts as above"),
        ("auto", 320_000, False, False, "below threshold: clearing to reach the ~305k floor saves nothing"),
        ("auto", None, False, False, "unreadable context must NEVER clear on a guess"),
        ("auto", 500_000, True, False, "--hard is urgent; a shrink delays the very reload it needs"),
        ("never", 500_000, False, False, "explicit opt-out wins over any context size"),
        ("force", 100_000, False, True, "force overrides the threshold"),
        ("force", None, False, True, "force does not need a context reading"),
        ("force", 500_000, True, False, "--hard beats force — urgency outranks thrift"),
    ],
)
def test_should_shrink_truth_table(mode, ctx, hard, expected, why) -> None:
    """should_shrink refuses in every direction that would trade a recoverable cost for an
    unrecoverable /clear, and only shrinks when the reload is genuinely expensive."""
    assert rt.should_shrink(mode, context_tokens=ctx, threshold=350_000, hard=hard) is expected, why


def test_shrink_threshold_agrees_with_the_dispatch_reload_guard() -> None:
    """The trigger's threshold IS dispatch's reload-guard threshold — same env var, same
    default. If these two ever diverge, dispatch defers a reload this script would have
    handled cheaply (or the reverse) and the disagreement is silent."""
    assert rt.shrink_threshold(env={}) == tm.RELOAD_GUARD_DEFAULT_THRESHOLD
    assert rt.shrink_threshold(
        env={"CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_THRESHOLD": "123456"}
    ) == 123456


# --- 2. THE ORDER of the post-clear bootstrap ---------------------------------------

def test_reload_is_the_first_bootstrap_step_before_arm() -> None:
    """The reload must precede /janitor-arm in the post-clear bootstrap.

    This is the entire cost argument: between /clear and the first API turn no prompt cache
    has been written yet, so /reload-plugins there invalidates nothing. Placing it after
    /janitor-arm (which IS an API turn) means the freshly-written ~305k base is re-billed at
    1.25x on the next turn. Reordering this list would keep every other test green while
    silently deleting the saving, so it is asserted explicitly."""
    then = [rt.RELOAD_CMD, *ct.BOOTSTRAP_CMDS]
    assert then[0] == rt.RELOAD_CMD
    assert then.index(rt.RELOAD_CMD) < then.index(ct.ARM_CMD)
    assert ct.ARM_CMD in then and ct.RESUME_CMD in then, (
        "dropping arm strands the session unwakeable (/clear destroys the cron); "
        "dropping resume strands it unresumed"
    )


def test_bootstrap_alias_tracks_the_private_pair() -> None:
    """BOOTSTRAP_CMDS is the public alias other triggers compose on. It must track the
    private tuple, so a third bootstrap step is inherited rather than silently missed."""
    assert ct.BOOTSTRAP_CMDS == ct._BOOTSTRAP_CMDS


# --- 3. THAT THE SETTLE IS REAL ------------------------------------------------------

class _FakeChannel:
    """Records the interleaving of typed commands and sleeps, so ordering is observable."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def sleeper(self, seconds: float) -> None:
        if seconds > 0:
            self.events.append(f"sleep:{seconds}")


def test_settle_between_s_pauses_between_bootstrap_commands(monkeypatch) -> None:
    """run_chained_inject sleeps between consecutive `then` commands when settle_between_s
    is set — and NOT before the first one (the clear-observed gate is a real signal and
    needs no padding).

    Exercises the real function with the injection points faked, so a regression that drops
    the sleep is caught rather than assumed."""
    ch = _FakeChannel()

    monkeypatch.setattr(terminal_trigger, "build_type_only_steps", lambda t, c: ["type"])
    monkeypatch.setattr(terminal_trigger, "build_submit_steps", lambda t: ["submit"])
    monkeypatch.setattr(
        terminal_trigger, "_step_runners", lambda t: ((lambda cmd: (lambda: None)), None, None)
    )
    monkeypatch.setattr(terminal_trigger, "_await_fresh_session", lambda *a, **k: True)

    def _fake_inject(terminal, cmd, **kwargs):
        ch.events.append(f"cmd:{cmd}")
        return True, "sent"

    monkeypatch.setattr(terminal_trigger, "inject_until_sent", _fake_inject)

    ok, why = terminal_trigger.run_chained_inject(
        {"kind": "tmux", "pane": "%1"},
        first="/clear",
        then=["/reload-plugins --force", "/janitor-arm", "/janitor-resume"],
        gate_stamp=Path("/nonexistent"),
        gate_baseline=0,
        settle_between_s=4.0,
        sleeper=ch.sleeper,
    )

    assert ok, why
    assert ch.events == [
        "cmd:/clear",
        "cmd:/reload-plugins --force",
        "sleep:4.0",
        "cmd:/janitor-arm",
        "sleep:4.0",
        "cmd:/janitor-resume",
    ], "the settle must fall AFTER the reload and BEFORE arm — that is the window it exists to shrink"


def test_settle_defaults_to_no_pause(monkeypatch) -> None:
    """settle_between_s defaults to 0.0, so every existing caller keeps its historical
    back-to-back behaviour and this change is additive."""
    ch = _FakeChannel()
    monkeypatch.setattr(terminal_trigger, "build_type_only_steps", lambda t, c: ["type"])
    monkeypatch.setattr(terminal_trigger, "build_submit_steps", lambda t: ["submit"])
    monkeypatch.setattr(
        terminal_trigger, "_step_runners", lambda t: ((lambda cmd: (lambda: None)), None, None)
    )
    monkeypatch.setattr(terminal_trigger, "_await_fresh_session", lambda *a, **k: True)
    monkeypatch.setattr(
        terminal_trigger,
        "inject_until_sent",
        lambda terminal, cmd, **kw: (ch.events.append(f"cmd:{cmd}"), (True, "sent"))[1],
    )

    ok, _ = terminal_trigger.run_chained_inject(
        {"kind": "tmux", "pane": "%1"},
        first="/clear",
        then=["/janitor-arm", "/janitor-resume"],
        gate_stamp=Path("/nonexistent"),
        gate_baseline=0,
        sleeper=ch.sleeper,
    )
    assert ok
    assert not [e for e in ch.events if e.startswith("sleep:")], "default must add no pauses"


# --- 4. the shrink path refuses rather than clearing blind ---------------------------

def test_spawn_shrink_chain_refuses_an_unreadable_channel(monkeypatch) -> None:
    """A pane that cannot be read back cannot verify its own /clear, so spawn_shrink_chain
    reports (False, why) and the caller falls back to a direct reload. Clearing blind is the
    one unrecoverable failure in this system — an expensive reload is merely expensive."""
    monkeypatch.setattr(ct, "_this_terminal", lambda: {"kind": "unknown"})
    monkeypatch.setattr(terminal_trigger, "channel_is_readable", lambda t: False)
    spawned_calls: list[dict] = []
    monkeypatch.setattr(ct, "_spawn_chain", lambda payload, **kw: spawned_calls.append(payload))

    spawned, why = ct.spawn_shrink_chain(then=["/reload-plugins --force"], directive="x")

    assert spawned is False
    assert "cannot be read back" in why
    assert spawned_calls == [], "nothing may be typed when the channel cannot be verified"


def test_spawn_shrink_chain_passes_settle_and_then_through(monkeypatch, tmp_path) -> None:
    """The caller's `then` list and settle reach the chain payload unaltered — the chain is
    reused, not re-implemented, so its lock and gate still apply."""
    monkeypatch.setattr(ct, "_this_terminal", lambda: {"kind": "tmux", "pane": "%1"})
    monkeypatch.setattr(terminal_trigger, "channel_is_readable", lambda t: True)
    monkeypatch.setattr(ct, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(ct, "_read_handoff", lambda: "handoff citing TRDD-ABCD1234")
    monkeypatch.setattr(ct, "_gate_baseline", lambda: 7)
    captured: list[dict] = []
    monkeypatch.setattr(ct, "_spawn_chain", lambda payload, **kw: captured.append(payload))

    then = ["/reload-plugins --force", *ct.BOOTSTRAP_CMDS]
    spawned, _ = ct.spawn_shrink_chain(then=then, directive="resume me", settle_between_s=4.0)

    assert spawned is True
    assert captured[0]["first"] == ct.CLEAR_CMD
    assert captured[0]["then"] == then
    assert captured[0]["settle_between_s"] == 4.0
    assert captured[0]["gate_baseline"] == 7


# --- 5. the two triggers must not drift apart ----------------------------------------

def test_both_triggers_share_ONE_shrink_policy() -> None:
    """`/reload-plugins` and `/reload-skills` decide identically, because they call the
    SAME objects — not because two copies happen to agree today.

    Their own docstrings say to "keep the two in step", and they had already drifted: the
    plugins path grew a context guard and the skills path never got one, so a skills reload
    on a 500k session paid the full re-cache with nothing even deferring it. Identity (`is`)
    is asserted rather than equality, because equal-but-separate copies are exactly what
    drifts."""
    import reload_shrink

    rst = _load("reload_skills_trigger_shrink_uut", "scripts/reload_skills_trigger.py")
    assert rt.should_shrink is reload_shrink.should_shrink
    assert rt.shrink_threshold is reload_shrink.shrink_threshold
    assert rt.RELOAD_SETTLE_S is reload_shrink.RELOAD_SETTLE_S
    assert rst.reload_shrink is reload_shrink, "the skills trigger must use the shared policy"


def test_skills_chain_puts_the_reload_before_arm_too() -> None:
    """The skills chain carries the same ordering invariant as the plugins one: reload
    first, while no prompt cache has been written yet, then arm, then resume."""
    rst = _load("reload_skills_trigger_order_uut", "scripts/reload_skills_trigger.py")
    then = [rst.RELOAD_SKILLS_CMD, *ct.BOOTSTRAP_CMDS]
    assert then[0] == rst.RELOAD_SKILLS_CMD
    assert then.index(rst.RELOAD_SKILLS_CMD) < then.index(ct.ARM_CMD)
    assert then[-1] == ct.RESUME_CMD
