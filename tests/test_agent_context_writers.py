"""Tests for the agent-context-writer guard (Emasoft/ai-maestro-janitor#110).

Two layers, both real (no mocks):
  * the PURE matcher ``agent_context_writers.command_invokes_agent_writer`` — the security
    logic, exhaustively exercised including the two false-positives the AgentlensPro reference
    impl already paid for;
  * the HOOK ``pre-tool-agent-generator-guard.py`` — run as a real subprocess with real stdin,
    fully sandboxed (HOME / CLAUDE_PROJECT_DIR / global-state redirected to tmp) so a test can
    never read or write the real ``~/.claude`` (the keepalive-test-isolation-fsevents lesson).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import agent_context_writers as acw  # noqa: E402

HOOK = REPO / "scripts" / "hooks" / "pre-tool-agent-generator-guard.py"


# --------------------------------------------------------------------------- pure matcher

# Commands that MUST be flagged (the generator is really invoked).
_DENY = [
    "playwright init-agents",
    "playwright init-agents --loop claude",
    "npx playwright init-agents",
    "npx playwright init-agents --loop copilot --project",
    "pnpm exec playwright init-agents",
    "yarn playwright init-agents",
    "./node_modules/.bin/playwright init-agents --prompts",
    "/usr/local/bin/playwright init-agents",
    "cd repo && playwright init-agents",          # compound: 2nd segment invokes it
    "clear; playwright init-agents",              # compound via ';'
    "playwright test init-agents",                # deliberate conservatism (later-in-segment)
]

# Commands that MUST pass (benign, or merely MENTION the command).
_ALLOW = [
    "playwright test",
    "playwright test --headed",
    "playwright install chromium",
    "playwright --version",
    "git status",
    "echo hello",
    "npm install playwright",
    # THE lesson: the guard's own filename carries both words but its basename is not the
    # binary — it must stay committable.
    "git add scripts/deny-playwright-init-agents.js",
    "git add scripts/hooks/pre-tool-agent-generator-guard.py",
    # A commit message that quotes the command: shlex keeps it ONE token, so no binary +
    # subcommand pair is exposed (the quote-aware extension of the token lesson).
    'git commit -m "add playwright init-agents guard"',
    # Cross-command: the two words live in different segments, neither of which invokes it.
    "playwright test && echo init-agents",
    "echo playwright | grep init-agents",
    "",
]


@pytest.mark.parametrize("command", _DENY)
def test_matcher_flags_real_invocations(command: str) -> None:
    """A real ``playwright init-agents`` invocation (bare, wrapped, or path-qualified) is
    flagged with the playwright writer."""
    writer = acw.command_invokes_agent_writer(command)
    assert writer is not None, command
    assert writer.package == "playwright"
    assert writer.subcommand == "init-agents"


@pytest.mark.parametrize("command", _ALLOW)
def test_matcher_allows_benign_and_mentions(command: str) -> None:
    """A benign command — or one that merely MENTIONS the words across a quote or a segment
    boundary — is not flagged. Covers the two documented false-positives."""
    assert acw.command_invokes_agent_writer(command) is None, command


def test_matcher_never_raises_on_junk() -> None:
    """PURE + total: a non-string, unbalanced quotes, or nonsense input returns None, never
    raises (the hook's fail-open contract relies on this)."""
    assert acw.command_invokes_agent_writer(None) is None  # type: ignore[arg-type]
    assert acw.command_invokes_agent_writer(123) is None  # type: ignore[arg-type]
    # Unbalanced quotes must NOT raise: shlex fails, the literal fallback takes over. On a real
    # invocation the fallback still flags it (conservative); on a benign one it returns None.
    assert acw.command_invokes_agent_writer('playwright init-agents "unclosed') is not None
    assert acw.command_invokes_agent_writer('echo "unclosed') is None


def test_table_is_data_driven() -> None:
    """The durable primitive is a TABLE — adding an offender is a data row. The playwright row
    exists and names the workflow-file write that makes the bare form dangerous."""
    pkgs = {w.package for w in acw.AGENT_CONTEXT_WRITERS}
    assert "playwright" in pkgs
    pw = next(w for w in acw.AGENT_CONTEXT_WRITERS if w.package == "playwright")
    assert pw.writes  # non-empty
    assert ".github/workflows/copilot-setup-steps.yml" in pw.writes


# ------------------------------------------------------------------------------- the hook

def _run_hook(command: str, tmp_path: Path, *, stdin: str | None = None,
              env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the hook as a real subprocess, fully sandboxed away from the real ~/.claude."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    project = tmp_path / "project"
    (project / ".janitor" / "state").mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(REPO),
        "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "global-state"),
    }
    if env_extra:
        env.update(env_extra)
    payload = stdin if stdin is not None else json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": command}},
    )
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, str(HOOK)],
        input=payload, capture_output=True, text=True, timeout=120, env=env,
        cwd=str(project),
    )


def _decision(proc: subprocess.CompletedProcess[str]) -> str | None:
    if not proc.stdout.strip():
        return None
    return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]


def test_hook_denies_real_invocation(tmp_path: Path) -> None:
    """The hook DENIES `playwright init-agents` and names the janitor + the opt-out."""
    proc = _run_hook("playwright init-agents", tmp_path)
    assert _decision(proc) == "deny"
    out = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "ai-maestro-janitor" in out
    assert "allow-agent-generators" in out


def test_hook_allows_benign(tmp_path: Path) -> None:
    """A benign Bash command passes silently (no JSON on stdout)."""
    proc = _run_hook("playwright test", tmp_path)
    assert proc.stdout.strip() == ""


def test_hook_allows_non_bash_tool(tmp_path: Path) -> None:
    """A non-Bash tool call is never this hook's business."""
    proc = _run_hook("", tmp_path, stdin=json.dumps(
        {"tool_name": "Edit", "tool_input": {"command": "playwright init-agents"}}))
    assert proc.stdout.strip() == ""


def test_hook_fail_open_on_malformed_stdin(tmp_path: Path) -> None:
    """LESSON 2: an unparseable payload ALLOWS — it must never block every Bash call."""
    proc = _run_hook("", tmp_path, stdin="{ this is not json")
    assert proc.stdout.strip() == ""
    assert proc.returncode == 0


def test_hook_project_opt_out_honored(tmp_path: Path) -> None:
    """A project that placed `.janitor/state/allow-agent-generators` is not blocked."""
    (tmp_path / "project" / ".janitor" / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "project" / ".janitor" / "state" / "allow-agent-generators").write_text("", encoding="utf-8")
    proc = _run_hook("playwright init-agents", tmp_path)
    assert proc.stdout.strip() == ""


def test_hook_master_knob_off(tmp_path: Path) -> None:
    """Setting the enable knob false disables the guard machine-wide."""
    proc = _run_hook("playwright init-agents", tmp_path,
                     env_extra={"CLAUDE_PLUGIN_OPTION_AGENT_GENERATOR_GUARD_ENABLED": "false"})
    assert proc.stdout.strip() == ""
