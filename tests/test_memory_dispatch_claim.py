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


# --- the legacy single-slot mirror (janitor#264 part b) ---------------------------------


def _mirror(sd: Path, p: Path) -> None:
    """Mirror a per-dispatch record into the legacy single slot, byte-for-byte — exactly what
    the scheduler does (`memory-maintenance.py::_write_pending` writes the same `text` twice)."""
    (sd / mdc.LEGACY_NAME).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")


def test_claiming_retires_the_legacy_mirror_of_that_dispatch(tmp_path):
    """janitor#264(b): the mirror outlived every dispatch it described — reported still naming
    `intervention: atomize` AFTER that pass completed (3 pages atomized, report written, lint
    75 -> 35) — so a finished chore was indistinguishable from a pending one for anything
    reading the legacy path, which the installed heartbeat-protocol rule still names."""
    p = _dispatch(tmp_path, 1700000000, "atomize")
    _mirror(tmp_path, p)

    got = mdc.claim_one(tmp_path)

    assert got is not None and got["intervention"] == "atomize"
    assert not (tmp_path / mdc.LEGACY_NAME).exists(), (
        "the mirror describes a dispatch that has now been claimed — leaving it makes a "
        "completed chore look pending forever"
    )


def test_claiming_an_older_dispatch_leaves_a_newer_mirror_alone(tmp_path):
    """The mirror always holds the NEWEST dispatch while claims run OLDEST-first, so clearing
    it blindly would strand the newer assignment for every reader that only knows the legacy
    path. Matching on dispatch_id is what makes that impossible."""
    old = _dispatch(tmp_path, 1700000000, "atomize")
    new = _dispatch(tmp_path, 1700009999, "split")
    _mirror(tmp_path, new)  # the scheduler's mirror always describes the newest
    assert old.exists()

    got = mdc.claim_one(tmp_path)

    assert got is not None and got["intervention"] == "atomize", "oldest-first is unchanged"
    mirrored = json.loads((tmp_path / mdc.LEGACY_NAME).read_text(encoding="utf-8"))
    assert mirrored["intervention"] == "split", (
        "the mirror of a STILL-PENDING newer dispatch must survive an older claim"
    )


def test_retiring_the_mirror_did_not_make_it_claimable(tmp_path):
    """Retiring must not quietly turn the legacy slot into a fallback SOURCE. Its single-slot
    clobbering is the very bug per-dispatch records exist to fix (janitor#242), so a lone
    mirror is still handed to nobody — and still not deleted, since it names work that no
    per-dispatch record covers."""
    (tmp_path / mdc.LEGACY_NAME).write_text(
        json.dumps({"intervention": "repair", "scope": "LOCAL", "dispatch_id": "x"}),
        encoding="utf-8")

    assert mdc.claim_one(tmp_path) is None
    assert (tmp_path / mdc.LEGACY_NAME).exists()


# ---------------------------------------------------------------------------
# janitor#275 — the chore FILTER (root cause of #280 and #273)
#
# The claim was FIFO-by-age and chore-BLIND while every caller is chore-SPECIFIC:
# the heartbeat emits ONE marker and the agent it spawns loads that chore's skill.
# With a different chore at the queue head, that agent renamed an assignment it
# cannot perform out of the pool — orphaning the dispatch that WAS runnable and
# doing nothing useful itself. Measured live as a permanently wedged atomize
# dispatch (janitor#273).
# ---------------------------------------------------------------------------


def test_a_chore_filtered_claim_skips_another_chores_dispatch(tmp_path):
    """THE BUG: the queue HEAD belongs to another chore. It must be left alone, and the
    matching (younger) dispatch claimed instead — the opposite of FIFO."""
    _dispatch(tmp_path, 100, "atomize")
    _dispatch(tmp_path, 200, "consolidate")
    got = mdc.claim_one(tmp_path, "consolidate")
    assert got is not None, "a matching dispatch existed and must be claimed"
    assert got["intervention"] == "consolidate"


def test_the_skipped_dispatch_stays_claimable_by_ITS_own_chore(tmp_path):
    """The orphaning half: after the mismatched agent ran, the older dispatch must still be
    there for the agent that can actually perform it. Before the filter it had been renamed
    out of the pool and was unreachable forever."""
    _dispatch(tmp_path, 100, "atomize")
    _dispatch(tmp_path, 200, "consolidate")
    mdc.claim_one(tmp_path, "consolidate")
    still = mdc.claim_one(tmp_path, "atomize")
    assert still is not None, "the other chore's dispatch was consumed — this is janitor#273"
    assert still["intervention"] == "atomize"


def test_no_matching_chore_claims_NOTHING_rather_than_the_wrong_thing(tmp_path):
    """An agent with no work must abstain. Returning someone else's dispatch is strictly
    worse than returning None: the skill's exit-2 path reports honestly, while a wrong
    payload sends it to edit a scope nobody asked it to touch."""
    _dispatch(tmp_path, 100, "atomize")
    assert mdc.claim_one(tmp_path, "consolidate") is None
    assert mdc.claim_one(tmp_path, "atomize") is not None, "the atomize dispatch must survive"


def test_an_empty_chore_keeps_the_historical_chore_blind_behaviour(tmp_path):
    """Back-compat, deliberately: an installed skill that predates the flag must keep
    working rather than silently start claiming nothing. A filtered claim is strictly
    narrower, so it can never consume what the unfiltered one would have left."""
    _dispatch(tmp_path, 100, "atomize")
    got = mdc.claim_one(tmp_path, "")
    assert got is not None and got["intervention"] == "atomize"


def test_every_memory_skill_passes_its_own_chore(tmp_path):
    """Pinned over the SHIPPED skills: the filter only helps if the callers use it, and a
    skill that forgets the flag silently reverts to the chore-blind bug for its chore."""
    root = Path(__file__).resolve().parents[1] / "skills"
    missing = []
    for chore in ("consolidate", "split", "repair", "atomize",
                  "retro-lesson", "conflict", "harvest"):
        text = (root / f"janitor-memory-{chore}" / "SKILL.md").read_text(encoding="utf-8")
        if "memory_dispatch_claim.py" in text and f"--chore {chore}" not in text:
            missing.append(chore)
    assert not missing, f"these skills claim without naming their chore: {missing}"
