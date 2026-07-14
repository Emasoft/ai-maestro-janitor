"""Every hook must SURVIVE BEING RUN — the guardrail for a silent import-time death.

WHY THIS EXISTS (the incident it prevents recurring): commit 4df60fc (2026-06-20) made
`on-session-start.py` import `global_state` via the `lib` package while putting only
`scripts/` on `sys.path`. `global_state.py` bare-imports a sibling (`import state`), which
resolves only when `scripts/lib/` is ALSO on the path. So the hook raised
ModuleNotFoundError at IMPORT time — it died before its first statement, on every session,
for three weeks. Nothing caught it: Claude Code does not surface a SessionStart hook crash,
so the only symptom was the absence of things nobody watches (rules stopped updating; a rule
added after that date never reached `~/.claude/rules` at all; the memory breadcrumb stopped
printing; the USER-memory backup mirror stopped syncing).

The unit tests could not have caught it either, because they IMPORT the libs directly (the
detector convention, which works) — they never RUN a hook the way Claude Code runs it. The
only test that catches this class is one that EXECUTES the hook as a subprocess. That is
this file: no mocks, real `uv run`, real stdin, one test per hook.

A hook is allowed to DECLINE (exit non-zero, print nothing, refuse the payload). It is NOT
allowed to die on import or blow up on a well-formed event. So the assertion is deliberately
narrow — no traceback, no ModuleNotFoundError — not "exit 0".

Everything is sandboxed: HOME, CLAUDE_PROJECT_DIR and the janitor's global-state dir all
point into a tmp tree, so running the real hooks cannot touch the real `~/.claude`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO / "scripts" / "hooks"

# A superset payload: every field any hook reads. Claude Code sends the subset that fits
# the event; a hook must tolerate extra keys, so one shared payload exercises them all.
_EVENT = {
    "session_id": "test-session-hooks-execute",
    "source": "startup",
    "hook_event_name": "SessionStart",
    "transcript_path": "/nonexistent/transcript.jsonl",
    "prompt": "hello",
    "tool_name": "Read",
    "tool_input": {"file_path": "/tmp/example.txt"},
    "tool_response": {"content": "ok"},
    "trigger": "manual",
}

# Import-time death signatures. A hook that dies here never ran a single statement — the
# failure mode this file exists to make impossible.
_FATAL = ("ModuleNotFoundError", "ImportError", "Traceback (most recent call last)")


def _hook_scripts() -> list[Path]:
    """Every hook the plugin ships. Discovered by GLOB, never a hardcoded list — a new
    hook must be covered the moment it lands, without anyone remembering to add it here."""
    return sorted(p for p in HOOKS_DIR.glob("*.py") if p.is_file())


def test_there_are_hooks_to_check() -> None:
    """Guard the guard: if the glob silently matched nothing, every test below would
    vacuously pass and the suite would report green while checking NOTHING."""
    assert len(_hook_scripts()) >= 10


@pytest.mark.parametrize("hook", _hook_scripts(), ids=lambda p: p.name)
def test_hook_runs_without_import_crash(hook: Path, tmp_path: Path) -> None:
    """Each hook executes end-to-end without an import-time death or an unhandled crash."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    # The plugin must look installed, or scope detection short-circuits and the hook
    # returns before reaching the code paths we want to exercise.
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"ai-maestro-janitor@ai-maestro-plugins": True}}),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()

    env = {
        **os.environ,
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(REPO),
        "CLAUDE_PROJECT_DIR": str(project),
        # Keep the daemon contract, the OS keepalive and the rotator away from the real
        # machine: a test must never spawn a daemon or read the real keychain.
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "global-state"),
        "CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED": "false",
        "CLAUDE_PLUGIN_OPTION_OS_KEEPALIVE_ENABLED": "false",
    }

    proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, str(hook)],
        input=json.dumps(_EVENT),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(project),
    )

    combined = f"{proc.stdout}\n{proc.stderr}"
    for signature in _FATAL:
        assert signature not in combined, (
            f"{hook.name} died while running (a hook that crashes on import never runs at "
            f"all, and Claude Code does not surface it):\n{combined[:2000]}"
        )


def test_on_session_start_actually_reaches_rule_install(tmp_path: Path) -> None:
    """The REGRESSION test proper, pinned to the exact failure.

    `on-session-start.py` is the hook that installs the plugin's rules. Proving it "does not
    crash" is not enough — the incident's real damage was that rules silently stopped being
    installed. So assert the OUTCOME: after the hook runs, the shipped rules are on disk in
    the sandbox's `~/.claude/rules/`. This fails loudly if the hook ever again dies before
    reaching `install_rules`, whatever the cause.
    """
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"ai-maestro-janitor@ai-maestro-plugins": True}}),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()

    env = {
        **os.environ,
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(REPO),
        "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "global-state"),
        "CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED": "false",
        "CLAUDE_PLUGIN_OPTION_OS_KEEPALIVE_ENABLED": "false",
    }

    subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, str(HOOKS_DIR / "on-session-start.py")],
        input=json.dumps(_EVENT),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(project),
    )

    shipped = {p.name for p in (REPO / "rules").glob("*.md")}
    installed = {p.name for p in (home / ".claude" / "rules").glob("*.md")}
    missing = shipped - installed
    assert not missing, (
        f"on-session-start ran but did NOT install {sorted(missing)} — the hook is not "
        f"reaching install_rules(). This is the 2026-06-20 regression class: the hook dies "
        f"(or returns) early and the rules silently freeze at whatever version last landed."
    )


def test_on_session_start_installs_rules_without_plugin_root_env(tmp_path: Path) -> None:
    """janitor#80 fix #2 (the __file__ plugin-root fallback), pinned to the DESTINATION.

    The hook must resolve its own plugin root from `Path(__file__).resolve().parents[2]`
    and STILL install the rules when CLAUDE_PLUGIN_ROOT is UNSET. On the OLD code an unset
    var hit an early `return 0` and installed NOTHING — so this test FAILS on the old
    behavior and PASSES on the new. It asserts the outcome (rules land in the sandbox
    `~/.claude/rules/`, universal-kanban.md included), never merely a return value: a
    return-value-only test would pass against an installer that never runs.
    """
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"ai-maestro-janitor@ai-maestro-plugins": True}}),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()

    # Deliberately OMIT CLAUDE_PLUGIN_ROOT — the harness failing to export it is exactly the
    # janitor#80 failure the __file__ fallback defends against.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}
    env.update(
        {
            "HOME": str(home),
            "CLAUDE_PROJECT_DIR": str(project),
            "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "global-state"),
            "CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED": "false",
            "CLAUDE_PLUGIN_OPTION_OS_KEEPALIVE_ENABLED": "false",
        }
    )

    subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, str(HOOKS_DIR / "on-session-start.py")],
        input=json.dumps(_EVENT),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(project),
    )

    shipped = {p.name for p in (REPO / "rules").glob("*.md")}
    installed = {p.name for p in (home / ".claude" / "rules").glob("*.md")}
    missing = shipped - installed
    assert not missing, (
        f"on-session-start with NO CLAUDE_PLUGIN_ROOT did not install {sorted(missing)} — "
        f"the __file__ plugin-root fallback (janitor#80) is not working; the hook took the "
        f"old unset-env early-return path and skipped rule installation."
    )
    assert "universal-kanban.md" in installed, "the IND governance rule must reach the dest"


def test_on_session_start_writes_pre_import_breadcrumb(tmp_path: Path) -> None:
    """janitor#80 fix #1: the hook stamps a DATED line into session-start.log BEFORE the
    `lib` imports, so a future import-time death (the 2026-06-20 failure mode) is dated and
    diagnosable instead of silent. Assert the breadcrumb reaches the log.
    """
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"ai-maestro-janitor@ai-maestro-plugins": True}}),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()

    env = {
        **os.environ,
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(REPO),
        "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "global-state"),
        "CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED": "false",
        "CLAUDE_PLUGIN_OPTION_OS_KEEPALIVE_ENABLED": "false",
    }
    # Ensure the log dir resolves to the project (no daemon override in a session hook).
    env.pop("JANITOR_LOG_DIR", None)

    subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, str(HOOKS_DIR / "on-session-start.py")],
        input=json.dumps(_EVENT),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(project),
    )

    log = project / ".janitor" / "logs" / "session-start.log"
    assert log.is_file(), "session-start.log was not written at all"
    text = log.read_text(encoding="utf-8")
    assert "session-start hook entered (pre-import)" in text, (
        "the pre-import breadcrumb (janitor#80 fix #1) did not reach the log — a future "
        "import-time death would again be undated and silent."
    )
