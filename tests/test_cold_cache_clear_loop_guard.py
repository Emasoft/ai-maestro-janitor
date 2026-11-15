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
import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import cold_cache_compact as ccc  # noqa: E402
import external_clear as ec  # noqa: E402
import global_state as gs  # noqa: E402
import state  # noqa: E402


def _hook():
    """Import the dash-named hook script as a fresh module (own copy of module globals)."""
    path = _ROOT / "scripts" / "hooks" / "on-session-start-cold-cache-clear.py"
    spec = importlib.util.spec_from_file_location("cold_cache_clear_loop_guard_hook", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _pin_module_identity(monkeypatch):
    """Make `sys.modules` hand the hook the SAME module objects this file imported and patches.

    WHY: ~22 other test files isolate themselves with `del sys.modules["state"]` (or pop
    `global_state`, ...). This file binds `ccc`/`ec`/`gs`/`state` once, at collection; under
    xdist (or any run where such a test precedes these) the entries are gone by the time the
    hook runs, so the hook's lazy `import external_clear` / `import state` loads FRESH copies.
    Every `monkeypatch.setattr(ec, ...)`, `state.log_line` capture and `gs.automation_python_path`
    patch here then lands on an orphan the hook never calls: the real decision runs, no log line
    is captured and no watcher is spawned. Run alone the entries survive, which is why the file
    passed by itself. Re-registering the objects under test is the minimal fix."""
    for name, mod in (
        ("cold_cache_compact", ccc),
        ("external_clear", ec),
        ("global_state", gs),
        ("state", state),
    ):
        monkeypatch.setitem(sys.modules, name, mod)


def _run_main_with_source(
    monkeypatch, source: str, tmp_path: Path, extra: dict | None = None
) -> int:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    monkeypatch.setenv(ec.ENABLED_ENV, "1")  # prove the short-circuit beats even an ENABLED lever
    payload = {"source": source, "session_id": "s1", "cwd": str(tmp_path), **(extra or {})}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return _hook().main()


def _write_transcript(path: Path, tokens: int) -> Path:
    """A real one-entry transcript whose sole assistant usage sums to `tokens`."""
    path.write_text(
        json.dumps(
            {
                "type": "assistant",
                "uuid": "u1",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"id": "m1", "usage": {"input_tokens": tokens}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _capture_watcher_spawn(monkeypatch) -> dict:
    """Intercept ONLY the watcher spawn (`external_handoff_clear.py`) and record its argv; any
    other `subprocess.Popen` in this process runs for real. Also pins the TCC-stable interpreter
    resolution, which shells out to `codesign` and is denied by this suite's subprocess sandbox."""
    captured: dict = {}
    real_popen = subprocess.Popen
    watcher_path = str(_ROOT / "scripts" / "external_handoff_clear.py")

    def _fake_popen(argv, **kwargs):  # noqa: ANN001, ANN003
        if any(watcher_path in str(a) for a in argv):
            captured["argv"] = [str(a) for a in argv]

            class _Proc:
                def wait(self, timeout=None):  # noqa: ANN001, ARG002
                    return 0

            return _Proc()
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(gs, "automation_python_path", lambda: sys.executable)
    # Patch the SHARED `subprocess` module object: `_run_main_with_source` builds a FRESH hook
    # module each call, so a per-module patch would patch a copy nobody executes.
    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    return captured


def _capture_hook_log(monkeypatch) -> list[str]:
    """Record every `cold-cache-clear` log line the hook writes (the decision line carries
    `fire=`, `why=` and the `transcript=` the verdict was measured from)."""
    lines: list[str] = []
    real_log_line = state.log_line

    def _log_line(name: str, message: str) -> None:
        if name == "cold-cache-clear":
            lines.append(message)
        real_log_line(name, message)

    monkeypatch.setattr(state, "log_line", _log_line)
    return lines


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


def test_resume_probe_is_scoped_to_the_payload_session_id(monkeypatch, tmp_path):
    """TRDD-8ZY3JU2H: the hook passes its SessionStart payload `session_id` to the cache probe,
    so a sibling session's cold cache cannot make it clear a resumed session that is warm."""
    captured: dict = {}

    def _fake_probe(*_a, **kw):
        captured.update(kw)
        return None

    monkeypatch.setattr(ec, "cache_certainly_expired", _fake_probe)
    monkeypatch.setattr(ec, "recovery_pending", lambda sd: False)
    monkeypatch.setattr(ccc, "context_tokens_for_resume", lambda *a, **kw: 1)
    monkeypatch.setattr(
        ec, "should_clear_on_resume", lambda **kw: ec.ClearVerdict(False, why="test-stub")
    )
    assert _run_main_with_source(monkeypatch, "resume", tmp_path) == 0
    assert captured["session_id"] == "s1"


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


def test_restart_with_a_stale_cache_spawns_the_jev_clear_watcher(monkeypatch, tmp_path):
    """TRDD-RAEGS1D5 card 4 item 4: SessionStart source in {startup, resume} with a stale/
    expired cache must actually SPAWN the watcher (`external_handoff_clear.py --on-resume`) —
    the same clear-then-inject-compacted-context chain every other automatic lever uses. This
    is the positive half of `test_resume_source_routes_through_the_shared_recovery_helper_and_
    the_widened_reader` above, which only proved what gets PASSED to the decider, not that a
    firing verdict actually launches the chain. TRDD-8ZY3JU2H: the session names its OWN
    transcript in the payload, and the spawned watcher is handed that same path."""
    own = _write_transcript(tmp_path / "own.jsonl", 500_000)
    captured = _capture_watcher_spawn(monkeypatch)
    monkeypatch.setattr(ec, "cache_certainly_expired", lambda *a, **kw: None)
    monkeypatch.setattr(ec, "recovery_pending", lambda sd: False)
    monkeypatch.setattr(ccc, "context_tokens_for_resume", lambda *a, **kw: 500_000)
    monkeypatch.setattr(
        ec, "should_clear_on_resume", lambda **kw: ec.ClearVerdict(True, why="cache-expired")
    )
    extra = {"transcript_path": str(own)}
    assert _run_main_with_source(monkeypatch, "startup", tmp_path, extra) == 0
    assert "argv" in captured, "the watcher subprocess was never spawned"
    assert str(_ROOT / "scripts" / "external_handoff_clear.py") in captured["argv"]
    assert "--on-resume" in captured["argv"]
    assert captured["argv"][captured["argv"].index("--transcript-path") + 1] == str(own)


def _resume_env(monkeypatch) -> None:
    """Pin the knobs the real (unpatched) decision reads, so these tests do not depend on the
    host: default 300k floor, no agentlensPro subprocess."""
    monkeypatch.delenv(ec.MIN_CONTEXT_ENV, raising=False)
    monkeypatch.setenv(ec.CACHE_EXPIRED_COMMAND_ENV, "")


_HARNESS_EXPIRED = {"prompt_cache_likely_expired": True}


def test_a_big_sibling_transcript_never_triggers_a_clear_in_a_small_session(monkeypatch, tmp_path):
    """TRDD-8ZY3JU2H: the project's newest transcript (patched to be a 900k SIBLING) must not
    size this session. The session's OWN transcript (240k, under the 300k floor) refuses the
    clear, whatever the cache verdict. With the old `newest_transcript` read it would fire."""
    _resume_env(monkeypatch)
    sibling = _write_transcript(tmp_path / "sibling.jsonl", 900_000)
    own = _write_transcript(tmp_path / "own.jsonl", 240_000)
    monkeypatch.setattr(ccc, "newest_transcript", lambda root: sibling)
    captured = _capture_watcher_spawn(monkeypatch)
    log = _capture_hook_log(monkeypatch)
    extra = {"transcript_path": str(own), **_HARNESS_EXPIRED}
    assert _run_main_with_source(monkeypatch, "resume", tmp_path, extra) == 0
    assert any(f"transcript={own}" in line and "fire=False" in line for line in log), log
    assert "argv" not in captured, "a small session was cleared because of a big sibling"


@pytest.mark.parametrize("own_payload", [{}, {"transcript_path": "no-such-file.jsonl"}])
def test_an_absent_or_missing_own_transcript_never_clears_even_beside_a_big_sibling(
    monkeypatch, tmp_path, own_payload
):
    """TRDD-8ZY3JU2H: no `transcript_path`, or one naming a file that does not exist, means the
    session's size is UNKNOWN, and unknown never authorises a clear -- even though
    `newest_transcript` (patched) would hand back a 900k sibling that the old code measured."""
    _resume_env(monkeypatch)
    sibling = _write_transcript(tmp_path / "sibling.jsonl", 900_000)
    monkeypatch.setattr(ccc, "newest_transcript", lambda root: sibling)
    captured = _capture_watcher_spawn(monkeypatch)
    log = _capture_hook_log(monkeypatch)
    extra = {**own_payload, **_HARNESS_EXPIRED}
    assert _run_main_with_source(monkeypatch, "startup", tmp_path, extra) == 0
    assert any("transcript=missing" in line and "fire=False" in line for line in log), log
    assert "argv" not in captured, "a session with no known own transcript was cleared"


def test_a_big_expired_own_transcript_fires_and_is_handed_to_the_watcher(monkeypatch, tmp_path):
    """TRDD-8ZY3JU2H: a 500k OWN transcript with a harness-expired cache fires, and the watcher
    is spawned with `--transcript-path <own>` so it measures and summarises the same session.
    The patched `newest_transcript` is a tiny SIBLING: the old code would have refused."""
    _resume_env(monkeypatch)
    sibling = _write_transcript(tmp_path / "sibling.jsonl", 10_000)
    own = _write_transcript(tmp_path / "own.jsonl", 500_000)
    monkeypatch.setattr(ccc, "newest_transcript", lambda root: sibling)
    captured = _capture_watcher_spawn(monkeypatch)
    log = _capture_hook_log(monkeypatch)
    extra = {"transcript_path": str(own), **_HARNESS_EXPIRED}
    assert _run_main_with_source(monkeypatch, "resume", tmp_path, extra) == 0
    assert any(f"transcript={own}" in line and "fire=True" in line for line in log), log
    argv = captured["argv"]
    assert argv[argv.index("--transcript-path") + 1] == str(own)
    assert "--on-resume" in argv
