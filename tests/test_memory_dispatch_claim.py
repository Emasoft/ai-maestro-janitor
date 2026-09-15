"""The memory-dispatch claim (janitor#242) — the consumed flag the system never had.

The measured failure was not "the agent read a stale file"; it was that the file it was
told to trust could CHANGE while it worked, with nothing recording that anyone had taken
the assignment. These pin the properties that make that impossible.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
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


def _claimed(sd: Path, epoch: int, intervention: str, scope: str = "LOCAL") -> Path:
    """A CLAIMED (not pending) per-dispatch record, for `expire_stale_claims` tests."""
    p = sd / f"{mdc.CLAIMED_PREFIX}{epoch}-abcd1234.json"
    p.write_text(json.dumps({
        "marker": f"[janitor-memory-{intervention}]", "intervention": intervention,
        "scope": scope, "root": f"/tmp/{scope.lower()}/memory", "stamped_at": epoch,
        "dispatch_id": f"{epoch}-abcd1234",
    }), encoding="utf-8")
    return p


def test_claim_returns_the_oldest_dispatch_first(tmp_path):
    """Newest-first would starve the dispatch that has already waited longest."""
    _dispatch(tmp_path, 2000, "repair")
    _dispatch(tmp_path, 1000, "repair")
    got = mdc.claim_one(tmp_path, "repair")
    assert got is not None and got["dispatch_id"] == "1000-abcd1234"


def test_a_claimed_dispatch_is_never_handed_out_twice(tmp_path):
    """One assignment, one agent. The second caller must get the OTHER dispatch, not a
    second copy of the first."""
    _dispatch(tmp_path, 1000, "repair")
    _dispatch(tmp_path, 2000, "repair")
    first, second, third = (mdc.claim_one(tmp_path, "repair") for _ in range(3))
    assert first is not None and first["dispatch_id"] == "1000-abcd1234"
    assert second is not None and second["dispatch_id"] == "2000-abcd1234"
    assert third is None


def test_concurrent_claimers_never_collide(tmp_path):
    """THE measured bug, inverted: two agents live at once. `os.rename` is the atomic
    primitive that makes exactly one of them the winner for each dispatch."""
    for i in range(8):
        _dispatch(tmp_path, 1000 + i, f"chore{i}")
    with ThreadPoolExecutor(max_workers=8) as pool:
        got = [f.result() for f in [
            pool.submit(mdc.claim_one, tmp_path, f"chore{i}") for i in range(8)
        ]]
    ids = [g["dispatch_id"] for g in got if g]
    assert len(ids) == 8, "every dispatch must be claimed"
    assert len(set(ids)) == 8, f"a dispatch was handed to two claimers: {ids}"


def test_an_in_flight_claim_cannot_be_repointed_by_a_later_dispatch(tmp_path):
    """The exact janitor#242 scenario: a repair is claimed, then a consolidate is dispatched
    to the same root 367s later. The repair's own record must be byte-identical afterwards."""
    _dispatch(tmp_path, 1000, "repair")
    claimed = mdc.claim_one(tmp_path, "repair")
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
    assert mdc.claim_one(tmp_path, "repair") is None


def test_the_legacy_single_slot_is_not_a_fallback(tmp_path):
    """Consuming it would reintroduce the clobbering bug on the one path where it matters —
    when two dispatches overlap."""
    (tmp_path / mdc.LEGACY_NAME).write_text(
        json.dumps({"intervention": "consolidate", "scope": "LOCAL", "root": "/tmp/x"}),
        encoding="utf-8")
    assert mdc.claim_one(tmp_path, "consolidate") is None


def test_an_unreadable_record_is_skipped_not_consumed(tmp_path):
    """Renaming a corrupt file away would hide it from the orphan detector, turning a
    reportable fault into a silent one."""
    bad = tmp_path / f"{mdc.PENDING_PREFIX}1000-deadbeef.json"
    bad.write_text("{not json", encoding="utf-8")
    _dispatch(tmp_path, 2000, "repair")
    got = mdc.claim_one(tmp_path, "repair")
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

    got = mdc.claim_one(tmp_path, "atomize")

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

    got = mdc.claim_one(tmp_path, "atomize")

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

    assert mdc.claim_one(tmp_path, "repair") is None
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


def test_an_empty_chore_matches_nothing_now(tmp_path):
    """The chore-blind FIFO fallback is gone: a `[janitor-memory-split]` fire once
    claimed a queued `consolidate` record this way and burned 236k tokens (2026-09-15
    fleet audit). An empty chore must claim NOTHING, never fall back to FIFO."""
    _dispatch(tmp_path, 100, "atomize")
    got = mdc.claim_one(tmp_path, "")
    assert got is None
    assert mdc.claim_one(tmp_path, "atomize") is not None, "the record must still be there"


def test_is_claimable_true_for_a_freshly_written_matching_dispatch(tmp_path):
    """TRDD-LDSCQ0NU: the scheduler's write-then-verify gate must see its own write
    as claimable — this is the non-empty-pool path the acceptance criteria require
    to stay unaffected."""
    p = _dispatch(tmp_path, 100, "split")
    dispatch_id = p.name[len(mdc.PENDING_PREFIX):-len(".json")]
    assert mdc.is_claimable(tmp_path, dispatch_id, "split") is True


def test_is_claimable_false_for_a_missing_dispatch_id(tmp_path):
    """The empty-claim-pool case (janitor#300): no record on disk at all — the
    scheduler must be able to detect this and suppress its own marker."""
    assert mdc.is_claimable(tmp_path, "999-doesnotexist", "split") is False


def test_is_claimable_false_on_chore_mismatch(tmp_path):
    """A record exists but for a different chore — not claimable BY this chore's
    agent, so the marker naming this chore must not be printed either."""
    p = _dispatch(tmp_path, 100, "consolidate")
    dispatch_id = p.name[len(mdc.PENDING_PREFIX):-len(".json")]
    assert mdc.is_claimable(tmp_path, dispatch_id, "split") is False


def test_is_claimable_never_renames_the_record(tmp_path):
    """Read-only, by contract: a verification check must never itself consume the
    dispatch it is only supposed to be looking at."""
    p = _dispatch(tmp_path, 100, "atomize")
    dispatch_id = p.name[len(mdc.PENDING_PREFIX):-len(".json")]
    mdc.is_claimable(tmp_path, dispatch_id, "atomize")
    assert p.exists(), "is_claimable must not rename the pending record"
    got = mdc.claim_one(tmp_path, "atomize")
    assert got is not None, "the record must still be claimable by a real claim afterwards"


# ---------------------------------------------------------------------------
# TRDD-Q7X4M2KP — the scheduler's supersede-rename can win the race against a
# peer's `claim_one`: it reads the payload fine, then loses ITS OWN rename
# because the scheduler already renamed the file out from under it. The
# `except OSError: continue` guarding that rename must swallow the loss and
# move on to the next candidate rather than raise.
# ---------------------------------------------------------------------------


def test_claim_one_skips_a_record_superseded_under_it(tmp_path, monkeypatch):
    """A stale record is renamed away (simulating the scheduler's supersede)
    exactly when `claim_one` tries to claim it — `claim_one` must not raise, and
    must fall through to the next (still-pending) candidate instead."""
    stale = _dispatch(tmp_path, 100, "split")
    _dispatch(tmp_path, 200, "split")

    real_rename = os.rename

    def _flaky_rename(src, dst):
        if Path(src) == stale:
            raise OSError("simulated: superseded out from under the claim")
        return real_rename(src, dst)

    monkeypatch.setattr(os, "rename", _flaky_rename)

    got = mdc.claim_one(tmp_path, "split")

    assert got is not None, "claim_one must not raise on the lost race"
    assert got["dispatch_id"] == "200-abcd1234", "must fall through to the next candidate"
    assert stale.is_file(), "the superseded-away record was never actually renamed by claim_one"


# ---------------------------------------------------------------------------
# TRDD-N1CPV1QV — the claim script must be told the scheduler's actual state
# dir, not resolve one of its own from cwd. Parts (c)/(d)/(e).
# ---------------------------------------------------------------------------

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "memory_dispatch_claim.py"


def _run_cli(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, env=full_env,
    )


def test_rejects_empty_state_dir_argument():
    """An EXPLICITLY empty --state-dir must be a distinct error, never a silent
    fallback to cwd resolution (part (c))."""
    proc = _run_cli(["--chore", "repair", "--state-dir", ""])
    assert proc.returncode == 4, proc.stderr
    assert "empty" in proc.stderr


def test_refuses_when_state_dir_unresolved_and_no_pool(tmp_path):
    """No --state-dir given AND the cwd-resolved directory holds zero
    `memory-maint-*` files of either kind gets its OWN exit code, distinct from
    the ordinary 'nothing claimable' exit 2 (part (d))."""
    proc = _run_cli(["--chore", "repair"], env={"CLAUDE_PROJECT_DIR": str(tmp_path)})
    assert proc.returncode == 3, proc.stderr
    assert "no memory-maintenance state at all" in proc.stderr


def test_explicit_state_dir_with_no_pool_also_exits_3(tmp_path):
    """The same empty directory, reached via an EXPLICIT --state-dir, must ALSO
    exit 3 (part (e)) — a scheduler always writes its record before emitting the
    marker, so a state dir with zero memory-maint-* files is wrong however it was
    obtained. Previously this silently returned the ordinary 'nothing claimable'
    exit 2, which is exactly the code a verbatim-placeholder --state-dir produced
    (TRDD-N1CPV1QV part (e)) — a wrong path must never look like a correct abstain."""
    proc = _run_cli(["--chore", "repair", "--state-dir", str(tmp_path)])
    assert proc.returncode == 3, proc.stderr
    assert "--state-dir given" in proc.stderr


def test_explicit_placeholder_like_state_dir_exits_3_not_2():
    """A skill that pasted its literal spawn-prompt placeholder verbatim as
    --state-dir must exit 3, not the 'nothing claimable' exit 2 every skill
    treats as a correct abstain."""
    placeholder = "<the absolute path from the STATE_DIR=<path> line of your spawn prompt>"
    proc = _run_cli(["--chore", "repair", "--state-dir", placeholder])
    assert proc.returncode == 3, proc.stderr
    assert "--state-dir given" in proc.stderr


def test_claim_with_empty_chore_exits_2():
    """An empty --chore must be refused (argparse `choices=CHORES`) before any
    state-dir work runs — no chore-blind fallback from the CLI either."""
    proc = _run_cli(["--chore", ""])
    assert proc.returncode == 2, proc.stderr


def test_claim_with_a_chore_that_has_no_pending_record_hands_out_nothing(tmp_path):
    """A chore with no matching record must abstain even while another chore's
    dispatch sits right there in the same pool — never the wrong thing."""
    _dispatch(tmp_path, 100, "atomize")
    proc = _run_cli(["--chore", "consolidate", "--state-dir", str(tmp_path)])
    assert proc.returncode == 2, proc.stderr
    assert "no claimable memory-maintenance dispatch" in proc.stderr


def test_claim_one_refuses_a_foreign_state_dir(tmp_path):
    """A dispatch record whose payload `state_dir` names a DIFFERENT directory than
    the one the claim step was actually invoked on must be refused — distinct
    exception, record left untouched and still pending (part (e))."""
    foreign = _dispatch(tmp_path, 100, "split")
    payload = json.loads(foreign.read_text(encoding="utf-8"))
    payload["state_dir"] = "/some/other/project/.janitor/state"
    foreign.write_text(json.dumps(payload), encoding="utf-8")

    expected = tmp_path.resolve()
    try:
        mdc.claim_one(tmp_path, "split", expected_state_dir=expected)
        raised = False
    except mdc.StateDirMismatch:
        raised = True
    assert raised, "a foreign state_dir must raise StateDirMismatch, not silently skip"
    assert foreign.is_file(), "the mismatched record must be left untouched, still pending"


def test_claim_one_accepts_state_dir_through_a_symlink(tmp_path):
    """The comparison is normalised via `Path.resolve()` on both sides, so a claim
    invoked through a SYMLINKED pool directory still succeeds."""
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    _dispatch(real_dir, 100, "split")
    for p in real_dir.glob(f"{mdc.PENDING_PREFIX}*.json"):
        payload = json.loads(p.read_text(encoding="utf-8"))
        payload["state_dir"] = str(real_dir.resolve())
        p.write_text(json.dumps(payload), encoding="utf-8")

    link_dir = tmp_path / "link"
    link_dir.symlink_to(real_dir)

    got = mdc.claim_one(link_dir, "split", expected_state_dir=link_dir.resolve())
    assert got is not None, "a symlinked pool directory must still claim successfully"


def test_claim_one_accepts_a_record_with_no_state_dir_field(tmp_path):
    """An older-version payload with no `state_dir` field at all is a version gap,
    not evidence of a wrong directory — accepted, never refused."""
    _dispatch(tmp_path, 100, "split")  # helper never sets state_dir
    got = mdc.claim_one(tmp_path, "split", expected_state_dir=tmp_path.resolve())
    assert got is not None, "a missing state_dir field must never refuse the claim"


# ---------------------------------------------------------------------------
# `expire_stale_claims` (janitor#242, 2026-09-15 fleet audit + adversarial review):
# a claim has no "consumed" flag once its agent dies, so age alone must never be
# proof of death — a real pass can legitimately hold a claim past its own cadence.
# ---------------------------------------------------------------------------


def _fixed_cadence(monkeypatch, seconds: float = 100.0) -> None:
    """Pin every chore's cadence to a small fixed value so the 6h floor is what
    actually governs — deterministic regardless of this host's real memory-settings
    (a fresh checkout defaults `repair_per_day` to 1/day = 86400s, which would make
    these tests pass or fail depending on whatever settings the running machine has)."""
    monkeypatch.setattr(mdc.memory_settings, "interval_s_for", lambda chore: seconds)


def test_expire_stale_claims_leaves_a_young_claim_alone(tmp_path, monkeypatch):
    """Younger than the 6h floor (`_STALE_CLAIM_FLOOR_S`) must never be touched,
    however short its own chore's cadence."""
    _fixed_cadence(monkeypatch)
    p = _claimed(tmp_path, 1_000_000, "repair")
    acted = mdc.expire_stale_claims(tmp_path, now=1_000_000 + 500, max_age_s=0)
    assert acted == []
    assert p.is_file()


def test_expire_stale_claims_expires_a_dead_claim_with_no_report(tmp_path, monkeypatch):
    """Past the floor with no finishing report on disk: the owning agent is presumed
    dead — renamed to memory-maint-expired-<id>.json so the next scheduler pass can
    re-dispatch it."""
    _fixed_cadence(monkeypatch)
    epoch = 1_000_000
    p = _claimed(tmp_path, epoch, "repair")
    dispatch_id = p.name[len(mdc.CLAIMED_PREFIX):-len(".json")]

    acted = mdc.expire_stale_claims(tmp_path, now=epoch + 30_000, max_age_s=0)

    assert len(acted) == 1
    assert acted[0]["status"] == "expired" and acted[0]["dispatch_id"] == dispatch_id
    assert not p.exists()
    assert (tmp_path / f"{mdc.EXPIRED_PREFIX}{dispatch_id}.json").is_file()


def test_expire_stale_claims_never_looks_at_reports_anymore(tmp_path, monkeypatch):
    """janitor#242 adversarial review: a finishing report used to be read as proof of
    completion, but the correlation was by filename coincidence, not a primary key — a
    split report's `<ts>-split-<scope>-<page-slug>.md` shape never matches it, a manual
    run writes the identical shape as a scheduled one, and the scope's case can differ.
    A report on disk (however plausible) must no longer mark a claim DONE — only an
    explicit `complete_claim` by dispatch_id does that now."""
    _fixed_cadence(monkeypatch)
    project = tmp_path / "project"
    state_dir = project / ".janitor" / "state"
    state_dir.mkdir(parents=True)
    epoch = 1_000_000
    p = _claimed(state_dir, epoch, "repair")
    dispatch_id = p.name[len(mdc.CLAIMED_PREFIX):-len(".json")]
    reports_dir = project / "reports" / "janitor-memory-subconscious-agent"
    reports_dir.mkdir(parents=True)
    ts = datetime.fromtimestamp(epoch + 100, tz=timezone.utc).strftime("%Y%m%d_%H%M%S+0000")
    (reports_dir / f"{ts}-repair-local.md").write_text("done", encoding="utf-8")

    acted = mdc.expire_stale_claims(state_dir, now=epoch + 30_000, max_age_s=0)

    assert len(acted) == 1
    assert acted[0]["status"] == "expired" and acted[0]["dispatch_id"] == dispatch_id
    assert (state_dir / f"{mdc.EXPIRED_PREFIX}{dispatch_id}.json").is_file()


def test_expire_stale_claims_local_cadence_faster_than_floor_still_waits_for_floor(tmp_path, monkeypatch):
    """LOCAL cadence 4h, factor 1 (`cadence_threshold` = 4h) → the record must still
    survive to the 6h `_STALE_CLAIM_FLOOR_S`, not expire at 4h — the floor is a HARD
    MINIMUM regardless of how fast the record's own chore cadence is."""
    monkeypatch.setattr(mdc.memory_settings, "interval_s_for", lambda chore: 4 * 3600)
    epoch = 1_000_000
    p = _claimed(tmp_path, epoch, "repair", scope="LOCAL")
    dispatch_id = p.name[len(mdc.CLAIMED_PREFIX):-len(".json")]

    just_past_cadence = mdc.expire_stale_claims(tmp_path, now=epoch + 5 * 3600, max_age_s=0)
    assert just_past_cadence == [], "must not expire at 5h — before the 6h floor"
    assert p.is_file()

    past_floor = mdc.expire_stale_claims(tmp_path, now=epoch + 6 * 3600 + 1, max_age_s=0)
    assert len(past_floor) == 1 and past_floor[0]["dispatch_id"] == dispatch_id
    assert not p.exists()


def test_complete_claim_renames_claimed_to_done_with_report(tmp_path):
    """The primary-key check-in: a claimed record becomes a done one, carrying the
    report path and a completion timestamp — the only way a claim is now marked finished."""
    p = _claimed(tmp_path, 1_000_000, "repair")
    dispatch_id = p.name[len(mdc.CLAIMED_PREFIX):-len(".json")]

    assert mdc.complete_claim(tmp_path, dispatch_id, "/tmp/report.md", now=1_000_500) is True

    assert not p.exists()
    done = tmp_path / f"{mdc.DONE_PREFIX}{dispatch_id}.json"
    assert done.is_file()
    payload = json.loads(done.read_text(encoding="utf-8"))
    assert payload["report"] == "/tmp/report.md"
    assert payload["completed_at"] == 1_000_500
    assert "outcome" not in payload


def test_complete_claim_normalizes_relative_report_against_cwd(tmp_path, monkeypatch):
    """A relative report path is stored resolved against the cwd at complete time —
    MEMPASS-REPORT-MISSING checks this path from any project's cwd, so a relative
    path recorded by a curator with a different cwd would resolve against the wrong
    project (review 2026-09-15)."""
    p = _claimed(tmp_path, 1_000_000, "repair")
    dispatch_id = p.name[len(mdc.CLAIMED_PREFIX):-len(".json")]
    other_cwd = tmp_path / "cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    assert mdc.complete_claim(tmp_path, dispatch_id, "reports/x.md") is True

    done = tmp_path / f"{mdc.DONE_PREFIX}{dispatch_id}.json"
    payload = json.loads(done.read_text(encoding="utf-8"))
    assert payload["report"] == str(other_cwd / "reports" / "x.md")


def test_complete_claim_expands_home_in_report_path(tmp_path, monkeypatch):
    """A `~`-prefixed report path is expanded to an absolute home-relative path."""
    p = _claimed(tmp_path, 1_000_000, "repair")
    dispatch_id = p.name[len(mdc.CLAIMED_PREFIX):-len(".json")]
    monkeypatch.setenv("HOME", str(tmp_path))

    assert mdc.complete_claim(tmp_path, dispatch_id, "~/x/report.md") is True

    done = tmp_path / f"{mdc.DONE_PREFIX}{dispatch_id}.json"
    payload = json.loads(done.read_text(encoding="utf-8"))
    assert payload["report"] == str(tmp_path / "x" / "report.md")


def test_complete_claim_empty_report_stays_empty(tmp_path):
    """An empty report string is stored as-is, unchanged — the orphan detector's own
    missing-report check is what should flag it, not a resolved cwd path."""
    p = _claimed(tmp_path, 1_000_000, "repair")
    dispatch_id = p.name[len(mdc.CLAIMED_PREFIX):-len(".json")]

    assert mdc.complete_claim(tmp_path, dispatch_id, "") is True

    done = tmp_path / f"{mdc.DONE_PREFIX}{dispatch_id}.json"
    payload = json.loads(done.read_text(encoding="utf-8"))
    assert payload["report"] == ""


def test_complete_claim_unknown_id_returns_false(tmp_path):
    """A dispatch_id naming neither a claimed nor a done record is unknown — the CLI
    must exit non-zero rather than silently succeed."""
    assert mdc.complete_claim(tmp_path, "999-doesnotexist", "/tmp/report.md") is False


def test_complete_claim_is_idempotent(tmp_path):
    """Completing an already-done id twice must succeed both times — a retry after a
    lost reply, or a duplicate `complete` call, is not an error."""
    p = _claimed(tmp_path, 1_000_000, "repair")
    dispatch_id = p.name[len(mdc.CLAIMED_PREFIX):-len(".json")]
    assert mdc.complete_claim(tmp_path, dispatch_id, "/tmp/report.md") is True
    assert mdc.complete_claim(tmp_path, dispatch_id, "/tmp/report.md") is True


def test_complete_cli_prints_claim_id_last_and_completes(tmp_path):
    """End-to-end: a real claim prints CLAIM_ID=<id> as the LAST stdout line (so a
    positional reader of the earlier lines is unaffected), and the `complete`
    subcommand (given that id + the report path) renames the record DONE."""
    _dispatch(tmp_path, 1_000_000, "repair")
    proc = _run_cli(["--chore", "repair", "--state-dir", str(tmp_path)])
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln]
    assert lines[-1].startswith("CLAIM_ID="), proc.stdout
    dispatch_id = lines[-1].split("=", 1)[1]
    assert dispatch_id == "1000000-abcd1234"

    report = tmp_path / "report.md"
    report.write_text("pass notes\n<!-- janitor-outcome: noop reason=no-work -->\n", encoding="utf-8")
    proc2 = _run_cli(["complete", dispatch_id, "--state-dir", str(tmp_path), "--report", str(report)])
    assert proc2.returncode == 0, proc2.stderr
    done = tmp_path / f"{mdc.DONE_PREFIX}{dispatch_id}.json"
    assert done.is_file()
    payload = json.loads(done.read_text(encoding="utf-8"))
    assert payload["report"] == str(report)
    assert "outcome" not in payload


def test_complete_cli_unreadable_report_still_closes_the_claim(tmp_path):
    """A typo'd/missing `--report` path is evidence about the report, not about whether
    the pass ran — refusing to close the claim would leave it open until the 6h expiry
    and re-dispatch a pass that already finished. The claim closes; only the stderr
    line marks the report as unreadable."""
    p = _claimed(tmp_path, 1_000_000, "repair")
    dispatch_id = p.name[len(mdc.CLAIMED_PREFIX):-len(".json")]
    missing_report = tmp_path / "does-not-exist.md"

    proc = _run_cli(["complete", dispatch_id, "--state-dir", str(tmp_path),
                      "--report", str(missing_report)])

    assert proc.returncode == 0, proc.stderr
    assert f"report unreadable ({missing_report})" in proc.stderr
    assert "closed as unknown" in proc.stderr
    done = tmp_path / f"{mdc.DONE_PREFIX}{dispatch_id}.json"
    assert done.is_file()
    payload = json.loads(done.read_text(encoding="utf-8"))
    assert payload["report"] == str(missing_report)
    assert not p.exists()


def test_complete_cli_unknown_id_exits_nonzero(tmp_path):
    """The CLI surface of the unknown-id case must also fail loudly, not silently."""
    report = tmp_path / "report.md"
    report.write_text("<!-- janitor-outcome: noop reason=no-work -->\n", encoding="utf-8")
    proc = _run_cli(["complete", "999-doesnotexist", "--state-dir", str(tmp_path), "--report", str(report)])
    assert proc.returncode == 2, proc.stderr


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


# ---------------------------------------------------------------------------
# File-backed claim/report handoff (2026-09-15 addendum): shell variables set in one
# Bash tool call do not survive into a later one, so `claim_one` and `complete` fall
# back to disk when the id/report argument is omitted.
# ---------------------------------------------------------------------------

def test_claim_one_writes_keyed_current_claim_file(tmp_path):
    """A successful claim drops its id into a chore+scope-KEYED file, so a later
    argument-less `complete` in a fresh shell can still find it — and a second curator
    claiming a DIFFERENT chore/scope gets its own file, never this one's."""
    _dispatch(tmp_path, 1_000_000, "repair", scope="LOCAL")
    got = mdc.claim_one(tmp_path, "repair")
    assert got is not None
    claim_file = tmp_path / mdc._current_claim_filename("repair", "LOCAL")
    assert claim_file.read_text(encoding="utf-8") == got["dispatch_id"]


def test_set_report_writes_resolved_path_keyed_by_chore_scope(tmp_path, monkeypatch):
    """`set-report` resolves and stores the path the same way `complete_claim` would,
    under the chore+scope-keyed filename."""
    other_cwd = tmp_path / "cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    rc = mdc._run_set_report(
        ["reports/x.md", "--state-dir", str(tmp_path), "--chore", "repair", "--scope", "LOCAL"]
    )
    assert rc == 0
    stored = (tmp_path / mdc._current_report_filename("repair", "LOCAL")).read_text(encoding="utf-8")
    assert stored == str(other_cwd / "reports" / "x.md")


def test_complete_falls_back_to_the_single_in_flight_claim_file(tmp_path):
    """Exactly ONE keyed current-claim file on disk -> `complete --state-dir <dir>` alone
    finds it unambiguously, no --chore/--scope needed."""
    p = _claimed(tmp_path, 1_000_000, "repair", scope="LOCAL")
    dispatch_id = p.name[len(mdc.CLAIMED_PREFIX):-len(".json")]
    (tmp_path / mdc._current_claim_filename("repair", "LOCAL")).write_text(
        dispatch_id, encoding="utf-8"
    )
    report = tmp_path / "report.md"
    report.write_text("notes\n", encoding="utf-8")

    rc = mdc._run_complete(["--state-dir", str(tmp_path), "--report", str(report)])

    assert rc == 0
    done = tmp_path / f"{mdc.DONE_PREFIX}{dispatch_id}.json"
    assert done.is_file()


def test_complete_with_no_id_and_no_current_claim_file_exits_2(tmp_path):
    """No dispatch_id given and no keyed current-claim file on disk -> a clear exit 2,
    not a silent no-op or a crash."""
    rc = mdc._run_complete(["--state-dir", str(tmp_path)])
    assert rc == 2


def test_complete_with_two_in_flight_claims_requires_chore_and_scope(tmp_path):
    """TWO curators in flight on the same state_dir (different chore/scope) -> an
    argument-less `complete` refuses ambiguity with exit 2 and a listing, rather than
    guessing and closing the WRONG one's claim."""
    p1 = _claimed(tmp_path, 1_000_000, "repair", scope="LOCAL")
    id1 = p1.name[len(mdc.CLAIMED_PREFIX):-len(".json")]
    p2 = _claimed(tmp_path, 1_000_001, "atomize", scope="PROJECT")
    id2 = p2.name[len(mdc.CLAIMED_PREFIX):-len(".json")]
    (tmp_path / mdc._current_claim_filename("repair", "LOCAL")).write_text(id1, encoding="utf-8")
    (tmp_path / mdc._current_claim_filename("atomize", "PROJECT")).write_text(id2, encoding="utf-8")

    proc = _run_cli(["complete", "--state-dir", str(tmp_path)])
    assert proc.returncode == 2
    assert "multiple in-flight claims" in proc.stderr

    rc = mdc._run_complete(
        ["--state-dir", str(tmp_path), "--chore", "atomize", "--scope", "PROJECT"]
    )
    assert rc == 0
    assert (tmp_path / f"{mdc.DONE_PREFIX}{id2}.json").is_file()
    assert not (tmp_path / f"{mdc.DONE_PREFIX}{id1}.json").is_file()


def test_complete_falls_back_to_current_report_file_via_claimed_record(tmp_path):
    """No `--report` given, and dispatch_id given EXPLICITLY (no --chore/--scope) ->
    chore+scope are derived from the CLAIMED record itself to find the keyed report
    file (written by `set-report`)."""
    p = _claimed(tmp_path, 1_000_000, "repair", scope="LOCAL")
    dispatch_id = p.name[len(mdc.CLAIMED_PREFIX):-len(".json")]
    report = tmp_path / "report.md"
    report.write_text("notes\n", encoding="utf-8")
    (tmp_path / mdc._current_report_filename("repair", "LOCAL")).write_text(
        str(report), encoding="utf-8"
    )

    rc = mdc._run_complete([dispatch_id, "--state-dir", str(tmp_path)])

    assert rc == 0
    done = tmp_path / f"{mdc.DONE_PREFIX}{dispatch_id}.json"
    payload = json.loads(done.read_text(encoding="utf-8"))
    assert payload["report"] == str(report)


def test_complete_with_no_report_and_no_current_report_file_closes_as_empty(tmp_path):
    """No `--report` given and no keyed current-report file on disk -> the claim still
    closes, with an empty report string (same as an explicit empty `--report`)."""
    p = _claimed(tmp_path, 1_000_000, "repair", scope="LOCAL")
    dispatch_id = p.name[len(mdc.CLAIMED_PREFIX):-len(".json")]

    rc = mdc._run_complete([dispatch_id, "--state-dir", str(tmp_path)])

    assert rc == 0
    done = tmp_path / f"{mdc.DONE_PREFIX}{dispatch_id}.json"
    payload = json.loads(done.read_text(encoding="utf-8"))
    assert payload["report"] == ""


def test_complete_explicit_args_still_override_the_files(tmp_path):
    """Explicit dispatch_id + --report win over whatever is sitting in the keyed
    current-* files — the fallback is only for when the argument is omitted."""
    p = _claimed(tmp_path, 1_000_000, "repair", scope="LOCAL")
    dispatch_id = p.name[len(mdc.CLAIMED_PREFIX):-len(".json")]
    (tmp_path / mdc._current_claim_filename("repair", "LOCAL")).write_text(
        "wrong-id", encoding="utf-8"
    )
    (tmp_path / mdc._current_report_filename("repair", "LOCAL")).write_text(
        "/wrong/report.md", encoding="utf-8"
    )
    report = tmp_path / "report.md"
    report.write_text("notes\n", encoding="utf-8")

    rc = mdc._run_complete([dispatch_id, "--state-dir", str(tmp_path), "--report", str(report)])

    assert rc == 0
    done = tmp_path / f"{mdc.DONE_PREFIX}{dispatch_id}.json"
    payload = json.loads(done.read_text(encoding="utf-8"))
    assert payload["report"] == str(report)


def test_complete_claim_removes_its_own_keyed_files_on_success(tmp_path):
    """Cleanup on completion (2026-09-15 review): a stale keyed file left forever means
    every chore+scope pair ever claimed permanently blocks the 'exactly one in-flight
    claim' fast path — `complete_claim` must remove the marker it owns once done."""
    p = _claimed(tmp_path, 1_000_000, "repair", scope="LOCAL")
    dispatch_id = p.name[len(mdc.CLAIMED_PREFIX):-len(".json")]
    claim_marker = tmp_path / mdc._current_claim_filename("repair", "LOCAL")
    report_marker = tmp_path / mdc._current_report_filename("repair", "LOCAL")
    claim_marker.write_text(dispatch_id, encoding="utf-8")
    report_marker.write_text("/tmp/x.md", encoding="utf-8")

    assert mdc.complete_claim(tmp_path, dispatch_id, "/tmp/x.md") is True

    assert not claim_marker.exists()
    assert not report_marker.exists()


def test_complete_claim_leaves_a_newer_same_key_marker_alone(tmp_path):
    """If a SECOND claim of the same chore+scope overwrote the marker with its OWN
    (newer) dispatch_id before the first one completes, the first one's cleanup must
    NOT delete the newer claim's still-live pointer."""
    p1 = _claimed(tmp_path, 1_000_000, "repair", scope="LOCAL")
    id1 = p1.name[len(mdc.CLAIMED_PREFIX):-len(".json")]
    claim_marker = tmp_path / mdc._current_claim_filename("repair", "LOCAL")
    claim_marker.write_text(id1, encoding="utf-8")
    # A second, newer claim of the SAME chore+scope overwrites the marker.
    newer_id = "1000005-newer99"
    claim_marker.write_text(newer_id, encoding="utf-8")

    assert mdc.complete_claim(tmp_path, id1, "/tmp/x.md") is True

    assert claim_marker.read_text(encoding="utf-8") == newer_id


def test_complete_fast_path_survives_a_prior_completed_chore(tmp_path):
    """Regression for the cleanup fix: after ONE chore+scope has already been claimed
    and completed, a fresh claim of a DIFFERENT chore+scope must still be the ONLY
    keyed file on disk — an argument-less `complete` must not see the old one and
    report a false ambiguity."""
    _dispatch(tmp_path, 1_000_000, "repair", scope="LOCAL")
    got1 = mdc.claim_one(tmp_path, "repair")
    assert got1 is not None
    report1 = tmp_path / "r1.md"
    report1.write_text("x\n", encoding="utf-8")
    assert mdc.complete_claim(tmp_path, got1["dispatch_id"], str(report1)) is True

    _dispatch(tmp_path, 1_000_001, "atomize", scope="PROJECT")
    got2 = mdc.claim_one(tmp_path, "atomize")
    assert got2 is not None
    report2 = tmp_path / "r2.md"
    report2.write_text("y\n", encoding="utf-8")

    rc = mdc._run_complete(["--state-dir", str(tmp_path), "--report", str(report2)])

    assert rc == 0
    done = tmp_path / f"{mdc.DONE_PREFIX}{got2['dispatch_id']}.json"
    assert done.is_file()
