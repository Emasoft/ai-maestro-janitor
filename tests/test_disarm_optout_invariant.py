"""Guardrail: /janitor-disarm must establish the opt-out invariant the fleet layer reads.

Two bugs, both found 2026-07-09, both living in markdown that no Python test could see.

**1. `disarmed.flag` had four readers and zero writers.** `fleet_scan.diagnose_root`,
`session_liveness.diagnose_instance`, `fleet_status`, and `daemon` all treat the flag as
THE positive opt-out — the one signal that makes an instance `unarmed` and therefore
sacrosanct. `fleet_scan`'s own docstring says it is "written by `/janitor-disarm`". It was
not. `tests/test_fleet_scan.py` passed only because the test writes the flag itself, so the
missing writer was invisible from inside the Python suite. Live consequence: a user who
deliberately ran `/janitor-disarm` got no opt-out record, so the fleet guardian diagnosed the
project `cron_dead` and typed `/janitor-arm` back into their pane — re-arming exactly what
the user had just stopped.

**2. Disarm deleted a machine-wide file.** Step 4 removed
`${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`, which is ONE file shared by every project's cron
(the data dir is per-PLUGIN, not per-project). `/janitor-disarm` is also what a session runs
on the bare `[janitor-self-disarm]` marker, so a `/janitor-global-disarm` had every armed
session race to delete it: the first one won, and every other session's cron kept firing at a
missing file — burning a full billed turn per fire, forever, which is the precise cost
TRDD-RQ9FIFX6 set out to eliminate. The stub is inert without a cron; uninstall owns the
data dir. Nothing should delete it.

These tests assert both invariants against the shipped skill text. The skills ARE the
executable artifact here — an agent follows the markdown — so the markdown is what must be
guarded. Same technique as `test_memory_recall_shell_snippets.py`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import state  # type: ignore[import-not-found]  # noqa: E402

DISARM = REPO / "skills" / "janitor-disarm" / "SKILL.md"
ARM = REPO / "skills" / "janitor-arm" / "SKILL.md"
GUARD = REPO / "scripts" / "disarm_guard.py"
# Since TRDD-DLI76AUC the arm's shell steps live in this script rather than in the skill's
# markdown: each tool round-trip re-reads the whole conversation and is billed for it, so the arm
# was folded from six calls into four. The opt-out removal moved with them.
PREPARE = REPO / "scripts" / "arm_prepare.py"

# A shell line that removes the shared, machine-wide dispatcher stub. Matches any `rm`
# whose target names the stub, however the data dir is spelled.
STUB_RM = re.compile(r"^\s*rm\b[^\n]*dispatcher-stub\.py")

# Writing the flag: any shell that creates/truncates `disarmed.flag` (touch, >, printf >).
FLAG_WRITE = re.compile(r"(touch|>|printf|echo)[^\n]*disarmed\.flag")
# Removing the flag: an `rm` whose target names it.
FLAG_RM = re.compile(r"^\s*rm\b[^\n]*disarmed\.flag")
# Removing the flag from PYTHON — `(sd / state.DISARMED_FLAG).unlink()`. Matched through the
# CONSTANT, never the literal filename: the flag's name must have exactly one definition, which is
# the whole point of this file (it once had four independent spellings and zero writers).
FLAG_UNLINK_PY = re.compile(r"state\.DISARMED_FLAG\s*\)\s*\.unlink\(")


def _shell_lines(doc: Path) -> list[str]:
    """Every line inside a fenced ```bash block — the part an agent actually executes.

    Prose that merely NAMES a construct (an autopsy note, a Scope sentence) must never
    trip an assertion; only real commands count.
    """
    lines, in_bash = [], False
    for raw in doc.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_bash = stripped.startswith("```bash")
            continue
        if in_bash:
            lines.append(raw)
    return lines


def test_skills_exist() -> None:
    """Both skills are present, so the assertions below are not vacuous."""
    assert DISARM.is_file(), f"missing shipped skill: {DISARM}"
    assert ARM.is_file(), f"missing shipped skill: {ARM}"


def test_disarm_records_the_optout_through_the_guard() -> None:
    """Disarm must record the opt-out the whole fleet layer reads — but only when a HUMAN asked.

    The invariant is unchanged; its writer MOVED (TRDD-RDFWQIFA). The skill used to write the flag
    unconditionally, which meant an agent running `/janitor-disarm` on its own judgment forged a human
    decision and permanently disabled the guardian — the one mechanism designed to undo that mistake.
    It is not hypothetical: on 2026-07-14 an agent disarmed to save tokens and the session sat dead for
    hours.

    So the flag is now written by `disarm_guard.py`, and ONLY on real authority (a user-intent token
    stamped from raw keystrokes, or a genuine machine-wide stop). The skill must therefore CALL the
    guard, and the guard must be the thing that writes the flag. Both halves are asserted here, because
    either one alone can silently rot: a skill that stops calling the guard writes nothing, and a guard
    that stops writing leaves every disarm unrecorded.
    """
    shell = "\n".join(_shell_lines(DISARM))
    assert "disarm_guard.py" in shell, "janitor-disarm no longer calls disarm_guard.py — nothing records the opt-out, so the fleet guardian will re-arm projects the user deliberately disarmed"
    assert not FLAG_WRITE.search(shell), "janitor-disarm writes disarmed.flag DIRECTLY again — that is the forgeable path the guard exists to close: an agent could fake a human's opt-out and permanently disable the guardian"

    guard = GUARD.read_text(encoding="utf-8")
    assert "state.DISARMED_FLAG" in guard, "disarm_guard.py no longer writes the opt-out flag"
    assert "atomic_write" in guard, "the flag write must be atomic — a torn flag is read as absent"


def test_disarm_does_not_delete_the_shared_stub() -> None:
    """Disarm is project-scoped; the stub is machine-wide. It must not be deleted.

    On `/janitor-global-disarm` every armed session runs this skill. If it deletes the
    shared stub, the first session strands all the others firing at a missing file.
    """
    hits = [f"{DISARM.name}: {ln.strip()}" for ln in _shell_lines(DISARM) if STUB_RM.search(ln)]
    assert not hits, "janitor-disarm deletes the machine-wide dispatcher stub — a project-scoped command with a fleet-wide blast radius:\n" + "\n".join(hits)


def test_arm_clears_the_optout_flag() -> None:
    """Arming is the inverse of opting out, so it must clear the flag.

    Otherwise a re-armed project stays classified `unarmed` forever and the guardian
    never protects it again.

    Since TRDD-DLI76AUC the removal lives in `arm_prepare.py` rather than the skill's shell. That
    move STRENGTHENS the invariant rather than dodging it: the step is now real code with a
    behavioral test (`test_arm_scripts.py::test_prepare_revokes_the_opt_out_and_installs_the_stub`
    actually creates the flag and watches the script delete it) instead of markdown an agent had to
    remember to run. What this test still guards is that the step EXISTS AT ALL — wherever it lives.
    """
    assert FLAG_UNLINK_PY.search(PREPARE.read_text(encoding="utf-8")), "arm_prepare.py no longer removes state.DISARMED_FLAG — a re-armed project would stay 'unarmed' (sacrosanct) forever and the fleet guardian would never protect it again"


def test_the_reader_the_writer_and_the_skills_all_name_the_same_flag() -> None:
    """The reader and the writer must agree on the filename.

    This is the assertion that would have caught the original gap: it binds the shipped skill text to
    the Python that consumes it, which no unit test of either half could do on its own. It routes
    through `state.DISARMED_FLAG` so the name has exactly ONE definition — the four readers used to
    spell it independently, and nobody wrote it.

    Since TRDD-RDFWQIFA the writer is `disarm_guard.py` rather than the skill's own shell, and since
    TRDD-DLI76AUC the remover is `arm_prepare.py` rather than the arm skill's shell. So the chain
    under test is: guard WRITES the constant → fleet_scan READS the constant → arm_prepare REMOVES
    it. All three name `state.DISARMED_FLAG`; none of them spells the filename itself. That is the
    entire point — the flag once had four independent spellings and no writer at all, and nobody
    noticed because no unit test of any single half could see the disagreement.
    """
    scan = (REPO / "scripts" / "lib" / "fleet_scan.py").read_text(encoding="utf-8")
    assert "state.DISARMED_FLAG" in scan, "fleet_scan no longer reads the opt-out flag"

    guard = GUARD.read_text(encoding="utf-8")
    assert "state.DISARMED_FLAG" in guard, "disarm_guard.py does not write state.DISARMED_FLAG"

    # Arm clears it with no authority check — re-arming is the SAFE direction (the worst case is a
    # guarded project, which is the default anyway), so unlike the disarm it needs no guard.
    prepare = PREPARE.read_text(encoding="utf-8")
    assert "state.DISARMED_FLAG" in prepare, f"arm_prepare.py does not name state.DISARMED_FLAG ({state.DISARMED_FLAG}) — a hardcoded literal here is exactly the drift this test exists to prevent"
