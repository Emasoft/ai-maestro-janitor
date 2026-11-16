"""Pins that compose_agent_handoff writes a resume directive naming THIS run's own handoff (TRDD-W6DZPXLG)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import cold_cache_compact  # noqa: E402
import compose_agent_handoff  # noqa: E402
import handoff_files  # noqa: E402


def test_resume_directive_names_own_handoff_not_a_newer_foreign_one(
    tmp_path, monkeypatch
) -> None:
    """With a NEWER handoff of another session present, the directive names this run's own absolute path."""
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "deadbeef-abcd-efab-cdef-abcdefabcdef")

    sd = root / ".janitor" / "state"
    sd.mkdir(parents=True)
    foreign = handoff_files.write(sd, "feedface", "foreign session handoff", now=int(time.time()) + 3600)

    transcript = tmp_path / "s.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(cold_cache_compact, "newest_transcript", lambda _root: transcript)

    class _FakeAttempt:
        text = "own session summary"
        outcome = "ok"
        detail = ""

    monkeypatch.setattr(
        compose_agent_handoff.les, "summarize_with_retry", lambda *a, **k: _FakeAttempt()
    )
    monkeypatch.setattr(sys, "argv", ["compose_agent_handoff.py", "--project-root", str(root)])

    assert compose_agent_handoff.main() == 0

    own = list(sd.glob("agent-handoff-deadbeef-*.md"))
    assert len(own) == 1, "main() must write exactly one handoff under this session key"
    assert handoff_files.newest(sd) == foreign, "precondition: the foreign file is the newest"

    directive = (sd / "resume-directive.txt").read_text(encoding="utf-8")
    assert str(own[0].resolve()) in directive
    assert str(foreign) not in directive
    assert "newest" not in directive
