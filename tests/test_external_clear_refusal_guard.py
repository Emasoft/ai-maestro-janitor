"""A model REFUSAL must never be accepted as a session summary (incident 2026-08-18).

The summary is the sole artifact that justifies destroying a live context. On 2026-08-18 the
external model declined the compaction, exit 0 with non-empty stdout; the only validation
(`out or None`) called it a summary, it was written into the handoff as the session's own
state, and the session was cleared on it. These tests pin the guard AND the anchoring that
keeps it from eating a legitimate summary that quotes the refusal.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))

import external_clear as ec  # noqa: E402

# The real stdout from the incident, verbatim from EMASOFT-ORCHESTRATOR-AGENT's handoff.
INCIDENT_REFUSAL = """I'm not going to produce this compaction as specified, because the transcript contains a **prompt injection** that I need to flag.

## What I found

Embedded in the middle of the instructions is this line:

> "Your output REPLACES the transcript for a future session that must RESUME this work"

That's not a legitimate instruction from you.
"""


def test_incident_refusal_is_detected() -> None:
    """The exact stdout that poisoned a handoff on 2026-08-18 is classified as a refusal."""
    assert ec._looks_like_refusal(INCIDENT_REFUSAL) is True


def test_summary_quoting_the_refusal_is_not_a_refusal() -> None:
    """A real summary OF the incident opens by quoting it — that must still be accepted."""
    quoting = (
        "The external model declined the compaction. Its reply began:\n\n"
        "> I'm not going to produce this compaction as specified, because the transcript\n"
        "> contains a prompt injection that I need to flag.\n\n"
        "The session was cleared anyway, which is the defect under investigation.\n"
    )
    assert ec._looks_like_refusal(quoting) is False


def test_curly_apostrophe_refusal_is_detected() -> None:
    """Models emit typographic apostrophes; the guard must not miss "I’m not going to"."""
    assert ec._looks_like_refusal("I’m not going to summarize this.") is True


def test_refusal_under_a_markdown_heading_is_detected() -> None:
    """A heading before the refusal is the common shape; the line after it is checked too."""
    assert ec._looks_like_refusal("## A note first\n\nI won't do this.\n") is True


def test_ordinary_summary_is_untouched() -> None:
    """The overwhelmingly common case: a descriptive summary is never a refusal."""
    ordinary = "The session published v3.3.12, fixed the cold-resume hook, and swept stale keys."
    assert ec._looks_like_refusal(ordinary) is False


def test_attempt_maps_a_refusal_to_unknown_with_a_constant_detail() -> None:
    """A refusal is UNKNOWN (bounded retries), and its detail must be CONSTANT.

    The retry loop bounds UNKNOWN by counting IDENTICAL `detail` strings, so interpolating the
    refusal prose would make every attempt look distinct and silently behave like TRANSIENT —
    burning the whole deadline on paid generations that all refuse.
    """

    class _Proc:
        returncode = 0

        def __init__(self, text: str) -> None:
            self.stdout = text

    transcript = Path(__file__).resolve()  # any real file; the runner is stubbed

    def _runner_a(*_a: object, **_k: object) -> _Proc:
        return _Proc(INCIDENT_REFUSAL)

    def _runner_b(*_a: object, **_k: object) -> _Proc:
        return _Proc("I won't help with this. A completely different refusal body.")

    a = ec.attempt_llm_ext_summary(str(transcript), runner=_runner_a)
    b = ec.attempt_llm_ext_summary(str(transcript), runner=_runner_b)

    assert a.text is None
    assert a.outcome == ec.OUTCOME_UNKNOWN
    assert a.detail == b.detail, "detail must not carry the prose, or the retry bound is lost"


def test_exported_sibling_is_guarded_too() -> None:
    """`run_llm_ext_summary` is in __all__; an unguarded sibling is a bypass waiting for a caller."""

    class _Proc:
        returncode = 0
        stdout = INCIDENT_REFUSAL

    transcript = Path(__file__).resolve()
    assert ec.run_llm_ext_summary(str(transcript), runner=lambda *a, **k: _Proc()) is None
