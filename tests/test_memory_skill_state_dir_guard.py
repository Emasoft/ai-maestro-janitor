"""TRDD-N1CPV1QV parts (a)/(c)/(f) — the memory agent must be handed the scheduler's
absolute state dir instead of resolving it from its own (unreliable) cwd.

Two grep-based checks:
- every `janitor-memory-*` SKILL.md that invokes the claim step passes `--state-dir`,
  sourced from a `$STATE_DIR` that a `: "${STATE_DIR:?...}"` guard fails loudly on if unset
- the heartbeat rule's memory-agent spawn text carries the `STATE_DIR` placeholder that
  makes the path travel INSIDE the prompt, not on stdout (the rejected alternative in the
  card's "Rejected alternatives" section)

Only the 8 memory chores that actually call `memory_dispatch_claim.py` are in scope —
`janitor-memory-bootstrap/frequency/recall/record-recent/update/write` never call it and
must not be forced to carry a claim-step guard they have no claim step to guard.
"""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _PROJECT_ROOT / "skills"
_RULE_PATH = _PROJECT_ROOT / "rules" / "janitor-heartbeat-protocol.md"


def _claim_skill_paths() -> list[Path]:
    return [
        p
        for p in sorted(_SKILLS_DIR.glob("janitor-memory-*/SKILL.md"))
        if "memory_dispatch_claim.py" in p.read_text(encoding="utf-8")
    ]


def test_every_memory_chore_skill_actually_calls_the_claim_step():
    """Sanity check the fixture itself: the 8 chores this TRDD covers are exactly the ones
    that call memory_dispatch_claim.py, not a subset the grep below would silently pass."""
    names = {p.parent.name for p in _claim_skill_paths()}
    assert names == {
        "janitor-memory-atomize",
        "janitor-memory-conflict",
        "janitor-memory-consolidate",
        "janitor-memory-enrich",
        "janitor-memory-harvest",
        "janitor-memory-repair",
        "janitor-memory-retro-lesson",
        "janitor-memory-split",
    }


def test_every_memory_chore_skill_passes_state_dir_to_the_claim_step():
    """`grep -L -- '--state-dir' skills/janitor-memory-*/SKILL.md` (restricted to claim
    callers) must return nothing — a claim invocation with no `--state-dir` silently
    resolves the pool from the agent's own cwd, which is not guaranteed to be the project
    root (the bug this TRDD fixes)."""
    missing = [
        p for p in _claim_skill_paths() if "--state-dir" not in p.read_text(encoding="utf-8")
    ]
    assert not missing, f"claim step missing --state-dir in: {missing}"


def test_every_memory_chore_skill_guards_an_unset_state_dir():
    """Each command block must fail loudly, before invoking the claim step, when
    $STATE_DIR is unset or empty — never silently fall through to a claim call that then
    resolves the pool from cwd."""
    missing = [
        p
        for p in _claim_skill_paths()
        if 'STATE_DIR:?' not in p.read_text(encoding="utf-8")
    ]
    assert not missing, f"missing the ${{STATE_DIR:?...}} guard in: {missing}"


def test_every_memory_chore_skill_exports_state_dir_before_the_guard():
    """A `${STATE_DIR:?...}` guard with no prior `export STATE_DIR=` is a guaranteed
    abstain: the spawned agent's fresh shell never has the spawn prompt's STATE_DIR=<path>
    value in its environment, so the guard fires on every single invocation (found by the
    review fork on TRDD-N1CPV1QV). Each claim-calling skill must carry an
    `export STATE_DIR=` line strictly before its `${STATE_DIR:?` guard line."""
    for p in _claim_skill_paths():
        lines = p.read_text(encoding="utf-8").splitlines()
        export_line = next(
            (i for i, ln in enumerate(lines) if "export STATE_DIR=" in ln), None
        )
        guard_line = next((i for i, ln in enumerate(lines) if "STATE_DIR:?" in ln), None)
        assert export_line is not None, f"missing 'export STATE_DIR=' in: {p}"
        assert guard_line is not None, f"missing the STATE_DIR guard in: {p}"
        assert export_line < guard_line, (
            f"'export STATE_DIR=' must precede the '${{STATE_DIR:?...}}' guard in: {p}"
        )


def test_retro_lesson_claim_step_uses_a_fenced_code_block():
    """retro-lesson previously carried the claim invocation as inline backticked text on
    separate lines, unlike the other 7 chores' fenced ```bash blocks — bring it in line so
    all 8 are the same shape."""
    p = _SKILLS_DIR / "janitor-memory-retro-lesson" / "SKILL.md"
    text = p.read_text(encoding="utf-8")
    assert "```bash" in text, "retro-lesson's claim step must use a fenced ```bash block"
    fenced_block = text.split("```bash", 1)[1].split("```", 1)[0]
    assert "export STATE_DIR=" in fenced_block
    assert "STATE_DIR:?" in fenced_block
    assert "memory_dispatch_claim.py" in fenced_block


def test_heartbeat_rule_spawn_prompt_carries_the_state_dir_placeholder():
    """The spawning session must compose STATE_DIR and hand it to the spawned agent INSIDE
    the prompt text — never as a stdout payload line (the heartbeat "no unsolicited paths"
    contract; see the card's "Rejected alternatives" section)."""
    text = _RULE_PATH.read_text(encoding="utf-8")
    row = next(ln for ln in text.splitlines() if "memory_dispatch_claim.py" in ln)
    assert "STATE_DIR=<path>" in row or "STATE_DIR=" in row, (
        "the row must show the spawn prompt carrying STATE_DIR=<path> as prompt text"
    )
    assert '--state-dir "$STATE_DIR"' in row, (
        "the row must instruct the claim step to be invoked with the prompt-supplied "
        "$STATE_DIR, never resolved from the receiving agent's own cwd"
    )
    assert "do NOT spawn the memory agent" in row, (
        "an unresolvable STATE_DIR must abort the spawn rather than spawn an agent that "
        "will silently resolve the wrong project's pool"
    )
