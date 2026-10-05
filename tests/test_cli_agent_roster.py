"""Tests for scripts/lib/cli_agent_roster.py (TRDD-DFKEXO79)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))

import cli_agent_roster as car  # noqa: E402

# A real captured sample of `claude agents --json` output (probed 2026-08-08), trimmed to
# a few rows covering both the background and interactive row shapes.
REAL_SAMPLE = """
[
  {
    "id": "5704891f",
    "cwd": "/Users/testuser/Code/PROJECT-A",
    "kind": "background",
    "startedAt": 1783299091026,
    "sessionId": "5704891f-0fa1-479f-a828-279eabf977c7",
    "name": "Update AGENTS.md documentation",
    "state": "blocked"
  },
  {
    "pid": 44740,
    "cwd": "/Users/testuser/Code/PROJECT-B",
    "kind": "interactive",
    "startedAt": 1786117223783,
    "sessionId": "5df835f5-96e9-40b2-b24a-51ce4becc7d7",
    "name": "cvoice-plugin-conversion",
    "status": "idle"
  },
  {
    "pid": 45377,
    "cwd": "/Users/testuser/Code/AI-MAESTRO-JANITOR/ai-maestro-janitor",
    "kind": "interactive",
    "startedAt": 1786118464904,
    "sessionId": "35e1e917-2249-4deb-a6b4-f1a89faa806b",
    "name": "ai-maestro-janitor-be",
    "status": "busy"
  }
]
"""


def test_parse_real_sample_returns_three_rows() -> None:
    """A real captured `claude agents --json` array parses into 3 dict rows."""
    rows = car.parse_agents_json(REAL_SAMPLE)
    assert len(rows) == 3
    assert all(isinstance(r, dict) for r in rows)


def test_parse_empty_string_returns_empty_list() -> None:
    """Empty stdout fails open to []."""
    assert car.parse_agents_json("") == []


def test_parse_whitespace_only_returns_empty_list() -> None:
    """Whitespace-only stdout fails open to []."""
    assert car.parse_agents_json("   \n  ") == []


def test_parse_malformed_json_returns_empty_list() -> None:
    """Non-JSON garbage fails open to [] rather than raising."""
    assert car.parse_agents_json("{not json at all") == []


def test_parse_dict_wrapped_list_is_tolerated() -> None:
    """A defensive {"agents": [...]} wrapper shape is unwrapped."""
    payload = '{"agents": [{"cwd": "/a", "kind": "interactive", "name": "x"}]}'
    rows = car.parse_agents_json(payload)
    assert rows == [{"cwd": "/a", "kind": "interactive", "name": "x"}]


def test_parse_dict_with_no_list_value_returns_empty_list() -> None:
    """A dict payload with no list-valued key has nothing to unwrap."""
    assert car.parse_agents_json('{"count": 3}') == []


def test_parse_top_level_scalar_returns_empty_list() -> None:
    """A bare JSON scalar (not list/dict) is not a valid roster payload."""
    assert car.parse_agents_json("42") == []


def test_parse_drops_non_dict_entries() -> None:
    """Non-object array entries are dropped, valid dict entries kept."""
    rows = car.parse_agents_json('[1, "x", {"cwd": "/a", "kind": "interactive"}]')
    assert rows == [{"cwd": "/a", "kind": "interactive"}]


def test_roster_by_cwd_groups_real_sample_by_cwd() -> None:
    """Real sample rows land under their own project's cwd key, one row each."""
    rows = car.parse_agents_json(REAL_SAMPLE)
    grouped = car.roster_by_cwd(rows)
    assert set(grouped.keys()) == {
        "/Users/testuser/Code/PROJECT-A",
        "/Users/testuser/Code/PROJECT-B",
        "/Users/testuser/Code/AI-MAESTRO-JANITOR/ai-maestro-janitor",
    }
    for group in grouped.values():
        assert len(group) == 1


def test_roster_by_cwd_normalizes_trailing_slash() -> None:
    """A trailing "/" on cwd must not split one project into two groups."""
    rows = [
        {"cwd": "/a/b", "name": "one"},
        {"cwd": "/a/b/", "name": "two"},
    ]
    grouped = car.roster_by_cwd(rows)
    assert set(grouped.keys()) == {"/a/b"}
    assert len(grouped["/a/b"]) == 2


def test_roster_by_cwd_ignores_name_as_a_join_key() -> None:
    """Two rows with the SAME name but DIFFERENT cwd must land in separate groups.

    This is the load-bearing invariant: `name` is a mutable display string, never
    identity. If grouping ever keyed on `name` these two rows would collapse together.
    """
    rows = [
        {"cwd": "/project-one", "name": "same-name"},
        {"cwd": "/project-two", "name": "same-name"},
    ]
    grouped = car.roster_by_cwd(rows)
    assert set(grouped.keys()) == {"/project-one", "/project-two"}
    assert grouped["/project-one"][0]["cwd"] == "/project-one"
    assert grouped["/project-two"][0]["cwd"] == "/project-two"


def test_roster_by_cwd_drops_rows_missing_cwd() -> None:
    """A row with no cwd field cannot be placed under any project and is dropped."""
    rows = [{"name": "no-cwd-here"}]
    assert car.roster_by_cwd(rows) == {}


def test_roster_by_cwd_drops_rows_with_non_string_cwd() -> None:
    """A row whose cwd is not a string (e.g. null) is dropped, not crashed on."""
    rows = [{"cwd": None, "name": "x"}, {"cwd": "", "name": "y"}]
    assert car.roster_by_cwd(rows) == {}


def test_second_view_verdict_channel_blocked_not_empty() -> None:
    """osascript sees 0 while the CLI view sees sessions -> channel is blocked, not empty."""
    assert (
        car.second_view_verdict(osascript_sessions=0, cli_rows_for_host=5)
        == "channel-blocked-not-empty"
    )


def test_second_view_verdict_consistent_empty() -> None:
    """Both enumerators agree on 0 -> genuinely empty, not a blocked channel."""
    assert (
        car.second_view_verdict(osascript_sessions=0, cli_rows_for_host=0)
        == "consistent-empty"
    )


def test_second_view_verdict_channel_working() -> None:
    """osascript itself produced results -> the channel is not blocked."""
    assert (
        car.second_view_verdict(osascript_sessions=3, cli_rows_for_host=0)
        == "channel-working"
    )
    assert (
        car.second_view_verdict(osascript_sessions=1, cli_rows_for_host=10)
        == "channel-working"
    )


def _write_shim(tmp_path: Path, script: str) -> Path:
    """Write an executable shell script named `claude` under tmp_path and return its dir."""
    shim = tmp_path / "claude"
    shim.write_text(script)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return tmp_path


def _prepend_to_path(monkeypatch, shim_dir: Path) -> None:
    """Put `shim_dir` first on PATH, keeping the real PATH behind it.

    The shim scripts below use `/bin/sh` builtins like `cat`/`echo`/`sleep`, which must
    still resolve — replacing PATH outright (rather than prepending) leaves the shell
    unable to find its own coreutils and every shim fails with exit 127.
    """
    monkeypatch.setenv("PATH", f"{shim_dir}:{os.environ.get('PATH', '')}")


def test_fetch_agents_success_with_shim(tmp_path: Path, monkeypatch) -> None:
    """A `claude` shim on PATH that echoes real JSON is parsed with no error string."""
    shim_dir = _write_shim(
        tmp_path,
        f"#!/bin/sh\ncat <<'EOF'\n{REAL_SAMPLE}\nEOF\n",
    )
    _prepend_to_path(monkeypatch, shim_dir)
    rows, why = car.fetch_agents()
    assert why == ""
    assert len(rows) == 3


def test_fetch_agents_empty_stdout_is_not_an_error(tmp_path: Path, monkeypatch) -> None:
    """Exit 0 with empty stdout means a genuinely empty roster, not a failure."""
    shim_dir = _write_shim(tmp_path, "#!/bin/sh\nexit 0\n")
    _prepend_to_path(monkeypatch, shim_dir)
    rows, why = car.fetch_agents()
    assert rows == []
    assert why == ""


def test_fetch_agents_nonzero_exit_reports_exit_code(tmp_path: Path, monkeypatch) -> None:
    """A non-zero exit is reported as exit-<code>, distinguishable from an empty roster."""
    shim_dir = _write_shim(tmp_path, "#!/bin/sh\necho 'boom' >&2\nexit 7\n")
    _prepend_to_path(monkeypatch, shim_dir)
    rows, why = car.fetch_agents()
    assert rows == []
    assert why == "exit-7"


def test_fetch_agents_unparseable_stdout_is_reported(tmp_path: Path, monkeypatch) -> None:
    """Exit 0 with garbage stdout is reported as unparseable, not a silent empty roster."""
    shim_dir = _write_shim(tmp_path, "#!/bin/sh\necho 'not json at all'\n")
    _prepend_to_path(monkeypatch, shim_dir)
    rows, why = car.fetch_agents()
    assert rows == []
    assert why == "unparseable"


@pytest.mark.no_timeout_scale
def test_fetch_agents_timeout_is_reported(tmp_path: Path, monkeypatch) -> None:
    """A process that outlives the timeout is reported as timeout, not left to hang."""
    # OPT OUT of the harness's subprocess-timeout scale (TRDD-7NSRD8OV). Every other test wants
    # timeouts stretched so suite load cannot fake one; THIS test is the one that deliberately
    # CAUSES a timeout, so the stretch would defeat it — at the suite's scale of 10 a 1 s ceiling
    # becomes 10 s, the `sleep 5` shim finishes comfortably inside it, and the assertion fails
    # having proven nothing. A test that pins timeout behaviour has to own the scale.
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_SUBPROCESS_TIMEOUT_SCALE", "1")
    shim_dir = _write_shim(tmp_path, "#!/bin/sh\nsleep 5\n")
    _prepend_to_path(monkeypatch, shim_dir)
    rows, why = car.fetch_agents(timeout_s=1)
    assert rows == []
    assert why == "timeout"


def test_fetch_agents_binary_absent_reports_not_on_path(monkeypatch) -> None:
    """No `claude` binary anywhere on PATH is reported explicitly, never a silent []."""
    monkeypatch.setenv("PATH", "/nonexistent-dir-for-test")
    rows, why = car.fetch_agents()
    assert rows == []
    assert why == "claude-not-on-PATH"

@pytest.mark.skipif(sys.platform == "win32", reason="a live process's working directory cannot be removed on Windows")
def test_fetch_agents_works_when_the_inherited_working_directory_was_deleted(tmp_path: Path) -> None:
    """A process whose own working directory was removed still gets the roster (TRDD-0QCRG2YX)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Behaves like the real CLI: `pwd -P` fails from a deleted directory (`ls .` does not).
    _write_shim(
        bin_dir,
        "#!/bin/sh\n"
        # Control mode only: wait (builtins only) until the test has removed the shell's directory.
        'while [ -n "$WAIT_FOR" ] && [ ! -e "$WAIT_FOR" ]; do :; done\n'
        "pwd -P >/dev/null 2>&1 || { echo 'error: The current working directory was deleted' >&2; exit 1; }\n"
        "echo '[{\"pid\": 1, \"cwd\": \"/x\", \"kind\": \"interactive\", \"sessionId\": \"s\", \"name\": \"n\"}]'\n",
    )
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}", "JANITOR_LOG_DIR": str(tmp_path / "logs")}
    # Control, in a plain shell (the suite's Python spawn guards call os.getcwd(), which fails from a
    # deleted directory): the stand-in run from a deleted directory with no cwd must fail like the real CLI.
    victim = tmp_path / "victim-shell"
    victim.mkdir()
    shell = subprocess.Popen(
        ["/bin/sh", "-c", 'claude; echo "rc=$?"'],
        cwd=victim, env={**env, "WAIT_FOR": str(tmp_path / "go")}, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    victim.rmdir()  # removed while the stand-in waits
    (tmp_path / "go").write_text("")
    control_out, control_err = shell.communicate(timeout=30)
    assert "rc=1" in control_out
    assert "working directory was deleted" in control_err
    victim = tmp_path / "victim-python"
    victim.mkdir()
    lib = Path(car.__file__).resolve().parent
    child = (
        "import json, os, sys\n"
        f"sys.path.insert(0, {str(lib)!r})\n"
        "os.rmdir(os.getcwd())\n"
        "import cli_agent_roster as car\n"
        "print(json.dumps(car.fetch_agents()))\n"
    )
    out = subprocess.run([sys.executable, "-c", child], cwd=victim, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    rows, why = json.loads(out.stdout)
    assert why == ""
    assert [r["pid"] for r in rows] == [1]


def _failing_claude(monkeypatch, tmp_path: Path, log_dir: Path) -> None:
    """Put a `claude` that prints a distinctive stderr line and exits 7 on PATH; own log dir."""
    _prepend_to_path(monkeypatch, _write_shim(tmp_path, "#!/bin/sh\necho 'distinctive failure text' >&2\nexit 7\n"))
    monkeypatch.setattr(car._state, "log_dir", lambda: log_dir)
    monkeypatch.setattr(car, "_last_logged_failure", "")


def test_fetch_agents_failure_is_logged_with_the_child_error(tmp_path: Path, monkeypatch) -> None:
    """A non-zero exit keeps its return value and writes the stderr line to the daemon log."""
    _failing_claude(monkeypatch, tmp_path, tmp_path)
    assert car.fetch_agents() == ([], "exit-7")
    assert "agent-roster: exit-7 distinctive failure text" in (tmp_path / "daemon.log").read_text()


def test_fetch_agents_identical_failures_log_once(tmp_path: Path, monkeypatch) -> None:
    """Two identical failures in a row write a single daemon-log line."""
    _failing_claude(monkeypatch, tmp_path, tmp_path)
    car.fetch_agents()
    car.fetch_agents()
    assert (tmp_path / "daemon.log").read_text().count("agent-roster: exit-7") == 1


def test_fetch_agents_unwritable_log_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    """A daemon log that cannot be written changes neither the return value nor raises."""
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "daemon.log").mkdir()  # a directory in place of the file: opening it for append raises OSError
    _failing_claude(monkeypatch, tmp_path, bad)
    assert car.fetch_agents() == ([], "exit-7")



def test_fetch_agents_same_failure_after_a_success_logs_again(tmp_path: Path, monkeypatch) -> None:
    """Failure, healthy run, same failure again: two daemon-log lines (a new episode)."""
    _failing_claude(monkeypatch, tmp_path, tmp_path)
    car.fetch_agents()
    _write_shim(tmp_path, "#!/bin/sh\necho '[]'\n")
    assert car.fetch_agents() == ([], "")
    _write_shim(tmp_path, "#!/bin/sh\necho 'distinctive failure text' >&2\nexit 7\n")
    car.fetch_agents()
    assert (tmp_path / "daemon.log").read_text().count("agent-roster: exit-7") == 2


def test_child_cwd_falls_back_when_home_is_missing(tmp_path: Path, monkeypatch) -> None:
    """A HOME that points at a missing directory falls back to an existing directory."""
    monkeypatch.setenv("HOME", str(tmp_path / "no-such-home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "no-such-home"))
    cwd = car._child_cwd()
    assert Path(cwd).is_dir()
    assert cwd != str(tmp_path / "no-such-home")
