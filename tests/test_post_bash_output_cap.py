"""Tests for the S9 PostToolUse Bash-output cap hook (TRDD-ZNN0UK5K).

Real, no mocks: ``cap_text`` is exercised directly and ``main()`` is driven end-to-end by
feeding a real JSON payload on a monkeypatched stdin and parsing the JSON it writes to stdout.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

_HOOK = Path(__file__).resolve().parents[1] / "scripts" / "hooks" / "post-bash-output-cap.py"
_spec = importlib.util.spec_from_file_location("post_bash_output_cap", _HOOK)
assert _spec is not None and _spec.loader is not None
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _run(payload: dict, monkeypatch: pytest.MonkeyPatch, env: dict[str, str | None]) -> str | None:
    """Drive ``main()`` with ``payload`` on stdin under ``env``; return its stdout (or None)."""
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    monkeypatch.setattr(mod.sys, "stdin", io.StringIO(json.dumps(payload)))
    buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stdout", buf)
    assert mod.main() == 0
    return buf.getvalue() or None


def test_cap_text_short_passthrough() -> None:
    """Output within the cap is returned byte-identical (no truncation, no marker)."""
    assert mod.cap_text("hello world", 500) == "hello world"


def test_cap_text_head_and_tail_survive() -> None:
    """A long output keeps BOTH its head and its tail within the cap, with the hidden-count marker."""
    text = "HEADSTART" + ("x" * 5000) + "TAILEND"
    out = mod.cap_text(text, 500)
    assert len(out) <= 500
    assert "HEADSTART" in out  # head preserved
    assert "TAILEND" in out  # tail preserved (where pytest summaries / exit lines live)
    assert "janitor bash-cap" in out


def test_cap_text_tiny_cap_hard_cut() -> None:
    """A cap narrower than the marker degrades to a plain head-cut, still exactly <= cap."""
    out = mod.cap_text("y" * 1000, 40)
    assert len(out) == 40


def test_disabled_no_rewrite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """With neither the env flag nor the sentinel, an oversized Bash output is NOT rewritten."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    out = _run(
        {"tool_name": "Bash", "tool_response": {"stdout": "z" * 5000}},
        monkeypatch,
        {"CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_ENABLED": None, "CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_CHARS": None},
    )
    assert out is None


def test_enabled_via_env_rewrites(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The env flag replaces an oversized Bash output via updatedToolOutput, capped <= cap."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    out = _run(
        {"tool_name": "Bash", "tool_response": {"stdout": "z" * 5000}},
        monkeypatch,
        {"CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_ENABLED": "1", "CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_CHARS": "500"},
    )
    assert out is not None
    payload = json.loads(out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert len(payload["hookSpecificOutput"]["updatedToolOutput"]) <= 500


def test_enabled_via_sentinel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The per-project .janitor/state/bash-output-cap sentinel enables the cap without any env."""
    (tmp_path / ".janitor" / "state").mkdir(parents=True)
    (tmp_path / ".janitor" / "state" / "bash-output-cap").write_text("on")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    out = _run(
        {"tool_name": "Bash", "tool_response": {"stdout": "z" * 5000}},
        monkeypatch,
        {"CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_ENABLED": None, "CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_CHARS": "500"},
    )
    assert out is not None


def test_non_bash_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A non-Bash tool is never touched, even with the cap enabled."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    out = _run(
        {"tool_name": "Read", "tool_response": {"stdout": "z" * 5000}},
        monkeypatch,
        {"CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_ENABLED": "1"},
    )
    assert out is None


def test_cap_zero_disables(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A cap of 0 disables truncation even when otherwise enabled."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    out = _run(
        {"tool_name": "Bash", "tool_response": {"stdout": "z" * 5000}},
        monkeypatch,
        {"CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_ENABLED": "1", "CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_CHARS": "0"},
    )
    assert out is None


def test_stdout_stderr_combined(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """stdout and stderr are combined before the output is measured against the cap."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    out = _run(
        {"tool_name": "Bash", "tool_response": {"stdout": "a" * 300, "stderr": "b" * 300}},
        monkeypatch,
        {"CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_ENABLED": "1", "CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_CHARS": "500"},
    )
    assert out is not None  # 600 combined chars > 500 → rewritten


def test_malformed_stdin_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-JSON stdin never raises — the hook emits nothing and the real output is shown."""
    monkeypatch.setattr(mod.sys, "stdin", io.StringIO("not json"))
    buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stdout", buf)
    assert mod.main() == 0
    assert buf.getvalue() == ""
