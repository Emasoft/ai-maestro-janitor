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
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "pre-tool-token-budget.py"

assert _HOOK.is_file(), f"hook not found at {_HOOK}"

_ENABLED = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_ENABLED"
_BUDGET = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_OUTPUT"
_BUDGET_HARD = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_OUTPUT_HARD"
_CACHE = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_CACHE_CREATION"
_CACHE_HARD = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_CACHE_CREATION_HARD"
_ENFORCE = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_ENFORCE"
_ALL_VARS = (_ENABLED, _BUDGET, _BUDGET_HARD, _CACHE, _CACHE_HARD, _ENFORCE)


def _user(text: str) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})


def _assistant(out: int, *, tool: bool = False, text: str = "working", cache_creation: int = 0) -> str:
    content: list = [{"type": "text", "text": text}]
    if tool:
        content.append({"type": "tool_use", "name": "Bash", "input": {}})
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": content, "usage": {"input_tokens": 5, "output_tokens": out, "cache_creation_input_tokens": cache_creation}}})


def _write_transcript(tmp: Path, *lines: str) -> Path:
    p = tmp / "transcript.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _run(
    transcript_path: str | None,
    *,
    enabled: bool | None = True,
    budget: str | None = "100",
    tool_name: str = "Bash",
    env_extra: dict[str, str] | None = None,
    project_dir: str = "",
) -> subprocess.CompletedProcess[str]:
    payload: dict = {
        "session_id": "sess-1",
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {"command": "echo hi"},
    }
    if transcript_path is not None:
        payload["transcript_path"] = transcript_path
    env = os.environ.copy()
    for v in _ALL_VARS:
        env.pop(v, None)
    if enabled is True:
        env[_ENABLED] = "true"
    elif enabled is False:
        env[_ENABLED] = "false"
    # enabled is None → leave the var UNSET, exercising the DEFAULT-ON behaviour.
    if budget is not None:
        env[_BUDGET] = budget
    # ALWAYS set CLAUDE_PROJECT_DIR explicitly (default "") so the compact-grace check
    # (TRDD-TKNSTP82 A2) is deterministic regardless of the ambient shell's env — an
    # inherited CLAUDE_PROJECT_DIR pointing at a real project could otherwise pick up a
    # real resume-after-compact.ts and make these tests flaky/non-reproducible.
    env["CLAUDE_PROJECT_DIR"] = project_dir
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [str(_HOOK)],
        input=json.dumps(payload),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _decision(proc: subprocess.CompletedProcess[str]) -> dict:
    """The raw hookSpecificOutput (for deny tests, which _ctx forbids)."""
    return json.loads(proc.stdout)["hookSpecificOutput"]


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
    assert "Token spike" in ctx
    assert "150" in ctx


def test_default_on_when_unset(tmp_path: Path) -> None:
    """DEFAULT-ON (TRDD-KI24GR5Z): with ENABLED unset, an over-advisory turn still fires."""
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(150, tool=True))
    ctx = _ctx(_run(str(t), enabled=None))
    assert ctx is not None and "Token spike" in ctx


def test_cache_miss_spike_fires_independently_of_output(tmp_path: Path) -> None:
    """A CACHE-MISS write over its budget fires even when OUTPUT is tiny."""
    t = _write_transcript(
        tmp_path,
        _user("do real work"),
        _assistant(20, tool=True, cache_creation=30_000),  # output under 100, cache-miss over 25000
    )
    ctx = _ctx(_run(str(t), env_extra={_CACHE: "25000"}))
    assert ctx is not None
    assert "cache-miss" in ctx and "30000" in ctx


def test_hard_tier_emits_strong_stop_nudge(tmp_path: Path) -> None:
    """Output at/above the HARD budget → the runaway stop nudge (advisory when ENFORCE off)."""
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(50_000, tool=True))
    ctx = _ctx(_run(str(t), env_extra={_BUDGET_HARD: "40000"}))
    assert ctx is not None
    assert "TOKEN RUNAWAY" in ctx and "TaskStop" in ctx


def test_hard_tier_denies_subagent_spawn_under_enforce(tmp_path: Path) -> None:
    """hard tier + a Task/Agent spawn + ENFORCE=on → permissionDecision deny."""
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(50_000, tool=True))
    proc = _run(str(t), tool_name="Task", env_extra={_BUDGET_HARD: "40000", _ENFORCE: "true"})
    out = _decision(proc)
    assert out.get("permissionDecision") == "deny"
    assert "Do NOT spawn another subagent" in out.get("permissionDecisionReason", "")


def test_hard_tier_no_deny_without_enforce(tmp_path: Path) -> None:
    """hard + spawner but ENFORCE OFF → advisory nudge, never a deny (default = nudge)."""
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(50_000, tool=True))
    ctx = _ctx(_run(str(t), tool_name="Task", env_extra={_BUDGET_HARD: "40000"}))
    assert ctx is not None and "TOKEN RUNAWAY" in ctx


def test_hard_tier_no_deny_for_non_spawner_tool(tmp_path: Path) -> None:
    """hard + ENFORCE=on but the tool is NOT a subagent spawner → advisory, no deny."""
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(50_000, tool=True))
    ctx = _ctx(_run(str(t), tool_name="Bash", env_extra={_BUDGET_HARD: "40000", _ENFORCE: "true"}))
    assert ctx is not None and "TOKEN RUNAWAY" in ctx


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
    tool_result = json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "out"}]}})
    t = _write_transcript(
        tmp_path,
        _user("do real work"),
        _assistant(60, tool=True),
        tool_result,
        _assistant(60, tool=True),
    )
    ctx = _ctx(_run(str(t)))
    assert ctx is not None
    assert "120" in ctx  # 60 + 60 summed across the turn


def test_malformed_input_silent() -> None:
    env = os.environ.copy()
    env[_ENABLED] = "true"
    r = subprocess.run(
        [str(_HOOK)],
        input="not json",
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_no_turn_boundary_silent(tmp_path: Path) -> None:
    """A tail with only assistant entries (no user trigger) → tail_turn_usage None
    → silent (don't guess)."""
    t = _write_transcript(tmp_path, _assistant(999, tool=True))
    assert _run(str(t)).stdout.strip() == ""


def _write_resume_ts(project_dir: Path, ts: int) -> None:
    sd = project_dir / ".janitor" / "state"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "resume-after-compact.ts").write_text(str(ts), encoding="utf-8")


def test_fresh_compact_grace_suppresses_cache_miss(tmp_path: Path) -> None:
    """TRDD-TKNSTP82 A2: a FRESH resume-after-compact.ts + high cache_creation + low
    output → silent (the post-compact re-cache window)."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _write_resume_ts(proj, int(time.time()))
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(20, tool=True, cache_creation=30_000))
    r = _run(str(t), env_extra={_CACHE: "25000"}, project_dir=str(proj))
    assert r.stdout.strip() == ""


def test_stale_compact_ts_does_not_suppress(tmp_path: Path) -> None:
    """A STALE resume-after-compact.ts (older than the grace window) → unchanged
    behavior — the cache-miss trip still fires (regression)."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _write_resume_ts(proj, int(time.time()) - 10_000)  # far older than the 600s default grace
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(20, tool=True, cache_creation=30_000))
    ctx = _ctx(_run(str(t), env_extra={_CACHE: "25000"}, project_dir=str(proj)))
    assert ctx is not None
    assert "cache-miss" in ctx and "30000" in ctx


def test_absent_compact_ts_does_not_suppress(tmp_path: Path) -> None:
    """No resume-after-compact.ts at all (normal turn, no compaction) → unchanged
    behavior — the cache-miss trip still fires."""
    proj = tmp_path / "proj"
    proj.mkdir()
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(20, tool=True, cache_creation=30_000))
    ctx = _ctx(_run(str(t), env_extra={_CACHE: "25000"}, project_dir=str(proj)))
    assert ctx is not None and "cache-miss" in ctx


def test_compact_grace_zero_disables_suppression(tmp_path: Path) -> None:
    """CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_COMPACT_GRACE_S=0 disables the grace window even
    with a fresh resume-after-compact.ts."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _write_resume_ts(proj, int(time.time()))
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(20, tool=True, cache_creation=30_000))
    ctx = _ctx(
        _run(
            str(t),
            env_extra={_CACHE: "25000", "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_COMPACT_GRACE_S": "0"},
            project_dir=str(proj),
        )
    )
    assert ctx is not None and "cache-miss" in ctx


def test_compact_grace_never_suppresses_output_signal(tmp_path: Path) -> None:
    """The grace window is cache_creation-SCOPED only: an output-hard trip still fires
    the STOP nudge even inside a fresh compact-grace window."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _write_resume_ts(proj, int(time.time()))
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(50_000, tool=True))
    ctx = _ctx(_run(str(t), env_extra={_BUDGET_HARD: "40000"}, project_dir=str(proj)))
    assert ctx is not None
    assert "TOKEN RUNAWAY" in ctx and "TaskStop" in ctx


def test_cache_miss_only_wording_omits_compact_recommendation(tmp_path: Path) -> None:
    """TRDD-TKNSTP82 A3: a cache-miss-ONLY trip (no output signal) never recommends
    /compact — it's a one-time WRITE cost, not fixed by compacting again."""
    proj = tmp_path / "proj"
    proj.mkdir()
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(20, tool=True, cache_creation=80_000))
    ctx = _ctx(_run(str(t), env_extra={_CACHE_HARD: "75000"}, project_dir=str(proj)))
    assert ctx is not None
    assert "cache-miss" in ctx
    assert "/compact" not in ctx


def test_output_only_wording_keeps_compact_recommendation(tmp_path: Path) -> None:
    """An output-driven hard trip (no cache-miss signal) keeps the /compact
    recommendation — it's legitimately correct there."""
    proj = tmp_path / "proj"
    proj.mkdir()
    t = _write_transcript(tmp_path, _user("do real work"), _assistant(50_000, tool=True))
    ctx = _ctx(_run(str(t), env_extra={_BUDGET_HARD: "40000"}, project_dir=str(proj)))
    assert ctx is not None
    assert "/compact" in ctx

