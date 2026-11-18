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

import json
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
# TRDD-EZ3PMQYX (janitor#233) — the osascript call site must distinguish HOW an
# empty result happened: a nonzero exit / unrunnable binary ("error"), an exceeded
# deadline ("timeout"), or a clean call that simply returned nothing ("empty").
# ---------------------------------------------------------------------------
def test_run_probe_outcome_ok_on_clean_exit() -> None:
    stdout, outcome = fs._run_probe_outcome(["true"])
    assert outcome == "ok"
    assert stdout == ""


def test_run_probe_outcome_error_on_nonzero_exit() -> None:
    stdout, outcome = fs._run_probe_outcome(["false"])
    assert outcome == "error"


def test_run_probe_outcome_error_on_unrunnable_binary() -> None:
    _, outcome = fs._run_probe_outcome(["/no/such/binary/at/all"])
    assert outcome == "error"


def test_run_probe_outcome_timeout_on_exceeded_deadline() -> None:
    _, outcome = fs._run_probe_outcome(["sleep", "5"], timeout=0.05)
    assert outcome == "timeout"



def _probe_log() -> str:
    path = fs.state.log_dir() / "daemon.log"
    return path.read_text() if path.exists() else ""



def _probe_run(cmd: list[str], **kw: float) -> tuple[tuple[str, str], str]:
    # The daemon log is shared across tests: return only the lines this call wrote.
    # Each call starts from a clean dedupe state, or an identical earlier failure would hide this one.
    fs._probe_logged.clear()
    before = _probe_log()
    res = fs._run_probe_outcome(cmd, **kw)
    return res, _probe_log()[len(before):]


def test_run_probe_outcome_logs_exit_code_and_stderr() -> None:
    """A failing child's exit code and stderr reach the daemon log; the outcome is unchanged."""
    # A python child, not `sh -c "... >&2"`: the suite sandbox refuses shell strings with redirection.
    (_, outcome), log = _probe_run([sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"])
    assert outcome == "error"
    assert "iterm-probe: error" in log and "exit=3" in log and "boom" in log


def test_run_probe_outcome_logs_exception_type_for_missing_binary() -> None:
    """An unrunnable binary is logged with its exception type and bin=not-found."""
    _, log = _probe_run(["/no/such/binary/at/all"])
    assert "exception=FileNotFoundError" in log and "bin=not-found" in log


def test_run_probe_outcome_logs_timeout() -> None:
    """An exceeded deadline returns timeout and writes a timeout line."""
    (_, outcome), log = _probe_run(["sleep", "5"], timeout=0.05)
    assert outcome == "timeout"
    assert "iterm-probe: timeout" in log


def test_run_probe_outcome_logs_empty_success() -> None:
    """Exit 0 with no output logs an empty line and still returns ok."""
    (stdout, outcome), log = _probe_run(["true"])
    assert (stdout, outcome) == ("", "ok")
    assert "iterm-probe: empty" in log


def test_run_probe_outcome_logs_nothing_on_success() -> None:
    """A child that prints something returns ok and writes no probe line."""
    (stdout, outcome), log = _probe_run(["echo", "x"])
    assert (stdout.strip(), outcome) == ("x", "ok")
    assert log == ""


def test_run_probe_outcome_survives_an_empty_command() -> None:
    """An empty command returns ("", "error") instead of raising from the failure logger."""
    assert fs._run_probe_outcome([]) == ("", "error")



def test_run_probe_outcome_survives_an_unwritable_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A log that cannot be written does not change the result of a failing probe."""
    # Own log dir: the session-shared daemon.log must never be replaced by a directory.
    monkeypatch.setattr(fs.state, "log_dir", lambda: tmp_path)
    (tmp_path / "daemon.log").mkdir()  # a directory in place of the file: opening it for append raises OSError
    fs._probe_logged.clear()
    assert fs._run_probe_outcome(["false"]) == ("", "error")


def test_run_probe_outcome_decodes_invalid_utf8_stdout_as_ok() -> None:
    """A child that writes an invalid UTF-8 byte and exits 0 returns ok and does not raise."""
    (stdout, outcome), _ = _probe_run([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'a\\xffb')"])
    assert outcome == "ok" and stdout.startswith("a") and stdout.endswith("b")


def test_run_probe_outcome_logs_an_identical_failure_once_until_a_success() -> None:
    """Two identical failures in a row log one line; a success with output re-arms the log."""
    _, log = _probe_run(["false"])
    assert log.count("iterm-probe: error") == 1
    before = _probe_log()
    fs._run_probe_outcome(["false"])
    assert _probe_log() == before
    fs._run_probe_outcome(["echo", "x"])
    fs._run_probe_outcome(["false"])
    assert _probe_log()[len(before):].count("iterm-probe: error") == 1



def test_run_probe_outcome_logs_one_line_when_a_success_ends_a_failure_episode() -> None:
    """A success after a failure logs one recovery line naming the failure key, then nothing more."""
    _probe_run(["false"])
    before = _probe_log()
    fs._run_probe_outcome(["echo", "x"])
    recovered = _probe_log()[len(before):]
    assert recovered.count("iterm-probe: ok after failures") == 1 and "error exit=1" in recovered
    before = _probe_log()
    fs._run_probe_outcome(["echo", "x"])
    assert _probe_log() == before


def test_run_probe_outcome_recovery_survives_an_unwritable_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A recovery line that cannot be written still returns the result and clears the episode."""
    monkeypatch.setattr(fs.state, "log_dir", lambda: tmp_path)
    fs._probe_logged.clear()
    fs._run_probe_outcome(["false"])
    assert fs._probe_logged
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "daemon.log").mkdir()  # a directory in place of the file: opening it for append raises OSError
    monkeypatch.setattr(fs.state, "log_dir", lambda: bad)
    stdout, outcome = fs._run_probe_outcome(["echo", "x"])
    assert (stdout.strip(), outcome) == ("x", "ok") and not fs._probe_logged

def test_run_probe_outcome_ignores_the_error_text_when_deduping() -> None:
    """Two failures with the same exit code but different stderr text log one line."""
    _probe_run([sys.executable, "-c", "import sys; sys.stderr.write('first text'); sys.exit(3)"])
    before = _probe_log()
    fs._run_probe_outcome([sys.executable, "-c", "import sys; sys.stderr.write('other text'); sys.exit(3)"])
    assert _probe_log() == before


def test_run_probe_outcome_remembers_every_failure_of_the_episode() -> None:
    """Failures with different exit codes log once each; repeating the pair logs nothing more."""
    three = [sys.executable, "-c", "import sys; sys.exit(3)"]
    four = [sys.executable, "-c", "import sys; sys.exit(4)"]
    _probe_run(three)
    fs._run_probe_outcome(four)
    before = _probe_log()
    assert before.count("iterm-probe: error") >= 2
    fs._run_probe_outcome(three)
    fs._run_probe_outcome(four)
    assert _probe_log() == before


def test_run_probe_outcome_logs_a_persisting_failure_again_after_the_interval() -> None:
    """The same failure is written again once the relog interval has passed."""
    _probe_run(["false"])
    before = _probe_log()
    for key in fs._probe_logged:
        fs._probe_logged[key] -= fs._PROBE_RELOG_INTERVAL_S + 1
    fs._run_probe_outcome(["false"])
    assert _probe_log()[len(before):].count("iterm-probe: error") == 1


def test_log_probe_failure_never_raises_when_the_detail_cannot_be_built() -> None:
    """A stderr object the detail builder chokes on is swallowed (real failure, no patching)."""
    fs._log_probe_failure(["false"], "error", 1, object(), None)  # type: ignore[arg-type]


def test_log_probe_failure_survives_a_line_the_log_cannot_encode() -> None:
    """A stderr holding a lone surrogate makes the log write raise; the helper returns None and records no episode key."""
    fs._probe_logged.clear()
    assert fs._log_probe_failure(["false"], "error", 1, "\udcff", None) is None
    assert fs._probe_logged == {}


def test_probe_failure_detail_cleans_and_caps_stderr() -> None:
    """Multi-line stderr with the home path and a trailing error number becomes one capped line."""
    home = str(Path.home())
    err = (f"{home}/x.scpt: " + "word\n" * 120) + "execution error: Not allowed (-1743)"
    out = fs._probe_failure_detail(1, err, None)
    assert "\n" not in out and "code=-1743" in out and "~" in out and home not in out
    assert len(out.split(" stderr=", 1)[1]) <= 200


def test_probe_failure_detail_accepts_invalid_utf8_bytes() -> None:
    """Undecodable stderr bytes do not raise."""
    assert "exit=1" in fs._probe_failure_detail(1, b"bad \xff byte", None)


def test_probe_failure_detail_finds_the_code_before_trailing_text() -> None:
    """An error number followed by more sentences is still extracted."""
    out = fs._probe_failure_detail(1, "execution error: Not allowed (-1743). Try again later. Second sentence.", None)
    assert "code=-1743" in out


def test_probe_failure_detail_takes_the_last_code() -> None:
    """With two error numbers in stderr the last one wins."""
    out = fs._probe_failure_detail(1, "first (-1) then (-1743) and done", None)
    assert "code=-1743" in out and "code=-1 " not in out


def test_flag_carries_the_probe_outcome(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """RED without the fix: before this field existed, an "error" (denied/unrunnable) and
    a "timeout" (transient hang) both collapsed into the same silence the alarm then had
    to hedge between with two-cause language. Now the call site's own verdict rides the
    flag."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    sys.modules.pop("global_state", None)
    flag = tmp_path / fs.ITERM_TCC_FLAG

    fs.record_iterm_automation_state(True, probe_outcome="timeout")
    raw = flag.read_text(encoding="utf-8")
    assert fs.iterm_automation_probe_outcome(raw) == "timeout"

    # A DIFFERENT outcome IS a content change → the compare-and-write must catch it, the
    # same way a second_view change does (re-alarm once, not every beat).
    fs.record_iterm_automation_state(True, probe_outcome="error")
    assert fs.iterm_automation_probe_outcome(flag.read_text(encoding="utf-8")) == "error"


def test_probe_outcome_parse_fails_open() -> None:
    """Same fail-open contract as every other flag field: absent/pre-upgrade/garbage → ""."""
    assert fs.iterm_automation_probe_outcome("plain prose flag") == ""
    assert fs.iterm_automation_probe_outcome('{"interpreter": "/x"}') == ""
    assert fs.iterm_automation_probe_outcome('{"probe_outcome": 3}') == ""


# ---------------------------------------------------------------------------
# #237 — the flag carries the age of the newest `FIRED rearm → iterm` daemon-log line
# AT WRITE TIME, so a consumer that never reads the daemon log itself is not blind to
# the positive evidence dispatch.py's own alarm already correlates against.
# ---------------------------------------------------------------------------
def test_latest_iterm_rearm_epoch_finds_the_newest_matching_line() -> None:
    log = (
        "[2026-08-08T10:00:00+0200] some other line\n"
        "[2026-08-08T10:05:00+0200] FIRED rearm → iterm\n"
        "[2026-08-08T10:12:00+0200] FIRED rearm → iterm\n"
        "[not-a-timestamp] FIRED rearm → iterm\n"
    )
    import datetime as dt

    epoch = fs._latest_iterm_rearm_epoch(log)
    assert epoch == int(
        dt.datetime.strptime("2026-08-08T10:12:00+0200", "%Y-%m-%dT%H:%M:%S%z").timestamp()
    )


def test_latest_iterm_rearm_epoch_none_when_no_match() -> None:
    assert fs._latest_iterm_rearm_epoch("[2026-08-08T10:00:00+0200] nothing relevant\n") is None


def test_flag_carries_rearm_evidence_age_when_a_daemon_log_has_it(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    sys.modules.pop("global_state", None)
    import time as _time

    now = int(_time.time())
    rearm_epoch = now - 600  # 10 minutes ago
    import datetime as dt

    stamp = dt.datetime.fromtimestamp(rearm_epoch, tz=dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S+0000"
    )
    (tmp_path / "daemon.log").write_text(
        f"[{stamp}] FIRED rearm → iterm\n", encoding="utf-8"
    )

    fs.record_iterm_automation_state(True)

    raw = (tmp_path / fs.ITERM_TCC_FLAG).read_text(encoding="utf-8")
    age = fs.iterm_automation_rearm_evidence_age_s(raw)
    assert age is not None
    assert 590 <= age <= 700  # a few seconds of test-run slack either side of 600


def test_flag_omits_rearm_evidence_age_when_none_found(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """Absent evidence -> the field is OMITTED, not written as 0 (a 0 would read as
    "just happened" rather than "unknown"; acceptance criterion of TRDD-EZ3PMQYX)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    sys.modules.pop("global_state", None)

    fs.record_iterm_automation_state(True)

    raw = (tmp_path / fs.ITERM_TCC_FLAG).read_text(encoding="utf-8")
    assert "rearm_evidence_age_s" not in raw
    assert fs.iterm_automation_rearm_evidence_age_s(raw) is None


def test_rearm_evidence_age_does_not_force_a_rewrite_on_every_scan(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """RED without the fix: a live, ever-increasing age field naively included in the
    change-detection comparison would make the flag "change" (and dispatch's content-hash
    ack re-alarm) on every single scan of an unbroken episode, even though nothing about
    the OBSERVATION changed — precisely the alarm-fatigue bug the unchanged-content skip
    exists to prevent (see test_unchanged_observation_does_not_touch_the_flag_mtime)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    sys.modules.pop("global_state", None)
    import datetime as dt
    import time as _time

    stamp = dt.datetime.fromtimestamp(
        int(_time.time()) - 60, tz=dt.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%S+0000")
    (tmp_path / "daemon.log").write_text(
        f"[{stamp}] FIRED rearm → iterm\n", encoding="utf-8"
    )
    flag = tmp_path / fs.ITERM_TCC_FLAG

    fs.record_iterm_automation_state(True)
    first_mtime = flag.stat().st_mtime_ns
    os.utime(flag, ns=(first_mtime - 5_000_000_000, first_mtime - 5_000_000_000))
    aged_mtime = flag.stat().st_mtime_ns

    fs.record_iterm_automation_state(True)  # same observation, later wall-clock instant

    assert flag.stat().st_mtime_ns == aged_mtime, (
        "the live age field must not by itself trigger a rewrite/re-alarm"
    )

def _write_rearm_log(tmp_path: Path, seconds_ago: int) -> None:
    import datetime as dt
    import time as _time

    stamp = dt.datetime.fromtimestamp(
        int(_time.time()) - seconds_ago, tz=dt.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%S+0000")
    (tmp_path / "daemon.log").write_text(f"[{stamp}] FIRED rearm → iterm\n", encoding="utf-8")


def _daemon_beat(probe_outcome: str) -> None:
    """The three flag writers in the order and with the argument shapes `gather_fleet` uses."""
    fs.record_iterm_automation_state(True, probe_outcome=probe_outcome)
    fs.record_iterm_rescue_warranted(True)
    fs.record_iterm_host_exposure((2, 5))


def test_unchanged_beat_after_patches_does_not_rewrite_the_flag(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """TRDD-0QCRG2YX: a second full beat (base write + both patches) with only the evidence age
    different must leave the flag's bytes and mtime untouched."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    sys.modules.pop("global_state", None)
    import global_state as gs  # type: ignore[import-not-found]

    flag = tmp_path / fs.ITERM_TCC_FLAG
    _write_rearm_log(tmp_path, 60)
    _daemon_beat("empty")
    first_bytes, first_mtime = flag.read_bytes(), flag.stat().st_mtime_ns
    first_age = fs._iterm_rearm_evidence_age_s(gs)

    _write_rearm_log(tmp_path, 400)
    assert fs._iterm_rearm_evidence_age_s(gs) != first_age
    _daemon_beat("empty")

    assert flag.read_bytes() == first_bytes
    assert flag.stat().st_mtime_ns == first_mtime


def test_patch_keys_survive_an_unchanged_beat(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """The patch writers' keys are still in the flag, with their values, after a second beat."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    sys.modules.pop("global_state", None)
    flag = tmp_path / fs.ITERM_TCC_FLAG
    _write_rearm_log(tmp_path, 60)
    _daemon_beat("empty")
    _write_rearm_log(tmp_path, 400)
    _daemon_beat("empty")

    raw = flag.read_text(encoding="utf-8")
    assert fs.iterm_automation_rescue_warranted(raw) is True
    assert fs.iterm_automation_host_exposure(raw) == (2, 5)


def test_changed_probe_outcome_after_patches_still_rewrites_the_flag(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """A different probe_outcome is a real change: the base writer rewrites and the new file
    carries the new outcome."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    sys.modules.pop("global_state", None)
    flag = tmp_path / fs.ITERM_TCC_FLAG
    _daemon_beat("empty")
    _daemon_beat("empty")
    before = flag.read_bytes()

    fs.record_iterm_automation_state(True, probe_outcome="timeout")

    assert flag.read_bytes() != before
    assert '"probe_outcome": "timeout"' in flag.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TRDD-9PDH8G0W (janitor#92 peer self-correction 2026-08-08) — the UNCONDITIONAL
# NEGATIVE: a rescue was WARRANTED (cron_dead on an instance whose only channel was
# iTerm) AND the same scan's osascript enumeration came back empty. Unlike the
# rearm-evidence downgrade, this has no "quiet fleet" innocent explanation.
# ---------------------------------------------------------------------------
def _mk_instance(*, diagnosis: str, terminal: dict[str, str], root: str) -> "fs.Instance":
    return fs.Instance(
        pid=1, command="claude", tty="ttys001", project_root=root,
        terminal=terminal, diagnosis=diagnosis, recovery=None, dispatch_age_s=None,
        active=False, transcript_age_s=None,
    )


def test_rescue_warranted_true_when_cron_dead_has_no_other_channel(tmp_path: Path) -> None:
    """The ONLY channel a cron_dead instance could have used was iTerm (no tmux_pane,
    no aimaestro_session, no linux_gui_channel) — the exact "UNREACHABLE" case
    `fleet_scan._main` already prints."""
    fleet = [_mk_instance(diagnosis="cron_dead", terminal={}, root=str(tmp_path / "proj"))]
    assert fs.iterm_rescue_warranted(fleet) is True


def test_rescue_warranted_false_when_cron_dead_had_a_working_channel(tmp_path: Path) -> None:
    """A cron_dead instance reachable via tmux does not implicate the iTerm channel at
    all — this must not false-positive the unconditional negative."""
    fleet = [_mk_instance(diagnosis="cron_dead", terminal={"tmux_pane": "%3"}, root=str(tmp_path / "proj"))]
    assert fs.iterm_rescue_warranted(fleet) is False


def test_rescue_warranted_false_when_nothing_is_cron_dead(tmp_path: Path) -> None:
    """A healthy fleet with an unreachable-but-not-cron_dead instance did not WARRANT
    a rescue this scan — no unconditional negative to report."""
    fleet = [_mk_instance(diagnosis="healthy", terminal={}, root=str(tmp_path / "proj"))]
    assert fs.iterm_rescue_warranted(fleet) is False


def test_rescue_warranted_false_on_an_empty_fleet() -> None:
    assert fs.iterm_rescue_warranted([]) is False


# ---------------------------------------------------------------------------
# TRDD-EZ3PMQYX (janitor#235, #240 ask 2) — HOW MUCH is at stake. Deliberately a
# different question from rescue_warranted above: that one asks "did a rescue fail
# just now", this one asks "how many are one stall away from being unrescuable",
# which is what the run-under-tmux remedy actually acts on.
# ---------------------------------------------------------------------------
def test_exposure_counts_iterm_only_instances_regardless_of_diagnosis(tmp_path: Path) -> None:
    """The distinction from `rescue_warranted`, made explicit: a HEALTHY instance with no
    other channel is still exposed. Counting only the cron_dead ones would report zero on a
    fully-exposed fleet right up until the first casualty — which is exactly the moment the
    guidance stops being preventive."""
    fleet = [
        _mk_instance(diagnosis="healthy", terminal={}, root=str(tmp_path / "proj")),  # exposed
        _mk_instance(diagnosis="cron_dead", terminal={}, root=str(tmp_path / "proj")),  # exposed
        _mk_instance(diagnosis="healthy", terminal={"tmux_pane": "%3"}, root=str(tmp_path / "proj")),  # safe
        _mk_instance(diagnosis="healthy", terminal={"aimaestro_session": "a"}, root=str(tmp_path / "proj")),  # safe
        _mk_instance(diagnosis="cron_dead", terminal={"linux_gui_channel": "x"}, root=str(tmp_path / "proj")),  # safe
    ]
    assert fs.iterm_only_exposure(fleet) == (2, 5)
    # Only ONE of those two is rescue-warranted — the predicates must not collapse.
    assert fs.iterm_rescue_warranted(fleet) is True


def test_exposure_on_an_empty_fleet_is_zero_of_zero() -> None:
    assert fs.iterm_only_exposure([]) == (0, 0)


def test_host_exposure_reader_returns_none_rather_than_a_misleading_zero() -> None:
    """`None` and `(0, n)` mean different things and must never be confused: `None` is "not
    measured", `(0, n)` is "measured, nobody exposed". The alarm renders nothing for the
    first and a reassuring sentence for the second, so a reader on a pre-upgrade host must
    not be told everything is fine.

    A nonsensical pair is also `None`: an alarm that says "7 of 3 sessions" spends its
    credibility on the one line a human reads."""
    assert fs.iterm_automation_host_exposure('{"interpreter": "/x"}') is None  # pre-upgrade
    assert fs.iterm_automation_host_exposure("not json at all") is None
    assert fs.iterm_automation_host_exposure('{"iterm_only_count": 7, "fleet_total": 3}') is None
    assert fs.iterm_automation_host_exposure('{"iterm_only_count": -1, "fleet_total": 3}') is None
    assert fs.iterm_automation_host_exposure('{"iterm_only_count": "2", "fleet_total": 3}') is None
    # A bool IS an int in Python — `true` must not read as the count 1.
    assert fs.iterm_automation_host_exposure('{"iterm_only_count": true, "fleet_total": 3}') is None
    assert fs.iterm_automation_host_exposure('{"iterm_only_count": 0, "fleet_total": 4}') == (0, 4)
    assert fs.iterm_automation_host_exposure('{"iterm_only_count": 2, "fleet_total": 4}') == (2, 4)


def test_record_and_read_rescue_warranted_round_trips(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """The writer patches the flag `record_iterm_automation_state` already wrote this
    beat, and the reader reads it back. PAYLOAD ROUND-TRIP acceptance criterion."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    sys.modules.pop("global_state", None)
    flag = tmp_path / fs.ITERM_TCC_FLAG

    fs.record_iterm_automation_state(True)  # the early write, as gather_fleet does
    fs.record_iterm_rescue_warranted(True)  # the later patch, once diagnoses are known

    raw = flag.read_text(encoding="utf-8")
    assert fs.iterm_automation_rescue_warranted(raw) is True
    assert fs.iterm_automation_interpreter(raw) == sys.executable  # untouched by the patch


def test_rescue_warranted_patch_is_a_noop_when_the_flag_is_absent(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """The condition already cleared this beat — nothing to patch, and the patch must
    never CREATE the flag (that would resurrect a cleared alarm)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    sys.modules.pop("global_state", None)

    fs.record_iterm_rescue_warranted(True)

    assert not (tmp_path / fs.ITERM_TCC_FLAG).exists()


def test_rescue_warranted_stable_write_causes_no_ack_churn(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """Patching the SAME value twice must not re-touch the flag — dispatch's
    once-per-observation ack is keyed on the flag's content, so a spurious rewrite
    would re-alarm every beat (acceptance: 'no ack churn from the new field')."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    sys.modules.pop("global_state", None)
    flag = tmp_path / fs.ITERM_TCC_FLAG

    fs.record_iterm_automation_state(True)
    fs.record_iterm_rescue_warranted(False)
    first_mtime = flag.stat().st_mtime_ns
    os.utime(flag, ns=(first_mtime - 5_000_000_000, first_mtime - 5_000_000_000))
    aged_mtime = flag.stat().st_mtime_ns

    fs.record_iterm_rescue_warranted(False)  # same value again

    assert flag.stat().st_mtime_ns == aged_mtime


def test_rescue_warranted_parse_fails_open() -> None:
    """Same fail-open contract as every other flag field: absent/pre-upgrade/garbage
    reads as None ("not yet known"), never crashes, never invents a verdict."""
    assert fs.iterm_automation_rescue_warranted("plain prose flag") is None
    assert fs.iterm_automation_rescue_warranted('{"interpreter": "/x"}') is None
    assert fs.iterm_automation_rescue_warranted('{"rescue_warranted": "yes"}') is None


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


def test_stale_threshold_reads_the_staggered_arm_prepare_form_too() -> None:
    """arm_prepare._stagger rewrites `*/N` to `{offset}-59/N` (TRDD-D7RLXAN1 report §2) — a
    staggered cron must give the SAME window as its plain equivalent, not silently fall back
    to `base_stale_s` (the bug this test guards: before cron_period existed, the inline
    `first.startswith("*/")` check only matched the plain shape)."""
    assert fs.stale_threshold_for("11-59/15 * * * *") == fs.stale_threshold_for("*/15 * * * *") == 3 * 15 * 60
    assert fs.stale_threshold_for("0-59/30 * * * *") == 3 * 30 * 60


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



def test_resume_sent_marker_merges_into_episode_state_expires_and_writes_atomically(
    tmp_path: Path,
) -> None:
    """TRDD-RJJGXPIK: marking resume_sent MERGES into the existing episode state (the
    attempt/confirmed fields the next poll advances from survive), reads back True only
    within RESUME_EPISODE_TTL_S, and the write is tmp-then-os.replace — no temp file is left in the
    state directory."""
    root = str(tmp_path / "p")
    fs._write_retry_wedge_state(root, {"attempt": 2, "confirmed": True, "retry_in": "30s", "first_seen": 900})
    assert fs.retry_wedge_resume_sent(root, 1000) is False
    fs.mark_retry_wedge_resume_sent(root, 1000)
    st = fs._read_retry_wedge_state(root)
    assert st == {
        "attempt": 2, "confirmed": True, "retry_in": "30s", "first_seen": 900,
        "resume_sent": True, "resume_sent_at": 1000,
    }
    ttl = fs.session_liveness.RESUME_EPISODE_TTL_S
    assert fs.retry_wedge_resume_sent(root, 1000 + ttl) is True
    assert fs.retry_wedge_resume_sent(root, 1000 + ttl + 1) is False  # TTL: a fresh episode may resume again
    leftovers = [p.name for p in (tmp_path / "p" / ".janitor" / "state").iterdir()]
    assert leftovers == [fs._RETRY_WEDGE_STATE_FILE], leftovers
    # No prior state at all: the marker alone is still recorded (daemon fired before any scan).
    root2 = str(tmp_path / "q")
    fs.mark_retry_wedge_resume_sent(root2, 50)
    assert fs.retry_wedge_resume_sent(root2, 60) is True


def test_diagnose_root_carries_the_resume_marker_until_the_wedge_clears(tmp_path: Path) -> None:
    """Through `diagnose_root`: a recorded resume_sent survives the next poll of the SAME
    wedged pane (so the daemon stays ESC-only), and is gone once the pane no longer shows the
    wedge — the episode ended, so a fresh one may resume again (TRDD-RJJGXPIK)."""
    import time

    root = tmp_path / "p"
    (root / ".janitor" / "state").mkdir(parents=True)
    terminal = {"tmux_pane": "%5"}
    orig = fs.capture_pane_text
    try:
        fs.capture_pane_text = lambda t: "429 Rate limited · Retrying in 5h · attempt 5/300"  # type: ignore[assignment]
        fs.diagnose_root(str(root), now=1_000_000, transcript_age=3600, terminal=terminal)
        fs.mark_retry_wedge_resume_sent(str(root), int(time.time()))
        fs.diagnose_root(str(root), now=1_000_000, transcript_age=3600, terminal=terminal)
        assert fs.retry_wedge_resume_sent(str(root), int(time.time())) is True
        fs.capture_pane_text = lambda t: "⏺ all quiet, no retry banner here"  # type: ignore[assignment]
        fs.diagnose_root(str(root), now=1_000_000, transcript_age=3600, terminal=terminal)
        assert fs.retry_wedge_resume_sent(str(root), int(time.time())) is False
    finally:
        fs.capture_pane_text = orig  # type: ignore[assignment]



def test_resume_pending_marker_is_atomic_and_survives_the_episode_wipe(tmp_path: Path) -> None:
    """TRDD-RJJGXPIK continuity backstop: the resume-pending marker lives in its OWN file, so
    the episode wipe `diagnose_root` performs the moment the pane stops looking wedged (the ESC
    aborted the turn!) does not erase it. The write leaves no temp file, a corrupt file reads as
    "nothing pending", and None clears it."""
    root = tmp_path / "p"
    sdir = root / ".janitor" / "state"
    sdir.mkdir(parents=True)
    marker = {"esc_at": 1000, "tries": 1, "last_try_at": 1000, "identity": "1:ttys1"}
    fs.write_resume_pending(str(root), marker)
    fs._write_retry_wedge_state(str(root), {"attempt": 2, "confirmed": True})
    # A healthy (non-stale transcript) poll wipes the EPISODE state ...
    assert fs.diagnose_root(str(root), now=2000, transcript_age=10, terminal={"tmux_pane": "%5"})[:2] == ("healthy", None)
    assert not (sdir / fs._RETRY_WEDGE_STATE_FILE).exists()
    # ... and leaves the resume-pending marker alone.
    assert fs.read_resume_pending(str(root)) == marker
    assert sorted(p.name for p in sdir.iterdir()) == [fs._RESUME_PENDING_FILE]
    (sdir / fs._RESUME_PENDING_FILE).write_text("{not json", encoding="utf-8")
    assert fs.read_resume_pending(str(root)) is None
    fs.write_resume_pending(str(root), marker)
    fs.write_resume_pending(str(root), None)
    assert fs.read_resume_pending(str(root)) is None


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


def test_the_first_call_writes_since_and_a_later_one_leaves_it(tmp_path: Path) -> None:
    """`since` means WHEN THE LIMIT STARTED, so a re-observation must not move it forward.

    This pins the OUTCOME only. It does NOT pin the read-before-touch ordering inside the
    function — measured by mutation: hoisting the `touch()` leaves this test green, because the
    conjunction's `isfile(since)` clause is False on a fresh dir and `since` is written anyway.
    `test_a_flag_swept_out_from_under_us_re_arms_since` is the one that catches a reorder.

    Why it matters live: the rotation ESC pass re-runs every liveness beat whenever its
    actuation does not land (nothing landed → no dedupe stamp), so a churning `since` would
    stop `_resume_wake_pass`'s per-window dedupe from ever matching.
    """
    root = tmp_path / "p"
    (root / ".janitor" / "state").mkdir(parents=True)
    since = root / ".janitor" / "state" / "rate-limited-since.ts"
    fs.write_rate_limited_flag(str(root), 1_000_000)
    assert since.read_text(encoding="utf-8").strip() == "1000000", "the FIRST call must write it"
    fs.write_rate_limited_flag(str(root), 1_009_999)
    assert since.read_text(encoding="utf-8").strip() == "1000000", "a re-observation must not move it"


def test_a_flag_swept_out_from_under_us_re_arms_since(tmp_path: Path) -> None:
    """`sweep_stale_rate_limit` deletes the FLAG and can leave `since` orphaned. The next limit
    must re-arm it — which is why the guard is a conjunction and not a bare `not already_flagged`:
    a fresh flag beside a stale `since` would otherwise date the new limit to the old one.

    This is ALSO the test that pins the read-before-touch ordering in `write_rate_limited_flag`
    (verified by mutation): hoist the `touch()` above the `already_flagged` read and this fails,
    because the re-created flag makes us conclude "already flagged" and skip the re-arm — while
    every other test here stays green.

    The flag is unlinked directly rather than by calling `sweep_stale_rate_limit`, because what
    is under test is how this function reacts to that FILE STATE, not the sweeper's decision to
    produce it; driving the real sweeper would need a stale mtime and a max-age window, adding
    two failure modes that have nothing to do with the branch being pinned. The equivalence is
    narrow and that is all it needs to be: the sweeper guards heavily (a `disarmed.flag` skip,
    an mtime stat, a staleness policy, a lost-unlink race) but its only MUTATION is
    `os.unlink(flag)` and it never touches `since` — so when it does act, the post-state is the
    one constructed by hand here."""
    root = tmp_path / "p"
    (root / ".janitor" / "state").mkdir(parents=True)
    flag = root / ".janitor" / "state" / "rate-limited.flag"
    since = root / ".janitor" / "state" / "rate-limited-since.ts"
    fs.write_rate_limited_flag(str(root), 1_000_000)
    flag.unlink()  # the sweeper aged it out; `since` is left behind
    fs.write_rate_limited_flag(str(root), 2_000_000)
    assert since.read_text(encoding="utf-8").strip() == "2000000"


def test_iterm_probe_retries_a_transient_empty_and_reports_the_attempt_count() -> None:
    """A host under heavy load must not be declared unreachable on ONE quiet probe.

    Owner report 2026-08-28: the alarm fired `probe-failed:timeout` and told the human their
    guardian could not reach the machine, while a manual enumeration minutes later returned 22
    sessions on that same host with the Automation grant already granted. One 15 s probe on a box
    running 20+ parallel agents measures CONTENTION, not permission.

    The EMPTY case is the one that matters and the one a naive policy misses: the incident's probe
    returned cleanly with zero sessions, so retrying only on `timeout` would have left the alarm
    firing. Deadlines escalate rather than repeat, because a second identical slice under the same
    load is the least informative thing to spend."""
    import fleet_scan  # type: ignore[import-not-found]

    calls: list[float] = []
    slept: list[float] = []

    def fake_probe(cmd, *, timeout):  # noqa: ANN001, ANN202
        calls.append(timeout)
        # quiet, quiet, then the sessions that were there all along
        return ("", "ok") if len(calls) < 3 else ("/dev/ttys004|w0t0p0\n", "ok")

    orig = fleet_scan._run_probe_outcome
    fleet_scan._run_probe_outcome = fake_probe  # type: ignore[assignment]
    try:
        sessions, outcome, attempts = fleet_scan.probe_iterm_sessions(
            "script", sleep=slept.append
        )
    finally:
        fleet_scan._run_probe_outcome = orig  # type: ignore[assignment]

    assert sessions, "the third attempt found sessions and they must be returned"
    assert attempts == 3, "the human must be told HOW MANY times we asked"
    assert outcome == "ok"
    assert calls == [30.0, 60.0, 90.0], f"deadlines must ESCALATE, not repeat: {calls}"
    assert slept == [2.0, 4.0], f"backoff must be short and bounded: {slept}"


def test_iterm_probe_stops_at_the_first_success_so_a_healthy_host_pays_nothing() -> None:
    """The retry must cost nothing when the first probe answers — this runs every heartbeat."""
    import fleet_scan  # type: ignore[import-not-found]

    calls: list[float] = []

    def fake_probe(cmd, *, timeout):  # noqa: ANN001, ANN202
        calls.append(timeout)
        return "/dev/ttys004|w0t0p0\n", "ok"

    orig = fleet_scan._run_probe_outcome
    fleet_scan._run_probe_outcome = fake_probe  # type: ignore[assignment]
    try:
        sessions, _outcome, attempts = fleet_scan.probe_iterm_sessions(
            "script", sleep=lambda _s: (_ for _ in ()).throw(AssertionError("must not sleep"))
        )
    finally:
        fleet_scan._run_probe_outcome = orig  # type: ignore[assignment]

    assert sessions and attempts == 1 and calls == [30.0]


def test_iterm_probe_ladder_is_strictly_increasing_and_starts_at_30_seconds() -> None:
    """The enumeration deadlines must escalate and the first must be >= 30 s (owner, 2026-10-07)."""
    import fleet_scan  # type: ignore[import-not-found]

    ladder = fleet_scan._ITERM_PROBE_TIMEOUTS
    assert ladder[0] >= 30.0
    assert all(a < b for a, b in zip(ladder, ladder[1:], strict=False))


def test_a_genuine_denial_still_alarms_after_every_attempt_fails() -> None:
    """Narrowing the false-alarm window must NOT weaken the alarm itself."""
    import fleet_scan  # type: ignore[import-not-found]

    def fake_probe(cmd, *, timeout):  # noqa: ANN001, ANN202
        return "", "timeout"

    orig = fleet_scan._run_probe_outcome
    fleet_scan._run_probe_outcome = fake_probe  # type: ignore[assignment]
    try:
        sessions, outcome, attempts = fleet_scan.probe_iterm_sessions(
            "script", sleep=lambda _s: None
        )
    finally:
        fleet_scan._run_probe_outcome = orig  # type: ignore[assignment]

    assert sessions == {} and outcome == "timeout" and attempts == 3



def _tail_window_file(tmp_path: Path, name: str, data: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_tail_lines_keeps_the_first_record_when_the_window_starts_on_a_line_boundary(
    tmp_path: Path,
) -> None:
    """TRDD-A8DRRW0I: a read window that begins exactly on a record boundary must return
    that record whole; the old code dropped it as if it were a cut fragment."""
    path = _tail_window_file(tmp_path, "t.jsonl", b"aaaa\nbbbb\ncccc\n")
    assert fs._tail_lines(path, max_bytes=10) == ["bbbb", "cccc"]


def test_tail_lines_drops_the_fragment_when_the_window_cuts_a_record(tmp_path: Path) -> None:
    """A window that starts mid-record must not return the cut fragment; the next whole
    record is the first line returned."""
    path = _tail_window_file(tmp_path, "t.jsonl", b"aaaa\nbbbb\ncccc\n")
    assert fs._tail_lines(path, max_bytes=8) == ["cccc"]


def _activity_root(tmp_path: Path, monkeypatch: "pytest.MonkeyPatch", tag: str) -> tuple[Path, Path]:
    import memory_scopes  # type: ignore[import-not-found]

    home = tmp_path / tag
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    root = home / "proj"
    root.mkdir()
    slug = memory_scopes.project_slug(os.path.realpath(str(root)))
    tdir = home / ".claude" / "projects" / slug
    tdir.mkdir(parents=True)
    return root, tdir


def test_transcript_activity_keeps_the_first_record_on_a_line_boundary(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """TRDD-A8DRRW0I: the 64 KiB window starts exactly on a substantive record (age 4000)
    followed by fresh enqueues (age 20). The old code dropped that record and reported 20."""
    import json as _json

    now = 1_784_300_000
    root, tdir = _activity_root(tmp_path, monkeypatch, "c")
    window = 64 * 1024
    enq = _enqueue_line(now - 20) + "\n"
    n_enq = 10
    base = {"type": "assistant", "timestamp": _iso(now - 4000), "message": {}, "pad": ""}
    base_len = len(_json.dumps(base)) + 1
    pad = window - n_enq * len(enq) - base_len
    assert pad > 0
    base["pad"] = "x" * pad
    first = _json.dumps(base) + "\n"
    assert len(first) + n_enq * len(enq) == window
    (tdir / "s1.jsonl").write_text("filler-line\n" + first + enq * n_enq, encoding="utf-8")
    age, trailing, _awaiting = fs.transcript_activity(str(root), now)
    assert age == 4000
    assert trailing == n_enq


def test_transcript_activity_torn_last_line_keeps_the_documented_meanings(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """Pins the documented malformed-line meanings (guard, passes on the old code): a torn
    last line ends the trailing enqueue run, and it never proves a pending question."""
    now = 1_784_300_000
    root, tdir = _activity_root(tmp_path, monkeypatch, "d1")
    lines = [_substantive_line(now - 4000), _enqueue_line(now - 20), _enqueue_line(now - 3)]
    (tdir / "s1.jsonl").write_text("\n".join(lines) + '\n{"type": "assist', encoding="utf-8")
    age, trailing, awaiting = fs.transcript_activity(str(root), now)
    assert trailing == 0
    assert age == 4000
    assert awaiting is False

    root2, tdir2 = _activity_root(tmp_path, monkeypatch, "d2")
    lines2 = [_substantive_line(now - 4000), _tool_use_line(now - 2000, "toolu_PLAN")]
    (tdir2 / "s1.jsonl").write_text("\n".join(lines2) + '\n{"type": "assist', encoding="utf-8")
    _age2, _trailing2, awaiting2 = fs.transcript_activity(str(root2), now)
    assert awaiting2 is False


def test_transcript_activity_zero_byte_and_short_files_keep_their_results(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """Guard: an empty transcript falls back to its mtime age; a file shorter than the
    window is read whole."""
    now = 1_784_300_000
    root, tdir = _activity_root(tmp_path, monkeypatch, "e1")
    empty = tdir / "s1.jsonl"
    empty.write_bytes(b"")
    os.utime(empty, (now - 100, now - 100))
    assert fs.transcript_activity(str(root), now) == (100, 0, False)

    root2, tdir2 = _activity_root(tmp_path, monkeypatch, "e2")
    lines = [_substantive_line(now - 4000), _enqueue_line(now - 20)]
    (tdir2 / "s1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert fs.transcript_activity(str(root2), now) == (4000, 1, False)


def _row(epoch: int, rtype: str, content: object = "x") -> str:
    import json
    from datetime import datetime, timezone

    ts = datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return json.dumps({"type": rtype, "timestamp": ts, "message": {"role": rtype, "content": content}})


def test_transcript_activity_since_sees_only_user_or_assistant_rows_after_the_instant(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """TRDD-RJJGXPIK round 3: activity = a `user`/`assistant` row stamped AFTER `since`. A row
    from before, an `api-request` row, an attachment, and Claude Code's own interrupt marker
    (text or block form) are not; neither is a missing or empty transcript directory."""
    since = 1_790_000_000
    root, tdir = _activity_root(tmp_path, monkeypatch, "act-since")
    path = tdir / "s1.jsonl"

    def _write(*rows: str) -> None:
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        os.utime(path, (since + 100, since + 100))  # newer than `since`, so the file is read

    assert fs.transcript_activity_since(str(root), since) is False  # no rows at all
    _write(_row(since - 50, "user"), _row(since + 5, "api-request"), _row(since + 6, "attachment"))
    assert fs.transcript_activity_since(str(root), since) is False
    _write(_row(since + 7, "user", "[Request interrupted by user]"))
    assert fs.transcript_activity_since(str(root), since) is False
    _write(_row(since + 7, "user", [{"type": "text", "text": "[Request interrupted by user]"}]))
    assert fs.transcript_activity_since(str(root), since) is False
    _write(_row(since + 8, "user", "carry on"))
    assert fs.transcript_activity_since(str(root), since) is True
    _write(_row(since + 8, "assistant", [{"type": "text", "text": "ok"}]))
    assert fs.transcript_activity_since(str(root), since) is True
    # A file whose mtime is not past `since` cannot hold a newer row: skipped unread.
    os.utime(path, (since - 1, since - 1))
    assert fs.transcript_activity_since(str(root), since) is False
    assert fs.transcript_activity_since(str(tmp_path / "no-such-project"), since) is False



# --- TRDD-RJJGXPIK fast lane: ESC a frozen API-error countdown after ~2 beats, not at STALE_S ---

_FL_BASE = 1_790_000_000
_FL_TERM = {"tmux_pane": "%5"}


def _retry_frame(retry_in: str, attempt: int) -> str:
    """A real-shaped Claude Code pane frame: the status row sits right above the input box."""
    border = "─" * 40
    return (
        "⏺ earlier output\n"
        f"✻ Rate limited · Retrying in {retry_in} · attempt {attempt}/300\n"
        f"{border}\n❯ \n{border}\n"
    )


_IN_FLIGHT_ROWS = [
    _row(_FL_BASE - 400, "user", "say hi"),
]
_IDLE_ROWS = [  # a COMPLETED turn: the session sits at its prompt (real 2.1.323 row types)
    _row(_FL_BASE - 400, "user", "say hi"),
    _row(_FL_BASE - 397, "assistant", [{"type": "text", "text": "hi"}]),
    _row(_FL_BASE - 396, "system"),
    _row(_FL_BASE - 396, "api-request"),
]


class _PaneSpy:
    """Stands in for the pane READ only (the I/O boundary): returns `text`, counts the reads."""

    def __init__(self, text: str | None) -> None:
        self.text = text
        self.reads = 0

    def __call__(self, _terminal: object) -> str | None:
        self.reads += 1
        return self.text


def _fl_root(tmp_path: Path, monkeypatch: "pytest.MonkeyPatch", tag: str, rows: list[str]) -> Path:
    root, tdir = _activity_root(tmp_path, monkeypatch, tag)
    (tdir / "s1.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return root


def _fl_state_file(root: Path) -> Path:
    return root / ".janitor" / "state" / fs._RETRY_WEDGE_STATE_FILE


def test_turn_in_flight_reads_the_newest_user_or_assistant_row(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """A turn is in flight iff the newest user/assistant row is a user prompt or tool_result.
    Trailing bookkeeping rows, a completed assistant turn, a pending tool_use, Claude Code's own
    interrupt marker, a torn last line and a missing transcript are not (TRDD-RJJGXPIK)."""
    t = _FL_BASE
    result = _row(t, "user", [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}])
    bookkeeping = [_row(t + 1, "attachment"), _row(t + 1, "api-request"), _row(t + 1, "queue-operation")]
    cases = [
        ("prompt", [_row(t, "user", "say hi")], True),
        ("tool_result", [_row(t - 1, "assistant", [{"type": "tool_use", "id": "t1"}]), result], True),
        ("prompt+bookkeeping", [_row(t, "user", "say hi"), *bookkeeping], True),
        ("end_turn", [*_IDLE_ROWS], False),
        ("pending tool_use", [_row(t, "user", "x"), _row(t, "assistant", [{"type": "tool_use", "id": "t1"}])], False),
        ("interrupt", [_row(t, "user", "x"), _row(t + 1, "user", "[Request interrupted by user]")], False),
        ("no message rows", [_row(t, "attachment")], False),
        # Shapes found as the LAST user row of real 2.1.322/2.1.323 sessions idle for over an hour:
        ("interrupt for tool use", [_row(t, "user", [{"type": "text", "text": "[Request interrupted by user for tool use]"}])], False),
        ("/model stdout", [_row(t, "user", "<local-command-caveat>Caveat: the messages below…</local-command-caveat>"),
                           _row(t, "user", "<command-name>/model</command-name>\n<command-message>model</command-message>"),
                           _row(t, "user", "<local-command-stdout>Set model to Fable 5</local-command-stdout>")], False),
        ("/clear bare command", [_row(t, "user", "<command-name>/clear</command-name>")], False),
        ("heartbeat prompt", [_row(t, "user", "[janitor-heartbeat]\n/path/stub.py")], True),
        ("! shell escape", [_row(t, "user", "<bash-input> afplay /System/Library/Sounds/Glass.aiff</bash-input>"),
                            _row(t, "user", "<bash-stdout>(Bash completed with no output)</bash-stdout>")], False),
        ("bash input only", [_row(t, "user", "<bash-input> sleep 1</bash-input>")], False),
        # The real 529-fixture run on 2.1.323: retries append only `api-request` rows after the user row.
        ("529 retries", [_row(t, "user", "say hi"), _row(t, "attachment"), _row(t, "api-request-shape"),
                         _row(t, "api-request-blob"), _row(t, "api-request"), _row(t + 1, "api-request"),
                         _row(t + 3, "api-request")], True),
        # A NON-retryable error ends the turn: assistant isApiErrorMessage row + turn_duration.
        ("final api error", [_row(t, "user", "say hi"), _row(t, "api-request"),
                             _row(t + 5, "assistant", [{"type": "text", "text": "API Error: 400"}]),
                             _row(t + 5, "system")], False),
        ("/compact summary", [_row(t - 1, "system"),
                              _row(t, "user", "This session is being continued from a previous conversation that ran out of context.")], False),
    ]
    for tag, rows, expected in cases:
        slug = "".join(c if c.isalnum() else "-" for c in tag)
        root = _fl_root(tmp_path, monkeypatch, f"inflight-{slug}", rows)
        assert fs.transcript_turn_in_flight(str(root)) is expected, tag
    torn = _fl_root(tmp_path, monkeypatch, "inflight-torn", [_row(t, "user", "x")])
    with (next((tmp_path / "inflight-torn" / ".claude" / "projects").iterdir()) / "s1.jsonl").open("a") as fh:
        fh.write('{"type": "assist')
    assert fs.transcript_turn_in_flight(str(torn)) is True  # the torn line proves nothing
    assert fs.transcript_turn_in_flight(str(tmp_path / "no-such-project")) is False


@pytest.mark.parametrize(("gap", "fires_on_second_beat"), [(100, True), (119, True), (120, True), (99, False)])
def test_fast_lane_fires_on_a_frozen_countdown_at_the_real_beat_cadence(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch", gap: int, fires_on_second_beat: bool
) -> None:
    """The owner's requirement: ESC a frozen countdown a couple of minutes after it freezes, NOT
    after the 15-minute STALE_S gate. Two real beats `gap` seconds apart (no faked 1000 s jump;
    the transcript age stays far below STALE_S) read the byte-identical `Retrying in 12s`:
    >=100 s apart confirms on the second beat — 119 s included, the real 120 s beat's
    whole-second jitter — while 99 s needs one more beat."""
    root = _fl_root(tmp_path, monkeypatch, "fast", _IN_FLIGHT_ROWS)
    spy = _PaneSpy(_retry_frame("12s", 3))
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    age = 90
    assert age < fs.STALE_S
    first = fs.diagnose_root(str(root), now=_FL_BASE, transcript_age=age, terminal=_FL_TERM, fast_lane=True)
    assert first[:2] == ("healthy", None), "first sighting is only a baseline"
    second = fs.diagnose_root(str(root), now=_FL_BASE + gap, transcript_age=age + gap, terminal=_FL_TERM, fast_lane=True)
    assert (second[:2] == ("retry_wedged", "esc_retry")) is fires_on_second_beat
    if not fires_on_second_beat:
        third = fs.diagnose_root(str(root), now=_FL_BASE + 2 * gap, transcript_age=age + 2 * gap, terminal=_FL_TERM, fast_lane=True)
        assert third[:2] == ("retry_wedged", "esc_retry")


def test_fast_lane_never_acts_on_an_attempt_advance_alone(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """A retry that is PROGRESSING (attempt advances, countdown ticks) must not be ESCed early:
    the attempt-advance proof still needs the stale-transcript gate. Control: the same episode
    DOES diagnose retry_wedged once the transcript is stale."""
    root = _fl_root(tmp_path, monkeypatch, "advance", _IN_FLIGHT_ROWS)
    spy = _PaneSpy(None)
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    for k, attempt in enumerate((3, 4, 5, 6)):
        spy.text = _retry_frame(f"{30 - 5 * k}s", attempt)
        diag = fs.diagnose_root(str(root), now=_FL_BASE + 120 * k, transcript_age=90 + 120 * k, terminal=_FL_TERM, fast_lane=True)
        assert diag[:2] == ("healthy", None), k
    assert spy.reads == 4
    spy.text = _retry_frame("5s", 7)
    stale = fs.diagnose_root(str(root), now=_FL_BASE + 700, transcript_age=fs.STALE_S + 5, terminal=_FL_TERM, fast_lane=True)
    assert stale[:2] == ("retry_wedged", "esc_retry")


def test_stale_banner_on_an_idle_session_is_never_read_or_esced(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """A session that RECOVERED and sits idle at its prompt can still show its old
    `Retrying in 12s · attempt 3/10` banner, byte-identical on every read. Its transcript ends
    on a completed assistant turn, so it is not in flight: across every beat for > 5 minutes the
    pane is never read and the diagnosis stays healthy."""
    root = _fl_root(tmp_path, monkeypatch, "stale-banner", _IDLE_ROWS)
    spy = _PaneSpy(_retry_frame("12s", 3))
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    for k in range(5):
        diag = fs.diagnose_root(str(root), now=_FL_BASE + 120 * k, transcript_age=400 + 120 * k, terminal=_FL_TERM, fast_lane=True)
        assert diag[:2] == ("healthy", None), k
    assert spy.reads == 0
    assert not _fl_state_file(root).exists()


def test_quiet_healthy_session_with_an_old_episode_file_is_never_actuated(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """An episode file left over from an earlier wedge (confirmed, frozen proof) must not turn a
    healthy quiet session into rearm / reload / esc: an idle session is not read and the file is
    wiped; an in-flight session whose pane shows no retry banner (the model is just thinking) is
    read once, diagnosed healthy, and the file is wiped too."""
    old = {"attempt": 3, "confirmed": True, "retry_in": "12s", "first_seen": _FL_BASE - 5000,
           "proof": "frozen-countdown"}
    idle = _fl_root(tmp_path, monkeypatch, "old-idle", _IDLE_ROWS)
    fs._write_retry_wedge_state(str(idle), old)
    spy = _PaneSpy(_retry_frame("12s", 3))
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    assert fs.diagnose_root(str(idle), now=_FL_BASE, transcript_age=400, terminal=_FL_TERM, fast_lane=True)[:2] == ("healthy", None)
    assert spy.reads == 0 and not _fl_state_file(idle).exists()

    busy = _fl_root(tmp_path, monkeypatch, "old-busy", _IN_FLIGHT_ROWS)
    fs._write_retry_wedge_state(str(busy), old)
    spy.text = "⏺ working\n✻ Thinking… (95s)\n" + "─" * 40 + "\n❯ \n" + "─" * 40 + "\n"
    assert fs.diagnose_root(str(busy), now=_FL_BASE, transcript_age=400, terminal=_FL_TERM, fast_lane=True)[:2] == ("healthy", None)
    assert spy.reads == 1 and not _fl_state_file(busy).exists()


def test_advancing_transcript_blocks_the_fast_lane(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """A transcript that advanced within FROZEN_PROBE_S means the turn is making progress: the
    pane is not read, a seeded confirmed episode is wiped, and the diagnosis is healthy — the
    boundary is exact (59 s: no read, 60 s: read)."""
    root = _fl_root(tmp_path, monkeypatch, "advancing", _IN_FLIGHT_ROWS)
    fs._write_retry_wedge_state(str(root), {"attempt": 3, "confirmed": True, "retry_in": "12s",
                                            "first_seen": _FL_BASE - 500, "proof": "frozen-countdown"})
    spy = _PaneSpy(_retry_frame("12s", 3))
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    assert fs.diagnose_root(str(root), now=_FL_BASE, transcript_age=fs.FROZEN_PROBE_S - 1, terminal=_FL_TERM, fast_lane=True)[:2] == ("healthy", None)
    assert spy.reads == 0 and not _fl_state_file(root).exists()
    fs.diagnose_root(str(root), now=_FL_BASE, transcript_age=fs.FROZEN_PROBE_S, terminal=_FL_TERM, fast_lane=True)
    assert spy.reads == 1


def test_fast_lane_never_reroutes_into_frozen_cron_dead_or_version_and_skips_opt_outs(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """The fast lane must not leak into the stale-only diagnoses: with a rate-limited.flag
    present and an UNCONFIRMED wedge read, a quiet in-flight session stays healthy (not frozen /
    cron_dead -> rearm). An unreadable pane (None) is "cannot assess": even a persisted confirmed
    frozen episode does not fire. Unarmed and server_owned instances are never read."""
    root = _fl_root(tmp_path, monkeypatch, "noleak", _IN_FLIGHT_ROWS)
    sdir = root / ".janitor" / "state"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "rate-limited.flag").write_text("", encoding="utf-8")
    spy = _PaneSpy(_retry_frame("12s", 3))
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    assert fs.diagnose_root(str(root), now=_FL_BASE, transcript_age=200, terminal=_FL_TERM, fast_lane=True)[:2] == ("healthy", None)

    fs._write_retry_wedge_state(str(root), {"attempt": 3, "confirmed": True, "retry_in": "12s",
                                            "first_seen": _FL_BASE - 500, "proof": "frozen-countdown"})
    spy.text = None
    assert fs.diagnose_root(str(root), now=_FL_BASE + 120, transcript_age=320, terminal=_FL_TERM, fast_lane=True)[:2] == ("healthy", None)
    assert _fl_state_file(root).exists(), "a blind read leaves the episode untouched"

    reads = spy.reads
    (sdir / "disarmed.flag").write_text("", encoding="utf-8")
    assert fs.diagnose_root(str(root), now=_FL_BASE, transcript_age=200, terminal=_FL_TERM, fast_lane=True)[:2] == ("unarmed", None)
    (sdir / "disarmed.flag").unlink()
    assert fs.diagnose_root(str(root), now=_FL_BASE, transcript_age=200, terminal=_FL_TERM, fast_lane=True, server_owned=True)[:2] == ("server_owned", None)
    assert spy.reads == reads



def test_fast_lane_is_off_unless_the_caller_opts_in(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """TRDD-RJJGXPIK rule (a): `diagnose_root` defaults to stale-only pane reads. A quiet
    in-flight session (the fast-lane shape) is NOT read unless `fast_lane=True`, so fleet_status,
    cold-cache and the peer-freeze detector never trigger a pane read (an iTerm Apple Event)."""
    root = _fl_root(tmp_path, monkeypatch, "optin", _IN_FLIGHT_ROWS)
    spy = _PaneSpy(_retry_frame("12s", 3))
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    assert fs.diagnose_root(str(root), now=_FL_BASE, transcript_age=200, terminal=_FL_TERM)[:2] == ("healthy", None)
    assert spy.reads == 0
    fs.diagnose_root(str(root), now=_FL_BASE, transcript_age=200, terminal=_FL_TERM, fast_lane=True)
    assert spy.reads == 1


def test_a_non_liveness_scan_between_beats_does_not_wipe_the_fast_lane_episode(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """Production interleaving (TRDD-RJJGXPIK): every `gather_fleet` caller except the daemon
    liveness beat (the only `fast_lane=True` one) — cold-cache-clear, fleet_status,
    peer-freeze-recovery, the rotation-ESC tick, fleet-stop, the fleet_scan CLI — scans with
    `fast_lane=False` at its own cadence, which can fall between two liveness beats. On a quiet
    in-flight, non-stale transcript that scan polls no pane and must leave the episode the first
    beat wrote byte-for-byte UNTOUCHED: otherwise the frozen-countdown proof never gets its
    baseline and the fast lane never fires. The third call is placed `_FROZEN_COUNTDOWN_MIN_S`
    + 19 s after the first, so it is coupled to that proof bar on purpose."""
    root = _fl_root(tmp_path, monkeypatch, "interleave", _IN_FLIGHT_ROWS)
    spy = _PaneSpy(_retry_frame("12s", 3))
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    gap = fs.session_liveness._FROZEN_COUNTDOWN_MIN_S + 19
    first = fs.diagnose_root(str(root), now=_FL_BASE, transcript_age=90, terminal=_FL_TERM, fast_lane=True)
    assert first[:2] == ("healthy", None), "first liveness beat: baseline only"
    reads_before = spy.reads
    bytes_before = _fl_state_file(root).read_bytes()
    between = fs.diagnose_root(str(root), now=_FL_BASE + 30, transcript_age=120, terminal=_FL_TERM, fast_lane=False)
    assert between[:2] == ("healthy", None)
    assert spy.reads == reads_before, "a non-liveness scan polls no pane"
    assert _fl_state_file(root).read_bytes() == bytes_before, "the episode is left untouched"
    third = fs.diagnose_root(str(root), now=_FL_BASE + gap, transcript_age=90 + gap, terminal=_FL_TERM, fast_lane=True)
    assert third[:2] == ("retry_wedged", "esc_retry")


@pytest.mark.parametrize(
    ("dt", "drift", "spared"),
    [(30, 0, True), (600, 0, True), (37, 1, True), (37, -2, True), (37, 3, False), (37, -3, False)],
)
def test_the_spare_depends_on_the_transcript_instant_not_on_how_late_the_scan_runs(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch", dt: int, drift: int, spared: bool
) -> None:
    """The anchor is `now - transcript_age`: `gather_fleet` reads ONE `now` per scan and
    `transcript_activity` measures every age against that same `now`, so the pair is the fixed
    instant of the transcript row whatever the scan's wall-clock delay (a loaded host, a later
    `now`). A middle scan `dt` s after the beat, with the age growing by exactly `dt` (the
    transcript unchanged), must spare the episode (byte-identical); whole-second rounding
    (`drift` up to +-2 s) is tolerated and a transcript that really moved (+-3 s) clears it."""
    root = _fl_root(tmp_path, monkeypatch, "anchor-clock", _IN_FLIGHT_ROWS)
    spy = _PaneSpy(_retry_frame("12s", 3))
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    fs.diagnose_root(str(root), now=_FL_BASE, transcript_age=90, terminal=_FL_TERM, fast_lane=True)
    before = _fl_state_file(root).read_bytes()
    fs.diagnose_root(str(root), now=_FL_BASE + dt, transcript_age=90 + dt + drift, terminal=_FL_TERM, fast_lane=False)
    if spared:
        assert _fl_state_file(root).read_bytes() == before
    else:
        assert not _fl_state_file(root).exists()


@pytest.mark.parametrize(
    "case",
    ["transcript-advanced", "turn-not-in-flight", "no-terminal", "unarmed", "server-owned", "age-unknown", "anchor-moved", "no-anchor"],
)
def test_a_non_liveness_scan_still_clears_the_episode_unless_it_is_the_fast_lane_shape(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch", case: str
) -> None:
    """TRDD-RJJGXPIK negative companion: the spare covers ONLY the same quiet in-flight turn (an
    episode with a transcript anchor within 2 s of this scan's own transcript instant, a terminal,
    armed, client-owned, age >= FROZEN_PROBE_S). A `fast_lane=False` scan of any other shape
    still clears the episode, and the next liveness beat is a fresh baseline (healthy), not a
    frozen-countdown ESC. Cases: age below FROZEN_PROBE_S (anchor matching); the turn is not
    in flight (completed-turn rows); no terminal; deliberately unarmed; server-owned; unknown
    transcript age; the anchor moved (age still >= FROZEN_PROBE_S but the transcript advanced
    20 s); an episode with no anchor."""
    idle = case == "turn-not-in-flight"
    root = _fl_root(tmp_path, monkeypatch, f"interleave-{case}", _IDLE_ROWS if idle else _IN_FLIGHT_ROWS)
    spy = _PaneSpy(_retry_frame("12s", 3))
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    gap = fs.session_liveness._FROZEN_COUNTDOWN_MIN_S + 19
    mtime = _FL_BASE - 90  # the transcript instant the first beat saw (age 90 at _FL_BASE)
    if case == "transcript-advanced":
        mtime = _FL_BASE + 30 - (fs.FROZEN_PROBE_S - 1)  # this scan's own mtime, at age FROZEN_PROBE_S - 1
    if idle or case == "transcript-advanced":
        # Seed an episode (an old banner) anchored to THIS scan's own mtime, so ONLY the shape decides:
        # an idle session is never polled (the beat writes no episode), and an age below FROZEN_PROBE_S
        # with a matching anchor cannot come from a real beat (age only grows), so it is seeded too.
        fs._write_retry_wedge_state(str(root), {"attempt": 3, "confirmed": False, "retry_in": "12s", "first_seen": _FL_BASE, "transcript_instant": mtime})
    else:
        fs.diagnose_root(str(root), now=_FL_BASE, transcript_age=90, terminal=_FL_TERM, fast_lane=True)
    assert _fl_state_file(root).exists(), "the episode exists before the non-liveness scan"
    middle_now = _FL_BASE + 30
    middle_age: int | None = 120  # same transcript instant as the beat: now - age == mtime
    middle_terminal: dict[str, str] | None = _FL_TERM
    server_owned = False
    if case == "transcript-advanced":
        middle_age = fs.FROZEN_PROBE_S - 1
    elif case == "anchor-moved":
        middle_age = 100  # still >= FROZEN_PROBE_S and in flight, but the transcript advanced 20 s
        mtime = middle_now - middle_age
    elif case == "no-terminal":
        middle_terminal = None
    elif case == "unarmed":
        (root / ".janitor" / "state" / "disarmed.flag").write_text("", encoding="utf-8")
    elif case == "server-owned":
        server_owned = True
    elif case == "age-unknown":
        middle_age = None
    elif case == "no-anchor":
        episode = fs._read_retry_wedge_state(str(root))
        assert episode is not None
        episode.pop("transcript_instant")
        fs._write_retry_wedge_state(str(root), episode)
    fs.diagnose_root(str(root), now=middle_now, transcript_age=middle_age, terminal=middle_terminal, fast_lane=False, server_owned=server_owned)
    assert not _fl_state_file(root).exists(), "a scan that is not the fast-lane shape still clears"
    if idle:
        return  # the third beat never polls an idle session, so "healthy" would prove nothing here
    if case == "unarmed":
        (root / ".janitor" / "state" / "disarmed.flag").unlink()
    third_now = _FL_BASE + gap
    third = fs.diagnose_root(str(root), now=third_now, transcript_age=third_now - mtime, terminal=_FL_TERM, fast_lane=True)
    assert third[:2] == ("healthy", None)



def _append_rows(root: Path, rows: list[str]) -> None:
    """Append rows to the root's one transcript, exactly as Claude Code appends them."""
    with open(Path(fs._transcript_dir(str(root))) / "s1.jsonl", "a", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")


def _age_now(root: Path, now: int) -> int:
    """The transcript age `gather_fleet` hands `diagnose_root`: the REAL `transcript_activity`
    (substantive row instant), not a number the test picks."""
    age = fs.transcript_activity(str(root), now)[0]
    assert age is not None
    return age


@pytest.mark.parametrize("interrupt_at", [_FL_BASE + 40, _FL_BASE - 399], ids=["interrupt-later", "interrupt-within-anchor-tolerance"])
def test_an_interrupt_row_after_a_sent_resume_clears_the_episode_instead_of_sparing_it(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch", interrupt_at: int
) -> None:
    """Lost-resume case (TRDD-RJJGXPIK follow-up): the ESC aborts the turn and Claude Code writes
    `[Request interrupted by user]` as an ordinary `user` row. That row IS substantive for the
    liveness age (only queue bookkeeping is skipped), is in `_NOT_A_MODEL_REQUEST_PREFIXES`, and
    so the turn is no longer in flight: a non-polling scan must CLEAR the episode, resume_sent
    included, exactly as before the spare existed — it must neither delay nor suppress anything.
    `interrupt-within-anchor-tolerance` stamps the row inside the 2 s anchor tolerance so ONLY the
    in-flight guard can clear it; a control scan of the unchanged transcript proves the same
    episode IS spared without the interrupt row, so the clear is not a vacuous pass."""
    import fleet_recovery as fr  # type: ignore[import-not-found]

    root = _fl_root(tmp_path, monkeypatch, "lost-resume", _IN_FLIGHT_ROWS)
    spy = _PaneSpy(_retry_frame("12s", 3))
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    beat = _FL_BASE
    fs.diagnose_root(str(root), now=beat, transcript_age=_age_now(root, beat), terminal=_FL_TERM, fast_lane=True)
    fs.mark_retry_wedge_resume_sent(str(root), beat)
    assert fs.retry_wedge_resume_sent(str(root), beat) is True
    control = beat + 30
    fs.diagnose_root(str(root), now=control, transcript_age=_age_now(root, control), terminal=_FL_TERM, fast_lane=False)
    assert fs.retry_wedge_resume_sent(str(root), control) is True, "control: unchanged quiet turn is spared"

    _append_rows(root, [_row(interrupt_at, "user", "[Request interrupted by user]")])
    scan = beat + 120
    assert _age_now(root, scan) == scan - interrupt_at, "(a) the interrupt row counts as substantive"
    assert "[Request interrupted by user]".startswith(fs._NOT_A_MODEL_REQUEST_PREFIXES), "(b) it is a non-request prefix"
    assert fs.transcript_turn_in_flight(str(root)) is False, "(c) the turn is no longer in flight"
    reads = spy.reads
    fs.diagnose_root(str(root), now=scan, transcript_age=_age_now(root, scan), terminal=_FL_TERM, fast_lane=False)
    assert not _fl_state_file(root).exists(), "(d) the episode is cleared, not spared"
    assert fs.retry_wedge_resume_sent(str(root), scan) is False
    # Next liveness-path decision: the session is not wedged and a fresh wedge may resume again.
    nxt = fs.diagnose_root(str(root), now=scan + 120, transcript_age=_age_now(root, scan + 120), terminal=_FL_TERM, fast_lane=True)
    assert nxt[:2] == ("healthy", None) and spy.reads == reads, "an idle prompt is not polled"
    assert fr.action_for("retry_wedged", 0, resume_sent=fs.retry_wedge_resume_sent(str(root), scan + 120)) == "esc_nudge_resume"
    if interrupt_at > beat:
        # The daemon's resume-pending retry reads its OWN marker and ignores the interrupt row.
        assert fs.transcript_activity_since(str(root), beat + 20) is False


@pytest.mark.parametrize("queued", [5, 574], ids=["few-queue-rows", "substantive-row-out-of-the-window"])
def test_queue_rows_push_the_substantive_row_out_of_the_tail_and_the_anchor_then_fails_safe(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch", queued: int
) -> None:
    """`substantive_age_from_tail` skips trailing `queue-operation` rows while the substantive row
    is still inside the 64 KiB tail window, so the anchor (`now - transcript_age`) is unchanged and
    the episode is spared. Once enough queue rows (574 of the 113-byte shape here: 65536 / 114)
    push that row out of the window, the tail is ALL queue rows: the age is measured from the
    OLDEST queue row, the instant jumps forward, the anchor no longer matches and the episode is
    cleared (fail-safe). The mtime fallback is NOT what happens here; it needs a window with no
    parseable timestamp at all."""
    root = _fl_root(tmp_path, monkeypatch, "storm", _IN_FLIGHT_ROWS)
    monkeypatch.setattr(fs, "capture_pane_text", _PaneSpy(_retry_frame("12s", 3)))
    beat = _FL_BASE
    fs.diagnose_root(str(root), now=beat, transcript_age=_age_now(root, beat), terminal=_FL_TERM, fast_lane=True)
    anchor = fs._read_retry_wedge_state(str(root))["transcript_instant"]  # type: ignore[index]
    assert anchor == _FL_BASE - 400
    _append_rows(root, [_enqueue_line(beat + 10 + i, "resume") for i in range(queued)])
    in_window = any("say hi" in ln for ln in fs._tail_lines(os.path.join(fs._transcript_dir(str(root)), "s1.jsonl")))
    assert in_window is (queued < 574)
    scan = beat + 30 + queued
    age = _age_now(root, scan)
    matches = abs((scan - age) - anchor) <= fs._EPISODE_ANCHOR_TOLERANCE_S
    assert matches is in_window
    fs.diagnose_root(str(root), now=scan, transcript_age=age, terminal=_FL_TERM, fast_lane=False)
    assert _fl_state_file(root).exists() is in_window


def test_gather_fleet_gives_the_fast_lane_only_to_an_opted_in_scan_of_a_single_instance_root(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """The REAL `gather_fleet` loop, with only the process-table / tmux / lsof / pane-read
    boundary replaced. Rule (a): `fast_lane` defaults to False, so a default scan reads no pane.
    Rule (b): the transcript is per root but the pane per instance — with TWO live claude
    instances in one root (idle A with an old banner, in-flight B) the fast lane is withheld for
    both, so A is never read; a root with ONE instance, opted in, is read once."""
    now = 1_790_000_000
    root, tdir = _activity_root(tmp_path, monkeypatch, "gather")
    (root / ".janitor" / "state").mkdir(parents=True)
    path = tdir / "s1.jsonl"
    path.write_text(_row(now - 200, "user", "say hi") + "\n", encoding="utf-8")
    os.utime(path, (now - 200, now - 200))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    ps = {"text": "  101 ttys001 claude\n"}
    tmux_out = "/dev/ttys001 %5\n/dev/ttys002 %6\n"
    monkeypatch.setattr(
        fs, "_run", lambda cmd, **_k: ps["text"] if cmd[0] == "ps" else (tmux_out if cmd[0] == "tmux" else "")
    )
    monkeypatch.setattr(fs, "_cwd_of", lambda _pid: str(root))
    monkeypatch.setattr(fs, "_aimaestro_agents", lambda *_a, **_k: (None, [], False))
    spy = _PaneSpy(_retry_frame("12s", 3))
    monkeypatch.setattr(fs, "capture_pane_text", spy)

    assert [i.diagnosis for i in fs.gather_fleet(now=now)] == ["healthy"]
    assert spy.reads == 0, "a default scan is stale-only"
    assert [i.diagnosis for i in fs.gather_fleet(now=now, fast_lane=True)] == ["healthy"]
    assert spy.reads == 1, "one instance in the root, opted in: read once"

    ps["text"] = "  101 ttys001 claude\n  102 ttys002 claude\n"
    fleet = fs.gather_fleet(now=now, fast_lane=True)
    assert [i.diagnosis for i in fleet] == ["healthy", "healthy"]
    assert spy.reads == 1, "a root shared by two instances is stale-lane only"

@pytest.fixture(autouse=True)
def _recorded_recheck_pause(monkeypatch: "pytest.MonkeyPatch") -> list[float]:
    """The frozen-proof confirmation recheck waits FROZEN_RECHECK_S between two real pane reads.
    Replace only that wait (the module's `_sleep` seam): no test really sleeps, and the calls are
    recorded so a test can prove the pause happened (the logic under test is unchanged)."""
    calls: list[float] = []
    monkeypatch.setattr(fs, "_sleep", calls.append)
    return calls


class _SeqPaneSpy:
    """Pane READ boundary returning a scripted sequence of frames (last one repeats); counts reads."""

    def __init__(self, *frames: str | None) -> None:
        self.frames = frames
        self.reads = 0

    def __call__(self, _terminal: object) -> str | None:
        frame = self.frames[min(self.reads, len(self.frames) - 1)]
        self.reads += 1
        return frame


_STALE_AGE = fs.STALE_S + 5
# A frame caught mid-redraw: read fine, but no parsable `Retrying in` status row.
_UNPARSABLE_FRAME = "⏺ redrawing…\n" + "─" * 40 + "\n❯ \n" + "─" * 40 + "\n"


@pytest.mark.parametrize("lane", ["fast", "stale"])
@pytest.mark.parametrize(
    ("recheck", "outcome"),
    [
        pytest.param(_retry_frame("12s", 3), "acts", id="identical"),  # frozen beyond doubt
        pytest.param(_retry_frame("9s", 3), "moved", id="moved"),  # a LIVE retry that coincided at both beats
pytest.param(None, "blind", id="capture-failed"),  # cannot assess, never act
        pytest.param(_UNPARSABLE_FRAME, "blind", id="unparsable-frame"),  # read, but no countdown to compare
    ],
)
def test_frozen_proof_acts_only_if_the_recheck_countdown_is_byte_identical(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch", _recorded_recheck_pause: list[float],
    lane: str, recheck: str | None, outcome: str,
) -> None:
    """Two samples ~119 s apart show the same `Retrying in 12s`, which a frozen countdown AND a
    live one that happens to coincide both produce. On EITHER lane (fast: quiet in-flight
    transcript; stale: transcript >= STALE_S) one more capture, FROZEN_RECHECK_S later, must be
    byte-identical before acting. A recheck that was READ with a parsed, DIFFERENT countdown must not leave the frozen
    confirmation on disk (a carried `confirmed` would let the stale lane ESC a live retry later):
    persisted `confirmed` reverts to the previous poll's (False), no `proof`, `first_seen`
    restarts, `retry_in` is the recheck's. A recheck that could not be read, or has no parsable
    countdown (a mid-redraw frame), leaves the episode
    exactly as it stood before the beat (TRDD-RJJGXPIK)."""
    monkeypatch.setattr(fs, "FROZEN_RECHECK_S", 7)  # a sentinel: proves the configured pause is used
    root = _fl_root(tmp_path, monkeypatch, "recheck", _IN_FLIGHT_ROWS)
    frozen = _retry_frame("12s", 3)
    spy = _SeqPaneSpy(frozen, frozen, recheck)  # beat 1, beat 2 first read, beat 2 recheck
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    age = 90 if lane == "fast" else _STALE_AGE
    first = fs.diagnose_root(str(root), now=_FL_BASE, transcript_age=age, terminal=_FL_TERM, fast_lane=True)
    assert first[0] != "retry_wedged" and spy.reads == 1, "first sighting: baseline only, no recheck"
    assert _recorded_recheck_pause == []
    before = fs._read_retry_wedge_state(str(root))
    second = fs.diagnose_root(str(root), now=_FL_BASE + 119, transcript_age=age + 119, terminal=_FL_TERM, fast_lane=True)
    assert spy.reads == 3, "the frozen proof triggers exactly one recheck capture"
    assert _recorded_recheck_pause == [7], "the pause between the two captures really happens"
    assert (second[:2] == ("retry_wedged", "esc_retry")) is (outcome == "acts")
    persisted = fs._read_retry_wedge_state(str(root))
    assert persisted is not None, "the episode is never cleared by the recheck"
    if outcome == "acts":
        assert persisted["confirmed"] is True and persisted["proof"] == "frozen-countdown"
        assert persisted["first_seen"] == _FL_BASE
    elif outcome == "moved":
        assert persisted["confirmed"] is False and "proof" not in persisted
        assert persisted["first_seen"] == _FL_BASE + 119, "a live countdown must earn a fresh 100 s"
        assert persisted["retry_in"] == "9s", "the latest observation"
    else:
        # The decision state stands as it was; only the read stamp (TRDD-XVJ30M61) moves, because the
        # first capture of this beat DID read the pane: `read_at` is this beat, `last_retry_in` its raw countdown.
        assert before is not None
        assert persisted == {**before, "read_at": _FL_BASE + 119, "last_retry_in": "12s"}, (
            "an unreadable recheck leaves the episode exactly as it stood, bar the read stamp"
        )
    if outcome != "acts" and lane == "fast":
        assert second[:2] == ("healthy", None)


@pytest.mark.parametrize("lane", ["fast", "stale"])
@pytest.mark.parametrize("outcome", ["moved", "blind", "unparsable"])
def test_rejected_recheck_keeps_a_genuine_attempt_advance_confirmation(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch", lane: str, outcome: str
) -> None:
    """A rejected frozen proof must not erase what an earlier poll genuinely proved: with the
    episode already confirmed by an attempt ADVANCE (and a resume marker), a moved recheck keeps
    `confirmed` True, the resume marker and `proof` = attempt-advance (the state shape
    `retry_wedge_state_update` produces), restarts `first_seen` and stores the recheck's
    `retry_in`; an unreadable recheck leaves the seeded state exactly as it was. The stale lane
    still acts on that attempt-advance confirmation; the fast lane (no stale transcript) never
    acts on it (TRDD-RJJGXPIK)."""
    root = _fl_root(tmp_path, monkeypatch, "keep-advance", _IN_FLIGHT_ROWS)
    seed = {
        "attempt": 3, "confirmed": True, "retry_in": "12s", "first_seen": _FL_BASE - 119,
        "proof": "attempt-advance", "resume_sent": True, "resume_sent_at": _FL_BASE - 50,
    }
    fs._write_retry_wedge_state(str(root), dict(seed))
    recheck_frame = {"moved": _retry_frame("9s", 3), "blind": None, "unparsable": _UNPARSABLE_FRAME}[outcome]
    spy = _SeqPaneSpy(_retry_frame("12s", 3), recheck_frame)
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    age = 90 if lane == "fast" else _STALE_AGE
    diag = fs.diagnose_root(str(root), now=_FL_BASE, transcript_age=age, terminal=_FL_TERM, fast_lane=True)
    assert spy.reads == 2
    assert (diag[:2] == ("retry_wedged", "esc_retry")) is (lane == "stale")
    persisted = fs._read_retry_wedge_state(str(root))
    # The beat stamps the transcript anchor and the read stamp (TRDD-XVJ30M61) on the episode it keeps (the seed has neither); nothing else changes.
    anchored = {**seed, "transcript_instant": _FL_BASE - age, "read_at": _FL_BASE, "last_retry_in": "12s"}
    if outcome != "moved":
        assert persisted == anchored
        return
    assert persisted == {**anchored, "retry_in": "9s", "first_seen": _FL_BASE}


# Spelled out here (not read from fs) so removing an entry from the source tuple fails the test.
_NON_REQUEST_PREFIXES = (
    "[Request interrupted by user",
    "<local-command-caveat>",
    "<command-name>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "This session is being continued",
)


@pytest.mark.parametrize("prefix", _NON_REQUEST_PREFIXES)
def test_every_non_model_request_prefix_means_the_turn_is_not_in_flight(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch", prefix: str
) -> None:
    """Each entry of `_NOT_A_MODEL_REQUEST_PREFIXES` (interrupt marker, local slash command rows,
    shell-escape rows, compact summary) as the newest user row means the session is idle at its
    prompt, never in flight; the same row without the prefix (a plain prompt) is in flight."""
    assert set(_NON_REQUEST_PREFIXES) == set(fs._NOT_A_MODEL_REQUEST_PREFIXES), "update the expected list"
    slug = "".join(c if c.isalnum() else "-" for c in prefix)
    idle = _fl_root(tmp_path, monkeypatch, f"prefix-{slug}", [_row(_FL_BASE, "user", f"{prefix}payload")])
    assert fs.transcript_turn_in_flight(str(idle)) is False
    padded = _fl_root(tmp_path, monkeypatch, f"prefix-pad-{slug}", [_row(_FL_BASE, "user", f"\n  {prefix}payload")])
    assert fs.transcript_turn_in_flight(str(padded)) is False, "leading whitespace is ignored"
    prompt = _fl_root(tmp_path, monkeypatch, f"prefix-ctl-{slug}", [_row(_FL_BASE, "user", f"payload {prefix}")])
    assert fs.transcript_turn_in_flight(str(prompt)) is True, "only a LEADING prefix counts"



def test_only_the_liveness_beat_opts_into_the_fast_lane() -> None:
    """Every production `gather_fleet(...)` call (fleet_status, the cold-cache and peer-freeze
    scans, hooks, the CLI entry) must stay stale-only, because an iTerm pane read is an Apple
    Event; exactly one call — `task_session_liveness` in daemon.py — may pass `fast_lane` (and
    only as `True`). Found by walking the real sources' syntax trees (TRDD-RJJGXPIK rule (a))."""
    import ast

    scripts = Path(fs.__file__).resolve().parent.parent
    opted_in: list[str] = []
    calls = 0
    for src in [*scripts.glob("*.py"), *(scripts / "lib").glob("*.py")]:
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) == "gather_fleet":
                    calls += 1
                    for kw in node.keywords:
                        if kw.arg == "fast_lane":
                            assert isinstance(kw.value, ast.Constant) and kw.value.value is True
                            opted_in.append(f"{src.name}:{fn.name}")
    assert calls >= 4, "the walker must actually see the production callers"
    assert sorted(set(opted_in)) == ["daemon.py:task_session_liveness"]


# --- TRDD-XVJ30M61 (logging only): the retry-wedge countdown the daemon beat logs ---

_REAL_429 = (_PROJECT_ROOT / "tests" / "fixtures" / "pane_frames" / "real-wedged-rate-limit-429.txt").read_text()


def _stale_poll(root: Path, now: int) -> None:
    """One STALE-lane diagnose_root pane read (transcript older than STALE_S)."""
    fs.diagnose_root(str(root), now=now, transcript_age=fs.STALE_S + 5, terminal=_FL_TERM)


def test_the_real_429_frame_logs_attempt_countdown_and_a_zero_read_age(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """TRDD-XVJ30M61: the real `Retrying in 0s · attempt 5/300` frame, read through
    `diagnose_root` with no prior episode, yields the token `retry_wedge@5[0s] read_age=0s`;
    with no episode on disk there is nothing to log."""
    root = _fl_root(tmp_path, monkeypatch, "log-429", _IN_FLIGHT_ROWS)
    assert fs.retry_wedge_log_token(str(root), _FL_BASE) is None
    spy = _PaneSpy(_REAL_429)
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    _stale_poll(root, _FL_BASE)
    assert spy.reads == 1
    token = fs.retry_wedge_log_token(str(root), _FL_BASE)
    assert token is not None
    assert "retry_wedge@5[0s]" in token
    assert "read_age=0s" in token


def test_a_frame_without_a_parsable_countdown_never_logs_the_carried_zero_s(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """`retry_wedge_state_update` carries the previous poll's `retry_in` over a frame that has
    none; the log must show the countdown THIS read showed (none), not a fake `[0s]`."""
    root = _fl_root(tmp_path, monkeypatch, "log-no-countdown", _IN_FLIGHT_ROWS)
    spy = _PaneSpy(_REAL_429)
    monkeypatch.setattr(fs, "capture_pane_text", spy)
    _stale_poll(root, _FL_BASE)
    assert "[0s]" in (fs.retry_wedge_log_token(str(root), _FL_BASE) or "")
    border = "─" * 40
    # `Retrying in` + `attempt N/M` but no ` · ` before the attempt: the attempt parses, the countdown does not.
    spy.text = f"✻ Rate limited · Retrying in 0s attempt 6/300\n{border}\n❯ \n{border}\n"
    assert fs._read_retry_wedge_state(str(root)) is not None
    _stale_poll(root, _FL_BASE + 120)
    carried = fs._read_retry_wedge_state(str(root))
    assert carried is not None and carried["retry_in"] == "0s", "the state still carries it (premise)"
    token = fs.retry_wedge_log_token(str(root), _FL_BASE + 120)
    assert token is not None
    assert token.startswith("retry_wedge@6 "), token
    assert "[" not in token, token


def test_a_resume_marker_rewrite_does_not_refresh_the_read_age(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """`mark_retry_wedge_resume_sent` rewrites the episode file with no pane read: `read_age`
    must keep growing from the real read (240 s), not reset to the rewrite instant."""
    root = _fl_root(tmp_path, monkeypatch, "log-resume-marker", _IN_FLIGHT_ROWS)
    monkeypatch.setattr(fs, "capture_pane_text", _PaneSpy(_REAL_429))
    _stale_poll(root, _FL_BASE)
    fs.mark_retry_wedge_resume_sent(str(root), _FL_BASE + 240)
    token = fs.retry_wedge_log_token(str(root), _FL_BASE + 240)
    assert token is not None
    assert token == "retry_wedge@5[0s] read_age=240s"


def test_retry_wedge_log_token_is_none_for_a_state_it_cannot_age(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """No int attempt, or no int `read_at` (an older build's file), is not logged; a clock that
    went backwards clamps to 0 rather than printing a negative age."""
    root = _fl_root(tmp_path, monkeypatch, "log-unageable", _IN_FLIGHT_ROWS)
    sdir = root / ".janitor" / "state"
    sdir.mkdir(parents=True)
    path = sdir / fs._RETRY_WEDGE_STATE_FILE
    for body in (
        {"attempt": 5, "retry_in": "0s"},
        {"attempt": "5", "read_at": _FL_BASE},
        {"attempt": 5, "read_at": "x"},
        {"read_at": _FL_BASE},
        {"attempt": True, "read_at": _FL_BASE},
        {"attempt": 5, "read_at": True},
    ):
        path.write_text(json.dumps(body), encoding="utf-8")
        assert fs.retry_wedge_log_token(str(root), _FL_BASE) is None, body
    path.write_text(json.dumps({"attempt": 5, "read_at": _FL_BASE + 50}), encoding="utf-8")
    assert fs.retry_wedge_log_token(str(root), _FL_BASE) == "retry_wedge@5 read_age=0s"


def test_a_spared_non_polling_beat_lets_the_read_age_keep_growing(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """A non-polling scan on the same quiet in-flight turn spares the episode (no pane read, no
    write), so `read_at` stays the real read at the first beat and `read_age` grows to 120 s.
    The first read is the FAST lane: a stale-lane read cannot be followed by a non-stale
    transcript, and a stale one polls instead of sparing."""
    root = _fl_root(tmp_path, monkeypatch, "log-spared", _IN_FLIGHT_ROWS)
    monkeypatch.setattr(fs, "capture_pane_text", _PaneSpy(_REAL_429))
    fs.diagnose_root(str(root), now=_FL_BASE, transcript_age=90, terminal=_FL_TERM, fast_lane=True)
    assert fs.retry_wedge_log_token(str(root), _FL_BASE) == "retry_wedge@5[0s] read_age=0s"
    blind = _PaneSpy(None)
    monkeypatch.setattr(fs, "capture_pane_text", blind)
    fs.diagnose_root(str(root), now=_FL_BASE + 120, transcript_age=210, terminal=_FL_TERM, fast_lane=False)
    assert blind.reads == 0, "the non-polling beat reads no pane"
    assert fs.retry_wedge_log_token(str(root), _FL_BASE + 120) == "retry_wedge@5[0s] read_age=120s"
