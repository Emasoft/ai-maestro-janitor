"""The trash tier of the env-secret sweep (TRDD-ZANQ1QW0, issue #354): the timestamp batches of .trashcan are read by batch
name from a saved per-batch position, because a file moved into the trash keeps its old modification time and so
never passes the modification-time cursor.

Everything runs on real files in tmp dirs, with an injected clock where time matters and no mocks. The detector tests
run the detector as a real program in a throwaway git project, as tests/test_env_secret_on_disk_detector.py does.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import env_secrets  # noqa: E402

_DETECTOR = _ROOT / "scripts" / "detectors" / "env-secret-on-disk.py"
SALT = b"s" * 32
OLD = "20200101_000000+0000"
OLDER = "20190101_000000+0000"
NEWER = "20200201_000000+0000"
KB = b"x" * 1000


def _matcher(value: str) -> env_secrets.Matcher:
    return env_secrets.Matcher({"MY_API_TOKEN": value})


def _batch(trash: Path, name: str, files: dict[str, bytes]) -> Path:
    for relative, data in files.items():
        target = trash / name / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return trash / name


def _pass(trash: Path, positions: dict[str, env_secrets.TrashPos], budget: int, value: str = "", done: frozenset[str] = frozenset(), **kw) -> env_secrets.TrashReport:  # type: ignore[no-untyped-def]
    matcher = _matcher(value) if value else None
    return env_secrets.sweep_trash(str(trash), matcher, SALT, positions, done, int(time.time()), byte_budget=budget, clock=lambda: 0.0, **kw)


def test_a_cut_walk_resumes_after_the_cut_and_reads_nothing_twice(tmp_path: Path) -> None:
    """Three passes under a 2.5 KB budget walk a1 a2 | m/b1 m/b2 | z1 in order; the second pass starts after the cut."""
    trash = tmp_path / ".trashcan"
    value = secrets.token_urlsafe(36)
    _batch(trash, OLD, {"a1": KB, "a2": KB, "m/b1": KB, "m/b2": KB + value.encode(), "z1": KB})
    first = _pass(trash, {}, 2500, value)
    assert first.processed_by_batch[OLD] == [("a1",), ("a2",)] and first.left_for_next_pass == 1 and first.exhausted == []
    positions = env_secrets.advance_trash({}, first.processed_by_batch, {})
    assert positions == {OLD: ("a2",)}
    second = _pass(trash, positions, 2500, value)
    assert second.processed_by_batch[OLD] == [("m", "b1"), ("m", "b2")]  # a1 and a2 are not listed again
    assert [h.name for h in second.hits] == ["MY_API_TOKEN"] and first.hits == []
    positions = env_secrets.advance_trash(positions, second.processed_by_batch, {})
    assert positions == {OLD: ("m", "b2")}
    third = _pass(trash, positions, 2500, value)
    assert third.processed_by_batch[OLD] == [("z1",)] and third.exhausted == [OLD]


def test_a_newer_batch_that_arrives_mid_scan_is_read_first_and_the_older_one_keeps_its_place(tmp_path: Path) -> None:
    """Newest batch first; the older batch stays at its saved position until the newer one is finished."""
    trash = tmp_path / ".trashcan"
    _batch(trash, OLD, {f"f{i}": KB for i in range(1, 5)})
    first = _pass(trash, {}, 2500)
    positions = env_secrets.advance_trash({}, first.processed_by_batch, {})
    assert positions == {OLD: ("f2",)}
    _batch(trash, NEWER, {"g1": KB, "g2": KB})
    second = _pass(trash, positions, 2000)
    assert list(second.processed_by_batch) == [NEWER] and second.exhausted == [NEWER]
    assert env_secrets.advance_trash(positions, second.processed_by_batch, {})[OLD] == ("f2",)


def test_an_unsettled_batch_is_skipped_and_a_purged_batch_is_not_present(tmp_path: Path) -> None:
    """A batch younger than the settle time is left alone (a safe-delete run may still be filling it); a batch name
    that is gone from disk is no longer reported present, which is what drops it from the saved state."""
    trash = tmp_path / ".trashcan"
    fresh = time.strftime("%Y%m%d_%H%M%S%z", time.localtime(time.time() - 10))
    _batch(trash, fresh, {"a": KB})
    _batch(trash, OLD, {"b": KB})
    report = _pass(trash, {OLDER: ("zz",)}, 10**6, done=frozenset({OLDER}))
    assert list(report.processed_by_batch) == [OLD] and fresh not in report.exhausted
    assert sorted(report.present) == sorted([fresh, OLD])  # OLDER was purged: not present


def test_the_walk_order_is_the_tuple_order_not_the_joined_string_order(tmp_path: Path) -> None:
    """With a folder "a" holding x and a file "a-b": as names "a" < "a-b", as joined strings "a-b" < "a/x". A joined
    string compare skipped a-b after a cut behind a/x."""
    trash = tmp_path / ".trashcan"
    _batch(trash, OLD, {"a/x": KB, "a-b": KB})
    first = _pass(trash, {}, 1500)
    assert first.processed_by_batch[OLD] == [("a", "x")]
    positions = env_secrets.advance_trash({}, first.processed_by_batch, {})
    second = _pass(trash, positions, 1500)
    assert second.processed_by_batch[OLD] == [("a-b",)] and second.exhausted == [OLD]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-0 file")
def test_a_file_that_failed_to_read_holds_the_position_in_front_of_it(tmp_path: Path) -> None:
    """The position stops before the first held path, so the failed file is read again once it can be."""
    trash = tmp_path / ".trashcan"
    _batch(trash, OLD, {"a1": KB, "a2": KB, "a3": KB})
    locked = trash / OLD / "a2"
    locked.chmod(0)
    try:
        report = _pass(trash, {}, 10**6)
    finally:
        locked.chmod(0o600)
    assert report.processed_by_batch[OLD] == [("a1",), ("a3",)] and report.failed_by_batch[OLD] == [("a2",)]
    assert OLD not in report.exhausted
    positions = env_secrets.advance_trash({}, report.processed_by_batch, report.failed_by_batch)
    assert positions == {OLD: ("a1",)}
    again = _pass(trash, positions, 10**6)
    assert again.processed_by_batch[OLD] == [("a2",), ("a3",)] and again.exhausted == [OLD]


def test_no_secret_named_file_or_folder_is_read_descended_or_stored(tmp_path: Path) -> None:
    """A secret in a file or folder NAME: neither is read, the folder is not entered, the report names the folder
    above and the variable NAME, and the value is in no position."""
    trash = tmp_path / ".trashcan"
    value = secrets.token_urlsafe(36)
    batch = _batch(trash, OLD, {"ok1": KB, f"{value}.txt": KB, f"dir-{value}/inner.txt": KB, "ok2": KB})
    report = _pass(trash, {}, 10**6, value)
    assert report.scanned == 2 and sorted(report.secret_named) == [(str(batch), "MY_API_TOKEN")] * 2
    positions = env_secrets.advance_trash({}, report.processed_by_batch, {})
    stored = json.dumps({"positions": positions, "processed": report.processed_by_batch, "done": report.exhausted})
    assert value not in stored and value not in repr(report.secret_named)


def test_the_time_budget_stops_the_walk_and_leaves_the_batch_unfinished(tmp_path: Path) -> None:
    """An injected clock that moves one second per reading: a 2.5 s budget stops the walk after a few files."""
    trash = tmp_path / ".trashcan"
    _batch(trash, OLD, {f"f{i}": b"x" for i in range(1, 7)})
    ticks = iter(range(1000))
    report = env_secrets.sweep_trash(str(trash), None, SALT, {}, frozenset(), int(time.time()), time_budget_s=2.5, clock=lambda: float(next(ticks)))
    assert 0 < len(report.processed_by_batch[OLD]) < 6 and report.left_for_next_pass == 1 and report.exhausted == []


def test_roots_leave_out_the_batch_folders_and_keep_the_other_trash_children(tmp_path: Path) -> None:
    """The mtime sweep keeps README.txt, a manifest, migrate-memory-scope/ and a not-a-date lookalike; batches are not roots."""
    project = tmp_path / "proj"
    trash = project / ".trashcan"
    _batch(trash, OLD, {"a": b"x"})
    (trash / f"{OLD}.txt").write_text("manifest")
    (trash / "README.txt").write_text("readme")
    (trash / "migrate-memory-scope" / "s").mkdir(parents=True)
    (trash / "20201399_000000+0000").mkdir()
    roots = env_secrets.agent_writable_roots(project, 501, tmp_base=str(tmp_path / "none"))
    assert sorted(roots) == sorted(str(trash / n) for n in (f"{OLD}.txt", "README.txt", "migrate-memory-scope", "20201399_000000+0000"))


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".gitignore").write_text(".trashcan/\n.janitor/\n")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True, timeout=120, env={**os.environ, "HOME": str(tmp_path / "home")})
    return project


def _run(tmp_path: Path, project: Path, value: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "home").mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path / "home"),
        "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gstate"),
        "FAKE_API_TOKEN_0000": value,
    }
    return subprocess.run([sys.executable, str(_DETECTOR), "--one-shot"], env=env, capture_output=True, text=True, timeout=120, check=False)


def _state(project: Path) -> dict:
    return json.loads((project / ".janitor" / "state" / "env-secret-on-disk.cursor.json").read_text())


def test_detector_finds_a_value_in_a_trash_file_with_an_old_mtime_and_drops_a_purged_batch(tmp_path: Path) -> None:
    """A file moved into a batch with an mtime of 1970 is read (by batch name, whatever its mtime: .trashcan is not a root of the modification-time sweep), the batch joins done in
    the same state file as the covered range, and a batch purged from disk leaves the state on the next pass."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    leak = _batch(project / ".trashcan", OLD, {"dump.txt": f"leak {value}\n".encode()}) / "dump.txt"
    os.utime(leak, (1000.0, 1000.0))
    first = _run(tmp_path, project, value)
    assert first.returncode == 0, first.stderr
    assert "CRED-002" in first.stdout and "FAKE_API_TOKEN_0000" in first.stdout and value not in first.stdout
    assert _state(project)["trash"] == {"positions": {}, "done": [OLD]}
    assert _state(project)["covered"] is not None
    shutil.rmtree(project / ".trashcan" / OLD)
    _batch(project / ".trashcan", NEWER, {"clean.txt": b"nothing\n"})
    assert _run(tmp_path, project, value).returncode == 0
    assert _state(project)["trash"] == {"positions": {}, "done": [NEWER]}
    assert value not in (project / ".janitor" / "state" / "env-secret-on-disk.cursor.json").read_text()


def _write_state(project: Path, data: dict) -> Path:
    state_file = project / ".janitor" / "state" / "env-secret-on-disk.cursor.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(data))
    return state_file


def test_an_old_state_file_without_a_trash_key_keeps_its_flagged_list_and_drops_its_cursor(tmp_path: Path) -> None:
    """A state file from before the trash tier keeps its flagged list; its old cursor key is dropped, not migrated; only the trash state starts empty."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    gone = str(project / "elsewhere" / "gone.txt")  # in no sweep root and not on disk
    # TRDD-ZFD3KBM3 rule change: a flagged path that is gone with no trash copy is now withdrawn (nothing holds the value any more), so this test, which is about the
    # flagged list surviving the state-file upgrade, gives the path a copy in the trash (as safe-delete would have left it): the finding then stays, which is the
    # original intent. The withdrawal of a gone path is covered in test_env_secret_on_disk_detector.py.
    _batch(project / ".trashcan", OLD, {"elsewhere/gone.txt": b"nothing\n"})
    _write_state(project, {"cursor": [9000000000.0, ""], "retries": {}, "flagged": [gone]})
    assert _run(tmp_path, project, value).returncode == 0
    written = _state(project)
    assert "cursor" not in written and max(written["covered"][0][0], written["covered"][1][0]) < 9000000000.0  # a migrated cursor would put 9e9 in covered
    assert written["flagged"] == {gone: ["unknown"]}  # TRDD-ZFD3KBM3: the old list loads as unknown-secret entries and is written in the object shape
    assert "trash" in written


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-0 file")
def test_a_flagged_trash_file_that_cannot_be_read_is_not_withdrawn(tmp_path: Path) -> None:
    """A trash file whose read failed was not rescanned, so its CRED-002 finding stays in the flagged list."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    leak = _batch(project / ".trashcan", OLD, {"dump.txt": f"leak {value}\n".encode()}) / "dump.txt"
    _write_state(project, {"cursor": [0.0, ""], "retries": {str(leak): 1}, "flagged": [str(leak)], "trash": {"positions": {}, "done": []}})
    leak.chmod(0)
    try:
        assert _run(tmp_path, project, value).returncode == 0
    finally:
        leak.chmod(0o600)
    assert str(leak) in _state(project)["flagged"]
    assert _state(project)["retries"][str(leak)] == 2  # a file that fails again keeps its saved count plus one, so give-up counting survives


def test_a_flagged_trash_file_over_the_read_limit_is_not_withdrawn(tmp_path: Path) -> None:
    """A trash file larger than MAX_FILE_BYTES is counted in processed_by_batch but was not read, so its CRED-002 finding stays in the flagged list (TRDD-XNZFKX0L)."""
    # MAX_FILE_BYTES is lowered inside the detector process through runpy: the real limit is 256 MiB. The state file puts the file in a
    # batch that is not done and has no saved position, so the trash walk reaches it on this pass whatever its mtime.
    runner = (
        "import runpy, sys\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "import env_secrets\n"
        "env_secrets.MAX_FILE_BYTES = int(sys.argv[3])\n"
        "detector = sys.argv[1]\n"
        "sys.argv = [detector, \"--one-shot\"]\n"
        "runpy.run_path(detector, run_name=\"__main__\")\n"
    )
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    leak = _batch(project / ".trashcan", OLD, {"dump.txt": f"leak {value}\n".encode()}) / "dump.txt"
    _write_state(project, {"covered": None, "retries": {}, "flagged": [str(leak)], "trash": {"positions": {}, "done": []}})
    (tmp_path / "home").mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path / "home"), "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gstate"), "FAKE_API_TOKEN_0000": value,
    }
    argv = [sys.executable, "-c", runner, str(_DETECTOR), str(_ROOT / "scripts" / "lib"), str(leak.stat().st_size - 1)]
    out = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120, check=False)
    assert out.returncode == 0, out.stderr
    # Every file is over the lowered limit, so the count says nothing about this one: the log names the paths not read.
    log = (project / ".janitor" / "logs" / "env-secret-on-disk.log").read_text().splitlines()
    assert any("not fully covered" in line and str(leak) in line for line in log)  # the coverage line names the trash file: it was walked and skipped as too big
    assert str(leak) in _state(project)["flagged"]


def test_a_link_to_a_folder_in_trashcan_is_not_a_sweep_root(tmp_path: Path) -> None:
    """A link to a folder, batch-shaped or not, is no root: os.walk would descend it, and it lists a link without descending."""
    project = tmp_path / "proj"
    trash = project / ".trashcan"
    outside = tmp_path / "outside"
    outside.mkdir()
    trash.mkdir(parents=True)
    (trash / "some-link").symlink_to(outside, target_is_directory=True)
    (trash / OLD).symlink_to(outside, target_is_directory=True)
    roots = env_secrets.agent_writable_roots(project, 501, tmp_base=str(tmp_path / "none"))
    assert str(trash / "some-link") not in roots and str(trash / OLD) not in roots


def test_a_malformed_trash_state_falls_back_to_a_fresh_pass(tmp_path: Path) -> None:
    """A state file whose trash entry is malformed restarts everything: the cursor and the flagged list are dropped."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    gone = str(project / "elsewhere" / "gone.txt")  # in no sweep root and not on disk
    _write_state(project, {"cursor": [9000000000.0, ""], "retries": {}, "flagged": [gone], "trash": "bad"})
    assert _run(tmp_path, project, value).returncode == 0
    written = _state(project)
    assert "cursor" not in written and max(written["covered"][0][0], written["covered"][1][0]) < 9000000000.0  # a migrated cursor would put 9e9 in covered
    assert gone not in written["flagged"]


def test_the_trash_tier_reports_the_seconds_it_ran(tmp_path: Path) -> None:
    """After reading one file on a clock that moves one second per call, elapsed_s is above 0 (TRDD-ZANQ1QW0)."""
    trash = tmp_path / ".trashcan"
    _batch(trash, OLD, {"f1": b"x"})
    ticks = iter(range(1000))
    report = env_secrets.sweep_trash(str(trash), None, SALT, {}, frozenset(), int(time.time()), clock=lambda: float(next(ticks)))
    assert report.scanned == 1 and report.elapsed_s > 0.0


def test_a_cut_read_ends_the_trash_walk_and_the_file_is_held_not_processed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The hard bound cuts the first trash file: it is in failed_by_batch (the position stays in front of it), the walk stops there, and the next file is not read (TRDD-ZANQ1QW0)."""
    monkeypatch.setattr(env_secrets, "CHUNK_BYTES", 100)  # _read_one passes CHUNK_BYTES at call time, so a small file spans several chunks
    trash = tmp_path / ".trashcan"
    value = secrets.token_urlsafe(36)
    _batch(trash, OLD, {"a1": value.encode() + b"\n" + b"x" * 400, "a2": KB})
    # clock reads: start 0.0, the hard check before a1 1.0 (inside 1.5), the check before chunk 2 of a1 2.0 (past 1.5: the cut). Then the clock moves BACK to 0.0 for
    # ever, which a real clock never does: only the explicit stop after a cut, not a later deadline check, can keep a2 from being read.
    ticks = iter([0.0, 1.0, 2.0])
    report = env_secrets.sweep_trash(
        str(trash), _matcher(value), SALT, {}, frozenset(), int(time.time()), clock=lambda: next(ticks, 0.0), hard_deadline_s=1.5,
    )
    a1 = str(trash / OLD / "a1")
    assert report.cut == [a1] and [h.path for h in report.hits] == [a1]  # the hit before the cut is real
    assert report.failed_by_batch == {OLD: [("a1",)]} and report.processed_by_batch == {}
    assert report.scanned == 0 and report.read == [] and report.left_for_next_pass == 1 and report.exhausted == []
    assert env_secrets.advance_trash({}, report.processed_by_batch, report.failed_by_batch) == {}  # the position does not pass the cut file


def test_no_trash_read_starts_after_the_hard_deadline_even_for_a_small_file(tmp_path: Path) -> None:
    """A second small file is not opened once the hard deadline has passed. With no matcher no read is ever cut, so only the hard check before each read can stop it; the soft budgets stay out of it (1000 s time budget, default byte budget, over() reads the clock only after a read) (TRDD-ZANQ1QW0)."""
    trash = tmp_path / ".trashcan"
    _batch(trash, OLD, {"a1": b"x", "a2": b"x"})
    # No matcher, so no scan_file and no clock read inside a read. Reads of the clock: start 0.0, the hard check before a1 1.0 (inside 5.0: a1 is read), the hard check
    # before a2 100.0 (past 5.0: the walk stops). The soft guard is not the cause: over() reads the clock only after a read, and its time budget (1000 s) and byte budget
    # (the default) are far above anything this walk uses, so with the hard check removed a2 is read, not stopped.
    ticks = iter([0.0, 1.0, 100.0])
    report = env_secrets.sweep_trash(
        str(trash), None, SALT, {}, frozenset(), int(time.time()), time_budget_s=1000.0, clock=lambda: next(ticks, 100.0), hard_deadline_s=5.0,
    )
    assert report.processed_by_batch == {OLD: [("a1",)]} and report.failed_by_batch == {} and report.scanned == 1
    assert report.cut == [] and report.left_for_next_pass == 1 and report.exhausted == []
