"""Tests for scripts/lib/env_secrets.py (janitor issue #354, layers 2 and 3).

Every secret here is generated at test time and is never an environment value of this process: the matcher is
given an explicit mapping. No test prints a value, and the assertions check that no finding carries one.
"""

from __future__ import annotations

import base64
import dataclasses
import itertools
import os
import secrets
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import env_secrets  # noqa: E402

SALT = b"s" * 32


def _token(length: int = 40) -> str:
    """A random token-like value, different on every run."""
    return secrets.token_urlsafe(length)[:length]


def _matcher(name: str, value: str) -> env_secrets.Matcher:
    return env_secrets.Matcher(env_secrets.live_secrets({name: value}))


def _scan(tmp_path: Path, content: bytes, name: str, value: str, chunk: int = env_secrets.CHUNK_BYTES) -> list[env_secrets.Hit]:
    target = tmp_path / "out.txt"
    target.write_bytes(content)
    return env_secrets.scan_file(str(target), _matcher(name, value), SALT, chunk=chunk)


def test_live_secrets_takes_only_secret_named_long_varied_values(tmp_path: Path) -> None:
    """A secret NAME and a long, varied VALUE are both required; ids, paths, short and flat values are not needles."""
    environ = {
        "MY_API_TOKEN": _token(),
        "GH_PAT": _token(),
        "SESSION_COOKIE": _token(),
        "SESSION_ID": _token(),  # an identifier, not a secret name
        "CONFIG_TOKEN_FILE": _token(),  # about the secret, not the secret
        "SHORT_TOKEN": "abc12345",  # too short
        "DIGITS_TOKEN": "1234567890123456789",  # only digits
        "FLAT_TOKEN": "a" * 30,  # too few different characters
        "PATH_TOKEN": str(tmp_path),  # an existing path
        "PATH": "/usr/bin:/bin",
    }
    assert sorted(env_secrets.live_secrets(environ)) == ["GH_PAT", "MY_API_TOKEN", "SESSION_COOKIE"]


@pytest.mark.parametrize("form", ["exact", "url-quoted", "json-escaped", "base64", "part", "head", "tail"])
def test_planted_value_is_found_in_every_form_and_reported_by_name_only(tmp_path: Path, form: str) -> None:
    """Each way a tool can copy a value is found, and the finding names the variable, never the value."""
    token = _token(60)
    value = f"{token}={_token(8)}+/\"\\"  # after the token: characters that URL-quoting and JSON escaping change
    copies = {
        "exact": value.encode(),
        "url-quoted": urllib.parse.quote(value, safe="").encode(),
        "json-escaped": f'{{"k": "{value.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"}}'.encode(),
        "base64": base64.b64encode(value.encode()).rstrip(b"="),
        "part": token.encode(),
        "head": token[:24].encode(),
        "tail": token[-24:].encode(),
    }
    hits = _scan(tmp_path, b"line one\nprefix " + copies[form] + b" suffix\n", "MY_API_TOKEN", value)
    assert [h.name for h in hits] == ["MY_API_TOKEN"]
    assert hits[0].line == 2
    for text in (repr(hits[0]), str(dataclasses.asdict(hits[0]))):
        assert value not in text and token not in text


def test_value_on_a_chunk_edge_is_found_once(tmp_path: Path) -> None:
    """A value cut by a chunk boundary is found, and the copy that appears twice in the overlap is one hit."""
    # 30 characters: only the whole value can match. 48 characters: head and tail needles exist too, and the
    # copy cut by a chunk edge can match as a head in one chunk and whole in the next, which must still be one hit.
    for length in (30, 48):
        value = _token(length)
        content = b"x" * 61 + value.encode() + b"\n" + b"y" * 50
        for chunk in (64, 70, 80, 100):
            hits = _scan(tmp_path, content, "MY_API_TOKEN", value, chunk=chunk)
            assert [(h.name, h.line) for h in hits] == [("MY_API_TOKEN", 1)], (length, chunk)


def test_label_in_front_of_a_token_is_not_a_finding_when_only_the_label_is_written(tmp_path: Path) -> None:
    """A value "label:token" gives needles from the token only, so ordinary text that names the label is silent."""
    label = "work-account-primary"
    value = f"{label}:{_token(48)}"
    assert _scan(tmp_path, f"logged in as {label} at noon\n".encode() * 50, "MY_API_TOKEN", value) == []
    assert [h.form for h in _scan(tmp_path, f"x {value.split(':')[1]} y\n".encode(), "MY_API_TOKEN", value)] == ["part"]


def test_fingerprint_is_keyed_and_stable(tmp_path: Path) -> None:
    """Two findings of one secret share a fingerprint; another salt gives another one; the value is not in it."""
    value = _token(48)
    first = _scan(tmp_path, value.encode(), "MY_API_TOKEN", value)[0]
    second = _scan(tmp_path, b"z " + value.encode(), "MY_API_TOKEN", value)[0]
    other_salt = env_secrets.fingerprint(value, b"t" * 32)
    assert first.fingerprint == second.fingerprint != other_salt
    assert value not in first.fingerprint


def test_matcher_never_shows_its_values() -> None:
    """The needle table holds secrets, so its repr and str hide them."""
    value = _token(48)
    matcher = _matcher("MY_API_TOKEN", value)
    assert value not in repr(matcher) and value not in str(matcher)


def test_dump_shape_needs_five_anchors_and_a_token_like_secret_value() -> None:
    """A whole-environment text with a secret-named token-like value is dump-shaped; fewer anchors or a flat value is not."""
    token = _token(48)
    body = "\n".join(f"{k}=/x" for k in ("PATH", "HOME", "SHELL", "USER", "LOGNAME", "TERM"))
    assert env_secrets.env_dump_names(f"{body}\nMY_API_TOKEN={token}\n".encode()) == ["MY_API_TOKEN"]
    assert env_secrets.env_dump_names(f"{body}\nMY_API_TOKEN={token}\n".replace("\n", "\0").encode()) == ["MY_API_TOKEN"]
    assert env_secrets.env_dump_names(f"PATH=/x\nHOME=/x\nMY_API_TOKEN={token}\n".encode()) == []
    assert env_secrets.env_dump_names(f"{body}\nFAKE_TOKEN=FAKE_TOKEN_FAKE_TOKEN_0000\n".encode()) == []


def test_sweep_counts_what_it_did_not_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file that is too big, unreadable or over the budget is counted in the report, not skipped silently."""
    value = _token(48)
    matcher = _matcher("MY_API_TOKEN", value)
    (tmp_path / "hit.txt").write_text(f"a {value}\n")
    (tmp_path / "big.bin").write_bytes(b"x" * 200)
    locked = tmp_path / "locked.txt"
    locked.write_text("nothing")
    locked.chmod(0)
    monkeypatch.setattr(env_secrets, "MAX_FILE_BYTES", 100)
    try:
        report = env_secrets.sweep([str(tmp_path)], matcher, SALT)
    finally:
        locked.chmod(0o600)
    assert [h.name for h in report.hits] == ["MY_API_TOKEN"]
    assert report.too_big == [str(tmp_path / "big.bin")]
    assert report.unreadable == [str(locked)]
    monkeypatch.setattr(env_secrets, "MAX_FILE_BYTES", 10_000)
    (tmp_path / "a.txt").write_text("a" * 50)
    (tmp_path / "b.txt").write_text("b" * 50)
    limited = env_secrets.sweep([str(tmp_path)], matcher, SALT, byte_budget=60)
    assert limited.left_for_next_pass > 0 and limited.scanned >= 1


def test_the_range_resumes_after_the_last_file_and_holds_in_front_of_a_failure(tmp_path: Path) -> None:
    """The next pass reads only files outside the covered range, and hi never moves past a file that could not be read."""
    matcher = _matcher("MY_API_TOKEN", _token(48))
    older, newer = tmp_path / "older.txt", tmp_path / "newer.txt"
    older.write_text("one")
    newer.write_text("two")
    import os

    os.utime(older, (1000.0, 1000.0))
    os.utime(newer, (2000.0, 2000.0))
    first = env_secrets.sweep([str(tmp_path)], matcher, SALT, covered=((0.0, ""), (0.0, "")))  # both files above hi: the fresh tier, oldest first
    cursor = env_secrets.advance_cursor((0.0, ""), first.processed, first.failed)
    assert cursor == (2000.0, str(newer))
    assert env_secrets.sweep([str(tmp_path)], matcher, SALT, covered=((0.0, ""), cursor)).scanned == 0  # inside the range: not read again
    held = env_secrets.advance_cursor((0.0, ""), first.processed, [(1000.0, str(older))])
    assert held == (0.0, "")
    assert env_secrets.advance_cursor((0.0, ""), first.processed, [(2000.0, str(newer))]) == (1000.0, str(older))


def test_a_failing_file_stops_holding_the_cursor_after_it_is_given_up(tmp_path: Path) -> None:
    """A file named in give_up is reported as unreadable but no longer counts as a failure to retry."""
    locked = tmp_path / "locked.txt"
    locked.write_text("x")
    locked.chmod(0)
    try:
        held = env_secrets.sweep([str(tmp_path)], None, SALT)
        released = env_secrets.sweep([str(tmp_path)], None, SALT, give_up=frozenset({str(locked)}))
    finally:
        locked.chmod(0o600)
    assert len(held.failed) == 1 and held.unreadable == [str(locked)]
    assert released.failed == [] and released.unreadable == [str(locked)] and len(released.processed) == 1


def test_a_link_to_a_file_is_followed_and_scanned(tmp_path: Path) -> None:
    """A sub-agent output file is a link to its transcript: the sweep reads the target."""
    value = _token(48)
    real = tmp_path / "elsewhere" / "transcript.jsonl"
    real.parent.mkdir()
    real.write_text(f'{{"text": "{value}"}}\n')
    folder = tmp_path / "scratch"
    folder.mkdir()
    (folder / "agent.output").symlink_to(real)
    assert [h.name for h in env_secrets.sweep([str(folder)], _matcher("MY_API_TOKEN", value), SALT).hits] == ["MY_API_TOKEN"]


def test_roots_are_the_agent_writable_folders_that_exist(tmp_path: Path) -> None:
    """reports, every *_dev, .janitor, .trashcan and the project's session scratch folder; absent ones are left out."""
    project = tmp_path / "proj"
    for name in ("reports", "reports_dev", "docs_dev", ".janitor", "src"):
        (project / name).mkdir(parents=True)
    (project / "notes_dev").write_text("a file named like a dev folder")
    scratch = tmp_path / "tmp" / "claude-501" / str(project).replace("/", "-")
    scratch.mkdir(parents=True)
    roots = env_secrets.agent_writable_roots(project, 501, tmp_base=str(tmp_path / "tmp"))
    assert sorted(roots) == sorted(str(p) for p in (project / "reports", project / "reports_dev", project / "docs_dev", project / ".janitor", scratch))



# Review leads of 2026-11-15 (outside-model review of the code drop; each failure below was reproduced first).
def test_a_file_full_of_hits_is_scanned_in_linear_time(tmp_path: Path) -> None:
    """A 2 MiB log that carries the value on every line used to take 40 s (a newline count from offset 0 per match, so
    quadratic) and a larger one outlived the 120 s detector timeout; the count is carried forward now."""
    import time

    value = _token(40)
    line = f"Authorization: Bearer {value}\n".encode()
    count = (2 * 1024 * 1024) // len(line)
    target = tmp_path / "dense.log"
    target.write_bytes(line * count)
    started = time.monotonic()
    hits = env_secrets.scan_file(str(target), _matcher("MY_API_TOKEN", value), SALT)
    assert time.monotonic() - started < 10
    assert len(hits) == count and hits[-1].line == count


def _sweep_in_a_child(folder: Path) -> subprocess.CompletedProcess[str]:
    """Sweep a folder in a child process with a deadline, so a sweep that blocks fails the test instead of hanging it."""
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import env_secrets as e; "
        "r = e.sweep([sys.argv[2]], None, b's' * 32); print(r.scanned, len(r.not_regular), len(r.unreadable))"
    )
    lib = Path(env_secrets.__file__).resolve().parent
    return subprocess.run([sys.executable, "-c", code, str(lib), str(folder)], capture_output=True, text=True, timeout=20, check=False)


def test_a_named_pipe_or_a_device_link_is_counted_not_opened(tmp_path: Path) -> None:
    """open() on a FIFO waits for a writer and a link to /dev/zero never ends: both blocked the sweep for good."""
    os.mkfifo(tmp_path / "pipe")
    (tmp_path / "zero").symlink_to("/dev/zero")
    (tmp_path / "plain.txt").write_text("text")
    done = _sweep_in_a_child(tmp_path)
    assert done.stdout.split() == ["1", "2", "0"], done.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 0 folder")
def test_a_folder_the_walk_cannot_enter_is_counted_as_unreadable(tmp_path: Path) -> None:
    """os.walk skips a folder it cannot list without a word: the sweep counts it, so silence is not a pass."""
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "f.txt").write_text("x")
    locked.chmod(0)
    try:
        report = env_secrets.sweep([str(tmp_path)], None, SALT)
    finally:
        locked.chmod(0o700)
    assert report.unreadable == [str(locked)]



def test_a_file_whose_name_holds_the_value_is_reported_by_its_folder_and_never_by_path(tmp_path: Path) -> None:
    """A cache file named after its token would put the value in every list of paths (log, cursor, finding)."""
    value = _token(40)
    (tmp_path / f"cache-{value}.json").write_text("{}")
    (tmp_path / "plain.txt").write_text("text")
    report = env_secrets.sweep([str(tmp_path)], _matcher("MY_API_TOKEN", value), SALT)
    assert report.secret_named == [(str(tmp_path), "MY_API_TOKEN")]
    assert report.scanned == 1 and value not in repr(report)


def _stepping_clock(step: float):
    """A clock that moves `step` seconds on every call, so a test sets time by counting the sweep's own clock reads."""
    ticks = itertools.count()
    return lambda: next(ticks) * step


def _three_files_and_a_subfolder(folder: Path) -> None:
    for name in ("a.txt", "b.txt", "c.txt"):
        (folder / name).write_text(name)
    (folder / "sub").mkdir()


def test_a_listing_over_its_budget_is_cut_and_reads_nothing(tmp_path: Path) -> None:
    """A listing that overruns listing_budget_s reports the seconds it ran and reads nothing, so no cursor key exists to advance."""
    _three_files_and_a_subfolder(tmp_path)
    report = env_secrets.sweep([str(tmp_path)], None, SALT, clock=_stepping_clock(10.0), listing_budget_s=15.0)
    assert report.listing_cut_after_s == 20.0  # clock reads: start 0, first folder 10 (inside), second folder 20 (over)
    assert report.scanned == 0 and report.processed == [] and report.failed == []


def test_the_time_budget_includes_the_listing(tmp_path: Path) -> None:
    """The clock starts before the listing: the listing's own time is spent from time_budget_s, so reads stop after the second file here."""
    _three_files_and_a_subfolder(tmp_path)
    for name in ("a.txt", "b.txt", "c.txt"):
        os.utime(tmp_path / name, (100.0, 100.0))  # far below the live edge: the backlog tier, whose limit is the whole time budget
    # clock reads: start 0, two folders 1 and 2 (listing), the start of the reads 3, the end of the fresh tier 4 (TRDD-ZANQ1QW0: the phase timing
    # reads the clock between the tiers), then 5 before the second file and 6 before the third.
    # Started after the listing (the old order) the elapsed is 3 before the second file and 4 before the third, both inside 5.5: all three files are read.
    report = env_secrets.sweep([str(tmp_path)], None, SALT, clock=_stepping_clock(1.0), time_budget_s=5.5)
    assert report.listing_cut_after_s is None
    assert report.scanned == 2 and report.left_for_next_pass == 1


def test_a_completed_listing_has_no_cut(tmp_path: Path) -> None:
    """A listing inside its budget leaves listing_cut_after_s None and the files are read."""
    _three_files_and_a_subfolder(tmp_path)
    report = env_secrets.sweep([str(tmp_path)], None, SALT)
    assert report.listing_cut_after_s is None and report.scanned == 3


def test_one_flat_folder_is_cut_inside_the_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The listing clock is read every LISTING_CLOCK_EVERY_FILES files, so a single huge folder is bounded too."""
    monkeypatch.setattr(env_secrets, "LISTING_CLOCK_EVERY_FILES", 2)
    for index in range(5):
        (tmp_path / f"{index}.txt").write_text("x")
    report = env_secrets.sweep([str(tmp_path)], None, SALT, clock=_stepping_clock(10.0), listing_budget_s=15.0)
    assert report.listing_cut_after_s == 20.0  # clock reads: start 0, the folder 10 (inside), the second file 20 (over)
    assert report.scanned == 0



def _file_at(folder: Path, name: str, mtime: float, size: int = 10) -> str:
    """A file of `size` bytes whose modification time is set to `mtime`; returns its path."""
    target = folder / name
    target.write_bytes(b"x" * size)
    os.utime(target, (mtime, mtime))
    return str(target)


def test_a_fresh_state_reads_the_newest_file_first(tmp_path: Path) -> None:
    """With no saved range the sweep starts at the live edge: the newest file is read first and the older ones wait for later passes."""
    _file_at(tmp_path, "p100.txt", 100.0)
    _file_at(tmp_path, "p200.txt", 200.0)
    p300 = _file_at(tmp_path, "p300.txt", 300.0)
    report = env_secrets.sweep([str(tmp_path)], None, SALT, covered=None, byte_budget=15, wall=lambda: 1000.0)
    assert report.processed == [(300.0, p300)]
    assert report.left_for_next_pass == 2
    assert env_secrets.advance_covered(report.covered, report.processed, [], report.live_edge) == ((300.0, p300), (998.0, ""))


def test_hi_stays_below_the_live_edge(tmp_path: Path) -> None:
    """A file newer than the live edge is read but never covered by hi, so the next pass reads it again."""
    p600 = _file_at(tmp_path, "p600.txt", 600.0)
    p999 = _file_at(tmp_path, "p999.txt", 999.5)
    covered = ((50.0, ""), (500.0, ""))
    report = env_secrets.sweep([str(tmp_path)], None, SALT, covered=covered, wall=lambda: 1000.0)
    assert report.processed == [(600.0, p600), (999.5, p999)]
    advanced = env_secrets.advance_covered(report.covered, report.processed, [], report.live_edge)
    assert advanced[1] == (600.0, p600)
    again = env_secrets.sweep([str(tmp_path)], None, SALT, covered=advanced, wall=lambda: 1000.0)
    assert again.processed == [(999.5, p999)]


def test_a_fresh_file_over_the_whole_budget_does_not_stop_the_backlog(tmp_path: Path) -> None:
    """Each tier reads at least one file per pass, so one huge fresh file cannot starve the backlog below lo."""
    _file_at(tmp_path, "p300.txt", 300.0, size=40)
    p50 = _file_at(tmp_path, "p50.txt", 50.0, size=10)
    report = env_secrets.sweep([str(tmp_path)], None, SALT, covered=((100.0, ""), (200.0, "")), byte_budget=30, wall=lambda: 1000.0)
    assert sorted(mtime for mtime, _ in report.processed) == [50.0, 300.0]
    assert env_secrets.advance_covered(report.covered, report.processed, [], report.live_edge)[0] == (50.0, p50)


def test_a_backlog_hold_stops_lo_above_it() -> None:
    """lo moves down over the keys read but never to or below the highest backlog hold; hi stops in front of its first hold."""
    moved = env_secrets.advance_covered(((500.0, ""), (600.0, "")), [(400.0, "a"), (300.0, "b"), (200.0, "c")], [(300.0, "b")], 1000.0)
    assert moved == ((400.0, "a"), (600.0, ""))
    up = env_secrets.advance_covered(((100.0, ""), (200.0, "")), [(300.0, "x"), (400.0, "y"), (500.0, "z")], [(400.0, "y")], 1000.0)
    assert up[1] == (300.0, "x")


def test_raise_order_follows_each_edge() -> None:
    """Findings are raised above hi oldest first, then in the backlog newest first, then the trash files by path."""
    keys = {path: (mtime, path) for path, mtime in (("p700", 700.0), ("p650", 650.0), ("p400", 400.0), ("p300", 300.0))}
    ordered = env_secrets.raise_order(["p300", "p400", "p650", "p700", "trash/a"], keys, (600.0, ""))
    assert ordered == ["p650", "p700", "p400", "p300", "trash/a"]


def test_each_phase_of_a_pass_reports_its_seconds(tmp_path: Path) -> None:
    """A pass over a fresh file and a backlog file reports listing_s, fresh_s and backlog_s, all above 0 on a stepping clock (TRDD-ZANQ1QW0)."""
    _file_at(tmp_path, "p300.txt", 300.0)
    _file_at(tmp_path, "p50.txt", 50.0)
    report = env_secrets.sweep([str(tmp_path)], None, SALT, covered=((100.0, ""), (200.0, "")), wall=lambda: 1000.0, clock=_stepping_clock(1.0))
    assert len(report.processed) == 2 and report.listing_cut_after_s is None
    # clock reads: start 0, the one folder 1, the start of the reads 2, the end of the fresh tier 3, the end of the backlog tier 4.
    assert (report.listing_s, report.fresh_s, report.backlog_s) == (2.0, 1.0, 1.0)


def test_a_cut_listing_stores_its_seconds_once_and_reads_nothing(tmp_path: Path) -> None:
    """A cut listing keeps its elapsed in listing_cut_after_s and leaves listing_s, fresh_s and backlog_s at 0.0, so the seconds are stored once (TRDD-ZANQ1QW0)."""
    _file_at(tmp_path, "p300.txt", 300.0)
    report = env_secrets.sweep([str(tmp_path)], None, SALT, covered=((100.0, ""), (200.0, "")), wall=lambda: 1000.0, clock=_stepping_clock(1.0), listing_budget_s=0)
    assert report.listing_cut_after_s == 1.0 and report.listing_s == 0.0
    assert report.fresh_s == 0.0 and report.backlog_s == 0.0 and report.scanned == 0
