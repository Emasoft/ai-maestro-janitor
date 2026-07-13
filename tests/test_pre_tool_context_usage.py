"""Tests for the PreToolUse context-usage hook (scripts/hooks/pre-tool-context-usage.py).

The hook surfaces the live context-window % to the agent on every tool call by
reading the statusline's project-local snapshot and emitting
hookSpecificOutput.additionalContext. We test the pure render helpers directly
and the full main() via real subprocess runs (no mocks): env + stdin payload +
snapshot file on disk → JSON on stdout.
"""

from __future__ import annotations

import importlib.util as _u
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK_PATH = _PROJECT_ROOT / "scripts" / "hooks" / "pre-tool-context-usage.py"


def _import_hook():
    spec = _u.spec_from_file_location("pre_tool_context_usage_under_test", str(_HOOK_PATH))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(payload: dict, *, enabled: bool, snapshot: dict | None, project: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """Run the hook as a real subprocess; optionally pre-write the snapshot."""
    if snapshot is not None:
        d = project / ".claude" / "janitor"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"context-usage.{payload['session_id']}.json").write_text(json.dumps(snapshot), encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", ""), "CLAUDE_PROJECT_DIR": str(project)}
    if enabled:
        env["CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED"] = "true"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _ctx(proc: subprocess.CompletedProcess) -> str | None:
    """Extract additionalContext from the hook's stdout, or None if empty."""
    if not proc.stdout.strip():
        return None
    return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]


# ---------- pure helpers ---------------------------------------------------


def test_truthy_spellings() -> None:
    hook = _import_hook()
    # Explicit truthy spellings return True regardless of the (now mandatory) default.
    assert hook._truthy("true", default=False) is True
    assert hook._truthy("1", default=False) is True
    assert hook._truthy("yes", default=False) is True
    # Explicit false spellings (incl. whitespace, which strips to "") return False.
    for falsey in ("  ", "false", "0", "no", "off", "FALSE"):
        assert hook._truthy(falsey, default=True) is False, f"{falsey!r} is falsey"
    # Unset/empty falls back to the supplied default (the default-ON path).
    assert hook._truthy(None, default=True) is True
    assert hook._truthy("", default=True) is True
    assert hook._truthy(None, default=False) is False


def test_coerce_int_defaults_on_junk() -> None:
    hook = _import_hook()
    assert hook._coerce_int("75", 60) == 75
    assert hook._coerce_int(None, 60) == 60
    assert hook._coerce_int("not-a-number", 60) == 60
    assert hook._coerce_int("-5", 60) == 60  # negative rejected → default


def test_bucket_tokens_and_pct() -> None:
    """TRDD-YRPUSIFY: the cache-stable bucketers floor tokens to 10k and pct to 5-pt
    steps, so a band of raw values renders as ONE identical label."""
    hook = _import_hook()
    assert hook._bucket_tokens(650_000) == "~650k"
    assert hook._bucket_tokens(674_300) == "~670k"  # floored to the 10k bucket
    assert hook._bucket_tokens(1_000_000) == "~1.0M"
    assert hook._bucket_tokens(1_340_000) == "~1.3M"
    assert hook._bucket_tokens(9_999) == "~0k"
    assert hook._bucket_tokens(-5) == "~0k"
    assert hook._bucket_pct(71) == "~70%"
    assert hook._bucket_pct(72) == "~70%"  # same 5-pt band as 71
    assert hook._bucket_pct(85) == "~85%"
    assert hook._bucket_pct(-1) == "~0%"


def test_build_line_below_threshold_no_suggestion() -> None:
    hook = _import_hook()
    # _format_line takes already-resolved (pct, tokens, window, stale, suggest_pct).
    line = hook._format_line(30, 300_000, 1_000_000, False, 60)
    assert "~30% (~300k/~1.0M)" in line  # bucketed (TRDD-YRPUSIFY)
    assert "janitor-compact-context" not in line


def test_build_line_at_or_above_threshold_suggests() -> None:
    hook = _import_hook()
    line = hook._format_line(60, 600_000, 1_000_000, False, 60)
    assert "60%" in line
    assert "/janitor-compact-context" in line, "must suggest the skill at the threshold"


def test_build_line_stale_marks_lag() -> None:
    hook = _import_hook()
    # The render fn no longer computes age (that moved to _resolve_context); it takes a
    # stale bool and appends the lag caveat, which coexists with the usage detail.
    line = hook._format_line(40, 400_000, 1_000_000, True, 60)
    assert "~40% (~400k/~1.0M)" in line  # bucketed (TRDD-YRPUSIFY)
    assert "snapshot may lag" in line
    assert "/janitor-compact-context" not in line


def test_build_line_missing_pct_returns_none(tmp_path: Path) -> None:
    # The missing/non-int-pct -> None decision moved from the old render helper into
    # _resolve_context: a snapshot whose pct is absent or a non-int yields no usable
    # source, so (with no transcript) resolution returns the all-None tuple.
    hook = _import_hook()
    sid = "s1"
    snapdir = tmp_path / ".claude" / "janitor"
    snapdir.mkdir(parents=True)
    snap = snapdir / f"context-usage.{sid}.json"
    snap.write_text(json.dumps({"tokens": 1}), encoding="utf-8")  # pct absent
    got = hook._resolve_context(str(tmp_path), sid, "", 1_000_000, now=1)
    assert got == (None, None, None, False)
    snap.write_text(json.dumps({"pct": "67"}), encoding="utf-8")  # str pct
    got = hook._resolve_context(str(tmp_path), sid, "", 1_000_000, now=1)
    assert got == (None, None, None, False)


# ---------- full main() via subprocess (no mocks) -------------------------


def test_disabled_explicitly_no_output(tmp_path: Path) -> None:
    """The guard is DEFAULT-ON, so disabling is explicit: WATCHDOG_ENABLED=false -> a
    silent no-op even with a high-context snapshot present."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run({"session_id": "s1"}, enabled=False, snapshot={"pct": 80, "tokens": 800_000, "window": 1_000_000, "ts": int(time.time())}, project=p, extra_env={"CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED": "false"})
    assert proc.returncode == 0
    assert proc.stdout.strip() == "", "must be a silent no-op when explicitly disabled"


def test_enabled_fresh_low_silent_below_suggest(tmp_path: Path) -> None:
    """Enabled + a fresh snapshot below the suggest threshold -> NO output: the guard
    stays silent until near the cap so it adds zero per-turn context cost."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run({"session_id": "s1"}, enabled=True, snapshot={"pct": 30, "tokens": 300_000, "window": 1_000_000, "ts": int(time.time())}, project=p)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "", "below the suggest threshold the guard must be silent"


def test_enabled_high_injects_suggestion(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run({"session_id": "s1"}, enabled=True, snapshot={"pct": 70, "tokens": 700_000, "window": 1_000_000, "ts": int(time.time())}, project=p)
    ctx = _ctx(proc)
    assert ctx is not None and "70%" in ctx
    assert "/janitor-compact-context" in ctx


def test_enabled_missing_snapshot_silent(tmp_path: Path) -> None:
    """Enabled but the producer wrote no snapshot → silent (no injection)."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run({"session_id": "s1"}, enabled=True, snapshot=None, project=p)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_threshold_env_override(tmp_path: Path) -> None:
    """A custom suggest-pct env var changes when the nudge appears."""
    p = tmp_path / "proj"
    p.mkdir()
    # pct=50 is below default 60 (no nudge) but at/above an override of 50.
    proc = _run({"session_id": "s1"}, enabled=True, snapshot={"pct": 50, "tokens": 500_000, "window": 1_000_000, "ts": int(time.time())}, project=p, extra_env={"CLAUDE_PLUGIN_OPTION_CONTEXT_COMPACT_SUGGEST_PCT": "50"})
    ctx = _ctx(proc)
    assert ctx is not None and "/janitor-compact-context" in ctx


def test_no_permission_decision_emitted(tmp_path: Path) -> None:
    """The advisory hook must NEVER emit permissionDecision (would alter tool flow)."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run({"session_id": "s1"}, enabled=True, snapshot={"pct": 90, "tokens": 900_000, "window": 1_000_000, "ts": int(time.time())}, project=p)
    out = json.loads(proc.stdout)
    assert "permissionDecision" not in out["hookSpecificOutput"], "advisory-only: permissionDecision must be absent so the tool's permission flow is untouched"
    assert "permissionDecision" not in out


# ---------- TRDD-K1RJUYGK: the advisory must be LATCHED, not per-tool-call --------------
#
# WHY these exist: this hook was measured (agentlensPro, using Anthropic's own
# cache_creation/cache_read numbers) as the #1 prompt-cache breaker on the machine —
# 893 breaks, 4.96M tokens, $23.05 — because it injected an `additionalContext` block on
# EVERY tool call once context was >=60%. Claude Code STRIPS those system-reminder blocks
# retroactively, mid-transcript, and the strip mutates the cached PREFIX, re-billing every
# token after it. TRDD-YRPUSIFY tried to fix this by making the injected TEXT byte-stable
# (bucketing); that could not work and the data falsified it — a stripped block costs the
# same whatever it said. What must be bounded is the injection COUNT.


def _snap(pct: int) -> dict:
    return {"pct": pct, "tokens": pct * 10_000, "window": 1_000_000, "ts": int(time.time())}


def test_advisory_is_injected_once_per_band_not_on_every_tool_call(tmp_path: Path) -> None:
    """The >=60% advisory is announced ONCE per session per 10-point band; later tool calls
    in the same band inject NOTHING (the fix for the #1 machine-wide cache break)."""
    p = tmp_path / "proj"
    p.mkdir()
    seen = [_ctx(_run({"session_id": "s1"}, enabled=True, snapshot=_snap(65), project=p)) for _ in range(5)]
    assert seen[0] is not None, "the first crossing must still warn the model"
    assert all(x is None for x in seen[1:]), (
        f"tool calls 2..5 in the SAME band must inject nothing; got {seen[1:]!r}. "
        "Every injected block is later stripped by Claude Code and re-bills the cached prefix."
    )


def test_a_higher_band_re_announces(tmp_path: Path) -> None:
    """An escalating session still gets an escalating nudge: a NEW 10-point band re-warns."""
    p = tmp_path / "proj"
    p.mkdir()
    first = _ctx(_run({"session_id": "s1"}, enabled=True, snapshot=_snap(65), project=p))
    same = _ctx(_run({"session_id": "s1"}, enabled=True, snapshot=_snap(67), project=p))
    higher = _ctx(_run({"session_id": "s1"}, enabled=True, snapshot=_snap(75), project=p))
    assert first is not None
    assert same is None, "67% is the same 60-band as 65% — must not re-inject"
    assert higher is not None, "crossing into the 70-band must re-warn before enforcement"


def test_each_session_gets_its_own_latch(tmp_path: Path) -> None:
    """The latch is keyed by session: a fresh session warns again (it has a fresh transcript)."""
    p = tmp_path / "proj"
    p.mkdir()
    assert _ctx(_run({"session_id": "s1"}, enabled=True, snapshot=_snap(65), project=p)) is not None
    assert _ctx(_run({"session_id": "s1"}, enabled=True, snapshot=_snap(65), project=p)) is None
    assert _ctx(_run({"session_id": "s2"}, enabled=True, snapshot=_snap(65), project=p)) is not None


def test_a_compaction_re_arms_the_advisory_for_the_same_session(tmp_path: Path) -> None:
    """Dropping back below the threshold (i.e. a COMPACTION) must re-arm the advisory.

    `session_id` does NOT change across a compaction, so a latch keyed only on
    (session, band) is a one-way door: once a long session announced 60/70/80 and `prepare`,
    it could never announce them again — and EVERY auto-compaction after the first would
    arrive with no warning at all, which is exactly what the prepare/advisory tiers exist to
    prevent. Re-arming on the way DOWN keeps the injection budget bounded (~3 blocks per
    CLIMB, and a climb from 60% to 85% is slow) while restoring the warning.
    """
    p = tmp_path / "proj"
    p.mkdir()
    s = {"session_id": "s1"}
    assert _ctx(_run(s, enabled=True, snapshot=_snap(65), project=p)) is not None, "first climb warns"
    assert _ctx(_run(s, enabled=True, snapshot=_snap(65), project=p)) is None, "same band stays silent"
    # A compaction lands: context falls well below the 60% suggest threshold.
    assert _ctx(_run(s, enabled=True, snapshot=_snap(20), project=p)) is None, "below threshold: silent"
    # The SAME session climbs again — it must be warned again, not silently sail into the cap.
    assert _ctx(_run(s, enabled=True, snapshot=_snap(65), project=p)) is not None, (
        "after a compaction the SAME session must be warned again on the next climb — "
        "otherwise every compaction after the first happens unannounced"
    )


def test_dropping_below_threshold_does_not_re_arm_other_sessions(tmp_path: Path) -> None:
    """The latch file is shared by every session in the project, so a compaction in session A
    must release ONLY A's claims — B's latch must survive, or B re-injects a band it already
    announced."""
    p = tmp_path / "proj"
    p.mkdir()
    assert _ctx(_run({"session_id": "a"}, enabled=True, snapshot=_snap(65), project=p)) is not None
    assert _ctx(_run({"session_id": "b"}, enabled=True, snapshot=_snap(65), project=p)) is not None
    # Session A compacts (drops below threshold) → releases A's claims only.
    assert _ctx(_run({"session_id": "a"}, enabled=True, snapshot=_snap(20), project=p)) is None
    assert _ctx(_run({"session_id": "b"}, enabled=True, snapshot=_snap(65), project=p)) is None, (
        "session B never compacted — its 60-band claim must still hold"
    )
    assert _ctx(_run({"session_id": "a"}, enabled=True, snapshot=_snap(65), project=p)) is not None


def test_latch_fails_closed_when_it_cannot_be_recorded(tmp_path: Path) -> None:
    """If the latch cannot be written we CANNOT bound repeats, so we must stay SILENT.

    Failing open here would mean injecting on every tool call — the exact bug. The >=85%
    enforcement tier (a permissionDecision, not an injected block) remains the backstop.
    """
    p = tmp_path / "proj"
    p.mkdir()
    # Pre-write the snapshot while the state dir is still writable, then make `.janitor`
    # unwritable so the latch file can be neither created nor read.
    d = p / ".claude" / "janitor"
    d.mkdir(parents=True, exist_ok=True)
    (d / "context-usage.s1.json").write_text(json.dumps(_snap(65)), encoding="utf-8")
    state = p / ".janitor"
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o500)  # r-x: cannot create the latch file inside
    try:
        proc = _run({"session_id": "s1"}, enabled=True, snapshot=None, project=p)
        assert _ctx(proc) is None, "unwritable latch must suppress the advisory, never inject"
    finally:
        state.chmod(0o700)
