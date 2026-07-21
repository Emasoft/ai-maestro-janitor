"""Tests for the reload-context guard hook (scripts/hooks/on-prompt-submit-reload-guard.py),
F1 of TRDD-Z582IKIR.

Real subprocess runs (no mocks): env + stdin UserPromptSubmit payload + a statusline
context snapshot on disk → the hook's JSON stdout (block or silent pass-through).
"""

from __future__ import annotations

import importlib.util as _u
import json
import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK_PATH = _PROJECT_ROOT / "scripts" / "hooks" / "on-prompt-submit-reload-guard.py"


def _import_hook():
    spec = _u.spec_from_file_location("reload_guard_hook_under_test", str(_HOOK_PATH))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_snapshot(project: Path, session_id: str, *, pct: int, tokens: int, window: int, ts: int) -> None:
    d = project / ".claude" / "janitor"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"context-usage.{session_id}.json").write_text(
        json.dumps({"pct": pct, "tokens": tokens, "window": window, "ts": ts}), encoding="utf-8"
    )


def _run(payload: dict, *, project: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "CLAUDE_PROJECT_DIR": str(project)}
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


def _payload(prompt: str, project: Path, session_id: str = "sess-1") -> dict:
    return {
        "prompt": prompt,
        "session_id": session_id,
        "cwd": str(project),
        "transcript_path": str(project / "nonexistent.jsonl"),
    }


# ---------- fast-path: non-reload prompts are always a silent no-op --------


def test_non_reload_prompt_is_silent_noop(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    proc = _run(_payload("what is the weather", project), project=project)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_lookalike_command_not_intercepted(tmp_path: Path) -> None:
    """A command merely sharing the prefix (not a real form today, but future-proofed
    by the anchored regex) must NOT be treated as /reload-plugins."""
    project = tmp_path / "proj"
    project.mkdir()
    proc = _run(_payload("/reload-plugins-experimental", project), project=project)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


# ---------- blocking behavior -----------------------------------------------


def test_blocks_reload_when_context_above_threshold(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_snapshot(project, "sess-1", pct=50, tokens=500_000, window=1_000_000, ts=0)
    proc = _run(_payload("/reload-plugins", project), project=project, extra_env={"CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_THRESHOLD": "350000"})
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["decision"] == "block"
    assert "reload-guard" in out["reason"]
    assert "500,000" in out["reason"] or "500000" in out["reason"]
    assert out["systemMessage"] == out["reason"]


def test_blocks_reload_with_force_flag_suffix(tmp_path: Path) -> None:
    """The janitor's own self-trigger types `/reload-plugins --force` — must be caught too."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_snapshot(project, "sess-1", pct=90, tokens=900_000, window=1_000_000, ts=0)
    proc = _run(_payload("/reload-plugins --force", project), project=project)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["decision"] == "block"


def test_allows_reload_when_context_below_threshold(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_snapshot(project, "sess-1", pct=10, tokens=100_000, window=1_000_000, ts=0)
    proc = _run(_payload("/reload-plugins", project), project=project)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_fails_open_when_context_unknown(tmp_path: Path) -> None:
    """No snapshot and no readable transcript → context unresolvable → allow (never block)."""
    project = tmp_path / "proj"
    project.mkdir()
    proc = _run(_payload("/reload-plugins", project), project=project)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_threshold_zero_disables_guard(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_snapshot(project, "sess-1", pct=99, tokens=999_999, window=1_000_000, ts=0)
    proc = _run(
        _payload("/reload-plugins", project),
        project=project,
        extra_env={"CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_THRESHOLD": "0"},
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "", "threshold=0 must always allow the reload"


def test_hook_disabled_entirely_via_env(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_snapshot(project, "sess-1", pct=99, tokens=999_999, window=1_000_000, ts=0)
    proc = _run(
        _payload("/reload-plugins", project),
        project=project,
        extra_env={"CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_ENABLED": "false"},
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_custom_threshold_env_honored(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_snapshot(project, "sess-1", pct=6, tokens=60_000, window=1_000_000, ts=0)
    proc = _run(
        _payload("/reload-plugins", project),
        project=project,
        extra_env={"CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_THRESHOLD": "50000"},
    )
    out = json.loads(proc.stdout)
    assert out["decision"] == "block", "60k tokens must block against a lowered 50k threshold"


def test_malformed_stdin_never_crashes(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    proc = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input="not json{{{",
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", ""), "CLAUDE_PROJECT_DIR": str(project)},
        timeout=30,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


# ---------- pure helpers -----------------------------------------------------


def test_reload_regex_anchoring() -> None:
    hook = _import_hook()
    assert hook._RELOAD_RE.match("/reload-plugins")
    assert hook._RELOAD_RE.match("/reload-plugins --force")
    assert hook._RELOAD_RE.match("/reload-plugins\n")
    assert not hook._RELOAD_RE.match("/reload-plugins-experimental")
    assert not hook._RELOAD_RE.match("please run /reload-plugins")


def test_truthy_and_coerce_int_helpers() -> None:
    hook = _import_hook()
    assert hook._truthy(None, default=True) is True
    assert hook._truthy("false", default=True) is False
    assert hook._coerce_int("not-a-number", 42) == 42
    assert hook._coerce_int("64_000", 42) == 64_000
