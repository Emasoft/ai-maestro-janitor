"""`scripts/lib/llm_ext_summary.py` — the MANUAL lane's llm-ext retry/classify machinery
(TRDD-RAEGS1D5 card 3 C2).

Moved here, together with the module it tests, out of `tests/test_external_clear_retry.py`,
`tests/test_external_clear_llm_ext.py` and `tests/test_external_clear_refusal_guard.py` (54
tests total across the three) when the automatic SessionStart lane stopped calling llm-ext at
all (card 3 C1 rewired it onto `jev_compact.py compact`) and this retry/classify code moved out
of `scripts/lib/external_clear.py` to the module the sole remaining caller —
`scripts/compose_agent_handoff.py`, the manual `/janitor-write-handoff` tool — now imports
directly. Fleet-lease tests (`acquire_fleet_lease` & co., which STAYED in `external_clear.py`)
moved to `tests/test_external_clear.py` instead; the handful of tests exercising
`ec.compose_handoff`/`ec.recent_messages` (which also stayed) moved there too. Tests that
exercised the now-deleted `run_llm_ext_summary` (no production caller even before this move —
its own docstring said so) were dropped, not moved.

The two guarantees pinned in the retry-loop half are NOT the same guarantee:
  * the SUMMARY is best-effort — it retries across timeouts, 429s and a dead network, and
    eventually gives up;
  * the CLEAR/compose the caller does afterward is unconditional — when the summary never
    lands, the caller still writes a network-free fallback and proceeds anyway.
Confusing the two is how "must succeed no matter what" turns into a startup blocked forever, so
the tests assert the boundary explicitly. Clocks, sleepers and attempts are INJECTED — a test
that really slept through a 300 s backoff would be untestable, and one that mocked
`summarize_with_retry` itself would prove nothing about the loop being tested.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import external_clear as ec  # noqa: E402 -- fleet-lease + the shared LLM_EXT_TIMEOUT_S stay there
import llm_ext_summary as les  # noqa: E402
import pytest  # noqa: E402


class _Clock:
    """A fake clock whose `sleep` advances it — so backoff and deadlines interact for real."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.t = start
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def _attempts(*outcomes: les.SummaryAttempt):
    """An attempt fn that returns `outcomes` in order, repeating the last one forever."""
    calls: list[int] = []

    def run(_transcript: str) -> les.SummaryAttempt:
        i = min(len(calls), len(outcomes) - 1)
        calls.append(i)
        return outcomes[i]

    run.calls = calls  # type: ignore[attr-defined]
    return run


_OK = les.SummaryAttempt("a real summary", les.OUTCOME_OK)
_TRANSIENT = les.SummaryAttempt(None, les.OUTCOME_TRANSIENT, "timed out after 240s")
_PERMANENT = les.SummaryAttempt(None, les.OUTCOME_PERMANENT, "llm-ext is not installed")


def _retry(clock: _Clock, attempt, *, budget: float = 540.0, **kw):
    return les.summarize_with_retry(
        "/tmp/t.jsonl",
        deadline=clock.now() + budget,
        now_fn=clock.now,
        sleeper=clock.sleep,
        attempt=attempt,
        max_concurrent=kw.pop("max_concurrent", 0),  # lane off unless a test is about the lane
        jitter=kw.pop("jitter", lambda: 1.0),  # deterministic backoff
        **kw,
    )


# ---------- the retry loop ---------------------------------------------------------------


def test_a_first_try_success_does_not_sleep() -> None:
    """The common case must cost nothing: one call, no backoff, no lane wait."""
    clock = _Clock()
    run = _attempts(_OK)

    got = _retry(clock, run)

    assert got.outcome == les.OUTCOME_OK
    assert got.text == "a real summary"
    assert clock.slept == [], "a success must not sleep — this runs inside a blocking hook"


def test_it_retries_through_transient_failures_and_then_succeeds() -> None:
    """Timeouts and dropped connections are exactly what the loop exists for — the owner's
    'even if it gets timeouts or error or disconnects from the internet for hours'."""
    clock = _Clock()
    run = _attempts(_TRANSIENT, _TRANSIENT, _TRANSIENT, _OK)

    got = _retry(clock, run)

    assert got.outcome == les.OUTCOME_OK
    assert len(run.calls) == 4  # type: ignore[attr-defined]
    assert clock.slept == [5.0, 10.0, 20.0], "backoff must grow, not hammer"


def test_a_transient_failure_keeps_retrying_until_the_deadline() -> None:
    """A network that never comes back must not stop the loop early — only the deadline does."""
    clock = _Clock()
    run = _attempts(_TRANSIENT)

    got = _retry(clock, run, budget=540.0)

    assert got.outcome == les.OUTCOME_TRANSIENT
    assert got.text is None
    assert "deadline" in got.detail
    assert len(run.calls) > 5, "it must keep trying across the whole budget"  # type: ignore[attr-defined]
    assert clock.now() <= 1_000_000.0 + 540.0 + 300.0, "it must not overrun the budget wildly"


def test_a_permanent_failure_stops_immediately() -> None:
    """No binary on PATH fails identically on attempt 100 as on attempt 1."""
    clock = _Clock()
    run = _attempts(_PERMANENT)

    got = _retry(clock, run)

    assert got.outcome == les.OUTCOME_PERMANENT
    assert len(run.calls) == 1, "a permanent failure must not be retried at all"  # type: ignore[attr-defined]
    assert clock.slept == []


def test_an_identical_unknown_failure_gives_up_after_three_tries() -> None:
    """An IDENTICAL signature repeating is proof retrying cannot help."""
    clock = _Clock()
    same = les.SummaryAttempt(None, les.OUTCOME_UNKNOWN, "2|unknown flag --xyz")
    run = _attempts(same)

    got = _retry(clock, run)

    assert got.outcome == les.OUTCOME_PERMANENT
    assert "repeated" in got.detail
    assert len(run.calls) == les._UNKNOWN_REPEAT_GIVEUP  # type: ignore[attr-defined]


def test_changing_unknown_failures_keep_being_retried() -> None:
    """The give-up keys on an IDENTICAL signature; a rotating error text must not trip it."""
    clock = _Clock()
    run = _attempts(
        les.SummaryAttempt(None, les.OUTCOME_UNKNOWN, "1|upstream error req-aaa"),
        les.SummaryAttempt(None, les.OUTCOME_UNKNOWN, "1|upstream error req-bbb"),
        les.SummaryAttempt(None, les.OUTCOME_UNKNOWN, "1|upstream error req-ccc"),
        _OK,
    )

    got = _retry(clock, run)

    assert got.outcome == les.OUTCOME_OK, "distinct signatures must not trip the give-up"


def test_the_backoff_never_exceeds_the_remaining_budget() -> None:
    """A 300 s sleep with 20 s of budget left must be clamped to what is left."""
    clock = _Clock()
    run = _attempts(_TRANSIENT)

    _retry(clock, run, budget=12.0)

    assert clock.now() <= 1_000_000.0 + 12.0 + 0.001, "it must not sleep past the deadline"


# ---------- the timeout/TTL/deadline ordering invariant (TRDD-YOZ9TS3W) --------------------


def test_the_per_attempt_timeout_is_shorter_than_the_lease_ttl() -> None:
    """The invariant the whole coupling depends on, still pinned via `external_clear` — both
    constants stayed there. Asserted as a RELATIONSHIP so it survives future re-tuning."""
    assert ec.DEFAULT_FLEET_LEASE_TTL_S > ec.LLM_EXT_TIMEOUT_S


def test_the_summary_deadline_allows_more_than_one_attempt() -> None:
    """A total deadline no bigger than one per-attempt budget makes the retry loop incoherent."""
    assert ec.DEFAULT_SUMMARY_DEADLINE_S > 2 * ec.LLM_EXT_TIMEOUT_S
    assert ec.DEFAULT_SUMMARY_DEADLINE_S % ec.LLM_EXT_TIMEOUT_S != 0


def test_the_blocking_sessionstart_hook_timeout_covers_the_summary_deadline() -> None:
    """`hooks.json`'s cold-cache-clear entry must outlast `ec.DEFAULT_SUMMARY_DEADLINE_S`, or
    Claude Code tears the hook down before the fallback compose gets to run."""
    hooks_path = Path(__file__).resolve().parent.parent / "hooks" / "hooks.json"
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    matches = [
        h
        for entry in hooks["hooks"]["SessionStart"]
        for h in entry["hooks"]
        if "on-session-start-cold-cache-clear.py" in h.get("command", "")
    ]
    assert len(matches) == 1, "expected exactly one cold-cache-clear SessionStart hook entry"
    assert matches[0]["timeout"] > ec.DEFAULT_SUMMARY_DEADLINE_S


# ---------- the progress-observed retry gate (option B, TRDD-YOZ9TS3W) ---------------------


def _stuck_progress_fn():
    """Never changes — simulates a chunk whose checkpoint state never advances between tries."""
    return lambda: 1.0


def _advancing_progress_fn():
    """A fresh value on every call — simulates a checkpoint that DOES advance between tries."""
    calls = {"n": 0.0}

    def fn() -> float:
        calls["n"] += 1.0
        return calls["n"]

    return fn


def test_a_chunk_stuck_past_the_budget_stops_after_two_timeouts_not_the_deadline() -> None:
    """A chunk slower than `LLM_EXT_TIMEOUT_S` produces the SAME timeout forever with a
    checkpoint that never advances — without the gate this would burn the whole budget."""
    clock = _Clock()
    run = _attempts(_TRANSIENT)  # every attempt times out identically, forever

    got = _retry(clock, run, budget=10_000.0, progress_fn=_stuck_progress_fn())

    assert got.outcome == les.OUTCOME_PERMANENT
    assert "no progress" in got.detail
    assert len(run.calls) == les._NO_PROGRESS_TIMEOUT_GIVEUP  # type: ignore[attr-defined]


def test_a_chunk_that_keeps_checkpointing_is_not_mistaken_for_stuck() -> None:
    """Repeated timeouts whose checkpoint state DOES change are real forward progress."""
    clock = _Clock()
    run = _attempts(_TRANSIENT, _TRANSIENT, _TRANSIENT, _OK)

    got = _retry(clock, run, progress_fn=_advancing_progress_fn())

    assert got.outcome == les.OUTCOME_OK, "advancing checkpoints must not trip the no-progress gate"
    assert len(run.calls) == 4  # type: ignore[attr-defined]


def test_the_progress_gate_is_off_by_default() -> None:
    """`progress_fn` is opt-in — omitting it must reproduce the old unconditional-retry
    behaviour exactly."""
    clock = _Clock()
    run = _attempts(_TRANSIENT)

    got = _retry(clock, run, budget=50.0)

    assert got.outcome == les.OUTCOME_TRANSIENT
    assert "deadline" in got.detail
    assert len(run.calls) > les._NO_PROGRESS_TIMEOUT_GIVEUP  # type: ignore[attr-defined]


def test_a_non_timeout_transient_never_trips_the_no_progress_gate() -> None:
    """A 429 or dropped connection already got an answer from the server — it must never be
    treated as evidence of a stuck chunk."""
    clock = _Clock()
    network_drop = les.SummaryAttempt(None, les.OUTCOME_TRANSIENT, "socket hang up")
    run = _attempts(_TRANSIENT, network_drop, _TRANSIENT, network_drop, _OK)

    got = _retry(clock, run, progress_fn=_stuck_progress_fn())

    assert got.outcome == les.OUTCOME_OK, "alternating with non-timeout failures must not give up"


# ---------- failure classification ---------------------------------------------------------


def test_timeouts_and_network_errors_classify_transient() -> None:
    """Every shape a dead network takes must be retryable — the whole point of the loop."""
    for err in ("ETIMEDOUT", "socket hang up", "getaddrinfo ENOTFOUND openrouter.ai",
                "HTTP 429 Too Many Requests", "503 Service Unavailable", "fetch failed"):
        assert les.classify_llm_ext_failure(
            returncode=1, stderr=err, timed_out=False
        ) == les.OUTCOME_TRANSIENT, err


def test_a_timeout_flag_is_transient_whatever_stderr_says() -> None:
    """A killed process often has EMPTY stderr — the timeout itself is the evidence."""
    assert les.classify_llm_ext_failure(
        returncode=-9, stderr="", timed_out=True
    ) == les.OUTCOME_TRANSIENT


def test_an_unreadable_failure_is_unknown_not_permanent() -> None:
    """Bias toward retrying: a false 'transient' costs one more attempt, a false 'permanent'
    costs the entire summary."""
    assert les.classify_llm_ext_failure(
        returncode=2, stderr="Error: something went wrong", timed_out=False
    ) == les.OUTCOME_UNKNOWN


def test_the_signature_uses_only_the_first_stderr_line() -> None:
    """Later lines routinely carry a timestamp or request id and must not defeat the give-up."""
    a = les.failure_signature(returncode=2, stderr="boom\nreq-id: 111\nat 12:00:01")
    b = les.failure_signature(returncode=2, stderr="boom\nreq-id: 222\nat 12:00:09")
    assert a == b == "2|boom"


# ---------- the resume budgets (incident 2026-08-25) --------------------------------------


def test_every_attempt_holds_and_releases_a_lease(tmp_path: Path) -> None:
    """Each ATTEMPT takes a fleet lease and gives it back — a sleeping retrier does not occupy
    the lane for the whole backoff sequence."""
    clock = _Clock()
    run = _attempts(_TRANSIENT, _TRANSIENT, _OK)

    got = _retry(clock, run, max_concurrent=3, lane_dir=tmp_path)

    assert got.outcome == les.OUTCOME_OK
    held = json.loads((tmp_path / ec.FLEET_LEASE_FILE).read_text(encoding="utf-8"))
    assert held == {}, f"every lease must be released after its attempt, got {held}"


def test_a_resume_lease_budget_bounds_the_lane_wait(tmp_path: Path) -> None:
    """A saturated lane at resume declines within the budget, never at the 2600 s deadline.

    Pins the 2026-08-25 incident numbers: 16 sessions resumed together, every blocking
    SessionStart hook queued on the same lane, and the fleet froze for 40+ minutes.
    """
    clock = _Clock()
    held = ec.acquire_fleet_lease(
        now=clock.now(), max_concurrent=1, ttl_s=10_000, lane_dir=tmp_path
    )
    assert held is not None

    got = les.summarize_with_retry(
        "/tmp/t.jsonl",
        deadline=clock.now() + 2600.0,
        now_fn=clock.now,
        sleeper=clock.sleep,
        attempt=_attempts(_OK),
        max_concurrent=1,
        lease_ttl_s=10_000,
        lane_dir=tmp_path,
        jitter=lambda: 1.0,
        lease_wait_budget_s=45.0,
    )

    assert got.text is None, "no lease ⇒ no attempt ⇒ no summary"
    assert "lane full past budget" in got.detail
    waited = clock.now() - 1_000_000.0
    assert waited <= 45.0 + ec.FLEET_POLL_S + 1.0, (
        f"the decline must land within the lease budget, not the deadline (waited {waited:.0f}s)"
    )


def test_without_a_lease_budget_a_full_lane_polls_to_the_deadline(tmp_path: Path) -> None:
    """The abandoned-session path keeps the old behaviour: the deadline is the policy."""
    clock = _Clock()
    held = ec.acquire_fleet_lease(
        now=clock.now(), max_concurrent=1, ttl_s=10_000, lane_dir=tmp_path
    )
    assert held is not None

    got = les.summarize_with_retry(
        "/tmp/t.jsonl",
        deadline=clock.now() + 300.0,
        now_fn=clock.now,
        sleeper=clock.sleep,
        attempt=_attempts(_OK),
        max_concurrent=1,
        lease_ttl_s=10_000,
        lane_dir=tmp_path,
        jitter=lambda: 1.0,
    )

    assert got.text is None
    assert "lane full past budget" not in got.detail, "no budget ⇒ the deadline message"
    assert clock.now() - 1_000_000.0 >= 300.0 - ec.FLEET_POLL_S - 1.0, (
        "without a budget the wait runs to the deadline"
    )


# ---------- the real subprocess boundary ----------------------------------------------------


def _script(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    p.chmod(0o755)
    return p


def test_a_real_failing_binary_is_classified_not_swallowed(tmp_path: Path) -> None:
    """A non-zero exit whose stderr names a 429 must arrive as TRANSIENT, using a REAL process."""
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    fake = _script(tmp_path, "fake-llm-ext.sh", "echo 'HTTP 429 rate limit' >&2; exit 1")

    proc = subprocess.run(  # noqa: S603 - a script this test just wrote
        [str(fake)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert proc.returncode == 1
    assert les.classify_llm_ext_failure(
        returncode=proc.returncode, stderr=proc.stderr, timed_out=False
    ) == les.OUTCOME_TRANSIENT


def test_an_install_time_precondition_is_permanent_not_transient() -> None:
    """A precondition that cannot change between attempts must classify PERMANENT."""
    got = les.attempt_llm_ext_summary("/definitely/not/a/file.jsonl")

    assert got.outcome == les.OUTCOME_PERMANENT
    assert got.text is None
    assert got.detail in {
        "llm-ext is not installed",
        "no readable transcript",
    }, got.detail


def test_an_empty_transcript_path_is_permanent() -> None:
    """The other install-time precondition, pinned without depending on the host's PATH."""
    got = les.attempt_llm_ext_summary("")
    assert got.outcome == les.OUTCOME_PERMANENT


# ---------- resolving the CLI without an interactive PATH (TRDD-CEWVQ8DG) -------------------
#
# Moved from `tests/test_external_clear_cold_certainty.py` (D2): those functions exercised
# `les.resolve_llm_ext`/`les.attempt_llm_ext_summary` directly, so they belong here, not in a
# file about the automatic lane's cold-resume certainty math.


class TestResolveLlmExt:
    """Overrides the module's autouse `_pretend_llm_ext_is_installed` stub with a no-op: these
    tests exercise the REAL binary-discovery logic against HOME/PATH, so stubbing
    `resolve_llm_ext` away would test nothing."""

    @pytest.fixture(autouse=True)
    def _pretend_llm_ext_is_installed(self) -> None:
        return None

    @staticmethod
    def _install(home: Path, version: str, marketplace: str = "emasoft-plugins") -> Path:
        binary = (
            home / ".claude" / "plugins" / "cache" / marketplace / "llm-externalizer"
            / version / "bin" / "llm-ext"
        )
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        binary.chmod(0o755)
        return binary

    def test_the_cli_is_found_with_an_empty_path(self, tmp_path, monkeypatch) -> None:
        """The measured failure: a hook-spawned child has no profile PATH, but the binary is there."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PATH", "")
        binary = self._install(tmp_path, "13.5.1")
        assert les.resolve_llm_ext() == str(binary)

    def test_the_newest_version_wins_numerically_not_lexicographically(self, tmp_path, monkeypatch) -> None:
        """As strings '9.0.0' > '13.5.1', which would pin the OLDEST install forever."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PATH", "")
        self._install(tmp_path, "9.0.0")
        newest = self._install(tmp_path, "13.5.1")
        assert les.resolve_llm_ext() == str(newest)

    def test_a_genuinely_absent_cli_resolves_to_empty(self, tmp_path, monkeypatch) -> None:
        """No install anywhere must degrade to the template, not raise or invent a path."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PATH", "")
        assert les.resolve_llm_ext() == ""

    def test_a_real_path_entry_still_wins(self, tmp_path, monkeypatch) -> None:
        """An operator who put llm-ext on PATH keeps control — `which` is consulted first."""
        onpath = tmp_path / "bin"
        onpath.mkdir()
        shim = onpath / "llm-ext"
        shim.write_text("#!/bin/sh\n", encoding="utf-8")
        shim.chmod(0o755)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PATH", str(onpath))
        self._install(tmp_path, "13.5.1")
        assert les.resolve_llm_ext() == str(shim)

    def test_an_absent_cli_reports_the_exact_permanent_detail(self, tmp_path, monkeypatch) -> None:
        """The guardrail for the CI break this file's own rename caused (TRDD-CEWVQ8DG).

        Pins the string DETERMINISTICALLY by making absence the fixture, so the next rename
        fails on the machine that made it rather than twenty minutes later in CI.
        """
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PATH", "")
        transcript = tmp_path / "session.jsonl"
        transcript.write_text("{}\n", encoding="utf-8")

        got = les.attempt_llm_ext_summary(str(transcript))
        assert got.outcome == les.OUTCOME_PERMANENT
        assert got.detail == "llm-ext is not installed"

    def test_the_summary_attempt_no_longer_reports_not_on_path(self, tmp_path, monkeypatch) -> None:
        """The regression pin for D2: a plugin-cache-only install must produce a SUMMARY, not a
        permanent 'not on PATH' that skips every retry and degrades the handoff."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PATH", "")
        self._install(tmp_path, "13.5.1")
        (tmp_path / ".claude" / "plugins" / "data" / "llm-externalizer-emasoft-plugins").mkdir(
            parents=True, exist_ok=True
        )
        transcript = tmp_path / "session.jsonl"
        transcript.write_text("{}\n", encoding="utf-8")

        class _Proc:
            def __init__(self, rc: int, out: str = "", err: str = "") -> None:
                self.returncode, self.stdout, self.stderr = rc, out, err

        attempt = les.attempt_llm_ext_summary(
            str(transcript), runner=lambda *a, **k: _Proc(0, "a real summary")
        )
        assert attempt.outcome == les.OUTCOME_OK
        assert attempt.text == "a real summary"


# ---------- the progress-signal wiring (llm_ext_state_dir) ---------------------------------


def test_the_progress_signal_watches_the_CHECKPOINT_SUBDIR_not_the_config_root(
    tmp_path, monkeypatch
) -> None:
    """The gate must watch `session-summary-checkpoints/`, never the config root — only the
    SUBDIR's mtime ticks per completed chunk."""
    root = tmp_path / "llm-ext-state"
    (root / "session-summary-checkpoints").mkdir(parents=True)
    monkeypatch.setenv("LLM_EXT_CONFIG_DIR", str(root))
    assert les.llm_ext_state_dir() == str(root / "session-summary-checkpoints")
    assert les.llm_ext_state_dir() != str(root), "the config ROOT is a dead per-chunk signal"


def test_the_progress_signal_is_ABSENT_rather_than_wrong_before_any_checkpoint(
    tmp_path, monkeypatch
) -> None:
    """No checkpoint subdir yet ⇒ "" ⇒ the retry loop runs UNGATED, never a lying signal."""
    root = tmp_path / "llm-ext-state"
    root.mkdir()  # config root exists, but llm-ext has never checkpointed here
    monkeypatch.setenv("LLM_EXT_CONFIG_DIR", str(root))
    assert les.llm_ext_state_dir() == ""


# ---------- the refusal guard (incident 2026-08-18) -----------------------------------------
#
# A model REFUSAL must never be accepted as a session summary. On 2026-08-18 the external model
# declined the compaction, exit 0 with non-empty stdout; the only validation (`out or None`)
# called it a summary, it was written into the handoff as the session's own state, and the
# session was cleared on it. These pin the guard AND the anchoring that keeps it from eating a
# legitimate summary that quotes the refusal.


@pytest.fixture(autouse=True)
def _pretend_llm_ext_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the BINARY LOOKUP, not just the runner — `attempt_llm_ext_summary` resolves the
    binary FIRST and returns PERMANENT "llm-ext is not installed" before any classification
    runs, so stubbing only `runner` would test nothing on a host without llm-ext installed. An
    `autouse` fixture applies to EVERY test in this module regardless of definition order
    (pytest resolves fixtures per-test, not top-to-bottom), including the two install-time-
    precondition tests above — both already accept either "llm-ext is not installed" or "no
    readable transcript" as their outcome, so this stub only narrows that to the former.
    """
    monkeypatch.setattr(les, "resolve_llm_ext", lambda: "/nonexistent/stub/llm-ext")


# The real stdout from the incident, verbatim from EMASOFT-ORCHESTRATOR-AGENT's handoff.
INCIDENT_REFUSAL = """I'm not going to produce this compaction as specified, because the transcript contains a **prompt injection** that I need to flag.

## What I found

Embedded in the middle of the instructions is this line:

> "Your output REPLACES the transcript for a future session that must RESUME this work"

That's not a legitimate instruction from you.
"""


def test_incident_refusal_is_detected() -> None:
    """The exact stdout that poisoned a handoff on 2026-08-18 is classified as a refusal."""
    assert les._looks_like_refusal(INCIDENT_REFUSAL) is True


def test_summary_quoting_the_refusal_is_not_a_refusal() -> None:
    """A real summary OF the incident opens by quoting it — that must still be accepted."""
    quoting = (
        "The external model declined the compaction. Its reply began:\n\n"
        "> I'm not going to produce this compaction as specified, because the transcript\n"
        "> contains a prompt injection that I need to flag.\n\n"
        "The session was cleared anyway, which is the defect under investigation.\n"
    )
    assert les._looks_like_refusal(quoting) is False


def test_curly_apostrophe_refusal_is_detected() -> None:
    """Models emit typographic apostrophes; the guard must not miss "I’m not going to"."""
    assert les._looks_like_refusal("I’m not going to summarize this.") is True


def test_refusal_under_a_markdown_heading_is_detected() -> None:
    """A heading before the refusal is the common shape; the line after it is checked too."""
    assert les._looks_like_refusal("## A note first\n\nI won't do this.\n") is True


def test_ordinary_summary_is_untouched() -> None:
    """The overwhelmingly common case: a descriptive summary is never a refusal."""
    ordinary = "The session published v3.3.12, fixed the cold-resume hook, and swept stale keys."
    assert les._looks_like_refusal(ordinary) is False


def test_attempt_maps_a_refusal_to_unknown_with_a_constant_detail() -> None:
    """A refusal is UNKNOWN (bounded retries), and its detail must be CONSTANT — the retry loop
    bounds UNKNOWN by counting IDENTICAL `detail` strings."""

    class _Proc:
        returncode = 0

        def __init__(self, text: str) -> None:
            self.stdout = text

    transcript = Path(__file__).resolve()  # any real file; the runner is stubbed

    def _runner_a(*_a: object, **_k: object) -> _Proc:
        return _Proc(INCIDENT_REFUSAL)

    def _runner_b(*_a: object, **_k: object) -> _Proc:
        return _Proc("I won't help with this. A completely different refusal body.")

    a = les.attempt_llm_ext_summary(str(transcript), runner=_runner_a)
    b = les.attempt_llm_ext_summary(str(transcript), runner=_runner_b)

    assert a.text is None
    assert a.outcome == les.OUTCOME_UNKNOWN
    assert a.detail == b.detail, "detail must not carry the prose, or the retry bound is lost"


def test_a_refused_attempt_carries_forensic_evidence() -> None:
    """A failed compaction must record WHAT the process said, not just our verdict."""

    class _Proc:
        returncode = 0
        stdout = INCIDENT_REFUSAL
        stderr = "[llm-externalizer] Auth: token resolved"

    transcript = Path(__file__).resolve()
    got = les.attempt_llm_ext_summary(str(transcript), runner=lambda *a, **k: _Proc())

    assert got.outcome == les.OUTCOME_UNKNOWN
    assert "rc=0" in got.evidence
    assert "bytes=" in got.evidence and "elapsed=" in got.evidence
    assert "not going to produce" in got.evidence, "the refusal's own words must be recorded"
    assert "Auth: token resolved" in got.evidence, "stderr must no longer be discarded"
    assert "\n" not in got.evidence, "evidence lands in a line-oriented log"


def test_excerpt_keeps_both_ends() -> None:
    """Head-only excerpting keeps the wrong half: programs print the raw error LAST."""
    blob = "DIAGNOSIS-AT-THE-TOP " + ("x" * 5000) + " RAW-ERROR-AT-THE-BOTTOM"
    got = les._excerpt(blob)
    assert "DIAGNOSIS-AT-THE-TOP" in got
    assert "RAW-ERROR-AT-THE-BOTTOM" in got
    assert "elided" in got


# llm-ext >=13.5.4 stderr contract: non-zero exit + the literal `(nonconforming)` token means
# every candidate model produced non-schema output (usually a refusal). Verbatim message shape
# from the llm-externalizer session's contract notice, model ids interpolated.
NONCONFORMING_STDERR = (
    "session-summary: every candidate free model is unavailable — tried a/x, b/y. Last failure "
    "on 'b/y' (nonconforming): model returned text containing none of the 9 mandated section "
    "headings — it declined the task or ignored the schema (response: I cannot help with that)"
)


def test_nonconforming_outranks_the_transient_markers() -> None:
    """The nonconforming message also says "unavailable" — a `_TRANSIENT_MARKERS` hit — but the
    `(nonconforming)` token must win and yield the bounded UNKNOWN instead."""
    got = les.classify_llm_ext_failure(returncode=1, stderr=NONCONFORMING_STDERR, timed_out=False)
    assert got == les.OUTCOME_UNKNOWN


def test_nonconforming_signature_is_constant_across_model_rotations() -> None:
    """The driver interpolates the tried model ids; the signature must not vary with them."""
    other = NONCONFORMING_STDERR.replace("a/x, b/y", "c/z").replace("'b/y'", "'c/z'")
    assert les.failure_signature(
        returncode=1, stderr=NONCONFORMING_STDERR
    ) == les.failure_signature(returncode=1, stderr=other)
