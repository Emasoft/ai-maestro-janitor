"""Pins the marker prepend in compose_agent_handoff.py's write path (TRDD follow-on to bf553628).

WHY THIS EXISTS. `main()` prepends `handoff_files.COMPOSED_MARKER` before writing the composed
handoff. Nothing tested that prepend directly: if it is dropped, `clear_trigger.
check_handoff_concise` stops recognizing the file as composer-authored and resumes flagging
`too-large` on every oversized composer handoff — silently, because no test would redden.

WHAT IS AND IS NOT COVERED. `main()`'s only external dependency is `llm-ext` via
`llm_ext_summary.summarize_with_retry` (TRDD-RAEGS1D5 card 3 C2 moved that function, and the
rest of the manual lane's llm-ext machinery, out of `external_clear.py` and into
`scripts/lib/llm_ext_summary.py` — the automatic SessionStart lane no longer touches llm-ext at
all), which can shell out for minutes — never invoked here. This test monkeypatches
`summarize_with_retry` and `cold_cache_compact.newest_transcript` to return a canned oversized
summary, then runs the REAL `main()` body: the real marker prepend, the real
`handoff_files.write`, and the real `clear_trigger.check_handoff_concise` on the resulting file.
Not covered: the llm-ext subprocess invocation itself, and the retry/deadline machinery inside
`summarize_with_retry` (both are `llm_ext_summary.py`'s own test file's job).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import clear_trigger  # noqa: E402
import cold_cache_compact  # noqa: E402
import compose_agent_handoff  # noqa: E402
import handoff_files  # noqa: E402


def test_a_composed_handoff_is_stamped_and_passes_the_size_exemption(
    tmp_path, monkeypatch
) -> None:
    """The real main() write path must prepend COMPOSED_MARKER, and the stamped file must clear
    check_handoff_concise's size/reference gate even when far over the raw byte budget — the
    end-to-end claim commit bf553628 rests on."""
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "deadbeef-cafe-babe-feed-facefeedface")

    transcript = tmp_path / "s.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        cold_cache_compact, "newest_transcript", lambda _root: transcript
    )

    # Oversized on purpose: `clear_trigger._HANDOFF_MAX_BYTES` is 4096; this summary alone is
    # well over it, so a non-exempt file would fail on `too-large` and prove nothing.
    oversized_summary = "S" * 40_000

    class _FakeAttempt:
        text = oversized_summary
        outcome = "ok"
        detail = ""

    monkeypatch.setattr(
        compose_agent_handoff.les, "summarize_with_retry", lambda *a, **k: _FakeAttempt()
    )

    argv = ["compose_agent_handoff.py", "--project-root", str(root)]
    monkeypatch.setattr(sys, "argv", argv)

    rc = compose_agent_handoff.main()
    assert rc == 0

    state_dir = root / ".janitor" / "state"
    written = handoff_files.newest(state_dir)
    assert written is not None, "main() must have written a handoff file"

    text = written.read_text(encoding="utf-8")
    assert text.startswith(handoff_files.COMPOSED_MARKER), (
        "compose_agent_handoff.main() must prepend the composed marker — without it "
        "check_handoff_concise treats a real composer handoff as an ordinary, non-exempt one"
    )

    ok, reasons = clear_trigger.check_handoff_concise(text)
    assert ok, (
        f"a marker-stamped composer handoff must clear the size/reference exemption: {reasons}"
    )


def test_compose_hands_the_project_state_folder_to_the_summarizer(tmp_path, monkeypatch) -> None:
    """main() must pass `state_dir=<project-root>/.janitor/state` to summarize_with_retry: the
    redacted transcript copy llm-ext reads lives in a per-run folder under it (TRDD-TKQ274RE). The
    fake in the test above swallows every argument, so a dropped `state_dir=` would go unseen."""
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "c0ffee00-abcd-4abc-8abc-abcdefabcdef")

    transcript = tmp_path / "s.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        cold_cache_compact, "newest_transcript", lambda _root: transcript
    )

    class _FakeAttempt:
        text = "a short summary"
        outcome = "ok"
        detail = ""

    seen: dict[str, object] = {}

    def _capture(*args: object, **kwargs: object) -> _FakeAttempt:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return _FakeAttempt()

    monkeypatch.setattr(compose_agent_handoff.les, "summarize_with_retry", _capture)
    monkeypatch.setattr(
        sys, "argv", ["compose_agent_handoff.py", "--project-root", str(root), "--dry-run"]
    )

    assert compose_agent_handoff.main() == 0

    assert seen["args"] == (str(transcript),)
    kwargs = seen["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs.get("state_dir") == root.resolve() / ".janitor" / "state"


def test_an_oversized_summary_is_capped_before_it_is_written(tmp_path, monkeypatch, capsys) -> None:
    """A summary over handoff_files.COMPOSED_MAX_BYTES must land capped, with a truncation trailer,
    and HANDOFF_READY must report the capped size (TRDD-OWH1R0M9, issue 364 part b)."""
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "deadbeef-cafe-babe-feed-facefeedface")
    transcript = tmp_path / "s.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(cold_cache_compact, "newest_transcript", lambda _root: transcript)

    # Multi-byte lines on purpose: the cut must never land inside a character.
    huge = "\n".join(f"line {i} éè" for i in range(30_000))
    assert len(huge.encode("utf-8")) > 3 * handoff_files.COMPOSED_MAX_BYTES

    class _FakeAttempt:
        text = huge
        outcome = "ok"
        detail = ""

    monkeypatch.setattr(
        compose_agent_handoff.les, "summarize_with_retry", lambda *a, **k: _FakeAttempt()
    )
    monkeypatch.setattr(sys, "argv", ["compose_agent_handoff.py", "--project-root", str(root)])

    assert compose_agent_handoff.main() == 0

    written = handoff_files.newest(root / ".janitor" / "state")
    assert written is not None
    raw = written.read_bytes()
    # The marker line is prepended to the capped text, so allow for it on top of the cap.
    assert len(raw) <= handoff_files.COMPOSED_MAX_BYTES + len(handoff_files.COMPOSED_MARKER) + 1
    text = raw.decode("utf-8")  # raises if the cut split a multi-byte character
    assert "handoff truncated" in text
    ready = capsys.readouterr().out.split("HANDOFF_READY ")[1].split()[0]
    assert int(ready) <= handoff_files.COMPOSED_MAX_BYTES


def test_cap_composed_leaves_a_fitting_summary_untouched() -> None:
    """Text at or under the cap is returned byte-identical; only an oversized one is cut."""
    text = "x" * handoff_files.COMPOSED_MAX_BYTES
    assert handoff_files.cap_composed(text) == text
    assert handoff_files.cap_composed(text + "y") != text + "y"


def test_cap_composed_keeps_both_the_first_and_the_last_line() -> None:
    """An oversized summary keeps its unique first AND last line (the current state and next
    action sit at the end), fits the cap, and names the dropped middle; head-only dropped the last."""
    body = "\n".join(f"filler line {i}" for i in range(20_000))
    text = f"FIRST-UNIQUE-LINE\n{body}\nLAST-UNIQUE-LINE: next action is X"
    cap = handoff_files.COMPOSED_MAX_BYTES
    assert len(text.encode("utf-8")) > 2 * cap
    out = handoff_files.cap_composed(text)
    assert len(out.encode("utf-8")) <= cap
    assert out.startswith("FIRST-UNIQUE-LINE\n")
    assert out.endswith("LAST-UNIQUE-LINE: next action is X")
    assert "bytes dropped from the middle" in out
    assert "session transcript" in out


def test_cap_composed_never_splits_a_multibyte_character_at_either_cut() -> None:
    """Multi-byte-heavy input with no newlines (so both cuts hit characters) stays valid UTF-8
    and within the cap, across several offsets of the cut points."""
    for cap in (1000, 1001, 1002, 1003, 4096):
        out = handoff_files.cap_composed("é€𝄞" * 5000, max_bytes=cap)
        out.encode("utf-8").decode("utf-8")  # a lone surrogate or split char would raise
        assert len(out.encode("utf-8")) <= cap
        assert "�" not in out


def test_cap_composed_holds_the_bound_for_a_cap_smaller_than_the_marker() -> None:
    """A cap too small for the marker plus content gets a plain hard cut: still <= max_bytes,
    still valid UTF-8, never an exception (including a zero cap)."""
    for cap in (0, 1, 3, 50, 100, 150):
        out = handoff_files.cap_composed("é\n€𝄞" * 400, max_bytes=cap)
        assert len(out.encode("utf-8")) <= cap
