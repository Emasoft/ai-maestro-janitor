"""Pins the marker prepend in compose_agent_handoff.py's write path (TRDD follow-on to bf553628).

WHY THIS EXISTS. `main()` prepends `handoff_files.COMPOSED_MARKER` before writing the composed
handoff. Nothing tested that prepend directly: if it is dropped, `clear_trigger.
check_handoff_concise` stops recognizing the file as composer-authored and resumes flagging
`too-large` on every oversized composer handoff — silently, because no test would redden.

WHAT IS AND IS NOT COVERED. `main()`'s only external dependency is `llm-ext` via
`ec.summarize_with_retry`, which can shell out for minutes — never invoked here (see
test_external_clear_llm_ext.py's own rationale for not calling the real CLI). This test
monkeypatches `summarize_with_retry` and `cold_cache_compact.newest_transcript` to return a
canned oversized summary, then runs the REAL `main()` body: the real marker prepend, the real
`handoff_files.write`, and the real `clear_trigger.check_handoff_concise` on the resulting file.
Not covered: the llm-ext subprocess invocation itself (that is `external_clear.py`'s own test
file's job), and the retry/deadline machinery inside `summarize_with_retry`.
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
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "deadbeef-0000-0000-0000-000000000000")

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
        compose_agent_handoff.ec, "summarize_with_retry", lambda *a, **k: _FakeAttempt()
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
