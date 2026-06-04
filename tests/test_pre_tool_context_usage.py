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


def _run(payload: dict, *, enabled: bool, snapshot: dict | None, project: Path,
         extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """Run the hook as a real subprocess; optionally pre-write the snapshot."""
    if snapshot is not None:
        d = project / ".claude" / "janitor"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"context-usage.{payload['session_id']}.json").write_text(
            json.dumps(snapshot), encoding="utf-8"
        )
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
    assert hook._truthy("true") is True
    assert hook._truthy("1") is True
    assert hook._truthy("yes") is True
    for falsey in (None, "", "  ", "false", "0", "no", "off", "FALSE"):
        assert hook._truthy(falsey) is False, f"{falsey!r} should be falsey"


def test_coerce_int_defaults_on_junk() -> None:
    hook = _import_hook()
    assert hook._coerce_int("75", 60) == 75
    assert hook._coerce_int(None, 60) == 60
    assert hook._coerce_int("not-a-number", 60) == 60
    assert hook._coerce_int("-5", 60) == 60  # negative rejected → default


def test_fmt_tokens() -> None:
    hook = _import_hook()
    assert hook._fmt_tokens(650_000) == "650k"
    assert hook._fmt_tokens(1_000_000) == "1.0m"
    assert hook._fmt_tokens(674_300) == "674k"
    assert hook._fmt_tokens(512) == "512"


def test_build_line_below_threshold_no_suggestion() -> None:
    hook = _import_hook()
    snap = {"pct": 30, "tokens": 300_000, "window": 1_000_000, "ts": 1000}
    line = hook._build_context_line(snap, now=1000, suggest_pct=60)
    assert line is not None
    assert "30% (300k/1.0m)" in line
    assert "janitor-compact-context" not in line


def test_build_line_at_or_above_threshold_suggests() -> None:
    hook = _import_hook()
    snap = {"pct": 60, "tokens": 600_000, "window": 1_000_000, "ts": 1000}
    line = hook._build_context_line(snap, now=1000, suggest_pct=60)
    assert "/janitor-compact-context" in line, "must suggest the skill at the threshold"


def test_build_line_stale_marks_age() -> None:
    hook = _import_hook()
    snap = {"pct": 40, "tokens": 400_000, "window": 1_000_000, "ts": 1000}
    line = hook._build_context_line(snap, now=1000 + 999, suggest_pct=60)
    assert "old" in line and "999s" in line


def test_build_line_missing_pct_returns_none() -> None:
    hook = _import_hook()
    assert hook._build_context_line({"tokens": 1}, now=1, suggest_pct=60) is None
    assert hook._build_context_line({"pct": "67"}, now=1, suggest_pct=60) is None  # str, not int


# ---------- full main() via subprocess (no mocks) -------------------------

def test_disabled_by_default_no_output(tmp_path: Path) -> None:
    """Opt-in off (env unset) → no output even with a valid snapshot present."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run({"session_id": "s1"}, enabled=False,
                snapshot={"pct": 80, "tokens": 800_000, "window": 1_000_000, "ts": int(time.time())},
                project=p)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "", "must be a silent no-op when not enabled"


def test_enabled_fresh_low_injects_pct_no_suggestion(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run({"session_id": "s1"}, enabled=True,
                snapshot={"pct": 30, "tokens": 300_000, "window": 1_000_000, "ts": int(time.time())},
                project=p)
    assert proc.returncode == 0
    ctx = _ctx(proc)
    assert ctx is not None and "30%" in ctx
    assert "janitor-compact-context" not in ctx


def test_enabled_high_injects_suggestion(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run({"session_id": "s1"}, enabled=True,
                snapshot={"pct": 70, "tokens": 700_000, "window": 1_000_000, "ts": int(time.time())},
                project=p)
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
    proc = _run({"session_id": "s1"}, enabled=True,
                snapshot={"pct": 50, "tokens": 500_000, "window": 1_000_000, "ts": int(time.time())},
                project=p,
                extra_env={"CLAUDE_PLUGIN_OPTION_CONTEXT_COMPACT_SUGGEST_PCT": "50"})
    ctx = _ctx(proc)
    assert ctx is not None and "/janitor-compact-context" in ctx


def test_no_permission_decision_emitted(tmp_path: Path) -> None:
    """The advisory hook must NEVER emit permissionDecision (would alter tool flow)."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run({"session_id": "s1"}, enabled=True,
                snapshot={"pct": 90, "tokens": 900_000, "window": 1_000_000, "ts": int(time.time())},
                project=p)
    out = json.loads(proc.stdout)
    assert "permissionDecision" not in out["hookSpecificOutput"], \
        "advisory-only: permissionDecision must be absent so the tool's permission flow is untouched"
    assert "permissionDecision" not in out
