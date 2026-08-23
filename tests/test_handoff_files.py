"""Tests for per-write handoff filenames (scripts/lib/handoff_files.py) — TRDD-5RXBI65T option D.

The defect being pinned: `.janitor/state/agent-handoff.md` was one fixed path with several
independent writers, so the daemon's cheap auto-composed handoff silently destroyed the model's
expensive semantic one. These tests assert the property that makes that unrepresentable — every
write lands on its own path — plus the reader behaviour that replaces it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import handoff_files as hf  # noqa: E402


def _sd(tmp_path: Path) -> Path:
    os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True, exist_ok=True)
    return sd


def test_session_key_uses_the_transcript_stem_not_the_writer() -> None:
    """session_key derives the TARGET session id from a transcript path, lowercased to 8 chars."""
    key = hf.session_key("/x/projects/-Users-me-proj/d30bf250-a897-4d76-b74d-72783da6048f.jsonl")
    assert key == "d30bf250"
    assert hf.session_key("d30bf250-a897") == "d30bf250"
    assert hf.session_key("") == "", "an unresolvable target must not silently produce a key"
    assert hf.session_key(None) == ""


def test_name_roundtrips_through_parse() -> None:
    """handoff_name output is parseable back into (key, epoch, pid)."""
    name = hf.handoff_name("d30bf250", now=1787469366, pid=4242)
    parsed = hf.parse(name)
    assert parsed is not None
    key, ts, pid = parsed
    assert (key, ts, pid) == ("d30bf250", 1787469366, 4242)


def test_parse_rejects_foreign_names() -> None:
    """Only the exact grammar parses — a state dir holds many unrelated files."""
    for bad in (
        "agent-handoff.md",
        "precompact-handoff.md",
        "agent-handoff-d30bf250-20260823_091606.md",  # no pid
        "agent-handoff-d30bf250-20260823_999999+0200-1.md",  # impossible time
        "heartbeat-cron-id.txt",
    ):
        assert hf.parse(bad) is None, f"{bad!r} must not parse as a handoff"


def test_two_writers_in_the_same_second_produce_two_files(tmp_path: Path) -> None:
    """THE CARD'S CORE PROPERTY: a same-second second write cannot clobber the first."""
    sd = _sd(tmp_path)
    now = 1787469366
    a = hf.write(sd, "d30bf250", "RICH model-authored handoff", now=now)
    # Same key, same second, different process — the pid is the only thing separating them.
    b = Path(sd) / hf.handoff_name("d30bf250", now=now, pid=os.getpid() + 1)
    b.write_text("cheap auto-composed handoff", encoding="utf-8")

    assert a != b, "same-second writes must not collide on one path"
    assert a.read_text(encoding="utf-8") == "RICH model-authored handoff"
    assert len(hf.newest_group(sd)) == 2, "both writes belong to the same session group"


def test_newest_group_returns_one_session_in_write_order(tmp_path: Path) -> None:
    """A session's handoffs replay oldest-first; an older session's group is not mixed in."""
    sd = _sd(tmp_path)
    hf.write(sd, "old11111", "older session", now=1787400000)
    first = hf.write(sd, "d30bf250", "first", now=1787469000)
    second = hf.write(sd, "d30bf250", "second", now=1787469366)

    group = hf.newest_group(sd)
    assert group == [first, second], "newest group, ascending write time"
    assert all("old11111" not in p.name for p in group)


def test_a_late_second_handoff_keeps_its_group_current(tmp_path: Path) -> None:
    """Ranking is by a group's NEWEST member, so a 2-file session outranks a fresh 1-file one."""
    sd = _sd(tmp_path)
    hf.write(sd, "aaaaaaaa", "session A, first", now=1787400000)
    hf.write(sd, "bbbbbbbb", "session B, only", now=1787460000)
    a_late = hf.write(sd, "aaaaaaaa", "session A, later", now=1787470000)

    group = hf.newest_group(sd)
    assert a_late in group, "A wrote most recently, so A is the current group"
    assert len(group) == 2, "the whole of A comes back, not just its newest file"


def test_legacy_single_path_is_still_read(tmp_path: Path) -> None:
    """A pre-D agent-handoff.md is real knowledge — it must not become invisible on upgrade."""
    sd = _sd(tmp_path)
    legacy = sd / hf.LEGACY_NAME
    legacy.write_text("handoff from an older plugin version", encoding="utf-8")

    assert hf.newest_group(sd) == [legacy]
    assert hf.newest(sd) == legacy


def test_keyed_file_outranks_an_older_legacy_file(tmp_path: Path) -> None:
    """Once a keyed handoff exists it wins — legacy is a fallback, not a permanent peer."""
    sd = _sd(tmp_path)
    (sd / hf.LEGACY_NAME).write_text("old", encoding="utf-8")
    os.utime(sd / hf.LEGACY_NAME, (1787400000, 1787400000))
    fresh = hf.write(sd, "d30bf250", "new", now=1787470000)

    assert hf.newest(sd) == fresh
    assert hf.newest_group(sd) == [fresh]


def test_empty_state_dir_is_not_an_error(tmp_path: Path) -> None:
    """No handoff is a normal state (a fresh project), reported as emptiness, never a raise."""
    sd = _sd(tmp_path)
    assert hf.newest_group(sd) == []
    assert hf.newest(sd) is None
    assert hf.newest_group(tmp_path / "does-not-exist") == []
