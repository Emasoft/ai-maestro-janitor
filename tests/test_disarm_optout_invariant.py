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
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

DISARM = REPO / "skills" / "janitor-disarm" / "SKILL.md"
ARM = REPO / "skills" / "janitor-arm" / "SKILL.md"

# A shell line that removes the shared, machine-wide dispatcher stub. Matches any `rm`
# whose target names the stub, however the data dir is spelled.
STUB_RM = re.compile(r"^\s*rm\b[^\n]*dispatcher-stub\.py")

# Writing the flag: any shell that creates/truncates `disarmed.flag` (touch, >, printf >).
FLAG_WRITE = re.compile(r"(touch|>|printf|echo)[^\n]*disarmed\.flag")
# Removing the flag: an `rm` whose target names it.
FLAG_RM = re.compile(r"^\s*rm\b[^\n]*disarmed\.flag")


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


def test_disarm_writes_the_optout_flag() -> None:
    """Disarm must record the opt-out the whole fleet layer reads.

    Without this write, `deliberately_unarmed` is False for every real project and the
    `unarmed` branch of `diagnose_instance` is dead code — the guardian re-arms a project
    the user deliberately disarmed.
    """
    shell = "\n".join(_shell_lines(DISARM))
    assert FLAG_WRITE.search(shell), "janitor-disarm no longer writes .janitor/state/disarmed.flag — the fleet guardian will re-arm projects the user deliberately disarmed"


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
    """
    hits = [ln for ln in _shell_lines(ARM) if FLAG_RM.search(ln)]
    assert hits, "janitor-arm no longer removes .janitor/state/disarmed.flag — a re-armed project would stay 'unarmed' (sacrosanct) forever and never be guarded again"


def test_fleet_scan_reads_the_flag_the_skills_write() -> None:
    """The reader and the writer must agree on the filename.

    This is the assertion that would have caught the original gap: it binds the shipped
    skill text to the Python that consumes it, which no unit test of either half could do
    on its own.
    """
    scan = (REPO / "scripts" / "lib" / "fleet_scan.py").read_text(encoding="utf-8")
    assert '"disarmed.flag"' in scan, "fleet_scan no longer reads disarmed.flag"
    assert FLAG_WRITE.search("\n".join(_shell_lines(DISARM))), "…but janitor-disarm stopped writing it"
