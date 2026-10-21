"""The host-pressure gate (TRDD-C8SALZOO) — a janitor chore yields to a busy host.

THE OWNER DIRECTIVE (2026-10-20), verbatim: "make this rule for the janitor
chores: never execute them when the system is under pressure. wait a moment when
the system activity is low to launch them, and pause them as soon as the system
becomes too busy again. even if they will slip to the night, it is better than
having those chores executed while the other main agents are struggling for cpu
time and resources!"

THE FIVE ASSERTIONS the card names, and the reasoning that keeps them from being
VACUOUS. This repo has already produced three vacuous tests in this area: a test
whose SUBJECT was refused by an EARLIER clause, so the clause under test never
ran and the test proved nothing. Every test here is written so that the clause
under test is the ONLY thing that can refuse its subject:

  * the subject of the deferral test is a task that is DUE, NOT yielded, NOT
    own_thread, NOT a background task, and NOT pressure-exempt — so the
    ownership/due/bulk clauses cannot refuse it;
  * the subject of the exemption test is the EXEMPT task, and the gate is
    exercised with a reading that is over the bar — so the exemption clause is
    the only thing that can let it through;
  * the fail-open test uses an UNREADABLE reading, which every other clause
    treats as "not under pressure", so the fail-open clause is the only one
    that can be wrong.

MUTATION-VERIFIED: each test was checked against the buggy form of the code it
covers. The battery and its results are in
`docs_dev/c8salzoo-pressure-gate-report.md`.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DAEMON = _PROJECT_ROOT / "scripts" / "daemon.py"

assert _DAEMON.is_file(), f"daemon not found at {_DAEMON}"

sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import state  # noqa: E402  — the lru_cached state paths the fixture must clear


def _import_daemon_module():
    """Import scripts/daemon.py as a module so we can call its helpers directly.

    The shebang line + PEP 723 block is harmless inside Python's import path;
    only the `if __name__ == '__main__'` guard prevents main() from running.
    """
    import importlib.util as _u

    spec = _u.spec_from_file_location("janitor_daemon_under_test", str(_DAEMON))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The daemon module with its global state pinned to a throwaway dir.

    `JANITOR_CONTROL_DIR` is pinned too: the last-run stamps live in the
    FIXED control plane (`~/.claude/janitor-control/`), and without the
    override every test in this file would share the real process's home
    directory — one test's stamp would make another's chore "not due".

    `CLAUDE_PROJECT_DIR` is pinned for the same reason: the findings ledger
    resolves the "current project" from it, so a test that records a finding
    without the override writes into the REAL repo's ledger.

    THE STATE PATH CACHES ARE CLEARED because `state.project_root()` and
    friends are `lru_cache`d for the process lifetime: a value cached by an
    EARLIER test in the same session would win over the env var set here, and
    the ledger would land in that earlier test's directory. The same
    discipline `tests/test_findings_ledger.py::_isolate` uses.
    """
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "control"))
    project = tmp_path / "project"
    (project / ".janitor" / "state").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    for fn in (state.project_root, state.janitor_root, state.state_dir):
        fn.cache_clear()
    mod = _import_daemon_module()
    mod.gs.init_global_state()
    # The deferral latch is PROCESS state; a stale one from a previous test
    # would silence the next test's first-deferral assertion. The fixture
    # clears it — and the RELEASE QUEUE and the episode bookkeeping with it —
    # so every test starts with an empty latch and an empty queue.
    mod._pressure_deferral_logged.clear()
    mod._pressure_release_queue.clear()
    # `setattr` and not a plain assignment: the module is typed as
    # `ModuleType`, and pyright rejects an attribute assignment on it
    # ("Cannot assign to attribute ... for class ModuleType") even though
    # the attribute genuinely exists on the module object.
    setattr(mod, "_pressure_episode_started_at", None)
    setattr(mod, "_pressure_episode_deferred", [])
    setattr(mod, "_pressure_episode_summarised", False)
    yield mod
    for fn in (state.project_root, state.janitor_root, state.state_dir):
        fn.cache_clear()


def _pressure(daemon, runnable, bar: int = 300):
    """A `HostPressure` reading for the tests — never the real host's.

    The field is named `runnable`, not `count`: `tuple` already has a `count`
    method, so a NamedTuple field of that name overrides it with an
    incompatible type and BOTH mypy and pyright reject the module. The
    construction here is POSITIONAL, so the rename does not change the call.
    """
    import host_pressure as hp

    return hp.HostPressure(runnable, bar)


def _logged_lines(daemon, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture what the daemon logged during the test."""
    lines: list[str] = []
    monkeypatch.setattr(
        daemon.state, "log_line", lambda name, message: lines.append(message)
    )
    return lines


# ---------- 1. a chore is DEFERRED when the host is over the bar ----------------


def test_a_chore_is_deferred_when_the_host_is_over_the_bar(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Over the bar → the chore does NOT run, and its last-run stamp is untouched.

    THE SUBJECT IS SET UP SO THE GATE IS THE ONLY CLAUSE THAT CAN REFUSE IT:
    the task is a plain FOREGROUND task (not background, so the bulk-lane
    clause cannot refuse it), it is not in `_FOREGROUND_FLOOR` (so the budget
    clause cannot refuse it), it is not yielded, it is not own_thread, and it
    is NOT pressure-exempt. It is DUE (interval 1 s, last-run forced into the
    past). The ONLY clause left that can stop it is the pressure gate.
    """
    ran = {"n": 0}
    task = daemon.Task("some-chore", 1, lambda: ran.__setitem__("n", ran["n"] + 1))
    # Force the stamp into the past so the task is genuinely DUE.
    task.last_run_path.parent.mkdir(parents=True, exist_ok=True)
    task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")
    assert task.is_due(), "the subject must be DUE or the gate is never reached"

    _logged_lines(daemon, monkeypatch)
    daemon._run_due_tasks([task], set(), _pressure(daemon, 427))

    assert ran["n"] == 0, "the chore ran while the host was over the bar"
    # The stamp is UNTOUCHED: a deferred chore stays DUE and runs at the next
    # calm beat. A stamp written here would make the deferral permanent.
    assert task._last_run() == int(time.time()) - 60, (
        "the deferred chore's last-run stamp was written — it would never run again"
    )
    assert task.is_due(), "a deferred chore must stay due"


def test_the_pressure_probe_is_taken_ONCE_PER_PASS_not_once_per_chore(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The card's requirement (b): no per-chore probe, no subprocess spawn each.

    THE PROBE IS COUNTED, not inferred. A test that only asserts the OUTCOME
    (chores run / are deferred) cannot see a per-chore probe at all — the
    outcome is identical either way, which is why a mutation that added a
    second probe was NOT CAUGHT by the outcome tests.

    THE SUBJECT: a pass over SEVERAL due chores. The counting seam is
    `host_pressure.read_pressure`, the ONE function the pass calls. With the
    probe taken once per pass, the count is 1 no matter how many chores the
    pass holds; with a per-chore probe it is N.

    THE READING IS INJECTED, NOT TAKEN FROM THE LIVE HOST. The pass is given
    `pressure=None` so it takes the REAL reading — and the env seam
    (`JANITOR_RUNNABLE_COUNT`) makes that reading a FIXED number instead of
    whatever the machine happens to be doing. Without the seam the test read
    the live process table, so on a host with >=300 runnable processes — the
    exact condition the feature exists for, and this host has reached 427 —
    the five chores were CORRECTLY deferred and the test FAILED. That is a
    deterministic failure whenever the host is busy, not a flake. 130 is
    below the bar and inside the measured healthy band (118-169), so the
    chores run, deterministically, on any host.
    """
    import host_pressure as hp

    monkeypatch.setenv(hp.RUNNABLE_COUNT_ENV, "130")

    calls = {"n": 0}
    real = hp.read_pressure

    def _counting() -> hp.HostPressure:
        calls["n"] += 1
        return real()

    monkeypatch.setattr(daemon.host_pressure, "read_pressure", _counting)

    ran = {"n": 0}
    tasks = []
    for i in range(5):
        task = daemon.Task(f"chore-{i}", 1, lambda: ran.__setitem__("n", ran["n"] + 1))
        task.last_run_path.parent.mkdir(parents=True, exist_ok=True)
        task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")
        tasks.append(task)

    daemon._run_due_tasks(tasks, set(), None)  # None → the pass takes the REAL reading

    assert calls["n"] == 1, (
        f"the pressure probe was taken {calls['n']} times for one pass over "
        f"{len(tasks)} chores — it must be taken ONCE per pass"
    )
    assert ran["n"] == 5, "the chores did not run — the pass is broken"


# ---------- 2. a deferred chore runs at the next calm beat ----------------------


def test_a_deferred_chore_runs_at_the_next_calm_beat(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under the bar → the chore runs. The same task, the same due state.

    This is the other half of test 1: a gate that deferred everything, always,
    would satisfy test 1 and starve every chore forever. The bar is crossed in
    the SAME direction the card names: below it, the chore runs.
    """
    ran = {"n": 0}
    task = daemon.Task("some-chore", 1, lambda: ran.__setitem__("n", ran["n"] + 1))
    task.last_run_path.parent.mkdir(parents=True, exist_ok=True)
    task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")

    _logged_lines(daemon, monkeypatch)
    daemon._run_due_tasks([task], set(), _pressure(daemon, 130))

    assert ran["n"] == 1, "the chore did not run on a calm beat"
    assert task._last_run() > int(time.time()) - 60, "a run must stamp last-run"


# ---------- 3. THE ANTI-DEADLOCK TEST: the runaway-kill chore runs under pressure --


def test_the_runaway_kill_chore_runs_even_when_the_host_is_over_the_bar(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE MOST IMPORTANT TEST IN THIS FILE (the card's acceptance clause 3).

    The runaway-KILL beat is the mechanism that ENDS host pressure. A gate that
    deferred it whenever the host is busy would be a DEADLOCK: the one chore
    that must always run is the one a busy host would suppress — and the
    2026-10-20 incident is exactly the situation where the kill daemon is
    needed most.

    THE EXEMPTION MUST BE THE ONLY THING THAT CAN LET THIS SUBJECT THROUGH. The
    reading is over the bar (427, the measured incident value) and the task is
    due, not yielded, not own_thread, not background and not in
    `_FOREGROUND_FLOOR` — so the exemption is the ONLY clause that can permit
    the run. A revert of the exemption (a name comparison that no longer
    matches, or the flag being ignored) makes this test fail ON THE RULE.
    """
    ran = {"n": 0}
    task = daemon.Task(
        "runaway-guard", 1, lambda: ran.__setitem__("n", ran["n"] + 1),
        pressure_exempt=True,
    )
    task.last_run_path.parent.mkdir(parents=True, exist_ok=True)
    task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")
    assert task.is_due()

    _logged_lines(daemon, monkeypatch)
    daemon._run_due_tasks([task], set(), _pressure(daemon, 427))

    assert ran["n"] == 1, (
        "the runaway-kill chore was deferred under pressure — that is the deadlock"
    )


def test_the_registry_marks_exactly_the_KNOWN_CHORES_as_pressure_exempt(
    daemon,
) -> None:
    """The exemptions are VISIBLE IN THE REGISTRY, and they are exactly this set.

    Three claims, and all three matter. (a) The `runaway-guard` registration
    carries `pressure_exempt=True` — so a reader of `_build_tasks` can SEE the
    exemption instead of having to know a name comparison. (b) The OAuth
    survival chain (`oauth-rotator-supervisor`, `oauth-recovery`) carries it
    too — a busy host is exactly when a session is most likely to run out of
    usable accounts, so the rotator must never be the thing the gate starves.
    (c) NO OTHER CHORE is exempt — the default is "gated", which is the safe
    side: a new chore added tomorrow is covered by the gate without anyone
    remembering to opt it out.

    `oauth-rotator-tick` is DELIBERATELY NOT in the set: it is `own_thread`,
    so the main loop never dispatches it and the gate is never reached for it.
    Marking it would be a false claim about a path that does not exist — and
    the assertion below pins that fact, so a future reader cannot "fix" the
    set by adding it.
    """
    tasks = daemon._build_tasks()
    exempt = sorted(t.name for t in tasks if t.pressure_exempt)
    assert exempt == ["oauth-recovery", "oauth-rotator-supervisor", "runaway-guard"], (
        f"the exempt set must be exactly the three survival chores, got {exempt}"
    )
    # The registrations of `runaway-guard` (the registry lists it once, but
    # a defensive check that the NAME is the one the card names):
    guard = [t for t in tasks if t.name == "runaway-guard"]
    assert guard, "the runaway-guard chore is not registered at all"
    assert all(t.pressure_exempt for t in guard), (
        "a runaway-guard registration is NOT pressure-exempt"
    )
    # The OAuth survival chain, one by one — so a failure names the chore.
    for name in ("oauth-rotator-supervisor", "oauth-recovery"):
        found = [t for t in tasks if t.name == name]
        assert found, f"the {name} chore is not registered at all"
        assert all(t.pressure_exempt for t in found), (
            f"a {name} registration is NOT pressure-exempt"
        )
    # And `oauth-rotator-tick` is own_thread: the gate never reaches it, so
    # it must NOT claim an exemption it never gets to use.
    tick = [t for t in tasks if t.name == "oauth-rotator-tick"]
    assert tick, "the oauth-rotator-tick chore is not registered at all"
    assert all(t.own_thread for t in tick), (
        "oauth-rotator-tick is no longer own_thread — the main loop would now "
        "dispatch it, and the gate WOULD reach it"
    )
    assert not any(t.pressure_exempt for t in tick), (
        "oauth-rotator-tick claims a pressure exemption it never uses — the "
        "main loop never dispatches it, so the gate is never reached for it"
    )


# ---------- 4. an UNREADABLE reading does not block the chores ------------------


def test_an_unreadable_pressure_reading_does_not_block_the_chores(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reading that could not be taken → the chores RUN (fail-open).

    THE SUBJECT IS SET UP SO THE FAIL-OPEN CLAUSE IS THE ONLY ONE THAT CAN BE
    WRONG. The reading is None — which every other clause treats as "not over
    the bar" — so the only way this test can fail is if the fail-open rule
    itself is wrong (a gate that treats an unreadable reading as a busy host).
    """
    ran = {"n": 0}
    task = daemon.Task("some-chore", 1, lambda: ran.__setitem__("n", ran["n"] + 1))
    task.last_run_path.parent.mkdir(parents=True, exist_ok=True)
    task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")

    _logged_lines(daemon, monkeypatch)
    daemon._run_due_tasks([task], set(), _pressure(daemon, None))

    assert ran["n"] == 1, (
        "an unreadable pressure reading blocked a chore — the gate is fail-CLOSED"
    )


def test_an_unreadable_reading_reached_through_the_env_seam_is_also_fail_open(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SAME fail-open rule, reached through the real probe and its env seam.

    The first fail-open test injects a `HostPressure` directly. This one goes
    through `host_pressure.read_runnable_count()` — the code path the daemon
    actually uses — with the `JANITOR_RUNNABLE_COUNT` seam set to an EMPTY
    value, which is how the module spells "cannot be read". So the test proves
    the rule at BOTH levels: the object the gate consults, and the probe that
    produces it.
    """
    monkeypatch.setenv("JANITOR_RUNNABLE_COUNT", "")
    import host_pressure as hp

    assert hp.read_runnable_count() is None, (
        "an empty injection must read as 'unreadable', not as zero"
    )
    assert hp.under_pressure(hp.read_runnable_count(), 300) is False, (
        "an unreadable reading must never be over the bar"
    )


# ---------- 5. the deferral is LOGGED ONCE PER EPISODE, not on every beat --------


def test_the_deferral_is_logged_once_per_episode_and_not_on_every_beat(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The FIRST deferral of an episode is logged; the rest of it is silent.

    THE CARD'S ACCEPTANCE (6): "a chore that slips to the night is VISIBLE and
    not silently starved". VISIBLE means the first deferral says so. NOT ON
    EVERY BEAT means the log does not fill with the same line once a minute
    for the hours the host stays busy — the repetition the repo's
    `dedupe.emit_once` and the `host-load.py` "first fire of an episode"
    pattern exist to prevent.

    The episode ENDS when the host goes calm, so a SECOND busy period is
    announced again — otherwise a chore starved by a host that is busy once a
    day would go silent forever after its first deferral.
    """
    ran = {"n": 0}
    task = daemon.Task("some-chore", 1, lambda: ran.__setitem__("n", ran["n"] + 1))
    task.last_run_path.parent.mkdir(parents=True, exist_ok=True)
    task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")

    lines = _logged_lines(daemon, monkeypatch)

    # Beat 1 of the episode: over the bar → deferred and announced.
    daemon._run_due_tasks([task], set(), _pressure(daemon, 427))
    deferrals = [ln for ln in lines if "deferring chore under host pressure" in ln]
    assert len(deferrals) == 1, f"the first deferral was not announced: {lines}"
    assert "some-chore" in deferrals[0], (
        f"the deferral line must NAME the chore: {deferrals[0]}"
    )
    assert "427" in deferrals[0], (
        f"the deferral line must carry the READING: {deferrals[0]}"
    )

    # Beats 2..4 of the SAME episode: still over the bar, still deferred, and
    # the log stays quiet.
    for _ in range(3):
        daemon._run_due_tasks([task], set(), _pressure(daemon, 427))
    deferrals = [ln for ln in lines if "deferring chore under host pressure" in ln]
    assert len(deferrals) == 1, (
        f"the deferral repeated on every beat ({len(deferrals)} lines): {deferrals}"
    )
    assert ran["n"] == 0, "the chore ran during a busy episode"

    # The host goes calm, then busy again → a NEW episode → announced again.
    daemon._run_due_tasks([task], set(), _pressure(daemon, 130))
    assert ran["n"] == 1, "the chore did not run on the calm beat"

    # The calm beat RAN the chore, which stamped last-run — so the task is no
    # longer due and the gate is never reached for it. Re-arm the stamp so the
    # next busy beat has a DUE subject; without this the "second episode"
    # assertion would be vacuous (the not-due clause would refuse the subject
    # before the gate ever saw it).
    task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")
    assert task.is_due()
    daemon._run_due_tasks([task], set(), _pressure(daemon, 427))
    deferrals = [ln for ln in lines if "deferring chore under host pressure" in ln]
    assert len(deferrals) == 2, (
        f"a SECOND episode was not announced: {deferrals}"
    )
    assert ran["n"] == 1, "the chore ran during the second busy episode"


# ---------- 6. the HYSTERESIS BAND: the latch clears only when the host is CALM --


def test_the_latch_survives_a_reading_IN_the_hysteresis_band(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reading BELOW THE BAR but above the CLEAR threshold keeps the latch.

    THE DEFECT THIS FIXES. The latch was cleared on the first reading under
    the bar. A host hovering at 299/300 then alternates
    busy -> announce -> clear -> busy -> announce, so the once-per-episode
    discipline — the whole point of the latch — failed EXACTLY in the band
    where it matters.

    THE SUBJECT. The reading used here is inside the hysteresis band: above
    `clear_at` (bar * 0.7 = 210) and below the bar (300). The chore is DUE,
    not yielded, not own_thread, not background and not pressure-exempt, so
    the ONLY thing that can end the episode is the latch.

    THE CLAUSE UNDER TEST IS THE ONLY ONE THAT CAN BE WRONG. The reading is
    under the bar, so the gate is OPEN and the chore runs — the test is NOT
    about whether the chore ran. It is about whether the episode ENDED. The
    next busy beat must NOT announce a second episode, because the first
    episode never ended.
    """
    ran = {"n": 0}
    task = daemon.Task("some-chore", 1, lambda: ran.__setitem__("n", ran["n"] + 1))
    task.last_run_path.parent.mkdir(parents=True, exist_ok=True)
    task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")

    lines = _logged_lines(daemon, monkeypatch)

    # Beat 1: over the bar → deferred and announced.
    daemon._run_due_tasks([task], set(), _pressure(daemon, 427))
    deferrals = [ln for ln in lines if "deferring chore under host pressure" in ln]
    assert len(deferrals) == 1, f"the first deferral was not announced: {lines}"

    # Beat 2: INSIDE the hysteresis band (210 <= 250 < 300) → the host is
    # under the bar, so the chore RUNS — but the episode must NOT end.
    daemon._run_due_tasks([task], set(), _pressure(daemon, 250))
    assert ran["n"] == 1, "a reading under the bar must let the chore run"

    # Beat 3: busy again → the SAME episode, so NO second announcement.
    task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")
    assert task.is_due()
    daemon._run_due_tasks([task], set(), _pressure(daemon, 427))
    deferrals = [ln for ln in lines if "deferring chore under host pressure" in ln]
    assert len(deferrals) == 1, (
        "the episode was re-announced after a reading INSIDE the hysteresis "
        f"band — the latch must survive it: {deferrals}"
    )
    assert ran["n"] == 1, "the chore ran during the second busy episode"


def test_an_UNREADABLE_reading_does_NOT_clear_the_latch(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable reading is not evidence of a calm host, so it clears nothing.

    THE FAIL-OPEN DIRECTION IS INVERTED HERE, DELIBERATELY. On the GATE,
    fail-open means "an unreadable reading never BLOCKS a chore". On the
    LATCH, fail-open means "an unreadable reading never CHANGES the latch".
    A failed `ps` is not evidence that the host recovered, and clearing the
    latch on it would announce a fresh episode on the next busy beat — the
    exact repetition the latch exists to prevent.
    """
    ran = {"n": 0}
    task = daemon.Task("some-chore", 1, lambda: ran.__setitem__("n", ran["n"] + 1))
    task.last_run_path.parent.mkdir(parents=True, exist_ok=True)
    task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")

    lines = _logged_lines(daemon, monkeypatch)

    daemon._run_due_tasks([task], set(), _pressure(daemon, 427))
    deferrals = [ln for ln in lines if "deferring chore under host pressure" in ln]
    assert len(deferrals) == 1, f"the first deferral was not announced: {lines}"

    # An UNREADABLE reading → fail-open on the gate (the chore runs) and NOT
    # a latch clear.
    daemon._run_due_tasks([task], set(), _pressure(daemon, None))
    assert ran["n"] == 1, "an unreadable reading must not block the chore"

    task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")
    assert task.is_due()
    daemon._run_due_tasks([task], set(), _pressure(daemon, 427))
    deferrals = [ln for ln in lines if "deferring chore under host pressure" in ln]
    assert len(deferrals) == 1, (
        "an UNREADABLE reading cleared the latch — it is not evidence of a "
        f"calm host: {deferrals}"
    )


def test_a_genuinely_calm_reading_DOES_clear_the_latch(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reading BELOW the clear threshold ends the episode, so the next one is announced.

    The other half of the hysteresis test: a gate that never cleared its
    latch would satisfy "the latch survives the band" and announce every
    busy period ONCE FOREVER — a chore starved by a host that is busy once a
    day would go silent after its first deferral. The clear threshold is
    `bar * DEFAULT_PRESSURE_CLEAR_FRACTION` = 210 with the default bar, and
    130 (inside the measured healthy band) is below it.
    """
    ran = {"n": 0}
    task = daemon.Task("some-chore", 1, lambda: ran.__setitem__("n", ran["n"] + 1))
    task.last_run_path.parent.mkdir(parents=True, exist_ok=True)
    task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")

    lines = _logged_lines(daemon, monkeypatch)

    daemon._run_due_tasks([task], set(), _pressure(daemon, 427))
    task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")
    assert task.is_due()
    # GENUINELY calm: below the clear threshold.
    daemon._run_due_tasks([task], set(), _pressure(daemon, 130))

    task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")
    assert task.is_due()
    daemon._run_due_tasks([task], set(), _pressure(daemon, 427))
    deferrals = [ln for ln in lines if "deferring chore under host pressure" in ln]
    assert len(deferrals) == 2, (
        f"a genuinely calm reading did NOT end the episode: {deferrals}"
    )


# ---------- 7. NO THUNDERING HERD: the deferred chores come back ONE PER PASS ---


def test_the_deferred_chores_come_back_ONE_PER_CALM_PASS(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backlog of deferred chores is released ONE PER CALM PASS, not all at once.

    THE DEFECT THIS FIXES. The gate NEVER stamps last-run, so a chore
    deferred for twelve hours stays DUE — and would run at the FIRST moment
    the host dips under the bar. ALL the deferred chores at once, in one
    pass: a brief dip during an incident released the entire backlog
    simultaneously, which is the opposite of what the owner asked for.

    THE SUBJECT. Three chores, all DUE, all deferred by a busy beat. The
    first calm beat must release exactly ONE of them; the other two must
    still be deferred. The next calm beat releases the second, and so on.

    THE ASSERTION IS ON WHAT RAN, not on a return value: `ran` counts the
    executions, so a gate that released everything would show 3 on the first
    calm pass.

    NOTHING IS RE-ARMED BETWEEN THE PASSES, and that is load-bearing. A
    deferred chore is never stamped, so it stays DUE on its own; a RELEASED
    chore DID stamp its last-run, so it is no longer due and does not run
    again. Re-arming it would put it back in the "due" set and it would run
    a second time — which is correct behaviour, but it is not what this test
    is about: the test is about the BACKLOG, and the backlog is the set of
    chores still waiting for their turn.
    """
    ran: list[str] = []
    tasks = []
    for name in ("chore-a", "chore-b", "chore-c"):
        task = daemon.Task(name, 1, lambda n=name: ran.append(n))
        task.last_run_path.parent.mkdir(parents=True, exist_ok=True)
        task.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")
        assert task.is_due()
        tasks.append(task)

    _logged_lines(daemon, monkeypatch)

    # The busy beat: all three are deferred.
    daemon._run_due_tasks(tasks, set(), _pressure(daemon, 427))
    assert ran == [], f"the chores ran during the busy episode: {ran}"
    assert sorted(daemon._pressure_release_queue) == ["chore-a", "chore-b", "chore-c"], (
        "the deferred chores are not all queued for release: "
        f"{daemon._pressure_release_queue}"
    )

    # The FIRST calm beat: exactly ONE chore comes back.
    daemon._run_due_tasks(tasks, set(), _pressure(daemon, 130))
    assert len(ran) == 1, (
        f"the whole backlog was released at once ({ran}) — the deferred chores "
        "must come back ONE PER CALM PASS"
    )
    assert len(daemon._pressure_release_queue) == 2, (
        f"the release queue did not shrink by exactly one: "
        f"{daemon._pressure_release_queue}"
    )

    # The SECOND calm beat: the second chore, and only the second.
    daemon._run_due_tasks(tasks, set(), _pressure(daemon, 130))
    assert len(ran) == 2, (
        f"the second calm pass did not release exactly one more chore: {ran}"
    )
    assert len(daemon._pressure_release_queue) == 1, (
        f"the release queue did not shrink by exactly one: "
        f"{daemon._pressure_release_queue}"
    )

    # The THIRD: the last one. The backlog is now empty.
    daemon._run_due_tasks(tasks, set(), _pressure(daemon, 130))
    assert len(ran) == 3, f"the backlog did not drain one chore per pass: {ran}"
    assert daemon._pressure_release_queue == [], (
        f"the release queue did not drain: {daemon._pressure_release_queue}"
    )


def test_a_chore_that_was_NEVER_deferred_is_NOT_metered(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The release meter only touches the DEFERRED chores.

    A chore that was never deferred is not in the queue, so the ordinary
    path is unaffected: it runs on the first calm beat, in the same pass as
    the released one, and is not held back by the meter's backlog.

    THE SUBJECT IS SET UP SO THE CHORE IS NEVER DEFERRED: it is NOT DUE
    during the busy beat (its last-run stamp is fresh), so the gate never
    sees it and it never enters the queue. It is re-armed before the calm
    pass, so it is due then.
    """
    ran: list[str] = []
    deferred = daemon.Task("chore-a", 1, lambda: ran.append("chore-a"))
    fresh = daemon.Task("chore-b", 1, lambda: ran.append("chore-b"))
    for task in (deferred, fresh):
        task.last_run_path.parent.mkdir(parents=True, exist_ok=True)
    # `deferred` is due (stamp in the past); `fresh` is NOT (stamp = now).
    deferred.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")
    fresh.last_run_path.write_text(str(int(time.time())), encoding="utf-8")
    assert deferred.is_due()
    assert not fresh.is_due(), (
        "the test's subject is wrong: chore-b must NOT be due during the busy "
        "beat, or it would be deferred too and enter the queue"
    )
    tasks = [deferred, fresh]

    _logged_lines(daemon, monkeypatch)

    daemon._run_due_tasks(tasks, set(), _pressure(daemon, 427))
    assert ran == [], f"the chores ran during the busy episode: {ran}"
    assert daemon._pressure_release_queue == ["chore-a"], (
        "only the deferred chore should be queued: "
        f"{daemon._pressure_release_queue}"
    )

    # Re-arm the never-deferred chore so it is due on the calm pass.
    fresh.last_run_path.write_text(str(int(time.time()) - 60), encoding="utf-8")
    assert fresh.is_due()
    daemon._run_due_tasks(tasks, set(), _pressure(daemon, 130))
    assert sorted(ran) == ["chore-a", "chore-b"], (
        f"the never-deferred chore was held back by the release meter: {ran}"
    )


# ---------- the probe itself ----------------------------------------------------


def test_the_runnable_count_probe_counts_every_runnable_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe counts `R` and every MODIFIED runnable state, and nothing else.

    MEASURED on this host, the distinct `ps -axo state=` tokens are `Ss`, `S`,
    `S+`, `R`, `Rs`, `RN`, `R+`, `SN`, `Z`, `U` and `?E`. A comparison against
    the WHOLE token would miss `Rs`, `RN` and `R+` — three of the four
    runnable spellings — and undercount the pressure signal by roughly a
    third. Only the FIRST character decides.
    """
    import host_pressure as hp

    ps_text = "Ss  \nS   \nR   \nRs  \nRN  \nR+  \nSN  \nZ   \nU   \n?E  \n"
    assert hp.parse_runnable_count(ps_text) == 4, (
        "the probe must count R, Rs, RN and R+ — and only those"
    )
    assert hp.parse_runnable_count("") == 0
    assert hp.parse_runnable_count("S\nS\nS\n") == 0


def test_the_bar_is_the_measured_runnable_count_and_not_a_core_multiple(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bar is 300 runnable — a MEASURED absolute count, not cores x N.

    The card's acceptance clause 4 asked for a core-relative bar, and the
    measurement REFUTED it: on this host the load average sits permanently at
    13x the core count, so a core-relative bar would be permanently on. A
    runnable COUNT is not a rate, so "cores x N" has no meaning for it. The
    bar is the measured value, and it is overridable per host because a bar
    copied to another host without re-measuring is the mistake the card warns
    about.
    """
    import host_pressure as hp

    monkeypatch.delenv(hp.PRESSURE_BAR_ENV, raising=False)
    assert hp.pressure_bar() == 300
    assert hp.pressure_bar() == hp.DEFAULT_PRESSURE_BAR

    # A measured healthy band (118-169) is UNDER the bar; the measured
    # incident (427) is OVER it. Those are the two measured numbers, and the
    # bar must separate them.
    assert hp.under_pressure(169, hp.pressure_bar()) is False
    assert hp.under_pressure(118, hp.pressure_bar()) is False
    assert hp.under_pressure(427, hp.pressure_bar()) is True
    # AT the bar counts as over it.
    assert hp.under_pressure(300, hp.pressure_bar()) is True

    # The env override, and the refusal of a zero bar (a zero bar would close
    # the gate on EVERY host, including a calm one).
    monkeypatch.setenv(hp.PRESSURE_BAR_ENV, "500")
    assert hp.pressure_bar() == 500
    monkeypatch.setenv(hp.PRESSURE_BAR_ENV, "0")
    assert hp.pressure_bar() == hp.DEFAULT_PRESSURE_BAR
    monkeypatch.setenv(hp.PRESSURE_BAR_ENV, "not-a-number")
    assert hp.pressure_bar() == hp.DEFAULT_PRESSURE_BAR


def test_the_probe_reads_the_injected_count_instead_of_spawning_ps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The env seam replaces the real reading, and no subprocess is spawned.

    The seam is what makes the gate testable on ANY host: a test that read the
    real process table would be asserting about whatever the machine happened
    to be doing. It is the same shape as the existing `host-load.py` seam
    (`JANITOR_LOADAVG` / `JANITOR_CPU_COUNT`).
    """
    import host_pressure as hp

    def _boom(*_a, **_k):
        raise AssertionError("the probe spawned a subprocess despite the seam")

    monkeypatch.setattr(hp.subprocess, "run", _boom)
    monkeypatch.setenv(hp.RUNNABLE_COUNT_ENV, "427")
    assert hp.read_runnable_count() == 427

    monkeypatch.setenv(hp.RUNNABLE_COUNT_ENV, "")
    assert hp.read_runnable_count() is None

    monkeypatch.setenv(hp.RUNNABLE_COUNT_ENV, "not-a-number")
    assert hp.read_runnable_count() is None


# ---------- A-2 / A-3: the kill record lands in the VICTIM's ledger ------------


def _critical_pressure():
    """A `runaway_guard.Pressure` in the CRITICAL state, for the kill path."""
    import runaway_guard as rg

    return rg.Pressure(
        state="critical",
        free_mb=100,
        swap_used_mb=8000,
        swap_total_mb=8192,
        swap_pct=97,
        swapfiles=40,
        compressor_pct=95,
    )


def _victim(pid: int = 4242):
    import runaway_guard as rg

    return rg.ProcRow(
        pid=pid,
        ppid=1,
        rss_kb=8 * 1024 * 1024,
        etime_s=99_999,
        command="/usr/local/bin/node /x/agent.js",
    )


def _run_the_kill_beat(
    daemon,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict]:
    """Drive `task_runaway_guard` down the kill path, capturing the ledger call.

    Everything the beat touches is stubbed: the host pressure reads CRITICAL,
    the process snapshot and ancestry come back with one victim, the kill
    succeeds, and the BROADCAST is captured but never inspected here (the
    broadcast is host-level by design — TRDD-X92VBFNF — and the assertions
    here are about the LEDGER, not the broadcast).

    Returns the list of ledger entries the daemon recorded.
    """
    import runaway_alert as ral
    import runaway_guard as rg

    monkey = monkeypatch

    monkey.setenv("CLAUDE_PLUGIN_OPTION_RUNAWAY_GUARD_ENABLED", "1")
    monkey.setattr(rg, "host_pressure", lambda **kw: _critical_pressure())
    monkey.setattr(rg, "snapshot_processes", lambda p: [_victim()])
    monkey.setattr(rg, "snapshot_ancestry", lambda p: {})
    monkey.setattr(rg, "select_victim", lambda rows, **kw: rows[0])
    monkey.setattr(rg, "kill_process", lambda pid, **kw: True)
    monkey.setattr(ral, "record_kill", lambda root, rec: None)

    captured: list[dict] = []
    real_record = daemon.findings_ledger.record

    def _spy(**kwargs):
        captured.append(kwargs)
        return real_record(**kwargs)

    monkey.setattr(daemon.findings_ledger, "record", _spy)

    daemon.task_runaway_guard()
    return captured


def test_the_kill_entry_is_NOT_marked_human_only(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-3 (TRDD-ZIKYQQY0): the actor is NOT the human-only marker.

    `actor="human"` means "a remedy an agent structurally cannot perform —
    surface it to your human and move on" (TRDD-KU3ERYFX, janitor#234). It
    also makes the entry exempt from suppression and prepends a HUMAN-ONLY
    directive at delivery. A kill the janitor ALREADY performed is neither
    human-only nor a directive: there is nothing to attempt and nothing to
    re-evaluate, so the directive is a lie about a finding whose content is
    "I did it".

    The assertion is on the ACTOR, not on the field's presence: dropping the
    field entirely (leaving the ledger's default "agent") is correct, and so
    is any other non-human value. Only the human-only marker is wrong.
    """
    import findings_ledger as fl

    captured = _run_the_kill_beat(daemon, tmp_path, monkeypatch)

    assert len(captured) == 1, f"the kill was not recorded at all: {captured}"
    actor = captured[0].get("actor", "agent")
    assert actor != fl.HUMAN_ONLY_ACTOR, (
        "the kill entry is marked HUMAN-ONLY — it would be delivered with a "
        "directive to surface it and stop, which is wrong for an action the "
        "janitor already performed"
    )
    # And the severity stays HIGH.
    assert captured[0]["sev"] == "HIGH", (
        f"the kill entry's severity changed: {captured[0]['sev']!r}"
    )


def test_a_project_cannot_SUPPRESS_the_kill_entry(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project's own `.janitor.toml` CANNOT silence the kill record.

    THE CLAIM THIS EXERCISES. The kill is recorded with severity HIGH, and
    HIGH is in `NEVER_SUPPRESSED_SEVERITIES` — so a project that writes
    `[lint] ignore = ["RUNAWAY-KILLED"]` in its own `.janitor.toml` must STILL
    get the entry in its ledger.

    WHY THE OLD ASSERTION WAS VACUOUS. The previous test asserted
    `captured[0]["sev"] in fl.NEVER_SUPPRESSED_SEVERITIES` — a membership check
    on a CONSTANT. It proved that a frozenset contains "HIGH"; it never
    exercised the path the claim rests on, which is the SUPPRESSION PATH
    (`findings_ledger.is_suppressed`, reached from `record` at
    findings_ledger.py:293-300). A constant cannot fail, so the test could
    not fail.

    THE SUPPRESSION PATH, in full: `record` skips the entry only when
      * the code is not `CONFIG-001`, AND
      * the actor is not the human-only marker, AND
      * the severity is not in `NEVER_SUPPRESSED_SEVERITIES`, AND
      * `is_suppressed(code, project_dir)` is True.
    With the actor ABSENT (the ledger's default "agent") and the severity
    HIGH, the entry must SURVIVE — and this test proves it by actually
    writing the `.janitor.toml` and checking the LEDGER FILE, not a captured
    kwarg.

    THE `.janitor.toml` FORMAT is the one the repo's own tests use
    (`tests/test_findings_ledger.py`): a `[lint]` table with an `ignore` list.
    """
    import findings_ledger as fl

    # The fixture pins `CLAUDE_PROJECT_DIR` at `tmp_path/"project"`, and the
    # daemon records the kill with no `project_dir` — so that IS the project
    # the entry lands in, and the project whose `.janitor.toml` is read.
    project = tmp_path / "project"
    (project / ".janitor.toml").write_text(
        '[lint]\nignore = ["RUNAWAY-KILLED"]\n', encoding="utf-8"
    )

    captured = _run_the_kill_beat(daemon, tmp_path, monkeypatch)

    assert len(captured) == 1, f"the kill was not recorded at all: {captured}"
    assert captured[0]["sev"] == "HIGH", (
        f"the kill entry's severity changed: {captured[0]['sev']!r}"
    )
    # The premise of the claim: the project's own config DOES select the code.
    # Without this the test would pass for the wrong reason — a `.janitor.toml`
    # that does not match the code proves nothing about suppression.
    assert fl.is_suppressed("RUNAWAY-KILLED", str(project)) is True, (
        "the test's premise is broken: the project's .janitor.toml does not "
        "actually select RUNAWAY-KILLED, so this test would pass vacuously"
    )
    # And the entry SURVIVED the suppression path.
    ledger = fl.ledger_path(str(project))
    assert ledger.is_file(), f"the ledger was not written at {ledger}"
    raw = ledger.read_text(encoding="utf-8")
    assert "RUNAWAY-KILLED" in raw, (
        "a project's own .janitor.toml SILENCED the kill record — HIGH is in "
        f"NEVER_SUPPRESSED_SEVERITIES, so it must not be suppressible: {raw!r}"
    )


def test_the_kill_entry_is_still_recorded_and_still_rendered(
    daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-3's second half: dropping the human-only marker must NOT lose the entry.

    A human-only entry is ALSO recorded — the ledger keeps it — so "the entry
    is missing" is not the failure mode here. The failure mode is a DIRECTIVE
    that changes how the finding is READ, and a suppressed repeat. This test
    asserts the entry is present in the ledger file AND that its rendered line
    carries no HUMAN-ONLY directive.
    """
    import findings_ledger as fl

    # The fixture pins `CLAUDE_PROJECT_DIR` at `tmp_path/"project"`, and the
    # daemon records the kill with no `project_dir` — so the entry lands
    # THERE, in the janitor's own (guaranteed-writable) ledger.
    project = tmp_path / "project"

    _run_the_kill_beat(daemon, tmp_path, monkeypatch)

    ledger = fl.ledger_path(str(project))
    assert ledger.is_file(), f"the ledger was not written at {ledger}"
    raw = ledger.read_text(encoding="utf-8")
    assert "RUNAWAY-KILLED" in raw, f"the kill entry is not in the ledger: {raw!r}"
    assert "HUMAN-ONLY" not in raw, (
        f"the ledger entry is marked human-only: {raw!r}"
    )
    # The rendered line — what a session actually reads — must not carry the
    # directive either.
    assert fl.HUMAN_ONLY_DIRECTIVE not in fl.render_line(
        {
            "ts": 0,
            "sev": "HIGH",
            "code": "RUNAWAY-KILLED",
            "src": "runaway-guard",
            "ref": "1",
            "msg": "killed runaway pid 1 node",
        }
    )


# ---------- A-4: the printed-kill stamp is bounded and does not replay history ---


def _import_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`scripts/dispatch.py` with its project and global state pinned to tmp dirs.

    The stamp file lives in the PROJECT's state dir, so without the override
    the test would read and WRITE the real project's stamp — and a test that
    wrote to the developer's own `.janitor/state` is a test that changes the
    machine's behaviour.

    THE STATE PATH CACHES ARE CLEARED: `state.project_root()`,
    `state.janitor_root()` and `state.state_dir()` are `lru_cache`d for the
    process lifetime, so a value cached by an EARLIER test in this session
    would win over the env var set here — and the episode stamp, the
    last-run stamps and the findings ledger would all land in that earlier
    test's directory. The same discipline `tests/test_findings_ledger.py`
    uses. (The `daemon` fixture clears them for its own module; the two
    import paths are independent, so each clears its own.)
    """
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "global"))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "control"))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    for fn in (state.project_root, state.janitor_root, state.state_dir):
        fn.cache_clear()

    import importlib.util as _u

    spec = _u.spec_from_file_location(
        "janitor_dispatch_a4_under_test", str(_PROJECT_ROOT / "scripts" / "dispatch.py")
    )
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_kills(dispatch, kills: list[dict]) -> None:
    """Write kill records into the global-state broadcast file."""
    import runaway_alert as ral

    root = dispatch.gs.global_state_dir()
    root.mkdir(parents=True, exist_ok=True)
    for kill in kills:
        ral.record_kill(root, kill)


def _kill(pid: int, at: float) -> dict:
    import runaway_alert as ral

    return ral.kill_record(
        pid=pid, name="node", rss_mb=2100, age_s=7200,
        reason="host pressure critical", readings="free=100MB", at=at,
    )


def _stamp_path(dispatch):
    return dispatch.state.state_dir() / "runaway-alert-printed.txt"


def test_the_printed_kill_stamp_is_BOUNDED(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-4(a): the stamp file holds at most the cap, however many kills arrive.

    THE DEFECT: the old writer kept `sorted(seen | set(fresh_sigs))` — the
    union of every signature ever printed, never trimmed. On a host that kills
    regularly the file grows without limit, and past the daemon's own 50-kill
    retention no entry can ever match a live kill again.

    THE ASSERTION IS ON THE FILE, not on a return value: the file is the
    artefact that grows, so the file is what must be bounded.

    THE BROADCAST IS WRITTEN DIRECTLY, NOT THROUGH `record_kill`. The daemon's
    writer trims the broadcast to the last 50 kills, so going through it could
    only ever deliver 50 kills — and the test would then be asserting the
    DAEMON's trim, not the STAMP's bound. The stamp is what this test is
    about, so the broadcast is written raw and the stamp's own bound is what
    must hold. (MUTATION-VERIFIED: reverting the stamp's trim leaves this test
    PASSING when the broadcast goes through `record_kill` — that is the
    vacuous form this fix removes.)
    """
    import json
    import time

    dispatch = _import_dispatch(tmp_path, monkeypatch)
    now = time.time()
    # THE KILL COUNT AND THE BOUND ARE BOTH ABSOLUTE. An earlier version
    # derived the count from the module's own cap (`cap + 25`) and asserted
    # `len(lines) <= cap` — a TAUTOLOGY: raising the cap raised the count
    # with it, and the test kept passing (MUTATION-VERIFIED as NOT CAUGHT).
    # The bound asserted here is a FIXED number, so a cap raised past it
    # fails the test.
    absolute_bound = 50
    assert dispatch.RUNAWAY_ALERT_STAMP_MAX == absolute_bound, (
        f"the cap moved to {dispatch.RUNAWAY_ALERT_STAMP_MAX}; this test pins "
        f"the bound at {absolute_bound} and must be re-derived if it moves"
    )
    kills = [_kill(1000 + i, now) for i in range(200)]
    root = dispatch.gs.global_state_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "runaway-alert.json").write_text(
        json.dumps({"kills": kills}), encoding="utf-8"
    )

    dispatch._phase_runaway_alert()

    stamp = _stamp_path(dispatch)
    lines = [ln for ln in stamp.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) <= absolute_bound, (
        f"the stamp grew to {len(lines)} lines, past the bound of {absolute_bound}"
    )
    assert lines, "the stamp is empty — nothing was recorded at all"


def test_a_NEW_session_does_NOT_re_print_the_historical_kill_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-4(b): a fresh project (empty stamp) does not replay the kill HISTORY.

    THE DEFECT: the stamp lives in the PROJECT's state dir, so a session that
    has never seen the kills starts with an EMPTY stamp, finds every retained
    kill "unseen", and prints all of them as if they had just happened. The
    daemon's file is never cleared, so the history is permanent and every new
    project re-plays it.

    THE SUBJECT IS A FRESH PROJECT: the stamp file does not exist, so the
    "already printed" clause CANNOT refuse any kill — the recency clause is
    the only thing that can. A kill OLDER than the recency window must not be
    printed; a kill NEWER must be.
    """
    import time

    dispatch = _import_dispatch(tmp_path, monkeypatch)
    now = time.time()
    # THE AGES ARE ABSOLUTE, NOT DERIVED FROM THE MODULE'S WINDOW. A test
    # that computes its subject from the constant it is testing moves WITH
    # the constant: widening the window by 100x moved the "historical" kill
    # with it, and the test kept passing (MUTATION-VERIFIED). The kill must
    # be OLD by any plausible reading of "recent" — two days — so the window's
    # exact value is not what the test depends on.
    old = _kill(1111, now - 2 * 24 * 3600)
    new = _kill(2222, now - 60)
    _write_kills(dispatch, [old, new])

    from io import StringIO

    buf = StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        dispatch._phase_runaway_alert()
    finally:
        sys.stdout = old_stdout
    out = buf.getvalue()

    assert "1111" not in out, (
        f"the HISTORICAL kill was re-printed as a current event: {out!r}"
    )
    assert "2222" in out, (
        f"the RECENT kill was NOT printed — a session that never saw it must "
        f"still learn the host killed something: {out!r}"
    )


def test_a_recent_kill_is_printed_EXACTLY_ONCE_across_fires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stamp still does its ORIGINAL job: no re-print of the same kill.

    A-4 must not break the de-duplication the stamp existed for. The second
    fire finds the signature in the stamp and prints nothing.

    THE CLAUSE UNDER TEST IS THE ONLY ONE THAT CAN REFUSE THE SECOND PRINT:
    the kill is RECENT (so the recency clause does not refuse it) and the
    stamp holds its signature (so the "already printed" clause refuses it).
    """
    import time
    from io import StringIO

    dispatch = _import_dispatch(tmp_path, monkeypatch)
    _write_kills(dispatch, [_kill(3333, time.time() - 60)])

    def _fire() -> str:
        buf = StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            dispatch._phase_runaway_alert()
        finally:
            sys.stdout = old_stdout
        return buf.getvalue()

    first = _fire()
    second = _fire()
    assert "3333" in first, f"the first fire printed nothing: {first!r}"
    assert "3333" not in second, (
        f"the kill was re-printed on the second fire: {second!r}"
    )


def test_a_kill_with_an_UNREADABLE_timestamp_is_not_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A record with no readable `at` is not printed as news.

    A timestamp that cannot be read is not evidence that the kill is recent,
    and printing it would re-introduce the "history replayed as current"
    defect through the back door.
    """
    from io import StringIO

    dispatch = _import_dispatch(tmp_path, monkeypatch)
    import runaway_alert as ral

    root = dispatch.gs.global_state_dir()
    root.mkdir(parents=True, exist_ok=True)
    ral.record_kill(root, {"pid": 4444, "name": "node", "rss_mb": 1,
                           "age_s": 1, "reason": "x", "readings": "y"})

    buf = StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        dispatch._phase_runaway_alert()
    finally:
        sys.stdout = old_stdout
    assert "4444" not in buf.getvalue(), (
        f"a kill with no readable timestamp was printed: {buf.getvalue()!r}"
    )


# ---------- the DETECTOR-path gate -------------------------------------------


def test_the_heavy_roster_names_are_ALL_real_roster_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The heavy set is ASSERTED AGAINST THE REAL ROSTER, not against itself.

    THE VACUITY THIS FIXES. The heavy roster is a constant, and a test that
    asserts a constant against itself proves nothing: emptying the roster
    empties the subject and the test still passes. The roster is EXTRACTED
    FROM THE MODULE AT TEST TIME — never a hard-coded copy of it, which
    would drift the moment a detector is added or renamed.

    EVERY heavy name must be a REAL roster entry. A name that is not in the
    roster is a dead name: the gate would never defer it, because the gate
    is only ever consulted for detectors the roster actually holds.
    """
    dispatch = _import_dispatch(tmp_path, monkeypatch)

    roster = {name for name, _i, _e in dispatch._DETECTORS}
    assert roster, "the detector roster is empty — the module's roster changed shape"
    heavy = dispatch._PRESSURE_HEAVY_DETECTORS
    assert heavy, "the heavy roster is empty — every detector would be ungated"

    not_in_roster = sorted(heavy - roster)
    assert not not_in_roster, (
        f"these heavy detectors are NOT in the real roster — the gate would "
        f"never defer them: {not_in_roster}"
    )
    # And the intersection is not empty — the gate has something to act on.
    assert heavy & roster, (
        "the heavy roster and the real roster do not intersect — the gate "
        "would never defer anything"
    )


def test_a_heavy_detector_is_deferred_when_the_host_is_over_the_bar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dispatch path's gate refuses a HEAVY detector over the bar.

    THE CLAUSE UNDER TEST IS THE ONLY ONE THAT CAN REFUSE THE SUBJECT: the
    detector IS in the heavy set (so the roster clause does not refuse it),
    and the reading IS over the bar (so the recency/pressure clause is what
    refuses it).
    """
    import host_pressure as hp

    dispatch = _import_dispatch(tmp_path, monkeypatch)
    # THE HEAVY DETECTOR IS CHOSEN BY THE TEST, NOT READ FROM THE ROSTER. A
    # test that picks its subject out of the roster it is testing is VACUOUS
    # in a specific way: emptying the roster empties the subject, and the
    # test then asserts about nothing. (MUTATION-VERIFIED: replacing the
    # roster's first member with a non-member left this test PASSING before
    # this fix.) A fixed, named heavy detector is the subject.
    heavy = "memory-librarian"
    assert heavy in dispatch._PRESSURE_HEAVY_DETECTORS, (
        f"{heavy!r} is no longer a heavy detector — pick another named one"
    )
    # AND THE NAME IS A REAL ROSTER ENTRY — the roster membership is a
    # separate, explicit claim, asserted against the LIVE roster extracted
    # from the module (not a hard-coded copy of it).
    roster = {name for name, _i, _e in dispatch._DETECTORS}
    assert heavy in roster, (
        f"{heavy!r} is not in the real detector roster — the gate would never "
        "see it"
    )

    assert dispatch._pressure_gate_blocks_detector(
        heavy, hp.HostPressure(427, 300)
    ) is True, "a heavy detector was NOT deferred under pressure"

    assert dispatch._pressure_gate_blocks_detector(
        heavy, hp.HostPressure(130, 300)
    ) is False, "a heavy detector WAS deferred on a calm host"


def test_a_LIGHT_detector_is_never_deferred_by_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A detector outside the heavy set is NEVER refused by the gate.

    THIS IS THE REASONING THE CARD ASKED FOR, made executable: the heartbeat
    IS the mechanism that notices a pressure problem, and a light detector
    costs less than the heartbeat's own tick — deferring it would cost a
    whole interval to save a fraction of a second.
    """
    import host_pressure as hp

    dispatch = _import_dispatch(tmp_path, monkeypatch)
    light = "dirty-tree"  # a cheap, read-only detector
    assert light not in dispatch._PRESSURE_HEAVY_DETECTORS

    assert dispatch._pressure_gate_blocks_detector(
        light, hp.HostPressure(427, 300)
    ) is False, "a LIGHT detector was deferred — the whole heartbeat must not be gated"


def _fire_dispatch(
    dispatch,
    monkeypatch: pytest.MonkeyPatch,
    roster: list[tuple[str, int, str]],
    *,
    in_harness: bool = False,
    lines: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Run ONE real heartbeat fire over `roster` and report what happened.

    THE SUBJECT IS THE PRODUCTION PATH. These tests drive `dispatch.main()` —
    the same entry a real cron fire takes — rather than a helper extracted
    from it, so what they assert on is what a fire DOES and not what a
    stand-in of a fire does. An extracted helper is a SECOND implementation
    of the loop, and a test of the helper is a test of that copy.

    THE HARNESS IS ENTERED THROUGH THE ENV VAR the production code reads
    (`AIMAESTRO_AGENT=1`), not by replacing the predicate: the point of the
    harness test is that the fire really takes the harness path.

    `lines` is the ACCUMULATOR: the caller passes the same list across
    several fires to see the log of the whole episode. A fresh list per fire
    would hide the repetition this file exists to catch.

    RETURNS: (the detectors that ran, the log lines).
    """
    monkeypatch.setattr(dispatch, "_DETECTORS", roster)
    # The daemon spawn and the branch-protection applier are the two phases
    # that would touch the MACHINE from a test. Both are stubbed; nothing
    # else in the fire is.
    monkeypatch.setattr(dispatch.gs, "ensure_daemon_running", lambda *a, **k: None)
    monkeypatch.setattr(dispatch, "_phase_guard_branch_protection", lambda: None)
    if in_harness:
        monkeypatch.setenv("AIMAESTRO_AGENT", "1")
    else:
        monkeypatch.delenv("AIMAESTRO_AGENT", raising=False)

    ran: list[str] = []
    monkeypatch.setattr(dispatch, "_run_detector", lambda name, interval, **kw: ran.append(name))
    collected = lines if lines is not None else []
    monkeypatch.setattr(
        dispatch.state, "log_line", lambda name, message: collected.append(message)
    )

    assert dispatch.main() == 0, "the fire did not return 0"
    return ran, collected


def test_a_detector_that_is_NOT_due_is_never_reported_as_deferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The due-check comes FIRST, so a not-due detector is never "deferred".

    THE DEFECT THIS FIXES. The gate was evaluated BEFORE the detector's own
    due-check. On a busy host the log then claimed a detector was "deferred"
    when it may not have been DUE AT ALL — a FALSE STATEMENT in the log a
    human reads when asking "why did this not run?".

    THE SUBJECT IS A NOT-DUE HEAVY DETECTOR. Its last-run stamp is fresh, so
    it is not due; the host is over the bar. Neither fact alone decides the
    outcome: the not-due fact is what must WIN, because a detector that was
    never going to run is not deferred, it simply was not due.

    THE ASSERTION IS ON THE LOG, which is what the human reads, and on the
    fact that the detector did not run.
    """
    dispatch = _import_dispatch(tmp_path, monkeypatch)
    import state

    state.init_state()
    heavy = "memory-librarian"
    assert heavy in dispatch._PRESSURE_HEAVY_DETECTORS

    # The detector is NOT due: a fresh last-run stamp.
    state.atomic_write(state.state_dir() / f"last-run-{heavy}.ts", str(int(time.time())))
    assert dispatch._detector_is_due(heavy, 3600) is False, (
        "the test's subject is wrong: the detector must NOT be due"
    )

    monkeypatch.setenv("JANITOR_RUNNABLE_COUNT", "427")
    ran, lines = _fire_dispatch(
        dispatch,
        monkeypatch,
        [(heavy, 3600, "CLAUDE_PLUGIN_OPTION_MEMORY_LIBRARIAN_INTERVAL")],
    )

    assert not any("host-pressure" in ln for ln in lines), (
        f"a NOT-DUE detector produced a host-pressure log line: {lines}"
    )
    assert ran == [], f"a NOT-DUE detector ran: {ran}"


def test_a_DUE_heavy_detector_IS_deferred_and_the_line_names_the_COUNT(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A due heavy detector over the bar is deferred, and the line says how many.

    THE OTHER HALF of the ordering test: a gate that deferred NOTHING would
    satisfy the previous test. Here the subject IS due and the host IS over
    the bar, so the gate MUST refuse it — and the detector must not run and
    must not stamp last-run (so it stays due for the next calm beat).
    """
    dispatch = _import_dispatch(tmp_path, monkeypatch)
    import state

    state.init_state()
    heavy = "memory-librarian"
    assert heavy in dispatch._PRESSURE_HEAVY_DETECTORS
    # No last-run stamp → the detector is DUE.
    assert dispatch._detector_is_due(heavy, 3600) is True

    monkeypatch.setenv("JANITOR_RUNNABLE_COUNT", "427")
    ran, lines = _fire_dispatch(
        dispatch,
        monkeypatch,
        [(heavy, 3600, "CLAUDE_PLUGIN_OPTION_MEMORY_LIBRARIAN_INTERVAL")],
    )

    assert ran == [], f"the deferred detector ran: {ran}"
    # The detector STAYS DUE — the gate never stamps last-run.
    assert dispatch._detector_is_due(heavy, 3600) is True, (
        "the deferred detector stamped last-run — it would be skipped for its "
        "whole interval"
    )
    # The line names HOW MANY detectors were deferred and the READING.
    pressure_lines = [ln for ln in lines if "host-pressure" in ln]
    assert len(pressure_lines) == 1, (
        f"the deferral was not announced exactly once: {pressure_lines}"
    )
    assert "1" in pressure_lines[0], (
        f"the deferral line must carry the COUNT of deferred detectors: "
        f"{pressure_lines[0]}"
    )
    assert "427" in pressure_lines[0], (
        f"the deferral line must carry the READING: {pressure_lines[0]}"
    )


def test_the_detector_deferral_is_logged_ONCE_PER_EPISODE(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The detector path logs ONE line per episode, not one per fire per detector.

    THE DEFECT THIS FIXES. The gate logged "host-pressure: deferring detector
    '<name>' under host pressure" on EVERY fire for EVERY heavy detector. The
    daemon path has a whole documented discipline against exactly this — "a
    per-beat line would drown the log in the exact situation the log is for" —
    and the heartbeat runs from a FRESH PROCESS each fire, so the daemon's
    process-local latch does not help here. The mechanism is a FILE-BASED
    episode stamp in the project's state dir (the daemon's own
    `runaway-alert-printed.txt` is the precedent).

    THE SUBJECT IS THE WHOLE FIRE, run four times: the first fire announces
    the episode, the second fire (same episode) says NOTHING, and after the
    host goes calm the NEXT episode is announced again.
    """
    dispatch = _import_dispatch(tmp_path, monkeypatch)
    import state

    state.init_state()
    heavy = "memory-librarian"
    roster = [(heavy, 3600, "CLAUDE_PLUGIN_OPTION_MEMORY_LIBRARIAN_INTERVAL")]
    # ONE accumulator for the WHOLE episode: a fresh list per fire would
    # hide exactly the repetition this test exists to catch.
    lines: list[str] = []

    # BEAT 1: the host is over the bar → the episode opens and is announced.
    monkeypatch.setenv("JANITOR_RUNNABLE_COUNT", "427")
    _fire_dispatch(dispatch, monkeypatch, roster, lines=lines)
    pressure_lines = [ln for ln in lines if "host-pressure" in ln]
    assert len(pressure_lines) == 1, (
        f"the first deferral was not announced: {pressure_lines}"
    )

    # BEAT 2: the SAME episode → the line must NOT repeat. The heartbeat is a
    # FRESH PROCESS each fire, so the stamp must be a FILE, not process state.
    _fire_dispatch(dispatch, monkeypatch, roster, lines=lines)
    pressure_lines = [ln for ln in lines if "host-pressure" in ln]
    assert len(pressure_lines) == 1, (
        f"the deferral repeated on the next fire of the same episode: "
        f"{pressure_lines}"
    )

    # BEAT 3: the host is calm → the episode closes.
    monkeypatch.setenv("JANITOR_RUNNABLE_COUNT", "130")
    _fire_dispatch(dispatch, monkeypatch, roster, lines=lines)

    # BEAT 4: the host is busy again → a NEW episode → announced again.
    monkeypatch.setenv("JANITOR_RUNNABLE_COUNT", "427")
    _fire_dispatch(dispatch, monkeypatch, roster, lines=lines)
    pressure_lines = [ln for ln in lines if "host-pressure" in ln]
    assert len(pressure_lines) == 2, (
        f"a SECOND episode was not announced: {pressure_lines}"
    )


def test_the_probe_is_NOT_taken_for_a_heavy_detector_the_harness_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `ps` spawn is not paid for a reading the fire never uses.

    THE DEFECT THIS FIXES. The probe was taken when the roster held ANY heavy
    detector — but the loop then skips the detectors that do not run in the
    harness (`_detector_runs_in_harness`). If the only heavy detector in the
    roster is one the harness skips, the fire still paid a `ps` spawn for a
    reading it never consulted.

    THE SUBJECT: a roster in which the ONLY heavy detector is one the harness
    skips. The reading must not be taken.
    """
    dispatch = _import_dispatch(tmp_path, monkeypatch)
    import host_pressure as hp

    probes = {"n": 0}
    real = hp.read_pressure

    def _counting() -> hp.HostPressure:
        probes["n"] += 1
        return real()

    monkeypatch.setattr(hp, "read_pressure", _counting)

    # A roster with ONE heavy detector, and that detector is SKIPPED in the
    # harness. `_detector_runs_in_harness` is the harness's own predicate, so
    # the test drives it directly: what matters for the probe is that the
    # heavy detector would NOT run in this fire.
    skipped_heavy = "worktree-janitor"
    assert skipped_heavy in dispatch._PRESSURE_HEAVY_DETECTORS

    real_runs_in_harness = dispatch._detector_runs_in_harness

    def _skipped(name: str) -> bool:
        return False if name == skipped_heavy else real_runs_in_harness(name)

    monkeypatch.setattr(dispatch, "_detector_runs_in_harness", _skipped)
    assert not dispatch._detector_runs_in_harness(skipped_heavy), (
        "the test's subject is wrong: the heavy detector must be one the "
        "harness skips for this test to mean anything"
    )

    monkeypatch.setenv("JANITOR_RUNNABLE_COUNT", "130")
    _fire_dispatch(
        dispatch,
        monkeypatch,
        [(skipped_heavy, 900, "CLAUDE_PLUGIN_OPTION_WORKTREE_JANITOR_INTERVAL")],
        in_harness=True,
    )
    assert probes["n"] == 0, (
        f"the probe ran {probes['n']} time(s) for a fire whose only heavy "
        "detector the harness skips"
    )

def test_the_pressure_gate_on_the_detector_path_is_FAIL_OPEN(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable reading never blocks a detector.

    The reading is None — which every other clause treats as "not over the
    bar" — so the only way this test can fail is if the fail-open rule itself
    is wrong.
    """
    import host_pressure as hp

    dispatch = _import_dispatch(tmp_path, monkeypatch)
    heavy = "memory-librarian"
    assert heavy in dispatch._PRESSURE_HEAVY_DETECTORS

    assert dispatch._pressure_gate_blocks_detector(
        heavy, hp.HostPressure(None, 300)
    ) is False, "an unreadable reading blocked a detector — the gate is fail-CLOSED"
