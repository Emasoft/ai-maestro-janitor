"""Tests for the daemon-side fleet scanner (TRDD-324223a6).

The parsers are pure — real captured tool output, no mocks. ``diagnose_root``
runs against real files in a tmp tree (still no mocks; just real ``.janitor``
state). The load-bearing properties: a claude process is recognized from either
install shape; a TTY round-trips ps→lsof→iTerm; and a ``disarmed.flag`` makes a
project sacrosanct no matter how broken its other signals look.

The ai-maestro / Linux-GUI identity tagging (TRDD-ME8V2YJF follow-up) is tested
the same way: pure functions given pre-fetched inputs, and ``_aimaestro_agents``
with its two subprocess-touching calls monkeypatched — no real CLI, no network.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import fleet_scan as fs  # type: ignore[import-not-found]  # noqa: E402
import pytest  # noqa: E402


def test_parse_ps_claude_recognizes_both_shapes() -> None:
    """A versions-launcher path and a bare 'claude' argv0 are both claude; an
    unrelated daemon and a non-matching node cmd are not. TTY is normalized."""
    txt = (
        "  101 s001 /Users/x/.local/share/claude/versions/2.1.0/claude --continue\n"
        "  202 ?? /usr/sbin/some-daemon --foo\n"
        "  404 s004 claude\n"
        "   bad line without enough fields\n"
    )
    res = fs.parse_ps_claude(txt)
    pids = sorted(r[0] for r in res)
    assert pids == [101, 404]
    by_pid = {r[0]: r[1] for r in res}
    assert by_pid[101] == "ttys001"
    assert by_pid[404] == "ttys004"


def test_parse_ps_claude_excludes_one_shot_subcommands() -> None:
    """TRDD-R3D5YRQJ, from a live scan: `claude daemon run` and `claude plugin marketplace
    update` were counted among the fleet's `cron_dead` instances and scheduled for `rearm`.
    Neither is a session — neither has a cron to be dead. Both argv strings are the REAL ones
    recorded in that scan, not synthesized shapes."""
    txt = (
        "46727 ?? claude daemon run --json-path /tmp/d.json --origin transient\n"
        "54330 ?? claude plugin marketplace update\n"
        " 7588 s003 claude --add-dir /tmp --continue\n"
    )
    assert sorted(r[0] for r in fs.parse_ps_claude(txt)) == [7588]


def test_a_real_session_with_an_empty_tty_is_still_included() -> None:
    """The opposite and worse mistake. A headless/harness session has no tty, so a tty-shaped
    filter would drop exactly the sessions the guardian exists to recover. The discriminator
    must be argv-shaped, and an empty tty must not disqualify anything."""
    txt = "9001 ?? claude --agent worker --dangerously-skip-permissions\n"
    assert [r[0] for r in fs.parse_ps_claude(txt)] == [9001]


def test_flag_values_are_never_mistaken_for_subcommands() -> None:
    """Only position 1 is consulted, so a flag VALUE cannot be read as a verb. `--agent
    plugin` is adversarial on purpose: the value is itself a real subcommand name, and a
    'first non-flag token' scan would drop this real session."""
    for cmd in (
        "claude --add-dir /tmp --continue",
        "claude --agent plugin",
        "claude --model sonnet --continue",
    ):
        assert fs.is_repl_invocation(cmd), cmd


def test_an_unknown_first_token_is_treated_as_a_session() -> None:
    """The ratified failure direction: including a non-session costs one no-op recovery,
    excluding a real session costs a lost one. So a future (or hidden) verb this set does not
    know must fail toward SESSION — the old bug, in the safe direction."""
    assert fs.is_repl_invocation("claude some-future-verb --flag")
    assert fs.is_repl_invocation("claude")
    # ...but every hidden verb we have actually OBSERVED must be KNOWN, not left to that
    # fallback. `daemon` motivated the card; `bg-spare` and `bg-pty-host` were found running
    # on the host while fixing it — one live scan, two more verbs no help listing mentions.
    for hidden in ("claude daemon run",
                   "claude bg-spare --bg-spare /tmp/x.claim.sock",
                   "claude bg-pty-host --bg-pty-host /tmp/x.pty.sock 200 50"):
        assert not fs.is_repl_invocation(hidden), hidden


def test_parse_iterm_sessions() -> None:
    """tty|id lines → {normalized_tty: id}; malformed/half rows dropped. The
    delimiter is a literal '|' because AppleScript's `tab` constant emits the
    three letters 'tab' via osascript -e, not a tab byte (the bug that made every
    instance read UNREACHABLE)."""
    txt = "/dev/ttys003|4C4A6F99-ABC\n/dev/ttys005|5FDB-DEF\n|onlyid\n/dev/ttys006|\n"
    assert fs.parse_iterm_sessions(txt) == {
        "ttys003": "4C4A6F99-ABC",
        "ttys005": "5FDB-DEF",
    }


def test_parse_tmux_panes() -> None:
    """`#{pane_tty} #{pane_id}` lines → {normalized_tty: pane}; junk dropped."""
    txt = "/dev/ttys004 %5\n/dev/ttys007 %9\ngarbage-no-pane\n"
    assert fs.parse_tmux_panes(txt) == {"ttys004": "%5", "ttys007": "%9"}


def test_find_janitor_root(tmp_path: Path) -> None:
    """Walks up to the nearest .janitor project; None when none above / no cwd."""
    proj = tmp_path / "proj"
    (proj / ".janitor" / "state").mkdir(parents=True)
    sub = proj / "a" / "b"
    sub.mkdir(parents=True)
    assert fs.find_janitor_root(str(sub)) == os.path.realpath(str(proj))
    assert fs.find_janitor_root(str(tmp_path)) is None
    assert fs.find_janitor_root(None) is None


def test_diagnose_root_health_progression(tmp_path: Path) -> None:
    """Transcript age drives the diagnosis: fresh = healthy (working OR heartbeat
    firing); stale = cron_dead→rearm; +rate-limit = frozen→esc_nudge (ESC-only,
    TRDD-P7WU40G9); +disarm = unarmed→leave alone (sacrosanct even though stale+rate-limited)."""
    root = tmp_path / "p"
    sdir = root / ".janitor" / "state"
    sdir.mkdir(parents=True)
    (root / ".janitor" / "logs").mkdir(parents=True)
    now = 1_000_000

    assert fs.diagnose_root(str(root), now=now, transcript_age=60)[:2] == ("healthy", None)
    assert fs.diagnose_root(str(root), now=now, transcript_age=3600)[:2] == ("cron_dead", "rearm")

    (sdir / "rate-limited.flag").write_text("")
    assert fs.diagnose_root(str(root), now=now, transcript_age=3600)[:2] == ("frozen", "ladder")

    (sdir / "disarmed.flag").write_text("")  # user opted out → sacrosanct
    assert fs.diagnose_root(str(root), now=now, transcript_age=3600)[:2] == ("unarmed", None)


def test_diagnose_root_fresh_transcript_is_healthy_despite_rate_limit(tmp_path: Path) -> None:
    """A fresh transcript (working OR heartbeat-firing) is HEALTHY even with a
    rate-limit flag — the exact false positive the dashboard surfaced. dispatch.log
    is never consulted for liveness; only the transcript is."""
    root = tmp_path / "p"
    sdir = root / ".janitor" / "state"
    sdir.mkdir(parents=True)
    (sdir / "rate-limited.flag").write_text("")
    assert fs.diagnose_root(str(root), now=1_000_000, transcript_age=60)[:2] == ("healthy", None)


def test_diagnose_root_unknown_transcript_is_not_flagged(tmp_path: Path) -> None:
    """An unlocatable transcript (age None) is NOT flagged — we never act on a
    liveness we cannot actually assess (conservative, fail-safe)."""
    root = tmp_path / "p"
    (root / ".janitor" / "state").mkdir(parents=True)
    assert fs.diagnose_root(str(root), now=1_000_000, transcript_age=None)[:2] == ("healthy", None)


def test_tag_aimaestro_identity_matches_by_root() -> None:
    """A matching ai-maestro agent (workingDirectory == the instance's project root)
    tags aimaestro_session/aimaestro_cli; no match, no cli, or no agents => no-op
    (never a dangling identity key on a host without ai-maestro running)."""
    agents = [{"workingDirectory": "/proj/a", "session": {"tmuxSessionName": "agent-a"}}]

    terminal: dict = {}
    fs.tag_aimaestro_identity(terminal, agents=agents, cli="/bin/aimaestro-agent.sh", root="/proj/a")
    assert terminal == {"aimaestro_session": "agent-a", "aimaestro_cli": "/bin/aimaestro-agent.sh"}

    no_match: dict = {}
    fs.tag_aimaestro_identity(no_match, agents=agents, cli="/bin/aimaestro-agent.sh", root="/proj/other")
    assert no_match == {}

    no_cli: dict = {}
    fs.tag_aimaestro_identity(no_cli, agents=agents, cli=None, root="/proj/a")
    assert no_cli == {}

    no_agents: dict = {}
    fs.tag_aimaestro_identity(no_agents, agents=[], cli="/bin/aimaestro-agent.sh", root="/proj/a")
    assert no_agents == {}


def test_tag_linux_gui_identity_only_when_no_tmux_or_iterm() -> None:
    """The GUI tag is the LAST-RESORT identity: it never overrides an already-
    resolved tmux/iTerm channel, and no-ops with no channel."""
    reachable = {"tmux_pane": "%1"}
    fs.tag_linux_gui_identity(reachable, channel="wtype")
    assert "linux_gui_channel" not in reachable

    unreachable: dict = {}
    fs.tag_linux_gui_identity(unreachable, channel="xdotool")
    assert unreachable == {"linux_gui_channel": "xdotool"}

    no_channel: dict = {}
    fs.tag_linux_gui_identity(no_channel, channel=None)
    assert no_channel == {}


def test_aimaestro_agents_best_effort_on_missing_cli(monkeypatch) -> None:
    """No CLI resolvable => (None, [], False) — never raises, never shells out further."""
    monkeypatch.setattr(fs.terminal_trigger, "_resolve_aimaestro_cli", lambda env: None)
    assert fs._aimaestro_agents({}) == (None, [], False)


def test_aimaestro_agents_parses_json_list(monkeypatch) -> None:
    """A successful `list --json` call is parsed into the agents list (both the bare
    list and the {"agents": [...]} wrapper shapes), and list_ok=True records that the
    SERVER answered — the live-server proof the harness exclusion keys on
    (TRDD-PZLVT2RN)."""

    class _Proc:
        def __init__(self, out):
            self.returncode = 0
            self.stdout = out

    monkeypatch.setattr(fs.terminal_trigger, "_resolve_aimaestro_cli", lambda env: "/bin/aimaestro-agent.sh")
    monkeypatch.setattr(
        fs.terminal_trigger, "_run_aimaestro_cli",
        lambda cli, args, *, env, timeout: _Proc('[{"workingDirectory": "/a"}]'),
    )
    cli, agents, list_ok = fs._aimaestro_agents({})
    assert cli == "/bin/aimaestro-agent.sh"
    assert agents == [{"workingDirectory": "/a"}]
    assert list_ok is True

    monkeypatch.setattr(
        fs.terminal_trigger, "_run_aimaestro_cli",
        lambda cli, args, *, env, timeout: _Proc('{"agents": [{"workingDirectory": "/b"}]}'),
    )
    cli, agents, list_ok = fs._aimaestro_agents({})
    assert agents == [{"workingDirectory": "/b"}]
    assert list_ok is True


def test_aimaestro_agents_best_effort_on_bad_json(monkeypatch) -> None:
    """A non-JSON response or a failed CLI call degrades to an empty agents list with
    list_ok=False (the server did NOT provably answer), never raises — a broken
    ai-maestro install must never break the fleet scan."""

    class _Proc:
        def __init__(self, out, rc=0):
            self.returncode = rc
            self.stdout = out

    monkeypatch.setattr(fs.terminal_trigger, "_resolve_aimaestro_cli", lambda env: "/bin/aimaestro-agent.sh")
    monkeypatch.setattr(
        fs.terminal_trigger, "_run_aimaestro_cli",
        lambda cli, args, *, env, timeout: _Proc("not json"),
    )
    assert fs._aimaestro_agents({}) == ("/bin/aimaestro-agent.sh", [], False)

    monkeypatch.setattr(
        fs.terminal_trigger, "_run_aimaestro_cli",
        lambda cli, args, *, env, timeout: None,
    )
    assert fs._aimaestro_agents({}) == ("/bin/aimaestro-agent.sh", [], False)


# ---------------------------------------------------------------------------
# TCC-denial detection (TRDD-VQ4LX7ND part 2). A running iTerm ALWAYS has at least one
# session, so "iTerm is up but osascript enumerated zero sessions" cannot mean "no
# sessions" — it means the Apple Event was blocked. That distinction is the whole
# detector: it separates a real, actionable denial from the boring case (iTerm closed).
# ---------------------------------------------------------------------------
def test_blocked_when_iterm_is_up_but_no_sessions_come_back() -> None:
    assert fs.iterm_automation_blocked(iterm_running=True, sessions={}) is True


def test_not_blocked_when_sessions_are_readable() -> None:
    """The channel works — this is the state a session-spawned daemon is in."""
    assert fs.iterm_automation_blocked(
        iterm_running=True, sessions={"ttys001": "w0t0p0"}) is False


def test_not_blocked_when_iterm_is_not_running() -> None:
    """No iTerm, no grant needed. Alarming here would be a false positive on every
    tmux-only or headless machine."""
    assert fs.iterm_automation_blocked(iterm_running=False, sessions={}) is False


def test_flag_is_written_and_then_self_clears(tmp_path: Path,
                                              monkeypatch: "pytest.MonkeyPatch") -> None:
    """The flag must clear itself the moment sessions become readable. An alarm the human
    has to remember to silence is one they learn to ignore."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    for mod in ("global_state",):
        sys.modules.pop(mod, None)
    flag = tmp_path / fs.ITERM_TCC_FLAG

    fs.record_iterm_automation_state(True)
    assert flag.is_file()

    fs.record_iterm_automation_state(False)   # the human granted it; sessions came back
    assert not flag.exists()


def test_recording_never_raises_on_an_unusable_state_dir(monkeypatch: "pytest.MonkeyPatch") -> None:
    """It runs inside a fleet scan — a stamp failure must never break the guardian."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", "/proc/nonexistent/cannot-write")
    for mod in ("global_state",):
        sys.modules.pop(mod, None)
    fs.record_iterm_automation_state(True)  # must not raise


# ---------------------------------------------------------------------------
# janitor#229 — the flag must carry the INTERPRETER the Automation grant follows, and
# must refresh when that path changes, WITHOUT refreshing when nothing changed (dispatch
# keys its once-per-session ack on this file's mtime).
# ---------------------------------------------------------------------------
def test_flag_records_the_interpreter_that_made_the_blocked_call(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """macOS attributes the grant to a binary, so an alarm that names none is
    unactionable. This process IS the one whose Apple Event came back empty."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    sys.modules.pop("global_state", None)

    fs.record_iterm_automation_state(True)

    recorded = (tmp_path / fs.ITERM_TCC_FLAG).read_text(encoding="utf-8")
    assert fs.iterm_automation_interpreter(recorded) == sys.executable


def test_unchanged_observation_does_not_touch_the_flag_mtime(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """The ack that makes this alarm once-per-session is keyed on the flag's MTIME, so a
    rewrite on every beat would re-alarm on every beat — the "alarm you learn to ignore"
    failure this whole flag exists to avoid."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    sys.modules.pop("global_state", None)
    flag = tmp_path / fs.ITERM_TCC_FLAG

    fs.record_iterm_automation_state(True)
    first = flag.stat().st_mtime_ns
    os.utime(flag, ns=(first - 5_000_000_000, first - 5_000_000_000))
    aged = flag.stat().st_mtime_ns

    fs.record_iterm_automation_state(True)  # same observation, same interpreter

    assert flag.stat().st_mtime_ns == aged, "an unchanged observation must not re-alarm"


def test_a_changed_interpreter_path_reaches_the_flag(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """The bug this replaces: the writer only wrote `if not flag.exists()`, so when a uv
    upgrade moved the interpreter the alarm went on naming a binary that no longer ran —
    sending the human to grant Automation to the wrong thing (janitor#229)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    sys.modules.pop("global_state", None)
    flag = tmp_path / fs.ITERM_TCC_FLAG
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(
        fs.iterm_automation_payload(interpreter="/old/uv/python3.12"), encoding="utf-8"
    )

    fs.record_iterm_automation_state(True)

    assert fs.iterm_automation_interpreter(flag.read_text(encoding="utf-8")) == sys.executable


def test_interpreter_parse_fails_open_on_a_pre_upgrade_flag() -> None:
    """A flag written before this was JSON is plain prose. It must parse to "" so the
    alarm omits the path, never crashes and never prints garbage as a binary name."""
    assert fs.iterm_automation_interpreter("macOS Automation grant denied\n") == ""
    assert fs.iterm_automation_interpreter("") == ""
    assert fs.iterm_automation_interpreter("[1, 2]") == ""
    assert fs.iterm_automation_interpreter('{"interpreter": 17}') == ""


def test_flag_carries_the_second_view_verdict(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """TRDD-DFKEXO79: the grant-free `claude agents --json` verdict rides the flag so a
    verdict CHANGE re-alarms once — the moment the second view first proves
    'blocked-not-empty' is exactly new information the human needs."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    sys.modules.pop("global_state", None)
    flag = tmp_path / fs.ITERM_TCC_FLAG

    fs.record_iterm_automation_state(True, second_view="channel-blocked-not-empty")

    raw = flag.read_text(encoding="utf-8")
    assert fs.iterm_automation_second_view(raw) == "channel-blocked-not-empty"
    assert fs.iterm_automation_interpreter(raw) == sys.executable  # both fields coexist
    # A verdict change IS a content change → compare-and-write rewrites (re-alarm once).
    fs.record_iterm_automation_state(True, second_view="consistent-empty")
    assert fs.iterm_automation_second_view(flag.read_text(encoding="utf-8")) == "consistent-empty"


def test_second_view_parse_fails_open() -> None:
    """Same fail-open contract as the interpreter field: absent/pre-upgrade/garbage → ""."""
    assert fs.iterm_automation_second_view("plain prose flag") == ""
    assert fs.iterm_automation_second_view('{"interpreter": "/x"}') == ""
    assert fs.iterm_automation_second_view('{"second_view": 3}') == ""


# ---------------------------------------------------------------------------
# TRDD-8DR0X08A — substantive liveness: the guardian's own typed command appends
# a queue-operation line that refreshed the mtime probe, resetting the attempt
# budget and re-injecting forever. These pin the fix at every layer.
# ---------------------------------------------------------------------------

def _iso(epoch: int) -> str:
    """A transcript-style UTC timestamp ('2026-07-17T16:55:41.797Z' shape)."""
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def _enqueue_line(epoch: int, content: str = "/janitor-arm") -> str:
    import json as _json

    return _json.dumps(
        {"type": "queue-operation", "operation": "enqueue",
         "timestamp": _iso(epoch), "content": content}
    )


def _substantive_line(epoch: int) -> str:
    import json as _json

    return _json.dumps({"type": "assistant", "timestamp": _iso(epoch), "message": {}})


def _tool_use_line(epoch: int, tid: str, name: str = "ExitPlanMode") -> str:
    import json as _json

    return _json.dumps(
        {
            "type": "assistant",
            "timestamp": _iso(epoch),
            "message": {"content": [{"type": "tool_use", "id": tid, "name": name}]},
        }
    )


def _tool_result_line(epoch: int, tid: str) -> str:
    import json as _json

    return _json.dumps(
        {
            "type": "user",
            "timestamp": _iso(epoch),
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid}]},
        }
    )


def test_awaiting_user_decision_detects_an_unanswered_tool_use() -> None:
    """THE 2026-07-17 case (TRDD-8IZ8COQ8). A session parked on `ExitPlanMode` is waiting
    for a HUMAN, but its transcript goes as silent as a dead one — measured, 33 minutes —
    so the guardian diagnosed `cron_dead` and typed into the approval dialog. The tell is
    on disk: the newest substantive record is a tool_use with no answering tool_result."""
    now = 1_784_300_000
    tail = [
        _substantive_line(now - 4000),
        _tool_use_line(now - 2000, "toolu_PLAN"),
    ]
    assert fs.awaiting_user_decision(tail) is True


def test_awaiting_user_decision_is_false_once_the_tool_answered() -> None:
    """An ANSWERED tool_use is ordinary mid-turn work, not a pending question — the
    guardian must stay free to recover a genuinely dead session."""
    now = 1_784_300_000
    tail = [
        _tool_use_line(now - 2000, "toolu_A"),
        _tool_result_line(now - 1999, "toolu_A"),
    ]
    assert fs.awaiting_user_decision(tail) is False


def test_awaiting_user_decision_sees_through_trailing_enqueues() -> None:
    """The guardian's own typed command appends queue bookkeeping. That must not hide the
    pending question underneath it — otherwise the FIRST injection masks the evidence that
    would have prevented the second."""
    now = 1_784_300_000
    tail = [
        _tool_use_line(now - 2000, "toolu_PLAN"),
        _enqueue_line(now - 10),
    ]
    assert fs.awaiting_user_decision(tail) is True


def test_awaiting_user_decision_false_for_a_merely_long_running_tool() -> None:
    """An unanswered tool_use ALSO describes a tool that is simply still RUNNING. Bash
    timeouts here are 20 minutes, which outlives the staleness threshold, so a broad
    predicate would decline recovery for a working session AND push a human notification
    claiming it "waits on YOUR answer" — false, and the misleading half is worse than the
    missed recovery. Only tools that genuinely address a PERSON count."""
    now = 1_784_300_000
    tail = [_tool_use_line(now - 2000, "toolu_BASH", name="Bash")]
    assert fs.awaiting_user_decision(tail) is False


def test_awaiting_user_decision_false_on_a_plain_stale_session() -> None:
    """A genuinely idle/dead session ends on ordinary content — it must remain recoverable,
    or this guard would disable fleet recovery entirely."""
    now = 1_784_300_000
    assert fs.awaiting_user_decision([_substantive_line(now - 4000)]) is False
    assert fs.awaiting_user_decision([]) is False


def test_substantive_age_ignores_trailing_enqueues() -> None:
    """Enqueue bookkeeping must not refresh liveness: the age comes from the newest
    SUBSTANTIVE line, and the queued commands are counted as wedged evidence."""
    now = 1_784_300_000
    tail = [
        _substantive_line(now - 2000),
        _enqueue_line(now - 10),
        _enqueue_line(now - 5),
    ]
    age, trailing = fs.substantive_age_from_tail(tail, now=now, fallback_age=5)
    assert age == 2000
    assert trailing == 2


def test_substantive_age_all_enqueue_tail_stays_stale() -> None:
    """A tail that is ALL queue bookkeeping uses its OLDEST timestamp — a lower bound
    on the true substantive age — so a wedged session keeps diagnosing stale instead
    of oscillating healthy on every injection."""
    now = 1_784_300_000
    tail = [_enqueue_line(now - 3000), _enqueue_line(now - 5)]
    age, trailing = fs.substantive_age_from_tail(tail, now=now, fallback_age=5)
    assert age == 3000
    assert trailing == 2


def test_substantive_age_falls_back_to_mtime_on_unknown_format() -> None:
    """No parseable timestamp anywhere → degrade to the mtime age, never crash."""
    age, trailing = fs.substantive_age_from_tail(
        ["not json at all"], now=1_784_300_000, fallback_age=42
    )
    assert age == 42
    assert trailing == 0


def test_substantive_age_counts_only_enqueues_in_trailing_run() -> None:
    """A non-enqueue queue-operation (e.g. a dequeue/remove) in the trailing run is
    skipped as bookkeeping but never counted as wedged evidence; a malformed line
    ends the trailing run without ending the timestamp walk."""
    now = 1_784_300_000
    import json as _json

    dequeue = _json.dumps(
        {"type": "queue-operation", "operation": "remove", "timestamp": _iso(now - 100)}
    )
    tail = [_substantive_line(now - 500), dequeue, _enqueue_line(now - 50)]
    age, trailing = fs.substantive_age_from_tail(tail, now=now, fallback_age=5)
    assert age == 500
    assert trailing == 1

    tail2 = [_substantive_line(now - 900), "garbage-line", _enqueue_line(now - 10)]
    age2, trailing2 = fs.substantive_age_from_tail(tail2, now=now, fallback_age=5)
    assert age2 == 900
    assert trailing2 == 1


def test_transcript_activity_sees_through_enqueue_freshness(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """End-to-end on real files: a transcript whose tail is fresh enqueue lines (fresh
    mtime!) must report the OLD substantive age plus the queued-command count."""
    import memory_scopes  # type: ignore[import-not-found]

    monkeypatch.setenv("HOME", str(tmp_path))
    now = 1_784_300_000
    root = tmp_path / "proj"
    root.mkdir()
    slug = memory_scopes.project_slug(os.path.realpath(str(root)))
    tdir = tmp_path / ".claude" / "projects" / slug
    tdir.mkdir(parents=True)
    lines = [
        _substantive_line(now - 4000),
        _enqueue_line(now - 20),
        _enqueue_line(now - 3),
    ]
    (tdir / "s1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    age, trailing, _awaiting = fs.transcript_activity(str(root), now)
    assert age == 4000
    assert trailing == 2
    assert fs.transcript_age(str(root), now) == 4000


def test_stale_threshold_scales_with_armed_cadence() -> None:
    """F4: the staleness window is 3× the armed heartbeat interval, floored at the
    */5 default — a session legitimately demoted to */30 is not stale at 20 min."""
    assert fs.stale_threshold_for("*/5 * * * *") == fs.STALE_S
    assert fs.stale_threshold_for("*/15 * * * *") == 3 * 15 * 60
    assert fs.stale_threshold_for("*/30 * * * *") == 3 * 30 * 60
    assert fs.stale_threshold_for("") == fs.STALE_S
    assert fs.stale_threshold_for("7 * * * *") == fs.STALE_S
    assert fs.stale_threshold_for("*/bogus * * * *") == fs.STALE_S


def test_diagnose_root_respects_slow_armed_cadence(tmp_path: Path) -> None:
    """A */30-armed idle session is HEALTHY at a 28-min-old transcript (its own next
    beat has not even fired yet) and cron_dead only past 3× its interval."""
    root = tmp_path / "p"
    sdir = root / ".janitor" / "state"
    sdir.mkdir(parents=True)
    (sdir / "armed-cadence.cron").write_text("*/30 * * * *\n", encoding="utf-8")
    now = 1_000_000
    assert fs.diagnose_root(str(root), now=now, transcript_age=1700)[:2] == ("healthy", None)
    assert fs.diagnose_root(str(root), now=now, transcript_age=6000)[:2] == (
        "cron_dead", "rearm",
    )


def test_awaiting_user_survives_a_trailing_bookkeeping_record() -> None:
    """2026-08-02 review finding: a message-less harness record (summary/system/
    progress) appended AFTER an unanswered ExitPlanMode must not hide it — the
    walk skips what can neither ask nor answer. A real prose message still
    terminates (someone spoke)."""
    import json as _json
    pending = _json.dumps({"message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "ExitPlanMode"}]}})
    bookkeeping = _json.dumps({"type": "summary", "summary": "compacted"})
    assert fs.awaiting_user_decision([pending, bookkeeping]) is True
    prose = _json.dumps({"message": {"content": "the user answered in prose"}})
    assert fs.awaiting_user_decision([pending, bookkeeping, prose]) is False


# --- TRDD-WKTD5JTC: retry-wedge detection wired into the scanner ------------------

def test_capture_pane_text_declines_iterm_when_automation_blocked(tmp_path, monkeypatch) -> None:
    """Advisor correction #4: iTerm capture AND inject both ride osascript, so a
    TCC-denied launchd daemon silently empties BOTH. Decline the read EARLY when
    `iterm-automation-blocked.flag` is set instead of burning an attempt on a channel
    proven dead this beat. A tmux channel is unaffected (no osascript involved)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    (tmp_path / fs.ITERM_TCC_FLAG).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        fs.terminal_trigger, "read_pane_text", lambda rt: "SHOULD NEVER BE CALLED"
    )
    assert fs.capture_pane_text({"iterm_session_id": "w0t1p0:ABCDEF12-3456"}) is None
    # tmux is a different channel — unaffected by the iTerm TCC flag.
    monkeypatch.setattr(fs.terminal_trigger, "read_pane_text", lambda rt: "tmux frame")
    assert fs.capture_pane_text({"tmux_pane": "%5"}) == "tmux frame"


def test_capture_pane_text_reads_iterm_when_not_blocked(tmp_path, monkeypatch) -> None:
    """With no TCC-block flag, the iTerm channel reads through normally."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(fs.terminal_trigger, "read_pane_text", lambda rt: "iterm frame")
    assert fs.capture_pane_text({"iterm_session_id": "w0t1p0:ABCDEF12-3456"}) == "iterm frame"


def test_capture_pane_text_no_channel_is_none() -> None:
    assert fs.capture_pane_text({}) is None


def test_diagnose_root_retry_wedged_requires_advance_across_polls(tmp_path: Path) -> None:
    """End-to-end through `diagnose_root`: the FIRST poll of a wedged pane is only a
    baseline (not yet wedged); the SECOND poll, with the attempt number advanced, is
    diagnosed `retry_wedged` — never `frozen`'s 'ladder', and the persisted episode
    state on disk is what carries the advance requirement across daemon beats."""
    root = tmp_path / "p"
    sdir = root / ".janitor" / "state"
    sdir.mkdir(parents=True)
    now = 1_000_000
    terminal = {"tmux_pane": "%5"}

    frame = {"text": "429 Rate limited · Retrying in 0s · attempt 5/300"}
    orig = fs.capture_pane_text
    try:
        fs.capture_pane_text = lambda t: frame["text"]  # type: ignore[assignment]
        diag1 = fs.diagnose_root(str(root), now=now, transcript_age=3600, terminal=terminal)
        assert diag1[:2] == ("cron_dead", "rearm"), "first sighting is only a baseline"
        assert (sdir / fs._RETRY_WEDGE_STATE_FILE).exists()

        frame["text"] = "429 Rate limited · Retrying in 5s · attempt 6/300"
        diag2 = fs.diagnose_root(str(root), now=now, transcript_age=3600, terminal=terminal)
        assert diag2[:2] == ("retry_wedged", "esc_retry")
    finally:
        fs.capture_pane_text = orig  # type: ignore[assignment]

    # A healthy (non-stale) poll afterwards clears the persisted episode.
    assert fs.diagnose_root(str(root), now=now, transcript_age=60, terminal=terminal)[:2] == (
        "healthy", None,
    )
    assert not (sdir / fs._RETRY_WEDGE_STATE_FILE).exists()


def test_diagnose_root_never_polls_a_static_string_into_wedged(tmp_path: Path) -> None:
    """The self-trigger hazard, exercised through `diagnose_root`: a pane statically
    showing this TRDD's own quoted wedge line matches the regex every poll, but never
    advances — so repeated beats never confirm `retry_wedged`."""
    root = tmp_path / "p"
    (root / ".janitor" / "state").mkdir(parents=True)
    now = 1_000_000
    terminal = {"tmux_pane": "%5"}
    static_text = "`429 Rate limited · Retrying in 0s · attempt 5/300`"
    orig = fs.capture_pane_text
    try:
        fs.capture_pane_text = lambda t: static_text  # type: ignore[assignment]
        for _ in range(4):
            diag = fs.diagnose_root(str(root), now=now, transcript_age=3600, terminal=terminal)
            assert diag[:2] == ("cron_dead", "rearm"), "must never confirm on a static display"
    finally:
        fs.capture_pane_text = orig  # type: ignore[assignment]


def test_diagnose_root_skips_pane_poll_for_unarmed_and_server_owned(tmp_path: Path) -> None:
    """Guardrail: never touch (not even READ) an unarmed or server_owned instance's
    pane — the poll must not even fire for them."""
    root = tmp_path / "p"
    sdir = root / ".janitor" / "state"
    sdir.mkdir(parents=True)
    (sdir / "disarmed.flag").write_text("")
    now = 1_000_000
    called = {"n": 0}
    orig = fs.capture_pane_text

    def _spy(t):
        called["n"] += 1
        return "429 Rate limited · Retrying in 0s · attempt 5/300"

    try:
        fs.capture_pane_text = _spy  # type: ignore[assignment]
        assert fs.diagnose_root(
            str(root), now=now, transcript_age=3600, terminal={"tmux_pane": "%5"}
        )[:2] == ("unarmed", None)
        assert called["n"] == 0, "an unarmed instance's pane must never be polled"

        (sdir / "disarmed.flag").unlink()
        assert fs.diagnose_root(
            str(root), now=now, transcript_age=3600, terminal={"tmux_pane": "%5"},
            server_owned=True,
        )[:2] == ("server_owned", None)
        assert called["n"] == 0, "a server-owned instance's pane must never be polled"
    finally:
        fs.capture_pane_text = orig  # type: ignore[assignment]


def test_write_rate_limited_flag_matches_on_stop_failure_shape(tmp_path: Path) -> None:
    """TRDD-WKTD5JTC §1b — the daemon's own fallback stamps the SAME two files
    `on-stop-failure.py` writes, so the existing `[janitor-resume]` chain (which reads
    them) proceeds unchanged downstream."""
    root = tmp_path / "p"
    sdir = root / ".janitor" / "state"
    sdir.mkdir(parents=True)
    now = 1_000_000
    fs.write_rate_limited_flag(str(root), now)
    assert (sdir / "rate-limited.flag").is_file()
    assert (sdir / "rate-limited-since.ts").read_text(encoding="utf-8").strip() == str(now)
