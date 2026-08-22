#!/usr/bin/env python3
"""USER decision #12 (2026-08-22) drew ONE line and this file guards both sides of it.

    "github issues/comments and pending PRs/branches/TRDDs are always only notify, while
     TRDD/PRRD/SPECS/WIKIMEM formatting errors are always autofix."

The two halves are not symmetric in risk, so they are not symmetric in what is tested:

* The NOTIFY half already existed (`tickets.open_ticket` refuses a PROJECT-domain incident
  without an approved TRDD). Nothing here builds it; the tests pin it, because the failure
  mode is a quiet one — a future change that makes the janitor "helpful" in someone else's
  repo would pass every other test in the suite.
* The AUTOFIX half is new, and the danger is not that it fails, it is that it succeeds too
  broadly. So most of what follows asserts what it REFUSES to touch. A formatter that edits
  a document's meaning is not a formatter.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_DRIFT = _ROOT / "scripts" / "detectors" / "trdd-drift.py"

sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import tickets  # noqa: E402
import trdd_common  # noqa: E402

BOM = trdd_common.BOM
_GOOD = "---\ntrdd-id: ABCD1234\ncolumn: dev\n---\n\n# A card\n\nbody text\n"


def _run_drift(project: Path, *, autofix: bool) -> str:
    """Drive the REAL detector over `project`. Mirrors test_trdd_drift_future_updated._run."""
    (project / ".janitor" / "state").mkdir(parents=True, exist_ok=True)
    (project / ".janitor" / "state" / "autofix-mode.txt").write_text(
        "on" if autofix else "off", encoding="utf-8"
    )
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_SESSION_ID"] = "sess"
    env["JANITOR_FORCE_AI_MAESTRO"] = "1"
    for k in ("CLAUDE_PLUGIN_OPTION_TRDD_STALENESS_DAYS", "CLAUDE_PLUGIN_OPTION_TRDD_PATH"):
        env.pop(k, None)
    res = subprocess.run(
        [sys.executable, str(_DRIFT)], capture_output=True, text=True, env=env, timeout=60,
    )
    return res.stdout


def _card(tmp_path: Path, content: str) -> Path:
    tasks = tmp_path / "design" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    p = tasks / "TRDD-20260101_000000+0000-ABCD1234-slug.md"
    p.write_text(content, encoding="utf-8")
    old = time.time() - 100 * 86400
    os.utime(p, (old, old))
    return p


# --------------------------------------------------------------------------- #
# the AUTOFIX half — and mostly, what it declines to do
# --------------------------------------------------------------------------- #

def test_a_wellformed_card_is_left_alone() -> None:
    """No repair on a healthy file — an autofix that rewrites clean input is churn that
    shows up as a diff on every heartbeat and trains everyone to ignore the lane."""
    assert trdd_common.repair_frontmatter_prelude(_GOOD) is None


@pytest.mark.parametrize("prelude,label", [
    (BOM, "a UTF-8 BOM"),
    ("\n", "one blank line"),
    ("\n\n\n", "several blank lines"),
    ("   \n\t\n", "whitespace-only lines"),
    (BOM + "\n\n", "a BOM followed by blank lines"),
])
def test_meaningless_bytes_above_the_block_are_removed(prelude: str, label: str) -> None:
    """These are the ONLY repairs in the lane, and they share the property that makes the
    lane safe: the removed bytes are invisible to a reader, so the repaired card asserts
    exactly what it asserted before. Pinned per shape ({label}) because each reaches the
    predicate by a different path."""
    broken = prelude + _GOOD
    assert trdd_common.frontmatter_defect(broken) is not None, "fixture must be broken"
    fixed = trdd_common.repair_frontmatter_prelude(broken)
    assert fixed == _GOOD, f"{label}: repair must yield the original bytes exactly"
    assert trdd_common.frontmatter_defect(fixed) is None


def test_a_real_line_above_the_block_is_never_touched() -> None:
    """THE most important test here. A stray `# title` above the frontmatter is the exact
    TRDD-WEBA1RMF defect this lane looks tempting for — and it is CONTENT. Deleting it
    destroys an assertion; moving it means deciding where it belongs. Either is a machine
    answering a question only the author can, which is the line decision #12 drew."""
    broken = "# A card\n" + _GOOD
    assert trdd_common.frontmatter_defect(broken) is not None
    assert trdd_common.repair_frontmatter_prelude(broken) is None


def test_an_unclosed_block_is_never_touched() -> None:
    """Repairing this needs knowing where the author meant the block to end. A guess
    silently re-partitions the file into frontmatter and body at a boundary nobody chose,
    and the result parses — so nothing downstream would ever report the mistake."""
    broken = "---\ntrdd-id: ABCD1234\ncolumn: dev\n\n# A card\n"
    assert trdd_common.frontmatter_defect(broken) is not None
    assert trdd_common.repair_frontmatter_prelude(broken) is None


def test_an_empty_file_is_never_touched() -> None:
    """Nothing to repair, and a "repair" that invents frontmatter would fabricate a card."""
    assert trdd_common.repair_frontmatter_prelude("") is None


def test_a_partial_improvement_is_refused() -> None:
    """Stripping the blanks here still leaves an unparseable file, so the real defect is
    something else. Returning the half-fixed text would rewrite a card for no benefit and
    leave the next reader unable to tell it had been touched."""
    broken = "\n\n" + "# A card\n" + _GOOD
    assert trdd_common.repair_frontmatter_prelude(broken) is None


def test_the_repair_preserves_every_byte_of_the_document_body() -> None:
    """The safety argument is byte equality, not a subjective read of "looks the same" —
    so it is asserted as byte equality on a body carrying awkward content (unicode, a
    fence, trailing whitespace) rather than on the tidy fixture above."""
    body = "---\nid: X\n---\n\n# T\n\n```py\nx = 'é —\\t'\n```\n\ntrailing   \n"
    fixed = trdd_common.repair_frontmatter_prelude(BOM + "\n" + body)
    assert fixed == body


# --------------------------------------------------------------------------- #
# the lane end-to-end, through the real detector
# --------------------------------------------------------------------------- #

def test_e2e_a_bom_card_is_repaired_on_disk_and_reported_as_autofixed(tmp_path: Path) -> None:
    """The pure predicate being right proves nothing about the detector actually calling it,
    writing the file, and saying so — so this drives the real `trdd-drift.py` and reads the
    bytes back."""
    card = _card(tmp_path, BOM + "\n" + _GOOD)
    out = _run_drift(tmp_path, autofix=True)
    assert card.read_text(encoding="utf-8") == _GOOD, "the card must be repaired on disk"
    fixed_lines = [ln for ln in out.splitlines() if "AUTOFIXED" in ln]
    assert fixed_lines, f"the repair must be reported, not silent: {out!r}"
    assert "/janitor-autofix-off" in fixed_lines[0], (
        "an unrequested edit must name its own off switch, or the user cannot stop it"
    )


def test_e2e_autofix_off_reports_but_does_not_touch_the_file(tmp_path: Path) -> None:
    """The off switch is the whole basis for acting without asking, so it is tested as a
    behaviour rather than trusted as a flag: same broken card, `/janitor-autofix-off` set,
    file must come back byte-identical and the finding must still be REPORTED."""
    broken = BOM + "\n" + _GOOD
    card = _card(tmp_path, broken)
    out = _run_drift(tmp_path, autofix=False)
    assert card.read_text(encoding="utf-8") == broken, "autofix off must mean hands off"
    assert any("unreadable frontmatter" in ln for ln in out.splitlines()), (
        f"switching autofix off must not also switch off the REPORT: {out!r}"
    )


def test_e2e_a_card_with_a_real_line_above_the_block_is_reported_not_edited(
    tmp_path: Path,
) -> None:
    """The TRDD-WEBA1RMF shape, end to end. This is the case the lane must be trusted to
    leave alone even with autofix fully on — the line above the block is content, and the
    detector's job there is to say so, not to guess."""
    broken = "# A card\n" + _GOOD
    card = _card(tmp_path, broken)
    out = _run_drift(tmp_path, autofix=True)
    assert card.read_text(encoding="utf-8") == broken, "content must never be auto-edited"
    assert any("unreadable frontmatter" in ln for ln in out.splitlines()), (
        f"declining to fix must still report: {out!r}"
    )


# --------------------------------------------------------------------------- #
# the NOTIFY half — pre-existing, pinned so it cannot drift into a fixer
# --------------------------------------------------------------------------- #

def test_a_project_incident_cannot_be_opened_without_human_approval(tmp_path: Path) -> None:
    """"Always only notify" in code: the janitor may PROPOSE work in the user's own project
    but never authorize it. Without this the janitor becomes an uninvited contributor to
    every repo it is armed in — and it would do so silently, one ticket at a time."""
    project_kinds = [k for k, s in tickets.KIND_REGISTRY.items() if s.domain == tickets.PROJECT]
    assert project_kinds, "fixture assumption broken: no PROJECT-domain ticket kinds exist"
    for kind in project_kinds:
        ticket, msg = tickets.open_ticket(
            kind=kind, title="t", evidence=["e"], state_dir=tmp_path, trdd="",
        )
        assert ticket is None, f"{kind} opened without approval"
        assert "PROPOSE" in msg, f"{kind}: the refusal must say what to do instead — got {msg!r}"


def test_an_approved_trdd_is_what_unlocks_it(tmp_path: Path) -> None:
    """The counterpart, and what stops the test above from being vacuous: approval is a
    real, working path, not a wall. A gate nobody can pass gets removed."""
    kind = next(k for k, s in tickets.KIND_REGISTRY.items() if s.domain == tickets.PROJECT)
    ticket, msg = tickets.open_ticket(
        kind=kind, title="t", evidence=["e"], state_dir=tmp_path, trdd="ABCD1234",
    )
    assert ticket is not None, f"an approved TRDD must open the ticket: {msg}"
