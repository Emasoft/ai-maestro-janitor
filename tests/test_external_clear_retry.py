"""The compaction must survive hours of failure, and the fleet must not burst (owner, 2026-08-13).

Two guarantees are pinned here, and they are NOT the same guarantee:

  * the SUMMARY is best-effort — it retries across timeouts, 429s and a dead network, and
    eventually gives up;
  * the CLEAR is unconditional — when the summary never lands, the caller still writes a
    network-free template handoff and shrinks the session.

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

import external_clear as ec  # noqa: E402


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


def _attempts(*outcomes: ec.SummaryAttempt):
    """An attempt fn that returns `outcomes` in order, repeating the last one forever."""
    calls: list[int] = []

    def run(_transcript: str) -> ec.SummaryAttempt:
        i = min(len(calls), len(outcomes) - 1)
        calls.append(i)
        return outcomes[i]

    run.calls = calls  # type: ignore[attr-defined]
    return run


_OK = ec.SummaryAttempt("a real summary", ec.OUTCOME_OK)
_TRANSIENT = ec.SummaryAttempt(None, ec.OUTCOME_TRANSIENT, "timed out after 240s")
_PERMANENT = ec.SummaryAttempt(None, ec.OUTCOME_PERMANENT, "llm-ext is not installed")


def _retry(clock: _Clock, attempt, *, budget: float = 540.0, **kw):
    return ec.summarize_with_retry(
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

    assert got.outcome == ec.OUTCOME_OK
    assert got.text == "a real summary"
    assert clock.slept == [], "a success must not sleep — this runs inside a blocking hook"


def test_it_retries_through_transient_failures_and_then_succeeds() -> None:
    """Timeouts and dropped connections are exactly what the loop exists for — the owner's
    'even if it gets timeouts or error or disconnects from the internet for hours'."""
    clock = _Clock()
    run = _attempts(_TRANSIENT, _TRANSIENT, _TRANSIENT, _OK)

    got = _retry(clock, run)

    assert got.outcome == ec.OUTCOME_OK
    assert len(run.calls) == 4  # type: ignore[attr-defined]
    assert clock.slept == [5.0, 10.0, 20.0], "backoff must grow, not hammer"


def test_a_transient_failure_keeps_retrying_until_the_deadline() -> None:
    """A network that never comes back must not stop the loop early — only the deadline does.

    This is the half that must NOT be 'smart': an outage looks identical on attempt 2 and
    attempt 20, so a give-up heuristic here would abandon exactly the case retrying fixes.
    """
    clock = _Clock()
    run = _attempts(_TRANSIENT)

    got = _retry(clock, run, budget=540.0)

    assert got.outcome == ec.OUTCOME_TRANSIENT
    assert got.text is None
    assert "deadline" in got.detail
    assert len(run.calls) > 5, "it must keep trying across the whole budget"  # type: ignore[attr-defined]
    assert clock.now() <= 1_000_000.0 + 540.0 + 300.0, "it must not overrun the budget wildly"


def test_a_permanent_failure_stops_immediately() -> None:
    """No binary on PATH fails identically on attempt 100 as on attempt 1. Sleeping through the
    whole budget to re-learn that would block a session start for nine minutes for nothing."""
    clock = _Clock()
    run = _attempts(_PERMANENT)

    got = _retry(clock, run)

    assert got.outcome == ec.OUTCOME_PERMANENT
    assert len(run.calls) == 1, "a permanent failure must not be retried at all"  # type: ignore[attr-defined]
    assert clock.slept == []


def test_an_identical_unknown_failure_gives_up_after_three_tries() -> None:
    """A broken invocation (wrong flag → the same exit 2 forever) is not a network problem. It is
    retried a few times — an unreadable error might still be transient — but an IDENTICAL
    signature repeating is proof retrying cannot help, so it degrades to the template early."""
    clock = _Clock()
    same = ec.SummaryAttempt(None, ec.OUTCOME_UNKNOWN, "2|unknown flag --xyz")
    run = _attempts(same)

    got = _retry(clock, run)

    assert got.outcome == ec.OUTCOME_PERMANENT
    assert "repeated" in got.detail
    assert len(run.calls) == ec._UNKNOWN_REPEAT_GIVEUP  # type: ignore[attr-defined]


def test_changing_unknown_failures_keep_being_retried() -> None:
    """The give-up keys on an IDENTICAL signature. A server rotating error text (a request id,
    a timestamp) must not be mistaken for a broken install and abandoned."""
    clock = _Clock()
    run = _attempts(
        ec.SummaryAttempt(None, ec.OUTCOME_UNKNOWN, "1|upstream error req-aaa"),
        ec.SummaryAttempt(None, ec.OUTCOME_UNKNOWN, "1|upstream error req-bbb"),
        ec.SummaryAttempt(None, ec.OUTCOME_UNKNOWN, "1|upstream error req-ccc"),
        _OK,
    )

    got = _retry(clock, run)

    assert got.outcome == ec.OUTCOME_OK, "distinct signatures must not trip the give-up"


def test_the_backoff_never_exceeds_the_remaining_budget() -> None:
    """A 300 s sleep with 20 s of budget left would overshoot the hook's timeout and be killed
    mid-sleep — no handoff written, no clear fired. The sleep is clamped to what is left."""
    clock = _Clock()
    run = _attempts(_TRANSIENT)

    _retry(clock, run, budget=12.0)

    assert clock.now() <= 1_000_000.0 + 12.0 + 0.001, "it must not sleep past the deadline"


# ---------- the timeout/TTL/deadline ordering invariant (TRDD-YOZ9TS3W) --------------------


def test_the_per_attempt_timeout_is_shorter_than_the_lease_ttl() -> None:
    """The invariant the whole coupling depends on: a lease must never expire under a call that
    is still legitimately running, or a fourth worker gets silently admitted while three are
    still active, defeating the machine-wide concurrency cap with nothing reporting the breach.
    Asserted as a RELATIONSHIP (not literal numbers) so it survives future re-tuning of either
    constant — the two are now DERIVED from each other, but a future edit could still hand-pick
    one of them back to a literal and silently break the ordering, which is exactly what this
    test exists to catch."""
    assert ec.DEFAULT_FLEET_LEASE_TTL_S > ec.LLM_EXT_TIMEOUT_S


def test_the_summary_deadline_allows_more_than_one_attempt() -> None:
    """A total deadline no bigger than one per-attempt budget makes the retry loop incoherent:
    `classify_llm_ext_failure` treats every timeout as worth retrying, but if the deadline can't
    outlast a single attempt, there is never a SECOND attempt to retry with. Asserted as a
    relationship (not a literal): the deadline must clear at least 2 full per-attempt budgets,
    with room left over — it is deliberately NOT an exact multiple of `LLM_EXT_TIMEOUT_S` (USER
    directive, TRDD-YOZ9TS3W): an exact multiple leaves zero room for inter-attempt backoff and
    lease acquisition, cutting the last attempt off mid-flight."""
    assert ec.DEFAULT_SUMMARY_DEADLINE_S > 2 * ec.LLM_EXT_TIMEOUT_S
    assert ec.DEFAULT_SUMMARY_DEADLINE_S % ec.LLM_EXT_TIMEOUT_S != 0


def test_the_blocking_sessionstart_hook_timeout_covers_the_summary_deadline() -> None:
    """The other half of the same class of drift (TRDD-YOZ9TS3W): the cold-cache-clear hook
    BLOCKS on `summarize_with_retry` by design (owner, 2026-08-13), so if `hooks.json` kills it
    at or before `ec.DEFAULT_SUMMARY_DEADLINE_S` elapses, Claude Code tears the hook down before
    (or exactly as) the fallback path — compose the template handoff, fire the clear — gets to
    run, and NO handoff is ever written. STRICTLY greater, not `>=` (USER directive): the
    fallback-compose work happens AFTER the deadline expires, so equality still kills it at the
    worst possible instant. This previously drifted silently (hooks.json said 120 s, a comment
    claimed 600 s, the real deadline was 540 s) because nothing asserted the relationship between
    the CONFIG file and the CODE constant. Reads the real `hooks.json`, not a hardcoded copy, so
    either side drifting reddens this test."""
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
    """The defect this gate exists for: a chunk slower than `LLM_EXT_TIMEOUT_S` produces the
    SAME timeout forever with a checkpoint that never advances. Without the gate this would
    retry until the deadline, burning the whole budget on zero forward progress."""
    clock = _Clock()
    run = _attempts(_TRANSIENT)  # every attempt times out identically, forever

    got = _retry(clock, run, budget=10_000.0, progress_fn=_stuck_progress_fn())

    assert got.outcome == ec.OUTCOME_PERMANENT
    assert "no progress" in got.detail
    assert len(run.calls) == ec._NO_PROGRESS_TIMEOUT_GIVEUP  # type: ignore[attr-defined]


def test_a_chunk_that_keeps_checkpointing_is_not_mistaken_for_stuck() -> None:
    """The other half of the same gate: repeated timeouts whose checkpoint state DOES change
    between attempts are real forward progress (a slow-but-moving chunk sequence), and must keep
    being retried rather than tripping the same give-up as a truly stuck chunk."""
    clock = _Clock()
    run = _attempts(_TRANSIENT, _TRANSIENT, _TRANSIENT, _OK)

    got = _retry(clock, run, progress_fn=_advancing_progress_fn())

    assert got.outcome == ec.OUTCOME_OK, "advancing checkpoints must not trip the no-progress gate"
    assert len(run.calls) == 4  # type: ignore[attr-defined]


def test_the_progress_gate_is_off_by_default() -> None:
    """`progress_fn` is opt-in — omitting it (the shape every pre-existing caller/test uses)
    must reproduce the old unconditional-retry behaviour exactly, so a stuck-forever timeout
    still retries to the deadline when no progress signal was supplied."""
    clock = _Clock()
    run = _attempts(_TRANSIENT)

    got = _retry(clock, run, budget=50.0)

    assert got.outcome == ec.OUTCOME_TRANSIENT
    assert "deadline" in got.detail
    assert len(run.calls) > ec._NO_PROGRESS_TIMEOUT_GIVEUP  # type: ignore[attr-defined]


def test_a_non_timeout_transient_never_trips_the_no_progress_gate() -> None:
    """A 429 or dropped connection already got an answer from the server — it is not 'still
    running the same chunk', so it must never be treated as evidence of a stuck chunk, and it
    must reset any timeout streak the gate was tracking."""
    clock = _Clock()
    network_drop = ec.SummaryAttempt(None, ec.OUTCOME_TRANSIENT, "socket hang up")
    run = _attempts(_TRANSIENT, network_drop, _TRANSIENT, network_drop, _OK)

    got = _retry(clock, run, progress_fn=_stuck_progress_fn())

    assert got.outcome == ec.OUTCOME_OK, "alternating with non-timeout failures must not give up"


# ---------- failure classification ---------------------------------------------------------


def test_timeouts_and_network_errors_classify_transient() -> None:
    """Every shape a dead network takes must be retryable — the whole point of the loop."""
    for err in ("ETIMEDOUT", "socket hang up", "getaddrinfo ENOTFOUND openrouter.ai",
                "HTTP 429 Too Many Requests", "503 Service Unavailable", "fetch failed"):
        assert ec.classify_llm_ext_failure(
            returncode=1, stderr=err, timed_out=False
        ) == ec.OUTCOME_TRANSIENT, err


def test_a_timeout_flag_is_transient_whatever_stderr_says() -> None:
    """A killed process often has EMPTY stderr — the timeout itself is the evidence."""
    assert ec.classify_llm_ext_failure(
        returncode=-9, stderr="", timed_out=True
    ) == ec.OUTCOME_TRANSIENT


def test_an_unreadable_failure_is_unknown_not_permanent() -> None:
    """Bias toward retrying: a false 'transient' costs one more attempt, a false 'permanent'
    costs the entire summary."""
    assert ec.classify_llm_ext_failure(
        returncode=2, stderr="Error: something went wrong", timed_out=False
    ) == ec.OUTCOME_UNKNOWN


def test_the_signature_uses_only_the_first_stderr_line() -> None:
    """Later lines routinely carry a timestamp or request id. Including them would make every
    identical failure look novel and defeat the repeat give-up entirely."""
    a = ec.failure_signature(returncode=2, stderr="boom\nreq-id: 111\nat 12:00:01")
    b = ec.failure_signature(returncode=2, stderr="boom\nreq-id: 222\nat 12:00:09")
    assert a == b == "2|boom"


# ---------- the fleet lane ------------------------------------------------------------------


def test_the_lane_caps_concurrency_at_three(tmp_path: Path) -> None:
    """THE point of the lane (owner: '20 compacting requests will surely result in a rate limit
    ban'), bounded the way the owner's timing requires: a run takes ~3 minutes, so SPACING 20
    sessions apart would queue the last one past any deadline and it would never run at all.
    Capping CONCURRENCY bounds the load without bounding throughput."""
    got = [
        ec.acquire_fleet_lease(now=1_000_000.0, max_concurrent=3, ttl_s=300, lane_dir=tmp_path)
        for _ in range(20)
    ]

    assert sum(1 for g in got if g) == 3, "exactly three may run at once"
    assert all(g is None for g in got[3:]), "the rest must be told to wait, not admitted"
    assert len({g for g in got if g}) == 3, "each holder must get a DISTINCT lease id"


def test_a_released_lease_lets_the_next_session_start_at_once(tmp_path: Path) -> None:
    """'after 3 requests in queue it must start to run them anyway' — the fourth session starts
    the moment one of the three finishes, not after a fixed spacing interval."""
    held = [
        ec.acquire_fleet_lease(now=1_000.0, max_concurrent=3, ttl_s=300, lane_dir=tmp_path)
        for _ in range(3)
    ]
    assert ec.acquire_fleet_lease(
        now=1_000.0, max_concurrent=3, ttl_s=300, lane_dir=tmp_path
    ) is None

    ec.release_fleet_lease(held[0], lane_dir=tmp_path)

    assert ec.acquire_fleet_lease(
        now=1_000.0, max_concurrent=3, ttl_s=300, lane_dir=tmp_path
    ) is not None


def test_a_lease_expires_so_a_killed_holder_cannot_wedge_the_lane(tmp_path: Path) -> None:
    """The holder is a process that can be killed. If expiry depended on a clean release, one
    crash would shrink the fleet's capacity permanently and every later session would degrade to
    the template forever — a failure that reports itself as 'the summary just never works'."""
    for _ in range(3):
        ec.acquire_fleet_lease(now=1_000.0, max_concurrent=3, ttl_s=300, lane_dir=tmp_path)

    assert ec.acquire_fleet_lease(
        now=1_100.0, max_concurrent=3, ttl_s=300, lane_dir=tmp_path
    ) is None, "still inside the TTL — the cap must hold"
    assert ec.acquire_fleet_lease(
        now=1_400.0, max_concurrent=3, ttl_s=300, lane_dir=tmp_path
    ) is not None, "past the TTL the dead holders' leases must be reclaimed"


def test_a_corrupt_or_absurd_lease_store_cannot_park_the_fleet(tmp_path: Path) -> None:
    """One bad write (or a clock jump) must not hold the lane shut — a lane that can strand the
    fleet is worse than no lane."""
    store = tmp_path / ec.FLEET_LEASE_FILE
    store.write_text('{"a": 99999999999, "b": 99999999999, "c": 99999999999}', encoding="utf-8")
    assert ec.acquire_fleet_lease(
        now=1_000.0, max_concurrent=3, ttl_s=300, lane_dir=tmp_path
    ) is not None

    store.write_text("not json at all", encoding="utf-8")
    assert ec.acquire_fleet_lease(
        now=1_000.0, max_concurrent=3, ttl_s=300, lane_dir=tmp_path
    ) is not None


def test_the_lane_is_off_at_zero_concurrency(tmp_path: Path) -> None:
    """Single-session hosts pay nothing: no store, no lock, no wait."""
    assert ec.acquire_fleet_lease(
        now=1_000.0, max_concurrent=0, ttl_s=300, lane_dir=tmp_path
    ) == "lane-disabled"
    assert not (tmp_path / ec.FLEET_LEASE_FILE).exists()


def test_an_unwritable_lane_fails_open(tmp_path: Path) -> None:
    """The lane must never be able to block the clear. Losing the cap costs a rate limit; losing
    the clear costs the full-price turn the whole feature exists to prevent."""
    blocked = tmp_path / "nope"
    blocked.write_text("i am a file, not a directory", encoding="utf-8")

    assert ec.acquire_fleet_lease(
        now=1_000.0, max_concurrent=3, ttl_s=300, lane_dir=blocked
    ) is not None


def test_awaiting_a_full_lane_past_the_deadline_gives_up() -> None:
    """A lane that stays full through the whole budget must return None so the caller degrades to
    the template — waiting forever for a nicer handoff would strand the session unshrunk."""
    full = Path("/nonexistent-so-we-inject-instead")
    calls: list[float] = []

    def _always_full(**kw) -> None:
        calls.append(kw["now"])
        return None

    original = ec.acquire_fleet_lease
    try:
        ec.acquire_fleet_lease = _always_full  # type: ignore[assignment]
        clock = _Clock()
        got = ec.await_fleet_lease(
            deadline=clock.now() + 12.0, max_concurrent=3, ttl_s=300, lane_dir=full,
            now_fn=clock.now, sleeper=clock.sleep, poll_s=5.0,
        )
    finally:
        ec.acquire_fleet_lease = original  # type: ignore[assignment]

    assert got is None
    assert len(calls) >= 2, "it must actually poll, not refuse on the first look"


def test_every_attempt_holds_and_releases_a_lease(tmp_path: Path) -> None:
    """Holding one lease for the whole retry sequence would keep a slot for the full backoff —
    minutes of sleeping while holding capacity three sessions are waiting for. Each ATTEMPT takes
    one and gives it back, so a sleeping retrier is not occupying the lane."""
    clock = _Clock()
    run = _attempts(_TRANSIENT, _TRANSIENT, _OK)

    got = _retry(clock, run, max_concurrent=3, lane_dir=tmp_path)

    assert got.outcome == ec.OUTCOME_OK
    import json as _json

    held = _json.loads((tmp_path / ec.FLEET_LEASE_FILE).read_text(encoding="utf-8"))
    assert held == {}, f"every lease must be released after its attempt, got {held}"


# ---------- the real subprocess boundary ----------------------------------------------------


def _script(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    p.chmod(0o755)
    return p


def test_a_real_failing_binary_is_classified_not_swallowed(tmp_path: Path) -> None:
    """The end-to-end shape, with a REAL process: a non-zero exit whose stderr names a 429 must
    arrive as TRANSIENT. `run_llm_ext_summary` collapses every failure to None, which makes an
    unplugged network indistinguishable from an uninstalled binary — the two want opposite
    responses, and that is why the classified sibling exists."""
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    fake = _script(tmp_path, "fake-llm-ext.sh", "echo 'HTTP 429 rate limit' >&2; exit 1")

    proc = subprocess.run(  # noqa: S603 - a script this test just wrote
        [str(fake)],
        capture_output=True,
        text=True,
        # Scaled for the suite by conftest's `_relax_subprocess_timeouts` seam, not here
        # (TRDD-7NSRD8OV). Measured: spawning this trivial `echo; exit 1` script exceeded 10 s
        # under suite load and raised TimeoutExpired straight through the test, which then
        # reads as a classification bug in `classify_llm_ext_failure` rather than a busy box.
        timeout=10,
        check=False,
    )

    assert proc.returncode == 1
    assert ec.classify_llm_ext_failure(
        returncode=proc.returncode, stderr=proc.stderr, timed_out=False
    ) == ec.OUTCOME_TRANSIENT


def test_an_install_time_precondition_is_permanent_not_transient() -> None:
    """A precondition that cannot change between attempts must classify PERMANENT so the loop
    stops at once instead of sleeping through the whole budget to re-learn it.

    Deliberately NOT named "missing binary": on a host where llm-ext IS installed this exercises
    the unreadable-transcript branch instead, and a test whose name asserts a branch it does not
    reach is the kind of green that means nothing. Both preconditions are install/run-time facts,
    both must be PERMANENT, and the detail says which one actually fired.
    """
    got = ec.attempt_llm_ext_summary("/definitely/not/a/file.jsonl")

    assert got.outcome == ec.OUTCOME_PERMANENT
    assert got.text is None
    # "is not installed", not the old "is not on PATH": since TRDD-CEWVQ8DG the CLI is resolved
    # by its plugin-cache layout too, so PATH is no longer the criterion. This set is what makes
    # the test environment-tolerant — WHICH precondition fires depends on the host — and that is
    # also why the rename escaped local review: on a machine where llm-ext IS installed this
    # reaches the transcript branch and never sees the renamed string. CI, with no llm-ext, did.
    # "data dir unresolvable" was REMOVED from this set 2026-08-16: the launcher self-derives
    # its data dir since 13.5.x, so the caller-side refusal no longer exists — it was the
    # CEWVQ8DG field failure (every daemon-context handoff degraded to the template).
    assert got.detail in {
        "llm-ext is not installed",
        "no readable transcript",
    }, got.detail


def test_an_empty_transcript_path_is_permanent() -> None:
    """The other install-time precondition, pinned without depending on the host's PATH."""
    got = ec.attempt_llm_ext_summary("")
    assert got.outcome == ec.OUTCOME_PERMANENT
