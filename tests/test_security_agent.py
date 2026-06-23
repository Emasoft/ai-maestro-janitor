"""Structural + wiring tests for the janitor-security-agent (TRDD-f12cae1a).

The agent is the SINGLE security curator — one opus agent that loads every
security SKILL and detects + fixes. These tests pin its contract so a
regression (a skill dropped from the list, a skill dir deleted, the fail-safe
policy reworded away, the heartbeat wiring removed) fails the plugin's own
test gate rather than slipping through to a publish.

pyyaml is the validator's own dependency (publish.py runs `uv run --with
pyyaml`); importorskip keeps the test green in a bare env instead of erroring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AGENT = _PROJECT_ROOT / "agents" / "janitor-security-agent.md"

# The COMPLETE security-skill set the agent must own (every security domain).
_EXPECTED_SKILLS = {
    "janitor-supply-chain-watcher",
    "janitor-credential-window-audit",
    "janitor-dependabot-doctor",
    "janitor-fork-pr-cache-audit",
    "janitor-github-workflow-doctor",
    "janitor-github-workflow-create",
    "janitor-branch-protection-setup",
    "janitor-skill-bundle-audit",
}


def _frontmatter() -> dict:
    txt = _AGENT.read_text(encoding="utf-8")
    assert txt.startswith("---"), "agent file has no YAML frontmatter"
    return yaml.safe_load(txt.split("---", 2)[1])


def _body() -> str:
    return _AGENT.read_text(encoding="utf-8").split("---", 2)[2]


def test_agent_file_exists() -> None:
    """The single security agent ships as agents/janitor-security-agent.md."""
    assert _AGENT.is_file()


def test_agent_identity_and_model() -> None:
    """It is named janitor-security-agent and runs on opus at high effort."""
    fm = _frontmatter()
    assert fm["name"] == "janitor-security-agent"
    assert fm["model"] == "opus"
    assert fm["effort"] == "high"


def test_agent_declares_exactly_the_security_skills() -> None:
    """Its skills list is EXACTLY the 8 security skills — no more, no less."""
    assert set(_frontmatter()["skills"]) == _EXPECTED_SKILLS


def test_every_declared_skill_dir_exists() -> None:
    """Each declared skill resolves to a real skills/<name>/SKILL.md."""
    missing = [
        s for s in _frontmatter()["skills"]
        if not (_PROJECT_ROOT / "skills" / s / "SKILL.md").is_file()
    ]
    assert missing == [], f"declared skills with no SKILL.md: {missing}"


def test_description_within_token_budget() -> None:
    """The description stays under CPV's ~300-token agent cap (~4 chars/token)."""
    assert len(_frontmatter()["description"]) < 1500


def test_body_states_detect_and_fix_failsafe_contract() -> None:
    """The body pins detect+fix, fail-safe, never-auto-rotate, never-suppress."""
    body = _body().lower()
    assert "detect" in body and "fix" in body
    assert "fail-safe" in body or "fail safe" in body
    assert "rotate" in body  # the credential-rotation FLAG-not-fix rule
    assert "suppress" in body  # the no-suppress (CPV no-exempt) rule


def test_heartbeat_wiring_present_in_detectors() -> None:
    """At least one security detector appends security_agent_hint() so the
    heartbeat actually SUGGESTS the agent on a finding (the USER's request)."""
    det_dir = _PROJECT_ROOT / "scripts" / "detectors"
    wired = [
        p.name for p in det_dir.glob("*.py")
        if "security_agent_hint(" in p.read_text(encoding="utf-8")
    ]
    assert len(wired) >= 8, f"too few detectors wire the hint: {wired}"
