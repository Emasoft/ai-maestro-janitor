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


def test_on_session_start_ensures_recommended_settings(tmp_path: Path) -> None:
    """End-to-end (TRDD-EQ792YPX): the hook WRITES the recommended settings into the sandbox
    ~/.claude/settings.json — the 8 Group-A env keys into the `env` block and the Group-B enforced
    key at the top level — WITHOUT disturbing a pre-existing `enabledPlugins`. Asserts the OUTCOME,
    not just crash-safety. Fully sandboxed (HOME + global-state → tmp), so the developer's real
    ~/.claude/settings.json is never touched (the isolation the ensurer's design depends on).
    """
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    import settings_ensurer as se

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

    data = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert data["enabledPlugins"] == {"ai-maestro-janitor@ai-maestro-plugins": True}  # preserved
    for key, val in se.ENV_ADD_IF_MISSING.items():
        assert data.get("env", {}).get(key) == val, f"env key {key} not ensured by the hook"
    for key, val in se.TOP_LEVEL_ENFORCE.items():
        assert data.get(key) == val, f"top-level {key} not enforced by the hook"


def test_harness_selftest_block_never_strands_the_stop_reminder(tmp_path: Path) -> None:
    """Placement / survival regression (TRDD-B0SABNP8, ATOM-B0SA-PLCE).

    The harness self-test block sits BEFORE the `_active_global_stop` early return. With a
    machine-wide stop set AND a probe forced RED, prove BOTH happened in one run:
      * the self-test RAN before the stop return — a HARNESS-DRIFT entry is in the project
        findings ledger, and its drift line is on stdout;
      * the survival emission that FOLLOWS the block still fired — the global-stop reminder
        printed and the hook returned cleanly.
    Both present ⇒ the block neither returned nor raised ⇒ it never stranded the survival
    emission below it (D4's form of the unifying invariant). Fully sandboxed.
    """
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    # A user-scope pluginConfigs declaring a janitor knob whose CLAUDE_PLUGIN_OPTION_* we
    # deliberately withhold below → probe_option_delivery goes RED (the 2.1.207 shape).
    (home / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "enabledPlugins": {"ai-maestro-janitor@ai-maestro-plugins": True},
                "pluginConfigs": {"ai-maestro-janitor@ai-maestro-plugins": {"github_repo": "o/r"}},
            }
        ),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    control = tmp_path / "control"
    control.mkdir()
    (control / "kill-switch.flag").write_text("set_at=1 by=test reason=placement-regression\n", encoding="utf-8")

    env = {
        **os.environ,
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(REPO),
        "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "global-state"),
        "JANITOR_CONTROL_DIR": str(control),  # machine-wide stop lives here (test override)
        "CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED": "false",
        "CLAUDE_PLUGIN_OPTION_OS_KEEPALIVE_ENABLED": "false",
    }
    # Guarantee the RED condition + standalone (#N) mode regardless of the dev's real env:
    # the withheld option must be absent, and no harness flag may flip the hook to thin mode.
    for k in (
        "CLAUDE_PLUGIN_OPTION_GITHUB_REPO",
        "AIMAESTRO_AGENT",
        "THIS_IS_AIMAESTRO",
        "AMP_AGENT_ID",
        "AID_AUTH",
    ):
        env.pop(k, None)

    proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, str(HOOKS_DIR / "on-session-start.py")],
        input=json.dumps(_EVENT),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(project),
    )

    # The survival emission below the block still fired.
    assert "globally DISARMED" in proc.stdout, (
        f"the global-stop reminder (the survival emission after the self-test block) did NOT "
        f"print — the block may have returned/raised and stranded it:\n{proc.stdout[:2000]}"
    )
    # The self-test ran BEFORE that return: its loud drift line is on stdout ...
    assert "harness self-test" in proc.stdout, (
        f"the harness self-test drift line is missing — the block did not run before the stop "
        f"return:\n{proc.stdout[:2000]}"
    )
    # ... and it routed the finding into THIS project's ledger.
    ledger = project / ".janitor" / "state" / "findings-ledger.ndjsonl"
    assert ledger.is_file() and "HARNESS-DRIFT" in ledger.read_text(encoding="utf-8"), (
        "the self-test failure was not recorded into the project findings ledger"
    )
