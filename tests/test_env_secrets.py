"""Tests for scripts/lib/env_secrets.py (janitor issue #354, layers 2 and 3).

Every secret here is generated at test time and is never an environment value of this process: the matcher is
given an explicit mapping. No test prints a value, and the assertions check that no finding carries one.
"""

from __future__ import annotations

import base64
import dataclasses
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


def test_cursor_resumes_after_the_last_file_and_holds_in_front_of_a_failure(tmp_path: Path) -> None:
    """The next pass reads only newer files, and never moves past a file that could not be read."""
    matcher = _matcher("MY_API_TOKEN", _token(48))
    older, newer = tmp_path / "older.txt", tmp_path / "newer.txt"
    older.write_text("one")
    newer.write_text("two")
    import os

    os.utime(older, (1000.0, 1000.0))
    os.utime(newer, (2000.0, 2000.0))
    first = env_secrets.sweep([str(tmp_path)], matcher, SALT)
    cursor = env_secrets.advance_cursor((0.0, ""), first.processed, first.failed)
    assert cursor == (2000.0, str(newer))
    assert env_secrets.sweep([str(tmp_path)], matcher, SALT, since=cursor).scanned == 0
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
