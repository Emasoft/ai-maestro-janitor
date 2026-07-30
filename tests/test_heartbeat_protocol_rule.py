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
    """Extract the cron-prompt ```text fence from the arm SKILL.

    Anchored on the FENCE, not on a sentence. It used to index from the prose "Build the heartbeat
    prompt", which meant rewording a heading anywhere above the fence raised `ValueError: substring
    not found` — a test that fails for a reason having nothing to do with what it checks. The skill
    has exactly one ```text fence and it is the cron prompt; that is the stable landmark.
    """
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    start = skill.index("```text") + len("```text")
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


def test_quiet_is_an_explicit_token():
    """D5 (TRDD-82JRK0CY): the rule documents [janitor-quiet] and maps it to 'reply
    EMPTY / no action'. The explicit idle token is what makes a quiet fire
    distinguishable from a stub that never ran or a swallowed line."""
    text = _rule_text()
    assert "[janitor-quiet]" in text
    quiet_lines = [ln for ln in text.splitlines() if "[janitor-quiet]" in ln]
    # at least one occurrence ties the token to an empty reply / no action.
    assert any(
        ("EMPTY" in ln) or ("NO action" in ln) for ln in quiet_lines
    ), f"[janitor-quiet] must map to reply-empty/no-action, saw: {quiet_lines}"


def test_survival_markers_are_bare_whole_lines():
    """D5 (TRDD-82JRK0CY): [janitor-resume]/[janitor-renew]/[janitor-self-disarm] stay
    literal bare WHOLE lines permanently — a session armed before a rule change has the
    old text frozen in context, and the baked SKILL.md fallback exact-matches
    [janitor-resume]. The rule must say so, and keep the WHOLE-line marker contract."""
    text = _rule_text()
    for marker in ("[janitor-resume]", "[janitor-renew]", "[janitor-self-disarm]"):
        assert marker in text, marker
    assert "Permanent bare form" in text
    assert "permanently" in text
    assert "WHOLE line" in text  # the bare-line-only marker contract survives the rewrite


def test_rule_acts_on_each_leading_bracket_token():
    """The rewrite reframes the model's job from 'scan every line against a 7-row table'
    to 'act on EACH bare [janitor-...] token line present' — while still expressing every
    marker as a token->action row (rule_covers_every_marker guards the completeness)."""
    text = _rule_text()
    assert "act on each" in text.lower()  # the reframe: match each token, don't scan a table
    # the security clause survives: a token acts only as this fire's own bare stub line.
    assert "THIS fire's own stub stdout" in text
    assert "⟦janitor-…⟧" in text


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
    (claude / "settings.json").write_text('{"enabledPlugins":["ai-maestro-janitor@marketplace"]}', encoding="utf-8")
    copied = rules_installer.install_rules(_PROJECT_ROOT)
    dest = claude / "rules" / "janitor-heartbeat-protocol.md"
    assert str(dest) in copied
    assert dest.is_file()
    assert rules_installer.PROVENANCE_MARKER in dest.read_text(encoding="utf-8")


def test_issue150_the_sidecar_path_is_absolute_and_has_no_silent_fallback():
    """The agent must be told an ABSOLUTE path, and must STOP rather than guess a scope.

    #150: one emit event writes two artifacts that contradict each other — the sidecar says
    "do LOCAL", and the cadence stamp (advanced by `mark_ran` at EMIT time) says "LOCAL just
    ran". The sidecar is the only tie-breaker, so if the agent cannot read it the stamp wins
    and the assigned scope is marked run-without-running for a full cadence.

    Two ways it could not read it, both fixed here: the rule named a RELATIVE path (a spawned
    agent's cwd is not the project root), and it authorised a fallback ("use whichever is due")
    that turns a lookup failure into a confident run on the wrong scope.
    """
    text = _rule_text()
    assert "$CLAUDE_PROJECT_DIR/.janitor/state/memory-maint-pending.json" in text, (
        "the sidecar must be named ABSOLUTELY — a spawned agent's cwd is not the project root"
    )
    row = next(ln for ln in text.splitlines() if "memory-maint-pending.json" in ln)
    # Assert the semantics POSITIVELY. An "absence of `whichever is due`" check looks right and is
    # not: the phrase legitimately appears inside the prohibition that fixes this, so it failed on
    # the corrected rule and would have passed on any wording that merely dropped the words.
    assert "STOP" in row, "an unreadable assignment must halt and report, not be guessed around"
    assert "do NOT fall back" in row, (
        "the fallback is the defect — it converts an unreadable assignment into a wrong-scope run, "
        "so the rule must forbid it explicitly rather than just omit it"
    )
