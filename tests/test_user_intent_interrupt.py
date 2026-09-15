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
    """No `~/.claude/projects/<slug>/` at all (no transcript_path override either) -> None."""
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
    """Two live sessions of the SAME project must not share a cooldown: an explicit
    `transcript_path` (the session that actually got interrupted) must be honored even though a
    DIFFERENT, newer-by-mtime transcript for the same project slug exists and holds no interrupt
    at all -- the exact two-session mix-up the newest-mtime fallback alone would get wrong."""
    home = tmp_path / "home"
    slug_dir = home / ".claude" / "projects" / "my-proj"
    slug_dir.mkdir(parents=True)

    older_but_interrupted = slug_dir / "session-a.jsonl"
    _write_jsonl(older_but_interrupted, [_interrupt_record(30)])

    newer_but_clean = slug_dir / "session-b.jsonl"
    _write_jsonl(newer_but_clean, [_prompt_record(5)])

    # Force session-b to be the newest by mtime, so the fallback (no transcript_path) would
    # pick IT and wrongly report "not interrupted".
    now_ts = time.time()
    import os

    os.utime(older_but_interrupted, (now_ts - 100, now_ts - 100))
    os.utime(newer_but_clean, (now_ts, now_ts))

    # The fallback path (no transcript_path) resolves to the newer, uninterrupted session.
    fallback_age = user_intent.recently_interrupted("/whatever/my-proj", now=NOW, home=home)
    assert fallback_age is None, "sanity: the fallback really did pick the newer, clean session"

    # The session-scoped path overrides the fallback and finds the real interrupt.
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
