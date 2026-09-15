"""`user_intent.recently_interrupted` — the ESC-interrupt breadcrumb (owner complaint 2026-09-15:
"esc key unable to stop the current agent from running"). An Esc/Ctrl-C keypress writes NO
keystroke the `typing_now` probe can see, so a queued self-injector types over "I just stopped it"
the moment the pane goes idle. This module reads Claude Code's OWN auto-generated
`[Request interrupted by user]` transcript record instead, using real (non-mocked) `.jsonl` files
on disk — the shape was verified against real `~/.claude/projects/*/*.jsonl` transcripts before
writing these tests.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))

import user_intent  # noqa: E402

NOW = 1_784_000_000.0


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch)) + ".000Z"


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _interrupt_record(age_s: float, *, for_tool_use: bool = False) -> dict:
    text = "[Request interrupted by user for tool use]" if for_tool_use else "[Request interrupted by user]"
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        "timestamp": _iso(NOW - age_s),
    }


def _prompt_record(age_s: float, text: str = "hello") -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        "timestamp": _iso(NOW - age_s),
    }


def test_recent_interrupt_returns_its_age(tmp_path: Path) -> None:
    """An interrupt 30s ago, inside the default 300s cooldown, returns ~30 as its age."""
    t = tmp_path / "session.jsonl"
    _write_jsonl(t, [_interrupt_record(30)])

    age = user_intent.recently_interrupted("proj", now=NOW, transcript_path=t)

    assert age is not None
    assert 29.0 <= age <= 31.0


def test_old_interrupt_outside_window_returns_none(tmp_path: Path) -> None:
    """An interrupt 10 minutes ago is outside a 300s cooldown -> None (proceed, don't defer)."""
    t = tmp_path / "session.jsonl"
    _write_jsonl(t, [_interrupt_record(600)])

    assert user_intent.recently_interrupted("proj", now=NOW, transcript_path=t) is None


def test_no_transcript_returns_none(tmp_path: Path) -> None:
    """A missing/non-existent transcript path fails OPEN — never blocks the caller's decision."""
    missing = tmp_path / "does-not-exist.jsonl"

    assert user_intent.recently_interrupted("proj", now=NOW, transcript_path=missing) is None


def test_no_project_transcript_dir_returns_none(tmp_path: Path) -> None:
    """No `transcript_path` given -> the cooldown is SKIPPED (session unknown), never a guess."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    age = user_intent.recently_interrupted(str(tmp_path / "some-project"), now=NOW, home=fake_home)

    assert age is None


def test_malformed_trailing_lines_still_find_an_earlier_interrupt(tmp_path: Path) -> None:
    """Junk at the tail must not hide a real interrupt written a few lines earlier."""
    t = tmp_path / "session.jsonl"
    lines = [
        json.dumps(_interrupt_record(45)),
        "{not valid json at all",
        "",
        "   ",
    ]
    t.write_text("\n".join(lines) + "\n", encoding="utf-8")

    age = user_intent.recently_interrupted("proj", now=NOW, transcript_path=t)

    assert age is not None
    assert 44.0 <= age <= 46.0


def test_interrupted_for_tool_use_variant_also_matches(tmp_path: Path) -> None:
    """The "for tool use" suffix is a real, observed variant — prefix match must catch it too."""
    t = tmp_path / "session.jsonl"
    _write_jsonl(t, [_interrupt_record(20, for_tool_use=True)])

    age = user_intent.recently_interrupted("proj", now=NOW, transcript_path=t)

    assert age is not None
    assert 19.0 <= age <= 21.0


def test_no_interrupt_at_all_returns_none(tmp_path: Path) -> None:
    """A transcript with only ordinary prompts (no interrupt record) never defers."""
    t = tmp_path / "session.jsonl"
    _write_jsonl(t, [_prompt_record(10), _prompt_record(5)])

    assert user_intent.recently_interrupted("proj", now=NOW, transcript_path=t) is None


def test_session_scoped_path_beats_newest_by_mtime_fallback(tmp_path: Path) -> None:
    """No `_newest_transcript` guessing anymore: omitting `transcript_path` skips the cooldown
    even when a newer, uninterrupted transcript exists for the same project slug, and passing
    `transcript_path` explicitly still finds a real interrupt in that exact file."""
    home = tmp_path / "home"
    slug_dir = home / ".claude" / "projects" / "my-proj"
    slug_dir.mkdir(parents=True)

    older_but_interrupted = slug_dir / "session-a.jsonl"
    _write_jsonl(older_but_interrupted, [_interrupt_record(30)])

    newer_but_clean = slug_dir / "session-b.jsonl"
    _write_jsonl(newer_but_clean, [_prompt_record(5)])

    now_ts = time.time()
    import os

    os.utime(older_but_interrupted, (now_ts - 100, now_ts - 100))
    os.utime(newer_but_clean, (now_ts, now_ts))

    # No transcript_path at all -> skipped (session unknown), never a guess at "the newest one".
    skipped_age = user_intent.recently_interrupted("/whatever/my-proj", now=NOW, home=home)
    assert skipped_age is None

    # The session-scoped path finds the real interrupt directly.
    scoped_age = user_intent.recently_interrupted(
        "/whatever/my-proj", now=NOW, transcript_path=older_but_interrupted, home=home
    )
    assert scoped_age is not None
    assert 29.0 <= scoped_age <= 31.0


def test_window_override_shortens_the_cooldown(tmp_path: Path) -> None:
    """`window_s` overrides the default 300s cooldown -- 30s ago is outside a 10s window."""
    t = tmp_path / "session.jsonl"
    _write_jsonl(t, [_interrupt_record(30)])

    assert user_intent.recently_interrupted("proj", window_s=10, now=NOW, transcript_path=t) is None


def test_resolve_interrupt_cooldown_s_env_override() -> None:
    """`resolve_interrupt_cooldown_s` reads the documented env var, defends against garbage."""
    assert user_intent.resolve_interrupt_cooldown_s({}) == user_intent.DEFAULT_INTERRUPT_COOLDOWN_S
    assert user_intent.resolve_interrupt_cooldown_s({user_intent.INTERRUPT_COOLDOWN_ENV: "60"}) == 60
    # Non-int and <=0 both coerce back to the default -- never a silently-disabled cooldown.
    assert (
        user_intent.resolve_interrupt_cooldown_s({user_intent.INTERRUPT_COOLDOWN_ENV: "not-a-number"})
        == user_intent.DEFAULT_INTERRUPT_COOLDOWN_S
    )
    assert (
        user_intent.resolve_interrupt_cooldown_s({user_intent.INTERRUPT_COOLDOWN_ENV: "0"})
        == user_intent.DEFAULT_INTERRUPT_COOLDOWN_S
    )


def test_unknown_session_skips_cooldown_and_logs(tmp_path: Path, monkeypatch) -> None:
    """No `transcript_path` -> the cooldown is skipped (never guessed) and the skip is logged."""
    logged: list[tuple[str, str]] = []
    monkeypatch.setattr(user_intent.state, "log_line", lambda name, msg: logged.append((name, msg)))

    age = user_intent.recently_interrupted("proj", now=NOW)

    assert age is None
    assert any("session unknown" in msg for _name, msg in logged)


def test_newer_user_prompt_after_interrupt_returns_none(tmp_path: Path) -> None:
    """An interrupt followed by a real, later user prompt means the user is back -> None."""
    t = tmp_path / "session.jsonl"
    _write_jsonl(t, [_interrupt_record(60), _prompt_record(10, "let's keep going")])

    assert user_intent.recently_interrupted("proj", now=NOW, transcript_path=t) is None


def test_prefix_only_text_does_not_count_as_interrupt(tmp_path: Path) -> None:
    """A compaction summary merely QUOTING the marker text must not be treated as a real
    interrupt: the match is EXACT, never a prefix match."""
    t = tmp_path / "session.jsonl"
    _write_jsonl(
        t,
        [_prompt_record(30, "summary: [Request interrupted by user] happened earlier in the session")],
    )

    assert user_intent.recently_interrupted("proj", now=NOW, transcript_path=t) is None


def test_large_tool_result_after_interrupt_still_found(tmp_path: Path) -> None:
    """A 150 KB tool-result line written right after the Esc must not push the interrupt
    record out of a fixed-size tail read -- the scan must grow its window until it finds it."""
    t = tmp_path / "session.jsonl"
    huge_tool_result = {
        "type": "tool_result",
        "message": {"role": "assistant", "content": "x" * (150 * 1024)},
        "timestamp": _iso(NOW - 5),
    }
    lines = [
        json.dumps(_interrupt_record(30)),
        json.dumps(huge_tool_result),
    ]
    t.write_text("\n".join(lines) + "\n", encoding="utf-8")

    age = user_intent.recently_interrupted("proj", now=NOW, transcript_path=t)

    assert age is not None
    assert 29.0 <= age <= 31.0


def test_multi_doubling_window_growth_still_finds_the_interrupt(tmp_path: Path, monkeypatch) -> None:
    """Force several window-doubling iterations (`_INTERRUPT_SCAN_CHUNK_BYTES` shrunk to 64) so
    an interrupt sitting well before the tail requires >1 growth step -- proves the
    re-scan-the-whole-window approach doesn't lose or misalign records across doublings. Asserts
    on the `_tail_bytes` call count too, not just the final answer: without it a future change
    that made the loop succeed on iteration 1 would still pass silently, testing nothing."""
    monkeypatch.setattr(user_intent, "_INTERRUPT_SCAN_CHUNK_BYTES", 64)
    real_tail_bytes = user_intent._tail_bytes
    calls: list[int] = []

    def _counting_tail_bytes(path, max_bytes=64 * 1024):
        calls.append(max_bytes)
        return real_tail_bytes(path, max_bytes)

    monkeypatch.setattr(user_intent, "_tail_bytes", _counting_tail_bytes)

    t = tmp_path / "session.jsonl"
    # Non-`user` padding so the (c) "newer user prompt -> user is back" short-circuit can never
    # fire on it -- these records are only here to push the interrupt out of a tiny first window.
    padding = [
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": f"padding line {i}" * 4},
            "timestamp": _iso(NOW - i),
        }
        for i in range(20)
    ]
    lines = [json.dumps(_interrupt_record(30)), *[json.dumps(r) for r in padding]]
    t.write_text("\n".join(lines) + "\n", encoding="utf-8")

    age = user_intent.recently_interrupted("proj", now=NOW, transcript_path=t)

    assert age is not None
    assert 29.0 <= age <= 31.0
    assert len(calls) > 1, "the test must actually force multiple window-doubling iterations"
    assert len(set(calls)) > 1, "must actually try more than one distinct window size"
