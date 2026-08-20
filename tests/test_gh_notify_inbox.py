"""The fleet-wide GitHub notification inbox (TRDD-079778RM).

The lane-level behaviour (N projects on one host all receiving a reply, the fail-open
fallbacks) is pinned end-to-end in `test_gh_reply_watch.py`. THIS file pins the inbox's own
contract, where the subtle half lives: a fetch is INCREMENTAL, so publishing it wrong loses
replies silently rather than loudly.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))

import gh_notify_inbox as inbox  # noqa: E402


@pytest.fixture(autouse=True)
def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the control dir so no test can touch the real machine-wide inbox."""
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "control"))


def _thread(tid: str, updated: str = "2026-08-20T12:00:00Z") -> dict:
    return {"id": tid, "updated_at": updated, "subject": {"title": f"t{tid}"}}


def _now() -> int:
    return int(time.mktime(time.strptime("2026-08-20T13:00:00+0000", "%Y-%m-%dT%H:%M:%S%z")))


def test_absent_inbox_reads_as_empty_and_not_fresh() -> None:
    """Nothing written yet -> a reader must fall back to a direct poll, so `is_fresh` is
    False. `read_threads` returning [] on its own would be indistinguishable from "no new
    replies", which is why freshness is a separate question."""
    assert inbox.read_threads() == []
    assert inbox.is_fresh() is False
    assert inbox.age_s() is None


def test_a_written_inbox_is_fresh_and_round_trips() -> None:
    assert inbox.write([_thread("1")]) is True
    assert inbox.is_fresh() is True
    assert [t["id"] for t in inbox.read_threads()] == ["1"]


def test_a_later_fetch_MERGES_rather_than_replaces() -> None:
    """THE CORRECTNESS CORE. The daemon fetches with `since=`, so each publish carries only
    what changed. A plain overwrite would leave the inbox holding just the newest delta,
    and any project that had not read the previous one would never see it — the exact
    starvation this whole change exists to end, reintroduced one layer down.
    """
    inbox.write([_thread("1")])
    inbox.write([_thread("2")])
    assert sorted(t["id"] for t in inbox.read_threads()) == ["1", "2"]


def test_a_rewritten_thread_keeps_ONE_entry_with_the_newer_body() -> None:
    """Merging is keyed on the thread id, so a thread updated twice must not accumulate a
    duplicate — the reader's own dedupe is by (id, updated_at) and would re-emit."""
    inbox.write([_thread("1", "2026-08-20T12:00:00Z")])
    inbox.write([_thread("1", "2026-08-20T12:30:00Z")])
    threads = inbox.read_threads()
    assert len(threads) == 1
    assert threads[0]["updated_at"] == "2026-08-20T12:30:00Z"


def test_threads_older_than_the_retention_window_are_pruned() -> None:
    """The window is the stated worst-case latency bound: a project that reads within
    RETAIN_S of a fetch misses nothing. Without pruning the file would grow forever."""
    now = _now()
    fresh = _thread("new", "2026-08-20T12:00:00Z")
    stale = _thread("old", "2026-08-01T00:00:00Z")
    kept = inbox.prune([fresh, stale], now)
    assert [t["id"] for t in kept] == ["new"]


def test_a_thread_with_an_unparseable_date_is_KEPT() -> None:
    """Fail toward remembering. Dropping it would silently lose a reply if GitHub ever
    changed the field's shape; keeping it costs a few bytes and one extra dedupe check."""
    assert len(inbox.prune([{"id": "x", "updated_at": "not-a-date"}], _now())) == 1
    assert len(inbox.prune([{"id": "y"}], _now())) == 1


def test_a_stale_inbox_reads_as_empty_but_reports_NOT_fresh() -> None:
    """The distinction a reader depends on: stale means "nobody is fetching" (spend a poll
    token), empty-and-fresh means "nothing new" (stay quiet). Collapsing the two would make
    a dead daemon look like a quiet inbox and silence the lane completely."""
    inbox.write([_thread("1")], now=1)  # epoch 1
    assert inbox.is_fresh() is False
    assert inbox.read_threads() == []
    assert inbox.read_threads(ignore_age=True) != []


def test_the_writer_folds_in_a_STALE_inbox_it_would_not_serve() -> None:
    """A daemon that was down for an hour must not truncate the inbox to its first delta on
    the way back up — so the merge reads with `ignore_age`, even though a reader at the same
    moment would refuse the same file."""
    inbox.write([_thread("1")], now=1)
    inbox.write([_thread("2")])
    assert sorted(t["id"] for t in inbox.read_threads()) == ["1", "2"]


def test_a_corrupt_inbox_is_treated_as_absent() -> None:
    """Torn JSON must read as "no inbox" (fall back), never as "no threads" (stay silent)."""
    inbox.inbox_path().parent.mkdir(parents=True, exist_ok=True)
    inbox.inbox_path().write_text('{"threads": [{"id"', encoding="utf-8")
    assert inbox.read_threads() == []
    assert inbox.is_fresh() is False


def test_a_non_dict_payload_is_rejected() -> None:
    """A JSON array is valid JSON and the wrong shape — accepting it would crash the reader
    on the first `.get`, in a lane whose whole posture is fail-open."""
    inbox.inbox_path().parent.mkdir(parents=True, exist_ok=True)
    inbox.inbox_path().write_text("[]", encoding="utf-8")
    assert inbox.read_threads() == []
    assert inbox.is_fresh() is False


def test_non_dict_entries_inside_threads_are_dropped() -> None:
    inbox.inbox_path().parent.mkdir(parents=True, exist_ok=True)
    inbox.inbox_path().write_text(
        json.dumps({"fetched_at": int(time.time()), "threads": [{"id": "1"}, "junk", None]}),
        encoding="utf-8",
    )
    assert [t["id"] for t in inbox.read_threads()] == ["1"]


# --------------------------------------------------------------------------- #
# Daemon wiring — the lane only works if something actually fetches
# --------------------------------------------------------------------------- #

def test_the_daemon_registers_the_inbox_fetch_as_a_foreground_task() -> None:
    """Without this Task nothing ever writes the inbox, every reader falls back to the old
    gated poll, and the starvation returns — silently, because the fallback is by design
    indistinguishable from normal operation. So the registration is asserted, not reviewed.

    FOREGROUND on purpose: the bulk lane runs ONE detached child at a time, so a 20-minute
    marketplace refresh would delay a one-second HTTP call that every project's reply
    latency depends on.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import daemon  # noqa: PLC0415

    task = next((t for t in daemon._build_tasks() if t.name == "gh-notify-inbox"), None)
    assert task is not None, "the daemon does not register the fleet-wide inbox fetch"
    assert task.background is False, "the inbox fetch must not queue behind the bulk lane"
    assert task.interval_s == 60, (
        "the fetch cadence IS the account's poll rate now that it is the only caller — it "
        f"must match GitHub's X-Poll-Interval of 60s, got {task.interval_s}"
    )


def test_the_POLLER_actually_writes_the_inbox_end_to_end(tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """The writer half, run for real — `uv`-less, via the interpreter, against a fake `gh`.

    Every other test in this file hands the reader an inbox written BY THE TEST, so all of
    them would still pass with `do_write_inbox` completely broken and the lane permanently
    empty. That is the gap this closes: fetch -> publish -> read, with only the external
    service faked.
    """
    import os
    import subprocess

    root = Path(__file__).resolve().parents[1]
    control = tmp_path / "control"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stdout.write('[{\"id\": \"77\", \"updated_at\": \"2999-01-01T00:00:00Z\"}]')\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)

    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "gh_issues_monitor" / "gh_notify_poll.py"),
         "--write-inbox"],
        capture_output=True, text=True, check=False, timeout=120,
        env={
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(tmp_path),
            "JANITOR_CONTROL_DIR": str(control),
            "CLAUDE_PROJECT_DIR": str(tmp_path / "proj"),
        },
    )
    assert proc.returncode == 0, proc.stderr
    written = json.loads((control / "gh-notify-inbox.json").read_text(encoding="utf-8"))
    assert [t["id"] for t in written["threads"]] == ["77"]
    assert written["fetched_at"] > 0
