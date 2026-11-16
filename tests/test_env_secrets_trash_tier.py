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
    subprocess.run(["git", "init", "-q"], cwd=project, check=True, env={**os.environ, "HOME": str(tmp_path / "home")})
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
    """A file moved into a batch with an mtime of 1970 is read (the mtime cursor never would), the batch joins done in
    the same state file as the cursor, and a batch purged from disk leaves the state on the next pass."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    leak = _batch(project / ".trashcan", OLD, {"dump.txt": f"leak {value}\n".encode()}) / "dump.txt"
    os.utime(leak, (1000.0, 1000.0))
    first = _run(tmp_path, project, value)
    assert first.returncode == 0, first.stderr
    assert "CRED-002" in first.stdout and "FAKE_API_TOKEN_0000" in first.stdout and value not in first.stdout
    assert _state(project)["trash"] == {"positions": {}, "done": [OLD]}
    assert "cursor" in _state(project)
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


def test_an_old_state_file_without_a_trash_key_keeps_its_cursor_and_flagged_list(tmp_path: Path) -> None:
    """A state file from before the trash tier keeps its cursor and flagged list; only the trash state starts empty."""
    value = secrets.token_urlsafe(36)
    project = _project(tmp_path)
    gone = str(project / "elsewhere" / "gone.txt")  # in no sweep root and not on disk
    _write_state(project, {"cursor": [9000000000.0, ""], "retries": {}, "flagged": [gone]})
    assert _run(tmp_path, project, value).returncode == 0
    written = _state(project)
    assert written["cursor"][0] == 9000000000.0
    assert written["flagged"] == [gone]
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
    assert written["cursor"][0] != 9000000000.0
    assert gone not in written["flagged"]
