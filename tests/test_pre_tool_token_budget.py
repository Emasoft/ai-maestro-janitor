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

import importlib.util as _u
import json
import os
import subprocess
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "pre-tool-token-budget.py"

assert _HOOK.is_file(), f"hook not found at {_HOOK}"


def _import_hook():
    """Load the dash-named hook by path so the pure helpers can be unit-tested directly
    (name != __main__, so main() never runs on import)."""
    spec = _u.spec_from_file_location("pre_tool_token_budget_under_test", str(_HOOK))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ENABLED = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_ENABLED"
_BUDGET = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_OUTPUT"
_BUDGET_HARD = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_OUTPUT_HARD"
_CACHE = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_CACHE_CREATION"
_CACHE_HARD = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_CACHE_CREATION_HARD"
_ENFORCE = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_ENFORCE"
_REPEAT = "CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_REPEAT_S"
_ALL_VARS = (_ENABLED, _BUDGET, _BUDGET_HARD, _CACHE, _CACHE_HARD, _ENFORCE, _REPEAT)


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
    # Disable repeat-suppression by DEFAULT (0 = documented "never suppress"). These tests
    # exercise the nudge's CONTENT and tiering; dedupe is a separate concern with its own
    # tests, which call `_repeat_suppressed` directly against a real project dir. Without
    # this the two get entangled: `_repeat_suppressed` now fails CLOSED when there is no
    # project dir to stamp into (TRDD-K1RJUYGK — an unbounded hook must go silent rather
    # than re-inject on every tool call), and `project_dir` is "" here by design, so every
    # content assertion would see a suppressed, empty response.
    env[_REPEAT] = "0"
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
    # TRDD-YRPUSIFY: the raw per-call count is bucketed away — the exact output (150) must
    # NOT appear (a raw count makes the injected nudge a unique, non-cacheable string).
    assert "150" not in ctx


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
    assert "cache-miss" in ctx and "~30k" in ctx  # 30_000 floored to the ~30k bucket (TRDD-YRPUSIFY)


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
    # 60 + 60 = 120 crosses the 100 budget (a single 60 stays silent), proving the sum;
    # TRDD-YRPUSIFY buckets the raw total away, so we assert it FIRED, not the literal 120.
    assert "Token spike" in ctx


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
    assert "cache-miss" in ctx and "~30k" in ctx  # bucketed (TRDD-YRPUSIFY)


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


def test_bucket_tokens_floors_to_10k() -> None:
    """TRDD-YRPUSIFY: the pure bucketer floors to the nearest 10k so a whole band of raw
    counts renders as ONE cache-stable label; sub-10k and negatives clamp to ~0k."""
    hook = _import_hook()
    assert hook._bucket_tokens(43_366) == "~40k"
    assert hook._bucket_tokens(47_912) == "~40k"  # same 10k bucket as 43_366
    assert hook._bucket_tokens(50_000) == "~50k"
    assert hook._bucket_tokens(9_999) == "~0k"
    assert hook._bucket_tokens(-5) == "~0k"
    assert hook._bucket_tokens(1_340_000) == "~1.3M"


def test_same_bucket_emits_identical_text(tmp_path: Path) -> None:
    """TRDD-YRPUSIFY: two turns whose raw output differs but falls in the SAME 10k bucket
    emit BYTE-IDENTICAL additionalContext (cache-shareable); a different bucket differs.
    Hard budget is raised so all three stay ADVISORY — isolating the bucket from the tier."""

    def ctx_for(out: int) -> str | None:
        t = _write_transcript(tmp_path, _user("do real work"), _assistant(out, tool=True))
        return _ctx(_run(str(t), env_extra={_BUDGET_HARD: "1000000"}))

    a = ctx_for(43_366)
    b = ctx_for(47_912)  # same ~40k bucket as 43_366
    c = ctx_for(53_000)  # ~50k bucket — a different band
    assert a is not None and b is not None and c is not None
    assert a == b, "same bucket -> identical string (cache-stable)"
    assert a != c, "different bucket -> different string"


# ---------- issue #79: throttle to STATE TRANSITIONS, not a time-windowed repeat --------
#
# TRDD-4MMXTJFB / TRDD-K1RJUYGK's `_repeat_suppressed` (removed) periodically re-nudged a
# STEADY tier (advisory included) every window. agentlensPro's raw-body measurement in
# issue #79 — taken AFTER K1RJUYGK shipped — still classified HOOK_INJECTION as the #2
# cache-break cause (~440-520k tokens re-billed per strip). `_track_tier` replaces it:
# advisory nudges ONLY on a genuine tier change (never periodically); hard still gets a
# periodic renudge, but on a shorter, hard-only interval (default 600s, was 1800s for
# every tier). These tests exercise `_track_tier` directly, mirroring the old suite's
# style of unit-testing the throttle helper in isolation.


def test_track_tier_fails_closed_without_project_dir() -> None:
    """No project dir → nowhere to persist the last tier → cannot detect a transition →
    stay SILENT (fail closed, same direction as the removed `_repeat_suppressed`)."""
    hook = _import_hook()
    assert hook._track_tier("hard", "", 1000, 600) is False
    assert hook._track_tier("advisory", "", 1000, 600) is False


def test_track_tier_window_disabled_always_fresh(tmp_path: Path) -> None:
    """`hard_renudge_s <= 0` is the documented full opt-out: every non-ok tier is always
    fresh (restores the pre-issue-#79 always-nudge behavior), and "ok" never is."""
    hook = _import_hook()
    proj = tmp_path / "proj"
    assert hook._track_tier("advisory", str(proj), 1000, 0) is True
    assert hook._track_tier("advisory", str(proj), 1001, 0) is True  # steady, still fresh
    assert hook._track_tier("hard", str(proj), 1002, -5) is True
    assert hook._track_tier("ok", str(proj), 1003, 0) is False


def test_track_tier_emits_only_on_transition_for_advisory(tmp_path: Path) -> None:
    """A steady ADVISORY tier is NOT fresh after the first call — no periodic re-nudge at
    all (the behavior change from the old uniform time window)."""
    hook = _import_hook()
    proj = tmp_path / "proj"
    (proj / ".janitor" / "state").mkdir(parents=True, exist_ok=True)
    assert hook._track_tier("advisory", str(proj), 1000, 600) is True, "ok(unseen)->advisory is a transition"
    assert hook._track_tier("advisory", str(proj), 1010, 600) is False, "steady advisory: silent"
    assert hook._track_tier("advisory", str(proj), 100_000, 600) is False, "still silent no matter how long it sits"
    assert hook._track_tier("hard", str(proj), 100_010, 600) is True, "advisory->hard is a transition"
    assert hook._track_tier("hard", str(proj), 100_020, 600) is False, "steady hard, inside the renudge window"
    assert hook._track_tier("advisory", str(proj), 100_030, 600) is True, "hard->advisory is a transition"


def test_track_tier_hard_renudges_after_interval(tmp_path: Path) -> None:
    """A steady HARD tier re-fires once `hard_renudge_s` has elapsed since the last
    emission, and the elapsed-clock resets on each re-fire."""
    hook = _import_hook()
    proj = tmp_path / "proj"
    (proj / ".janitor" / "state").mkdir(parents=True, exist_ok=True)
    assert hook._track_tier("hard", str(proj), 1000, 600) is True, "first hard observation"
    assert hook._track_tier("hard", str(proj), 1300, 600) is False, "300s < 600s: still silent"
    assert hook._track_tier("hard", str(proj), 1599, 600) is False, "599s < 600s: still silent"
    assert hook._track_tier("hard", str(proj), 1600, 600) is True, "600s elapsed: renudge fires"
    assert hook._track_tier("hard", str(proj), 1650, 600) is False, "clock reset by the renudge"
    assert hook._track_tier("hard", str(proj), 2200, 600) is True, "another 600s: renudges again"


def test_track_tier_ok_is_recorded_so_a_later_climb_is_a_fresh_transition(tmp_path: Path) -> None:
    """The "ok" tier is tracked too (even though it never itself nudges) — otherwise
    advisory -> ok -> advisory would be missed as a "steady advisory" replay of the FIRST
    advisory's stale persisted state (issue #79's explicit ok<->advisory example)."""
    hook = _import_hook()
    proj = tmp_path / "proj"
    (proj / ".janitor" / "state").mkdir(parents=True, exist_ok=True)
    assert hook._track_tier("advisory", str(proj), 1000, 600) is True
    assert hook._track_tier("ok", str(proj), 1010, 600) is False, "advisory->ok never nudges"
    reason = "ok->advisory IS a fresh transition, even though 'ok' itself never emitted — proves 'ok' observations are persisted, not skipped"
    assert hook._track_tier("advisory", str(proj), 1020, 600) is True, reason


def test_track_tier_recovers_from_a_corrupt_stamp(tmp_path: Path) -> None:
    """A garbled state file resolves to 'never seen before' — the fail-open direction that
    can only cause an EXTRA nudge, never suppress a real transition."""
    hook = _import_hook()
    proj = tmp_path / "proj"
    state_dir = proj / ".janitor" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "token-budget-last-tier.txt").write_text("not a valid stamp\n\x00\xff", encoding="utf-8")
    assert hook._track_tier("hard", str(proj), 1000, 600) is True


def test_track_tier_fails_closed_when_the_stamp_dir_is_unwritable(tmp_path: Path) -> None:
    """An unwritable state dir must still resolve the CURRENT call from its (unreadable)
    read side — `_read_last_tier` fails open to "" — so the first call still fires; but a
    write failure must never crash the hook."""
    hook = _import_hook()
    proj = tmp_path / "proj"
    state_dir = proj / ".janitor" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_dir.chmod(0o500)  # r-x: the stamp can be neither created nor replaced
    try:
        assert hook._track_tier("hard", str(proj), 1000, 600) is True
    finally:
        state_dir.chmod(0o700)


def test_hard_default_renudge_is_ten_minutes() -> None:
    """issue #79 explicitly asks for a 10-minute default (down from the old 30-minute
    window that used to also cover a steady advisory)."""
    hook = _import_hook()
    assert hook._DEFAULT_HARD_RENUDGE_S == 600


# ---------- end-to-end: the real hook wires _track_tier correctly -----------------------


def test_second_identical_hard_call_is_silent_then_renudges_after_the_interval(tmp_path: Path) -> None:
    """Two identical hard-tier tool calls in a row against a real project dir: the first
    nudges, the second (same tier, well inside the renudge window) is COMPLETELY silent —
    the concrete fix for issue #79's measured per-strip-event cost."""
    proj = tmp_path / "proj"
    (proj / ".janitor" / "state").mkdir(parents=True, exist_ok=True)
    t = _write_transcript(tmp_path, _user("go"), _assistant(500_000, tool=True))
    env = {_BUDGET_HARD: "1000", _REPEAT: "600"}
    first = _run(str(t), project_dir=str(proj), env_extra=env)
    second = _run(str(t), project_dir=str(proj), env_extra=env)
    assert _ctx(first) is not None, "the first hard nudge must fire"
    assert second.stdout.strip() == "", f"a steady hard tier inside the renudge window must inject NOTHING, got: {second.stdout!r}"


def test_deny_path_fires_every_time_regardless_of_the_additionalContext_throttle(tmp_path: Path) -> None:
    """ENFORCEMENT must be UNCHANGED by issue #79: two consecutive hard+spawner+ENFORCE
    calls must BOTH deny, even though the additionalContext channel would suppress the
    second one — the deny is a decision field, not a strippable transcript block."""
    proj = tmp_path / "proj"
    (proj / ".janitor" / "state").mkdir(parents=True, exist_ok=True)
    t = _write_transcript(tmp_path, _user("go"), _assistant(500_000, tool=True))
    env = {_BUDGET_HARD: "1000", _REPEAT: "600", _ENFORCE: "true"}
    first = _decision(_run(str(t), tool_name="Task", project_dir=str(proj), env_extra=env))
    second = _decision(_run(str(t), tool_name="Task", project_dir=str(proj), env_extra=env))
    assert first.get("permissionDecision") == "deny"
    assert second.get("permissionDecision") == "deny", "the deny path must never be throttled"
