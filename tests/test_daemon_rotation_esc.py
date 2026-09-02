"""Tests for the rotation-triggered ESC pass (TRDD-NACCL0CB).

The 2026-09-02 Fable-wall incident: the rotator swapped the account, stamped
`rotation-success.ts`, and every Claude Code pane kept showing
`✻ Fable limit reached · Retrying in 5h (Sep 8 at 5pm) · attempt 1/5` until the owner pressed
ESC by hand. Two things made the existing machinery blind: the typing gate deferred every beat
because the owner was typing in ANOTHER session, and the `retry_wedged` diagnosis needs an
attempt number that advances, which a 5-hour backoff never does.

Real pass, real per-project state files under tmp roots. Three seams, each for a hard reason:
``gather_fleet`` (a live wedged session cannot be conjured), ``capture_pane_text`` (a real
terminal read), and ``fleet_inject.fire`` (a test must NEVER send ESC to the developer's real
panes).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "oauth_rotator"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import daemon  # type: ignore[import-not-found]  # noqa: E402
import fleet_scan  # type: ignore[import-not-found]  # noqa: E402
import global_state as gs  # type: ignore[import-not-found]  # noqa: E402
import session_liveness as sl  # type: ignore[import-not-found]  # noqa: E402

WEDGE_LINE = "✻ Fable limit reached · Retrying in 5h (Sep 8 at 5pm) · attempt 1/5"
BORDER = "─" * 110
CHROME = f"{BORDER}\n❯ Press up to edit queued messages\n{BORDER}\n  🤖 Fable 5.1 v2.1.258 | 📁 proj\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
# Captured on this host 2026-09-02 21:03 from the pane that stayed wedged after the rotation:
# the retry line sits one queued command above the input box's upper border.
WEDGED_FRAME = (
    "⏺ janitor heartbeat\n  Ran 1 shell command\n✻ Running scheduled task (Sep 2 8:38pm)\n"
    "⏺ Remote Control disconnected — run /remote-control\n  /remote-control\n"
    "  Janitor re-arm step 1: prepare\n  ⎿  $ uv run --script --quiet arm_prepare.py\n"
    + WEDGE_LINE + "\n  ❯ /janitor-arm\n" + CHROME
)
CALM_FRAME = "⏺ some earlier output\n  detail\n✽ Boogieing… (1m 13s · ↓ 779 tokens)\n     (ctrl+b to run in background)\n" + CHROME
# The false-hit shape the reviewer named: an assistant reply QUOTING the red line, ending the
# turn, so its last rows sit directly above the input box.
QUOTED_FRAME = (
    "⏺ Root cause: every pane showed\n  " + WEDGE_LINE + "\n  until you pressed ESC by hand.\n"
    "✻ Cogitated for 9s · done 8:46 PM\n" + CHROME
)
# The second false-hit shape (review fork, settled on this session's own frame): a PAST USER
# PROMPT echoes at column 0 as `❯ text`, and the owner typed the red line into a prompt.
ECHO_FRAME = (
    "❯ the janitor failed, all sessions showed `" + WEDGE_LINE + "`\n"
    "⏺ Diagnosed: the typing gate deferred the ESC.\n" + CHROME
)


def _inst(diagnosis: str, root: Path, terminal: dict, *, awaiting: bool = False) -> "fleet_scan.Instance":
    return fleet_scan.Instance(
        pid=1, command="claude", tty="ttys1", project_root=str(root), terminal=terminal,
        diagnosis=diagnosis, recovery=None, dispatch_age_s=None, active=False,
        transcript_age_s=None, trailing_enqueues=0, awaiting_user=awaiting,
    )


def _setup(monkeypatch, tmp_path: Path, fleet: list, *, frame: str | None = WEDGED_FRAME,
           hid_idle: float = 0.0, fire: str = "1") -> list:
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    monkeypatch.setenv("JANITOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED", "0")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FLEET_RECOVERY_ENABLED", fire)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_SESSION_LIVENESS_ENABLED", "1")
    for fn in (daemon.state.project_root, daemon.state.janitor_root,
               daemon.state.state_dir, daemon.state.log_dir):
        fn.cache_clear()
    recorded: list = []
    monkeypatch.setattr(daemon.fleet_inject, "fire", lambda plan: bool(recorded.append(plan)) or True)
    monkeypatch.setattr(daemon.fleet_scan, "gather_fleet",
                        lambda *, now, sweep_stale_rate_limit_s=None: fleet)
    monkeypatch.setattr(daemon.fleet_scan, "capture_pane_text", lambda terminal: frame)
    # hid_idle 0.0 = the owner is typing RIGHT NOW — the condition that deferred every beat on
    # 2026-09-02. The ESC pass must not care.
    monkeypatch.setattr(daemon.user_intent, "hid_idle_seconds", lambda **kw: hid_idle)
    return recorded


def _escs(recorded: list) -> list:
    return [p for p in recorded if p.get("command") == ""]


def test_a_fresh_rotation_escs_the_wedged_pane_even_while_the_owner_types(tmp_path, monkeypatch) -> None:
    """THE incident: rotation done, pane on the red line, owner typing elsewhere → ESC anyway."""
    root = tmp_path / "proj"
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})])
    gs.record_rotation_success(int(time.time()))
    daemon.task_session_liveness()

    assert len(_escs(fired)) == 1, "one ESC must reach the wedged pane"
    assert fired[0]["channel"] == "tmux"
    sd = root / ".janitor" / "state"
    assert (sd / "rate-limited.flag").is_file(), "the flag is what makes dispatch resume after the Stop"
    assert (sd / daemon.state.DAEMON_ROTATION_ESC_FILE).read_text().strip() == str(gs.rotation_success_epoch())


def test_one_esc_per_pane_per_rotation_and_a_new_rotation_escs_again(tmp_path, monkeypatch) -> None:
    """A second beat inside the same rotation window must not ESC twice; a NEW rotation must."""
    root = tmp_path / "proj"
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})])
    first = int(time.time()) - 30
    gs.record_rotation_success(first)
    daemon.task_session_liveness()
    daemon.task_session_liveness()
    assert len(_escs(fired)) == 1, "same rotation → exactly one ESC"

    gs.record_rotation_success(first + 20)
    daemon.task_session_liveness()
    assert len(_escs(fired)) == 2, "a new rotation epoch re-arms the ESC"


def test_the_control_no_rotation_types_nothing(tmp_path, monkeypatch) -> None:
    """Same wedged pane, no rotation stamp: the pass must stay silent (it is rotation-keyed)."""
    root = tmp_path / "proj"
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})])
    daemon.task_session_liveness()
    assert _escs(fired) == []


def test_a_stale_rotation_does_not_authorize_an_esc(tmp_path, monkeypatch) -> None:
    """Only a rotation inside the wake window counts — an hour-old stamp is not evidence."""
    root = tmp_path / "proj"
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})])
    gs.record_rotation_success(int(time.time()) - daemon._ROTATION_WAKE_WINDOW_S - 60)
    daemon.task_session_liveness()
    assert _escs(fired) == []


def test_a_calm_pane_is_not_escd_after_a_rotation(tmp_path, monkeypatch) -> None:
    """A rotation is not a licence to ESC every pane — only the ones showing the wedge."""
    root = tmp_path / "proj"
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})], frame=CALM_FRAME)
    gs.record_rotation_success(int(time.time()))
    daemon.task_session_liveness()
    assert _escs(fired) == []
    assert not (root / ".janitor" / "state" / "rate-limited.flag").exists()


def test_a_reply_quoting_the_wedge_line_is_prose_not_a_wedge(tmp_path, monkeypatch) -> None:
    """The false-hit shape: an assistant reply quoting the red line right above the input box
    must NOT be ESC'd (that would interrupt a working session and flag it rate-limited)."""
    root = tmp_path / "proj"
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})], frame=QUOTED_FRAME)
    gs.record_rotation_success(int(time.time()))
    daemon.task_session_liveness()
    assert _escs(fired) == []
    assert not (root / ".janitor" / "state" / "rate-limited.flag").exists()


def test_a_prompt_echo_quoting_the_wedge_line_is_not_escd(tmp_path, monkeypatch) -> None:
    """The owner typed the red line into a prompt; that echo must not get a working session ESC'd."""
    root = tmp_path / "proj"
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})], frame=ECHO_FRAME)
    gs.record_rotation_success(int(time.time()))
    daemon.task_session_liveness()
    assert _escs(fired) == []


def test_server_owned_and_unarmed_and_dead_panes_are_never_escd(tmp_path, monkeypatch) -> None:
    """The hands-off classes stay hands-off even with the wedge on screen."""
    fleet = [
        _inst("server_owned", tmp_path / "a", {"tmux_pane": "%1"}),
        _inst("unarmed", tmp_path / "b", {"tmux_pane": "%2"}),
        _inst("dead", tmp_path / "c", {"tmux_pane": "%3"}),
        _inst("healthy", tmp_path / "d", {"tmux_pane": "%4"}, awaiting=True),
    ]
    fired = _setup(monkeypatch, tmp_path, fleet)
    gs.record_rotation_success(int(time.time()))
    daemon.task_session_liveness()
    assert _escs(fired) == []


def test_an_unreadable_pane_is_skipped_not_guessed(tmp_path, monkeypatch) -> None:
    """capture_pane_text → None means CANNOT ASSESS; the pass must neither ESC nor stamp."""
    root = tmp_path / "proj"
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})], frame=None)
    gs.record_rotation_success(int(time.time()))
    daemon.task_session_liveness()
    assert _escs(fired) == []
    assert not (root / ".janitor" / "state" / daemon.state.DAEMON_ROTATION_ESC_FILE).exists()


def test_dry_run_escs_nothing_and_stamps_nothing(tmp_path, monkeypatch) -> None:
    """With fleet recovery off the pass only logs what it would do."""
    root = tmp_path / "proj"
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})], fire="0")
    gs.record_rotation_success(int(time.time()))
    daemon.task_session_liveness()
    assert _escs(fired) == []
    sd = root / ".janitor" / "state"
    assert not (sd / "rate-limited.flag").exists()
    assert not (sd / daemon.state.DAEMON_ROTATION_ESC_FILE).exists()


def test_the_rotator_tick_escs_a_wedged_pane_without_waiting_for_the_liveness_beat(tmp_path, monkeypatch) -> None:
    """Second 2026-09-02 incident: the wall landed between two liveness beats and the owner
    rotated by hand in the gap — the 60 s rotator tick must run the ESC pass too."""
    root = tmp_path / "proj"
    fired = _setup(monkeypatch, tmp_path, [_inst("healthy", root, {"tmux_pane": "%5"})])
    monkeypatch.setattr(daemon.oauth_supervisor, "opt_in_present", lambda: True)
    monkeypatch.setattr(daemon, "_run_workload", lambda *a, **kw: None)
    gs.record_rotation_success(int(time.time()))
    daemon.task_oauth_rotator_tick()
    assert len(_escs(fired)) == 1, "the tick itself must ESC the wedged pane"
    daemon.task_session_liveness()
    assert len(_escs(fired)) == 1, "the liveness beat must not ESC it a second time (per-epoch dedupe)"


def _rearm_isolated(monkeypatch) -> None:
    """Isolate the new pre-type guard: the downstream field-busy checks read the real pane."""
    monkeypatch.setattr(daemon.fleet_inject, "command_plan_field_busy", lambda terminal, plan: False)
    monkeypatch.setattr(daemon.fleet_inject, "field_holds_our_queued_command", lambda terminal, plan: "")


def test_a_soft_command_is_never_typed_into_a_pane_showing_the_retry_line(tmp_path, monkeypatch) -> None:
    """The owner's 'the janitor is blind' finding: a cron_dead pane on the red line must NOT get
    `/janitor-arm` queued behind it (every queued command costs the human one more ESC)."""
    root = tmp_path / "proj"
    fired = _setup(monkeypatch, tmp_path, [_inst("cron_dead", root, {"tmux_pane": "%5"})],
                   frame=WEDGED_FRAME, hid_idle=600.0)
    _rearm_isolated(monkeypatch)
    daemon.task_session_liveness()
    assert [p for p in fired if p.get("command")] == [], "no command may be typed at a wedged pane"


def test_the_control_a_calm_cron_dead_pane_still_gets_its_rearm(tmp_path, monkeypatch) -> None:
    """Same instance, calm frame: the guard must not swallow the ordinary rearm."""
    root = tmp_path / "proj"
    fired = _setup(monkeypatch, tmp_path, [_inst("cron_dead", root, {"tmux_pane": "%5"})],
                   frame=CALM_FRAME, hid_idle=600.0)
    _rearm_isolated(monkeypatch)
    daemon.task_session_liveness()
    assert any("janitor-arm" in (p.get("command") or "") for p in fired), "the rearm must still fire"


def test_tail_parser_anchors_on_the_input_box_and_column_zero() -> None:
    """The positional guard, against frames shaped like this host's real captures."""
    assert sl.retry_wedge_attempt_at_tail(WEDGED_FRAME) == 1
    assert sl.retry_wedge_attempt_at_tail(CALM_FRAME) is None
    assert sl.retry_wedge_attempt_at_tail(QUOTED_FRAME) is None, "indented quote = prose"
    assert sl.retry_wedge_attempt_at_tail(ECHO_FRAME) is None, "a prompt echo is not a status row"
    # The session-limit and 429 variants share the status row and the same regex shape.
    session_limit = "✻ Session limit reached · Retrying in 2m 50s (2:10pm) · attempt 1/300\n" + CHROME
    assert sl.retry_wedge_attempt_at_tail(session_limit) == 1
    plain_429 = "· 429 Rate limited · Retrying in 0s · attempt 5/300\n" + CHROME
    assert sl.retry_wedge_attempt_at_tail(plain_429) == 5
    # A narrow pane wraps the status row (per-row matching returned None at 60 columns). The
    # continuation indent is unmeasured, so both an indented and a flush-left wrap must join.
    # Every width from 30 to 120 columns, all three wall variants: at 15 of them the wrap lands
    # right before the `·` separator, so the continuation row starts with the middle dot.
    import textwrap
    variants = {WEDGE_LINE: 1, session_limit.split("\n")[0]: 1, plain_429.split("\n")[0]: 5}
    for status, expected in variants.items():
        for width in range(30, 121):
            for indent in ("  ", ""):
                wrapped = "\n".join(textwrap.wrap(status, width, subsequent_indent=indent))
                got = sl.retry_wedge_attempt_at_tail(wrapped + "\n" + CHROME)
                assert got == expected, f"{status[:14]!r} at {width} cols indent={indent!r}: {got}"
    # The join must not stitch an indented QUOTE of the wedge line onto a calm status row.
    stitched = "✻ Cogitated for 9s\n  " + WEDGE_LINE + "\n" + CHROME
    assert sl.retry_wedge_attempt_at_tail(stitched) is None
    # A column-0 copy of the line far above the status block (an old turn) does not count.
    old_turn = WEDGE_LINE + "\n" + "\n".join(f"⏺ step {i}" for i in range(12)) + "\n" + CHROME
    assert sl.retry_wedge_attempt_at_tail(old_turn) is None
    # No input box in the frame at all (bare tmux capture): fall back to the bottom rows.
    assert sl.retry_wedge_attempt_at_tail("noise\n" + WEDGE_LINE + "\n") == 1
    assert sl.retry_wedge_attempt_at_tail("") is None
