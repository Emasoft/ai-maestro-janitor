"""Card 1 item 6 — the LOOP GUARD (TRDD-L32WC0H7).

Three separate guarantees, each pinned by its own test:

  1. `SessionStart` with `source` in {`clear`, `compact`} — a RE-ENTRY into a session this
     hook's own chain just shrunk — must never even ASK whether the cache is stale. The hook's
     own module docstring calls this "THE LOOP GUARD" and names the failure mode explicitly:
     "Acting on those is an infinite loop: shrink -> SessionStart(compact) -> shrink -> ...".
     `on-session-start-cold-cache-clear.py::main` short-circuits on `RESUME_SOURCES` before
     importing anything that could read a transcript or shell out to a probe — this test proves
     that ordering by making the staleness probe RAISE and asserting the hook still returns 0.
  2. A FAILED compaction attempt records `evaluated`, never `fired` — `cold_cache_compact.py`'s
     `mark_fired`/`mark_clear_fired` (fire stamps, gate cooldown) and `mark_evaluated` (spacing
     stamp, gates nothing) write to DIFFERENT files, so a HOLD verdict that only calls
     `mark_evaluated` must not also start a cooldown a real fire would.
  3. At most one automatic CLEAR per session per `CLEAR_COOLDOWN` window, WHATEVER THE TRIGGER —
     `should_clear_when_long_idle`'s fire path (`dispatch.py`), `should_clear_externally`'s
     (`external_handoff_clear.py`), and `should_clear_on_resume`'s (same file, `--on-resume`)
     all stamp and read the SAME `idle-clear-fired.ts` file via `mark_clear_fired`/
     `clear_in_cooldown`, so whichever fires first stands every other one down for the window.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import cold_cache_compact as ccc  # noqa: E402
import external_clear as ec  # noqa: E402


def _hook():
    """Import the dash-named hook script as a fresh module (own copy of module globals)."""
    path = _ROOT / "scripts" / "hooks" / "on-session-start-cold-cache-clear.py"
    spec = importlib.util.spec_from_file_location("cold_cache_clear_loop_guard_hook", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_main_with_source(monkeypatch, source: str, tmp_path: Path) -> int:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    monkeypatch.setenv(ec.ENABLED_ENV, "1")  # prove the short-circuit beats even an ENABLED lever
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(f'{{"source": "{source}", "session_id": "s1", "cwd": "{tmp_path}"}}'),
    )
    return _hook().main()


def test_source_compact_never_evaluates_cache_staleness(monkeypatch, tmp_path):
    """Item 6 part 1. `cache_certainly_expired` is the ONE subprocess/probe call the staleness
    evaluation needs — making it raise proves the hook never reaches it for `source=compact`."""

    def _boom(*a, **kw):
        raise AssertionError("cache staleness was evaluated for a compact re-entry")

    monkeypatch.setattr(ec, "cache_certainly_expired", _boom)
    assert _run_main_with_source(monkeypatch, "compact", tmp_path) == 0


def test_source_clear_never_evaluates_cache_staleness(monkeypatch, tmp_path):
    """Item 6 part 1, the `clear` re-entry — the MOST COMMON source's sibling in the same
    allow-list, per the hook's own docstring measurement (38 compact / 7 resume / 3 clear)."""

    def _boom(*a, **kw):
        raise AssertionError("cache staleness was evaluated for a clear re-entry")

    monkeypatch.setattr(ec, "cache_certainly_expired", _boom)
    assert _run_main_with_source(monkeypatch, "clear", tmp_path) == 0



def test_resume_source_routes_through_the_shared_recovery_helper_and_the_widened_reader(
    monkeypatch, tmp_path
):
    """TRDD-L32WC0H7 card 1 follow-up items 1+2: the SessionStart hook must feed
    `should_clear_on_resume` the SHARED `external_clear.recovery_pending` reading (not an inline
    flag check) and `cold_cache_compact.context_tokens_for_resume` (not the plain tail-only
    reader) — this proves the WIRING, independent of the deciders' own already-pinned policy."""
    captured: dict = {}

    def _fake_should_clear_on_resume(**kwargs):
        captured.update(kwargs)
        return ec.ClearVerdict(False, why="test-stub")

    # No signal from the (test-suite-blocked) agentlensPro subprocess -- irrelevant to this
    # test, which is only about WHAT gets passed to should_clear_on_resume, not the verdict.
    monkeypatch.setattr(ec, "cache_certainly_expired", lambda *a, **kw: None)
    monkeypatch.setattr(ec, "recovery_pending", lambda sd: True)
    monkeypatch.setattr(ccc, "context_tokens_for_resume", lambda *a, **kw: 424_242)
    monkeypatch.setattr(ec, "should_clear_on_resume", _fake_should_clear_on_resume)
    assert _run_main_with_source(monkeypatch, "resume", tmp_path) == 0
    assert captured["recovery_pending"] is True
    assert captured["context_tokens"] == 424_242


def test_a_failed_attempt_records_evaluated_never_fired(tmp_path):
    """Item 6 part 2. `mark_evaluated` (spacing) and `mark_fired`/`mark_clear_fired` (cooldown)
    are DIFFERENT stamps — recording only the former must leave the cooldown/`in_cooldown` gate
    untouched, so a HOLD verdict neither burns the cooldown nor blocks a real fire that follows."""
    sd = tmp_path
    now = 1_000_000

    ccc.mark_evaluated(sd, now=now)
    assert ccc.evaluated_recently(sd, now=now + 1) is True
    # The compact cooldown is untouched by an evaluation alone.
    assert ccc.in_cooldown(sd, now=now + 1) is False
    # Same for the clear cooldown.
    assert ccc.clear_in_cooldown(sd, now=now + 1) is False

    # A REAL fire, in contrast, DOES start the cooldown.
    ccc.mark_fired(sd, now=now)
    assert ccc.in_cooldown(sd, now=now + 1) is True
    ccc.mark_clear_fired(sd, now=now)
    assert ccc.clear_in_cooldown(sd, now=now + 1) is True


def test_at_most_one_automatic_clear_per_session_whatever_the_trigger(tmp_path):
    """Item 6 part 3. `should_clear_when_long_idle`'s caller, `should_clear_externally`, and
    `should_clear_on_resume` all gate on — and, on a fire, all stamp — the SAME file
    (`cold_cache_compact.mark_clear_fired` / `.clear_in_cooldown`), so whichever trigger wins the
    race stands every other one down for the window, regardless of which one fired."""
    sd = tmp_path
    now = 2_000_000

    assert ccc.clear_in_cooldown(sd, now=now) is False

    # should_clear_when_long_idle's OWN fire path stamps this exact function (dispatch.py's
    # `_phase_idle_clear_nudge` calls `cold_cache_compact.mark_clear_fired` on a real send).
    ccc.mark_clear_fired(sd, now=now)

    # Now EVERY OTHER trigger reads the shared stamp as cooling down — `should_clear_externally`
    # and `should_clear_on_resume` both take `in_cooldown` as an injected fact, fed by this same
    # reader in their real callers (`external_handoff_clear.py::_decide`,
    # `on-session-start-cold-cache-clear.py::main`).
    assert ccc.clear_in_cooldown(sd, now=now + 5) is True

    v_external = ec.should_clear_externally(
        idle_seconds=99_999,
        last_turn_age_s=30,
        ttl_minutes=5,
        seconds_to_next_fire=300,
        context_tokens=900_000,
        min_context=150_000,
        min_idle_s=60,
        headroom_s=60,
        active_waiting=False,
        in_cooldown=ccc.clear_in_cooldown(sd, now=now + 5),
        awaiting_user=False,
    )
    assert v_external.fire is False and v_external.why == "cooldown"

    v_resume = ec.should_clear_on_resume(
        source="resume",
        cache_expired=True,
        context_tokens=900_000,
        min_context=150_000,
        in_cooldown=ccc.clear_in_cooldown(sd, now=now + 5),
        already_fired_this_session=False,
    )
    assert v_resume.fire is False and v_resume.why == "cooldown"
