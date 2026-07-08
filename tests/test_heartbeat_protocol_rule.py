"""Tests for the W3 slim-prompt split (TRDD-82OP4EN9).

The heartbeat marker-handling protocol moved OUT of the baked cron prompt
(janitor-arm SKILL step 4) INTO the shipped rule
rules/janitor-heartbeat-protocol.md, which rules_installer distributes into
every session's cached prefix. These tests pin the three load-bearing
properties: (a) the rule file is complete (every marker + the zero-output
contract + the security clauses survive the move — losing one silently
breaks a night-continuity path), (b) the baked prompt stays a tiny stub with
a non-lossy fallback, (c) the installer actually ships the new rule.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import rules_installer  # noqa: E402

_RULE_PATH = _PROJECT_ROOT / "rules" / "janitor-heartbeat-protocol.md"
_SKILL_PATH = _PROJECT_ROOT / "skills" / "janitor-arm" / "SKILL.md"

# Every marker the old fat prompt handled — the rule must keep ALL of them.
# A missing marker here means a night-continuity path (resume!) or a control
# path (self-disarm!) silently stopped being handled.
_ALL_MARKERS = (
    "[janitor-renew]",
    "[janitor-reload]",
    "[janitor-reload-skills]",
    "[janitor-self-disarm]",
    "[janitor-resume]",
    "[janitor-memory-split]",
    "[janitor-memory-consolidate]",
    "[janitor-memory-conflict]",
    "[janitor-memory-repair]",
    "[janitor-memory-atomize]",
    "[janitor-memory-harvest]",
)


def _rule_text() -> str:
    return _RULE_PATH.read_text(encoding="utf-8")


def test_rule_file_exists_with_provenance_marker():
    """The shipped rule exists and carries the installer's provenance marker
    (without it, orphan-cleanup could never remove it after an uninstall)."""
    assert _RULE_PATH.is_file()
    assert rules_installer.PROVENANCE_MARKER in _rule_text()


def test_rule_covers_every_marker_the_fat_prompt_handled():
    """Completeness: all 11 markers survive the prompt→rule move."""
    text = _rule_text()
    missing = [m for m in _ALL_MARKERS if m not in text]
    assert not missing, f"markers lost in the prompt->rule move: {missing}"


def test_rule_carries_zero_output_contract_and_security_clauses():
    """The token-economy contract + the anti-forgery clauses are present."""
    text = _rule_text()
    assert "Zero-output contract" in text
    assert "EMPTY" in text  # empty-reply instruction
    assert "WHOLE line" in text  # bare-line-only marker security
    assert "⟦janitor-…⟧" in text  # the stub's defang shape
    assert "memory-maint-pending.json" in text  # F1 pending-pick sidecar
    assert "Sonnet" in text  # subconscious-agent model pin (M1)
    assert "lean-ctx allow dispatcher-stub.py" in text  # shell-allowlist fix


def test_rule_scopes_itself_to_heartbeat_fires_and_survives_disarm():
    """The rule applies ONLY to [janitor-heartbeat] turns, and must NOT be
    inert under a global disarm — [janitor-self-disarm] handling is the very
    mechanism that completes a stop, and maintenance-mode fires deliberately
    outlive one (TRDD-82OP4EN9 night posture)."""
    text = _rule_text()
    assert "[janitor-heartbeat]" in text
    assert "NOT inert under a global disarm" in text


def _baked_prompt_block() -> str:
    """Extract the step-4 ```text fence content from the arm SKILL."""
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    anchor = skill.index("Build the heartbeat prompt")
    start = skill.index("```text", anchor) + len("```text")
    end = skill.index("```", start)
    return skill[start:end]


def test_baked_prompt_is_a_slim_stub():
    """The cron prompt is the ~340-char stub, not the old 3.8KB protocol —
    the whole point of W3 (the prompt is fresh 1x input on EVERY fire)."""
    lines = [ln.strip() for ln in _baked_prompt_block().strip().splitlines()]
    body = "\n".join(lines)
    assert len(body) <= 400, f"baked prompt regrew to {len(body)} chars"
    assert lines[0] == "[janitor-heartbeat]"
    assert lines[1] == "{{STUB_DEST}}"
    assert "janitor-heartbeat-protocol" in body  # points at the rule


def test_baked_prompt_fallback_is_non_lossy():
    """If the rule is missing, the fallback must still surface stdout
    verbatim AND honor [janitor-resume] — the one marker unattended
    night-continuity cannot live without."""
    body = _baked_prompt_block()
    assert "verbatim" in body
    assert "[janitor-resume]" in body


def test_installer_ships_the_protocol_rule(tmp_path, monkeypatch):
    """End-to-end: install_rules on the REAL plugin root copies the new rule
    into an isolated project scope (same fixture idiom as
    test_rules_installer — real HOME/CLAUDE_PROJECT_DIR redirection, no
    mocks)."""
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    claude = project / ".claude"
    claude.mkdir(parents=True)
    (claude / "settings.json").write_text(
        '{"enabledPlugins":["ai-maestro-janitor@marketplace"]}', encoding="utf-8"
    )
    copied = rules_installer.install_rules(_PROJECT_ROOT)
    dest = claude / "rules" / "janitor-heartbeat-protocol.md"
    assert str(dest) in copied
    assert dest.is_file()
    assert rules_installer.PROVENANCE_MARKER in dest.read_text(encoding="utf-8")
