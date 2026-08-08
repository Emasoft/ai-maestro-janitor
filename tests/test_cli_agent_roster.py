"""Tests for scripts/lib/cli_agent_roster.py (TRDD-DFKEXO79)."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))

import cli_agent_roster as car  # noqa: E402

# A real captured sample of `claude agents --json` output (probed 2026-08-08), trimmed to
# a few rows covering both the background and interactive row shapes.
REAL_SAMPLE = """
[
  {
    "id": "5704891f",
    "cwd": "/Users/emanuelesabetta/Code/ANIME2SVG",
    "kind": "background",
    "startedAt": 1783299091026,
    "sessionId": "5704891f-0fa1-479f-a828-279eabf977c7",
    "name": "Update AGENTS.md documentation",
    "state": "blocked"
  },
  {
    "pid": 44740,
    "cwd": "/Users/emanuelesabetta/Code/claude-voice-loop",
    "kind": "interactive",
    "startedAt": 1786117223783,
    "sessionId": "5df835f5-96e9-40b2-b24a-51ce4becc7d7",
    "name": "cvoice-plugin-conversion",
    "status": "idle"
  },
  {
    "pid": 45377,
    "cwd": "/Users/emanuelesabetta/Code/AI-MAESTRO-JANITOR/ai-maestro-janitor",
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
        "/Users/emanuelesabetta/Code/ANIME2SVG",
        "/Users/emanuelesabetta/Code/claude-voice-loop",
        "/Users/emanuelesabetta/Code/AI-MAESTRO-JANITOR/ai-maestro-janitor",
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


def test_fetch_agents_timeout_is_reported(tmp_path: Path, monkeypatch) -> None:
    """A process that outlives the timeout is reported as timeout, not left to hang."""
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
