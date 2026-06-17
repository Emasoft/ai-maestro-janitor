"""Tests for the pre-tool-token-budget PreToolUse hook (TRDD-a4e41e89 Phase 2).

OPT-IN; tests set the enable env var and a low budget so fixtures stay small.
Verify:
  * a turn whose summed output >= the budget → an `additionalContext` nudge
  * a turn under budget → silent
  * disabled (no env) → silent even when over budget
  * missing transcript_path → silent
  * budget=0 → turn check disabled → silent
  * malformed / boundary-not-in-tail → silent
  * advisory only: never emits a permissionDecision
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "pre-tool-token-budget.py"

assert _HOOK.is_file(), f"hook not found at {_HOOK}"

_ENABLED = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_ENABLED"
_BUDGET = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_OUTPUT"


def _user(text: str) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})


def _assistant(out: int, *, tool: bool = False, text: str = "working") -> str:
    content: list = [{"type": "text", "text": text}]
    if tool:
        content.append({"type": "tool_use", "name": "Bash", "input": {}})
    return json.dumps({"type": "assistant", "message": {
        "role": "assistant", "content": content,
        "usage": {"input_tokens": 5, "output_tokens": out}}})


def _write_transcript(tmp: Path, *lines: str) -> Path:
    p = tmp / "transcript.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _run(
    transcript_path: str | None,
    *,
    enabled: bool = True,
    budget: str | None = "100",
) -> subprocess.CompletedProcess[str]:
    payload: dict = {
        "session_id": "sess-1",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
    }
    if transcript_path is not None:
        payload["transcript_path"] = transcript_path
    env = os.environ.copy()
    env.pop(_ENABLED, None)
    env.pop(_BUDGET, None)
    if enabled:
        env[_ENABLED] = "true"
    if budget is not None:
        env[_BUDGET] = budget
    return subprocess.run(
        [str(_HOOK)], input=json.dumps(payload), env=env,
        capture_output=True, text=True, timeout=30,
    )


def _ctx(proc: subprocess.CompletedProcess[str]) -> str | None:
    if not proc.stdout.strip():
        return None
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    # Advisory-only invariant: never a permission decision.
    assert "permissionDecision" not in out
    return out.get("additionalContext")


def test_warns_over_budget(tmp_path: Path) -> None:
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(150, tool=True))
    ctx = _ctx(_run(str(t)))
    assert ctx is not None
    assert "Token budget" in ctx
    assert "150" in ctx


def test_silent_under_budget(tmp_path: Path) -> None:
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(50, tool=True))
    assert _run(str(t)).stdout.strip() == ""


def test_silent_when_disabled(tmp_path: Path) -> None:
    """Over budget but the option is off → no output (zero-cost default)."""
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(150, tool=True))
    assert _run(str(t), enabled=False).stdout.strip() == ""


def test_silent_without_transcript_path() -> None:
    assert _run(None).stdout.strip() == ""


def test_budget_zero_disables_turn_check(tmp_path: Path) -> None:
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(150, tool=True))
    assert _run(str(t), budget="0").stdout.strip() == ""


def test_multistep_turn_sums_output(tmp_path: Path) -> None:
    """Output is summed across the turn's assistant messages (with tool_results
    interleaved), so a turn that drips over the budget across steps still fires."""
    tool_result = json.dumps({"type": "user", "message": {
        "role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "out"}]}})
    t = _write_transcript(
        tmp_path,
        _user("do real work"),
        _assistant(60, tool=True), tool_result,
        _assistant(60, tool=True),
    )
    ctx = _ctx(_run(str(t)))
    assert ctx is not None
    assert "120" in ctx          # 60 + 60 summed across the turn


def test_malformed_input_silent() -> None:
    env = os.environ.copy()
    env[_ENABLED] = "true"
    r = subprocess.run(
        [str(_HOOK)], input="not json", env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_no_turn_boundary_silent(tmp_path: Path) -> None:
    """A tail with only assistant entries (no user trigger) → tail_turn_usage None
    → silent (don't guess)."""
    t = _write_transcript(tmp_path, _assistant(999, tool=True))
    assert _run(str(t)).stdout.strip() == ""
