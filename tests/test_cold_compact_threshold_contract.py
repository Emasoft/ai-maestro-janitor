"""The cold-compact THRESHOLD contract — harness-relative, and read off a real transcript.

WHY THIS FILE EXISTS. `test_on_session_start_cold_cache.py` pins the *wiring* (which source
values fire, the cooldown, the disabled switch) and to do that it stubs the two things this
file refuses to stub: it monkeypatches `context_tokens_for` so the size is deterministic, and
it sets `CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_MIN_CONTEXT_TOKENS=350000` while DELETING
`CLAUDE_CODE_AUTO_COMPACT_WINDOW`. Both are correct choices for a wiring test — and together
they mean nothing in the suite ever exercised the harness-relative threshold resolution
(owner directive 2026-07-18) or a real transcript flowing into the gate.

WHAT THE HARNESS-RELATIVE NUMBER STILL GOVERNS (2026-08-04). `min_context_tokens()` is
unchanged and still resolves relative to `CLAUDE_CODE_AUTO_COMPACT_WINDOW` — it gates the
PROACTIVE warm-idle path, whose job really is "has the harness's own auto-compaction failed?".
The resolution tests below are therefore still live and still correct.

WHAT IT NO LONGER GOVERNS, and the incident that proves why. The two CACHE-EXPIRED gates
(`should_compact_on_resume`, `should_compact_after_idle`) used to consult it too. That made
them DEAD CODE: with the window at 700000 the bar resolved to 716_000 while the harness itself
compacts at 666_000, so no context could reach it. The USER hit this on 2026-08-04 — several
instances idle since the previous day, each carrying 500-600k, none compacted, every one paying
a full cold cache-write on its first turn. Their ruling: *"simply check the last turn datetime.
if it is older than 55 minutes, it should inject the compact command. no matter the value of the
context."* The prompt cache expires on TIME, not on size, and the window is a per-project knob
they change often — so coupling an unrelated bar to it made the trigger swing for no reason.

The old tripwire here asserted the opposite ("a 270k context must NOT fire") and has been
INVERTED rather than deleted, because the direction of the guard is the whole value:
`test_the_tripwire_a_small_cold_context_MUST_fire` now catches anyone re-coupling the cold path
to a size bar. Fix the criterion, never the code — in whichever direction the owner has ruled.

Everything here is real: real transcript files, real mtimes, real env resolution, no stubs.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_ROOT / "scripts"))

from lib import cold_cache_compact as ccc  # noqa: E402
from lib import token_meter  # noqa: E402

# Every knob that participates in the resolution, so a developer's shell can never decide a
# test's outcome (the "test reporting on the tester" class of flake conftest.py names).
_KNOBS = (
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
    "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_MIN_CONTEXT_TOKENS",
    "CLAUDE_PLUGIN_OPTION_COMPACT_BACKSTOP_MARGIN_TOKENS",
    "CLAUDE_PLUGIN_OPTION_CONTEXT_WINDOW_TOKENS",
    "CLAUDE_PLUGIN_OPTION_COMPACT_SUMMARY_TOKENS",
)


@pytest.fixture(autouse=True)
def _pristine_knobs(monkeypatch: pytest.MonkeyPatch):
    """Clear every threshold knob so each test states its own inputs explicitly."""
    for knob in _KNOBS:
        monkeypatch.delenv(knob, raising=False)


def _transcript(path: Path, total: int) -> Path:
    """A transcript whose newest assistant message reports `total` tokens of input context."""
    rows = [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "usage": {
                    "input_tokens": 1_000,
                    "cache_read_input_tokens": total - 11_000,
                    "cache_creation_input_tokens": 10_000,
                    "output_tokens": 500,
                },
            },
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


# --- the harness-relative resolution --------------------------------------------------


def test_the_documented_worked_example_resolves_to_716000(monkeypatch: pytest.MonkeyPatch):
    """`min_context_tokens()` reproduces its own docstring: 700000 -> 666000 -> 716000.

    Pinned because the docstring's worked example is the only statement of the arithmetic,
    and an untested example is a comment that drifts.
    """
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "700000")

    assert ccc.min_context_tokens() == 716_000


def test_the_threshold_sits_above_the_harness_compact_point(monkeypatch: pytest.MonkeyPatch):
    """The janitor is a BACKSTOP: it may only fire above where the harness already compacts.

    If this inverts, the two race at the boundary and the janitor compacts sessions the
    harness was about to handle — the exact behaviour the 2026-07-18 directive removed.
    """
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "700000")
    pred = token_meter.predict_auto_compact(0)

    assert pred is not None
    assert ccc.min_context_tokens() > pred.effective_compact_point


def test_with_no_auto_compact_window_the_threshold_exceeds_the_window():
    """Env unset => threshold ABOVE the context window, so the janitor cannot proactively fire.

    The docstring calls this "the harness owns it entirely". That is a real invariant, not a
    side effect: a context can never exceed its own window, so the gate is unreachable by
    construction. Nothing tested it, and it is one arithmetic slip away from a threshold that
    fires on every large session.
    """
    window = ccc.DEFAULT_CONTEXT_WINDOW_TOKENS

    assert ccc.min_context_tokens() > window


def test_an_explicit_operator_override_wins_verbatim(monkeypatch: pytest.MonkeyPatch):
    """The override is the documented escape hatch and must not be re-derived from the window."""
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "700000")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_MIN_CONTEXT_TOKENS", "420000")

    assert ccc.min_context_tokens() == 420_000


def test_a_tiny_auto_window_is_floored(monkeypatch: pytest.MonkeyPatch):
    """A pathologically small auto-window must not push the threshold under the post-compaction
    floor — below it there is nothing left to reclaim, so firing would be pure loss."""
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "40000")

    assert ccc.min_context_tokens() == ccc.DEFAULT_MIN_CONTEXT_TOKENS


# --- a REAL transcript through the REAL gate ------------------------------------------


def test_a_real_transcript_resolves_its_context_size(tmp_path: Path):
    """`context_tokens_for` sums input + cache_read + cache_creation off an actual file.

    The sibling wiring test stubs this function, so without this the parser and the gate are
    only ever connected in production.
    """
    t = _transcript(tmp_path / "s.jsonl", 750_000)

    assert ccc.context_tokens_for(t) == 750_000


def test_the_gate_fires_on_an_old_transcript_and_stays_quiet_on_a_fresh_one(tmp_path: Path):
    """End to end on real files: the gate reads the last-turn time off an actual transcript's
    mtime, fires when it is past the TTL and stays quiet when it is not.

    Both halves matter — an "it fires" test alone passes just as well on a gate that always
    fires, which is how a regression reaches production looking green.
    """
    now = 1_800_000_000
    old = _transcript(tmp_path / "old.jsonl", 40_000)     # SMALL and stale
    fresh = _transcript(tmp_path / "fresh.jsonl", 900_000)  # HUGE and warm
    os.utime(old, (now - 86_400, now - 86_400))           # last turn: yesterday
    os.utime(fresh, (now - 60, now - 60))                 # last turn: a minute ago

    old_age = ccc.last_turn_age_for(old, now=now)
    fresh_age = ccc.last_turn_age_for(fresh, now=now)
    assert old_age == 86_400
    assert fresh_age == 60

    min_idle = ccc.min_idle_seconds()
    assert ccc.should_compact_on_resume(old_age, min_idle_s=min_idle) is True
    assert ccc.should_compact_on_resume(fresh_age, min_idle_s=min_idle) is False


def test_the_tripwire_a_small_cold_context_MUST_fire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """THE TRIPWIRE, INVERTED by USER directive 2026-08-04.

    It used to assert that a 270k context must NOT fire, guarding the harness-relative
    threshold. That guard is what made the feature dead code: with
    `CLAUDE_CODE_AUTO_COMPACT_WINDOW=700000` the bar resolved to 716_000 while the harness
    itself compacts at 666_000, so NO context could ever reach it and a resumed 500-600k
    session was never compacted — it paid a full cold cache-write on its first turn instead.

    The USER's rule is now: *"simply check the last turn datetime. if it is older than 55
    minutes, it should inject the compact command. no matter the value of the context."* So a
    SMALL, COLD context must fire, and the auto-compact window — a per-project setting they
    change often — must not influence it at all. If this test ever goes green-by-NOT-firing,
    someone has re-coupled the cold path to a size bar and reintroduced the burn.
    """
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "700000")
    now = 1_800_000_000
    t = _transcript(tmp_path / "small_but_cold.jsonl", 40_000)
    os.utime(t, (now - 4_000, now - 4_000))

    assert ccc.context_tokens_for(t) == 40_000            # genuinely small…
    age = ccc.last_turn_age_for(t, now=now)
    assert ccc.should_compact_on_resume(age, min_idle_s=ccc.min_idle_seconds()) is True

    # …and the window knob must not move that verdict, at any value.
    for window in ("100000", "700000", "2000000"):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", window)
        assert ccc.should_compact_on_resume(age, min_idle_s=ccc.min_idle_seconds()) is True


def test_last_turn_age_refuses_to_invent_evidence(tmp_path: Path):
    """Absence of evidence is not evidence of expiry: an unreadable transcript and a
    future mtime (clock skew / a touched file) both yield None, and None never fires."""
    now = 1_800_000_000
    assert ccc.last_turn_age_for(None, now=now) is None
    assert ccc.last_turn_age_for(tmp_path / "does-not-exist.jsonl", now=now) is None

    future = _transcript(tmp_path / "future.jsonl", 50_000)
    os.utime(future, (now + 5_000, now + 5_000))
    assert ccc.last_turn_age_for(future, now=now) is None
    assert ccc.should_compact_on_resume(None, min_idle_s=ccc.min_idle_seconds()) is False
