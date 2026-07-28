"""The memgrep index-health detector's ledger channel (TRDD-CGYMUKO6).

The detector has two channels, and only one of them could ever have caught the incident that created
it. A corruption that is being RE-MANUFACTURED is invisible to state inspection, because memgrep's
self-heal races the observer and wins: whoever opens the index next repairs it, so the database is
always pristine by the time anyone looks. The self-heal LEDGER is the durable evidence, and these
tests cover reading it — including the ways a log we did not write can be malformed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

# The detector's filename is hyphenated (it is a script, not a module), so it is loaded by path.
_spec = importlib.util.spec_from_file_location("memgrep_index_health", ROOT / "scripts" / "detectors" / "memgrep-index-health.py")
assert _spec and _spec.loader
health = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(health)

NOW = 1_784_000_000


def _ledger(root: Path, lines: list[str]) -> Path:
    (root / ".memgrep").mkdir(parents=True, exist_ok=True)
    (root / ".memgrep" / "self-heal.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def test_no_ledger_means_no_heals(tmp_path: Path) -> None:
    """A healthy index heals nothing and records nothing. Absence is not a finding."""
    assert health.recent_heals(str(tmp_path), now=NOW) == []


def test_recent_heals_are_counted(tmp_path: Path) -> None:
    _ledger(tmp_path, [f"{NOW - 60} rebuild-fts [MEMGREP-001] corrupt", f"{NOW - 120} nuke-rebuild [MEMGREP-002] corrupt"])
    assert len(health.recent_heals(str(tmp_path), now=NOW)) == 2


def test_old_heals_fall_out_of_the_window(tmp_path: Path) -> None:
    """A corruption fixed months ago must not resurrect itself into today's ticket. The ledger is
    capped at 50 lines, so without a window an ancient entry would sit there forever, permanently
    holding the count one heal below the threshold — and one fresh heal would then fire a ticket
    about a defect that was fixed long ago."""
    _ledger(
        tmp_path,
        [
            f"{NOW - 100} rebuild-fts [MEMGREP-001] today",
            f"{NOW - 86400 - 60} rebuild-fts [MEMGREP-001] yesterday, just outside",
            f"{NOW - 86400 * 30} nuke-rebuild [MEMGREP-002] a month ago",
        ],
    )
    heals = health.recent_heals(str(tmp_path), now=NOW)
    assert len(heals) == 1
    assert "today" in heals[0]


def test_a_malformed_ledger_line_is_skipped_not_fatal(tmp_path: Path) -> None:
    """The ledger is written by another program (memgrep, in Rust). A truncated final line from a
    killed process, or a partially-written file, must never crash the heartbeat — losing one heal
    record is survivable; losing the fire is not."""
    _ledger(
        tmp_path,
        [
            "not-an-epoch rebuild-fts garbage",
            "",
            f"{NOW - 30} rebuild-fts [MEMGREP-001] a real one",
            "12",  # a torn write: an epoch with nothing after it
        ],
    )
    heals = health.recent_heals(str(tmp_path), now=NOW)
    assert len(heals) == 1
    assert "a real one" in heals[0]


@pytest.mark.parametrize("count,expected", [(0, False), (1, False), (2, True), (5, True)])
def test_one_heal_is_the_system_working_two_is_a_bug(tmp_path: Path, count: int, expected: bool) -> None:
    """The threshold that decides whether a repair is routine or a defect. ONE heal is the self-heal
    doing its job. TWO in a day means something keeps breaking the index, and repairing it a third
    time would just be participating in the loop instead of fixing the cause."""
    _ledger(tmp_path, [f"{NOW - 60 * i} rebuild-fts [MEMGREP-001] corrupt" for i in range(1, count + 1)] or ["# none"])
    heals = health.recent_heals(str(tmp_path), now=NOW)
    assert (len(heals) >= health._HEALS_BEFORE_TICKET) is expected


# --------------------------------------------------------------------------- #
# T-FATU6QPI — a CRITICAL ticket whose title was unreadable
# --------------------------------------------------------------------------- #


def test_shape_identifiers_lifts_the_table_and_column_out_of_a_real_message():
    """The exact message from the incident. The template's slots are IDENTIFIERS; the detector used
    to wedge this whole string into `table=` and pass `column=""`, producing a title reading
    ``a migration left `schema validation: `atoms` is missing…` without column ` ``."""
    msg = (
        "schema validation: `atoms` is missing column `status` "
        "(a migration failed to add it — recall on that column would silently return nothing)"
    )
    assert health.shape_identifiers(msg) == ("atoms", "status")


def test_shape_identifiers_handles_every_shape_message_memgrep_emits():
    """One message proving it is not enough — the detector sees whichever shape defect fires."""
    cases = {
        "schema validation: table `memories` is MISSING": ("memories", ""),
        "schema validation: FTS index `memories_fts` is MISSING": ("memories_fts", ""),
        "schema validation: FTS `atoms_fts` has no `keywords` column — it is STALE": (
            "atoms_fts",
            "keywords",
        ),
        "orphaned rows: `lessons` references memories that no longer exist": ("lessons", ""),
    }
    for msg, expected in cases.items():
        assert health.shape_identifiers(msg) == expected, msg


def test_an_unparsed_message_yields_EMPTY_not_the_whole_sentence():
    """The failure mode must be a LOUD empty field (which renders as `<?table?>`), never the
    sentence-in-a-noun-slot that produced the unreadable ticket."""
    assert health.shape_identifiers("something entirely unexpected happened") == ("", "")
    assert health.shape_identifiers("") == ("", "")
