"""The memory-dispatch claim (janitor#242) — the consumed flag the system never had.

The measured failure was not "the agent read a stale file"; it was that the file it was
told to trust could CHANGE while it worked, with nothing recording that anyone had taken
the assignment. These pin the properties that make that impossible.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import memory_dispatch_claim as mdc  # noqa: E402


def _dispatch(sd: Path, epoch: int, intervention: str, scope: str = "LOCAL") -> Path:
    p = sd / f"{mdc.PENDING_PREFIX}{epoch}-abcd1234.json"
    p.write_text(json.dumps({
        "marker": f"[janitor-memory-{intervention}]", "intervention": intervention,
        "scope": scope, "root": f"/tmp/{scope.lower()}/memory", "stamped_at": epoch,
        "dispatch_id": f"{epoch}-abcd1234",
    }), encoding="utf-8")
    return p


def test_claim_returns_the_oldest_dispatch_first(tmp_path):
    """Newest-first would starve the dispatch that has already waited longest."""
    _dispatch(tmp_path, 2000, "consolidate")
    _dispatch(tmp_path, 1000, "repair")
    got = mdc.claim_one(tmp_path)
    assert got is not None and got["intervention"] == "repair"


def test_a_claimed_dispatch_is_never_handed_out_twice(tmp_path):
    """One assignment, one agent. The second caller must get the OTHER dispatch, not a
    second copy of the first."""
    _dispatch(tmp_path, 1000, "repair")
    _dispatch(tmp_path, 2000, "consolidate")
    first, second, third = (mdc.claim_one(tmp_path) for _ in range(3))
    assert first is not None and first["intervention"] == "repair"
    assert second is not None and second["intervention"] == "consolidate"
    assert third is None


def test_concurrent_claimers_never_collide(tmp_path):
    """THE measured bug, inverted: two agents live at once. `os.rename` is the atomic
    primitive that makes exactly one of them the winner for each dispatch."""
    for i in range(8):
        _dispatch(tmp_path, 1000 + i, f"chore{i}")
    with ThreadPoolExecutor(max_workers=8) as pool:
        got = [f.result() for f in [pool.submit(mdc.claim_one, tmp_path) for _ in range(8)]]
    ids = [g["dispatch_id"] for g in got if g]
    assert len(ids) == 8, "every dispatch must be claimed"
    assert len(set(ids)) == 8, f"a dispatch was handed to two claimers: {ids}"


def test_an_in_flight_claim_cannot_be_repointed_by_a_later_dispatch(tmp_path):
    """The exact janitor#242 scenario: a repair is claimed, then a consolidate is dispatched
    to the same root 367s later. The repair's own record must be byte-identical afterwards."""
    _dispatch(tmp_path, 1000, "repair")
    claimed = mdc.claim_one(tmp_path)
    assert claimed is not None
    before = Path(claimed["claimed_path"]).read_bytes()
    _dispatch(tmp_path, 1367, "consolidate")
    (tmp_path / mdc.LEGACY_NAME).write_text(json.dumps({"intervention": "consolidate"}),
                                            encoding="utf-8")
    assert Path(claimed["claimed_path"]).read_bytes() == before
    assert json.loads(before)["intervention"] == "repair"


def test_no_dispatch_means_None_and_never_a_guess(tmp_path):
    """janitor#150: an agent that guesses runs a pass nobody scheduled on a scope nobody
    chose. Absence must stay absence."""
    assert mdc.claim_one(tmp_path) is None


def test_the_legacy_single_slot_is_not_a_fallback(tmp_path):
    """Consuming it would reintroduce the clobbering bug on the one path where it matters —
    when two dispatches overlap."""
    (tmp_path / mdc.LEGACY_NAME).write_text(
        json.dumps({"intervention": "consolidate", "scope": "LOCAL", "root": "/tmp/x"}),
        encoding="utf-8")
    assert mdc.claim_one(tmp_path) is None


def test_an_unreadable_record_is_skipped_not_consumed(tmp_path):
    """Renaming a corrupt file away would hide it from the orphan detector, turning a
    reportable fault into a silent one."""
    bad = tmp_path / f"{mdc.PENDING_PREFIX}1000-deadbeef.json"
    bad.write_text("{not json", encoding="utf-8")
    _dispatch(tmp_path, 2000, "repair")
    got = mdc.claim_one(tmp_path)
    assert got is not None and got["intervention"] == "repair"
    assert bad.is_file(), "the corrupt record must stay put for the orphan detector"


def test_claimed_records_are_pruned_too(tmp_path, monkeypatch):
    """A claim RENAMES the record out of the pending glob. Pruning only that glob would
    leak every claimed file forever into a directory nothing else sweeps — the kind of
    growth nobody notices until a state dir has ten thousand files in it."""
    sys.path.insert(0, str(_ROOT / "scripts" / "detectors"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mm", _ROOT / "scripts" / "detectors" / "memory-maintenance.py")
    assert spec is not None and spec.loader is not None
    mm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mm)
    monkeypatch.setattr(mm.state, "state_dir", lambda: tmp_path)
    for i in range(mm._PENDING_KEEP + 5):
        (tmp_path / f"{mm._CLAIMED_PREFIX}{1000 + i}-abcd1234.json").write_text("{}", encoding="utf-8")
    mm._prune_old_pending()
    left = list(tmp_path.glob(f"{mm._CLAIMED_PREFIX}*.json"))
    assert len(left) == mm._PENDING_KEEP, f"claimed records not capped: {len(left)}"
