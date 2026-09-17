"""Daemon singleton-chore coordination with the ai-maestro server (TRDD-PZLVT2RN Phase B2).

OWNER RULING 2026-08-05 — asked directly whether "the server's responsibility" means the
server is ALIVE or has CLAIMED the chore: **"it means both. the chores of daemon must all be
passed (claimed?) to the ai-maestro equivalent functionality when the ai-maestro server is
running."**

This SUPERSEDES the 2026-07-17 binary-on-liveness rule (TRDD-LU0C5KAR), which was right about
the direction and wrong about the granularity. Paired with the one-daemon-per-host exit, "a
live server owns the absorbed chores" meant a server claiming 5 of 11 silenced all 11: the
daemon was refused entirely and the other six ran NOWHERE. Measured on the owner's host —
eleven completion stamps 10-14 days stale, no alarm, including the fleet guardian
(ai-maestro#111, janitor#134).

What these tests now pin:
  1. A chore yields IFF the server is running AND has CLAIMED it. Claims come from the
     probe's capability list: `family-a` → the five family-A chores; a token equal to a
     CHORE NAME → that chore (so ai-maestro can migrate one at a time).
  2. FAIL TOWARD COVERAGE, always — `capabilities: []`, an unknown token, or a stale file
     claim NOTHING, so the janitor keeps every chore. A chore run twice is wasteful and
     lock-guarded; a chore run by nobody is invisible.
  3. The one exception is an EXPLICIT operator override, which has no capability list to
     read and is honoured as a claim on the legacy absorbed set.
  4. The absorbed set names REAL tasks (typo guard) and never includes a population-split
     or janitor-only Family-B task.

Property 5 — "the per-session staleness watchdog goes silent only for chores the server
has actually claimed" — was pinned here via `daemon_watchdog.emit_if_daemon_stale`. That
function's only caller was the marketplace refresh detector; once that detector retired
2026-09-17 the function had zero callers left and was deleted with it, so the property has
no surviving subject to test (the equivalent claim-suppression logic for the *daemon-side*
blackout detector is still pinned in tests/test_global_chore_blackout.py).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import daemon  # type: ignore[import-not-found]  # noqa: E402
import harness_backend as hb  # type: ignore[import-not-found]  # noqa: E402
import state as janitor_state  # type: ignore[import-not-found]  # noqa: E402

_OVERRIDE_VARS = (hb.SERVER_CHORES_ENV, hb.SERVER_STATE_ENV)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Isolated global state + no leftover overrides; NO test may read the REAL
    server-liveness probe file (this machine may run the ai-maestro server, so an
    un-overridden read of ~/.aimaestro/server-liveness.json would be nondeterministic)
    — point it at a guaranteed-absent path."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    for var in _OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(tmp_path / "absent-liveness.json"))
    # Flush state's process-lifetime path caches (project_root & friends): an
    # in-process test that ran EARLIER in the same pytest process may have pinned
    # the REAL repo root, which would send the watchdog's emit_once seen-file to
    # the repo's own .janitor/state — where a previous run's hour-key silences the
    # alarm and flips the control test (root-caused 2026-07-17).
    for fn in (janitor_state.project_root, janitor_state.janitor_root,
               janitor_state.state_dir, janitor_state.log_dir):
        fn.cache_clear()
    yield
    for fn in (janitor_state.project_root, janitor_state.janitor_root,
               janitor_state.state_dir, janitor_state.log_dir):
        fn.cache_clear()


# ---------- 1. the yield policy ----------


def _claim(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tokens: list[str],
           *, age_s: float = 0.0) -> float:
    """Publish a server-liveness probe advertising `tokens`, `age_s` seconds old.
    Returns the `ts` it wrote, so a boundary test can pin the probe's clock to it."""
    import json as _json

    ts = time.time() - age_s
    f = tmp_path / "liveness.json"
    f.write_text(
        _json.dumps({"ts": ts, "pid": 1, "capabilities": tokens}),
        encoding="utf-8",
    )
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    return ts


def test_a_chore_yields_only_when_the_server_has_CLAIMED_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The owner's ruling in one assertion: running is necessary, claimed is also required."""
    name = "version-update"
    _claim(monkeypatch, tmp_path, ["family-a"])
    claimed = hb.claimed_chores()
    assert daemon._task_yielded_to_server(name, True, claimed) is True
    assert daemon._task_yielded_to_server(name, False, claimed) is False, "a dead server owns nothing"


def test_an_absorbed_chore_the_server_has_NOT_claimed_does_not_yield(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """THE ai-maestro#111 regression. Membership in SERVER_ABSORBED_TASKS is a statement
    about what the server absorbs IN PRINCIPLE; it is not evidence the server is running the
    chore RIGHT NOW. Conflating the two is what left six chores with no runner for 10-14
    days, and this is the assertion that keeps them apart."""
    _claim(monkeypatch, tmp_path, [])  # alive, claiming nothing
    assert hb.server_is_alive() is True
    claimed = hb.claimed_chores()
    for name in hb.SERVER_ABSORBED_TASKS:
        assert daemon._task_yielded_to_server(name, True, claimed) is False, name


def test_non_absorbed_task_never_yields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A task outside the absorbed set runs even under a running server that claims the
    whole family-A set."""
    _claim(monkeypatch, tmp_path, ["family-a"])
    assert daemon._task_yielded_to_server("session-liveness", True, hb.claimed_chores()) is False


def test_a_per_chore_token_yields_exactly_that_chore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The granularity ai-maestro asked for on janitor#134, so the fleet can migrate one
    chore at a time without a janitor release for each."""
    _claim(monkeypatch, tmp_path, ["session-liveness"])
    claimed = hb.claimed_chores()
    assert daemon._task_yielded_to_server("session-liveness", True, claimed) is True
    assert daemon._task_yielded_to_server("memory-guard", True, claimed) is False


def test_an_unknown_token_claims_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fail toward coverage: a token from a future server must never be read as a claim."""
    _claim(monkeypatch, tmp_path, ["family-z", "something-new"])
    assert hb.claimed_chores() == frozenset()


def test_a_stale_probe_claims_nothing_even_listing_everything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A server that died holding a full claim must not keep chores yielded from the grave."""
    _claim(monkeypatch, tmp_path, sorted(hb.GLOBAL_CHORES),
           age_s=hb.LIVENESS_STALE_AFTER_S + 5)
    assert hb.claimed_chores() == frozenset()


def test_an_EXPLICIT_operator_override_claims_the_legacy_absorbed_set(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one branch that claims without a capability list to read.

    The override knob has no way to express per-chore claims, so degrading it to a no-op
    would break an operator tool rather than fix anything. It is honoured as a claim on the
    legacy absorbed set — and it CAN recreate the #111 blackout for the other six chores,
    which is acceptable only because it takes a deliberate human action, unlike the default
    that caused it."""
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "up")
    assert hb.claimed_chores() == hb.SERVER_ABSORBED_TASKS

    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "down")
    assert hb.claimed_chores() == frozenset(), "forcing the server down claims nothing"


def test_absorbed_set_matches_the_contract() -> None:
    """Pin the exact absorbed-chore set: the OAuth pair + `version-update` + the
    github-config audit (joined 2026-08-18, janitor#274 ratified on the rev-8/#126
    thread — the server has stamped it since 2026-08-05) — a drift here silently
    changes which chores the handoff covers. `user-plugins-update` LEFT the set
    2026-08-19 (TRDD-TIZHEPNC / ai-maestro PE54D95Q AC6): the harness self-updates
    plugins, so the absorbed loop duplicated it; it is daemon-owned again.
    The marketplace refresh chore RETIRED 2026-09-17 — the chore itself was deleted,
    not just yielded, so it no longer has a place in this set at all."""
    assert hb.SERVER_ABSORBED_TASKS == frozenset({
        "version-update",
        "oauth-rotator-supervisor",
        "oauth-rotator-tick",
        "github-config-audit",
    })


def test_absorbed_set_names_real_tasks() -> None:
    """Typo guard: every absorbed name must be a task `_build_tasks` actually builds —
    a misspelled entry would silently gate nothing."""
    built = {t.name for t in daemon._build_tasks()}
    missing = hb.SERVER_ABSORBED_TASKS - built
    assert not missing, f"absorbed names not built by the daemon: {sorted(missing)}"


def test_population_split_and_family_b_tasks_stay_janitor() -> None:
    """The split the owner directed: liveness/fleet-stop run on BOTH sides (each for its
    own population), and the janitor-only Family-B chores never yield."""
    keep = {
        "session-liveness",
        "fleet-stop",
        "memory-guard",
        "cache-prune",
        "rules-cleanup",
        # github-config-audit left this set 2026-08-18: the server executes and
        # stamps it (janitor#274, ratified rev 8), so it is absorbed, not Family-B.
    }
    overlap = keep & hb.SERVER_ABSORBED_TASKS
    assert not overlap, f"population-split/Family-B tasks must never yield: {sorted(overlap)}"


def test_yielded_names_cover_exactly_the_CLAIMED_chores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Claimed ⇒ exactly those yield; server gone ⇒ nothing does. The same set drives the
    due-loop AND the next-due sleep exclusion, so getting it wrong busy-spins the daemon at
    1 s ticks."""
    _claim(monkeypatch, tmp_path, ["family-a"])
    tasks = daemon._build_tasks()
    claimed = hb.claimed_chores()
    assert daemon._yielded_task_names(tasks, True, claimed) == hb.SERVER_ABSORBED_TASKS
    assert daemon._yielded_task_names(tasks, False, claimed) == set()


def test_a_partial_claim_yields_only_its_own_chores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Mid-migration shape: the server has taken two chores by name and nothing else, so
    the daemon must keep the other nine — including the rest of the family-A set."""
    _claim(monkeypatch, tmp_path, ["session-liveness", "cache-prune"])
    tasks = daemon._build_tasks()
    assert daemon._yielded_task_names(tasks, True, hb.claimed_chores()) == {
        "session-liveness", "cache-prune",
    }


# ---------- 2. the liveness signal ----------


def test_chores_override_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """`$JANITOR_AIMAESTRO_SERVER_CHORES` is the chores-only operator knob; an
    unrecognized value falls through to the liveness probe (absent file here ⇒ False)."""
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "up")
    assert hb.server_runs_chores() is True
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "down")
    assert hb.server_runs_chores() is False
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "unknown")
    assert hb.server_runs_chores() is False


def test_chores_signal_honors_state_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset chores knob ⇒ the STATE override governs — forcing the server "down" for
    adoption also resumes the chores, immediately."""
    monkeypatch.setenv(hb.SERVER_STATE_ENV, "down")
    assert hb.server_runs_chores() is False
    monkeypatch.setenv(hb.SERVER_STATE_ENV, "up")
    assert hb.server_runs_chores() is True


def test_probe_file_drives_the_claim_yield_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """END-TO-END through the REAL probe (no monkeypatched internals), across the three
    states that matter — and note the FIRST one is the case that used to be wrong: a fresh
    file advertising NO capabilities means the server is running but owns nothing, so the
    janitor keeps every chore rather than yielding them into a hole."""
    import json as _json
    import time as _time

    f = tmp_path / "liveness.json"
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))
    tasks = daemon._build_tasks()

    # 1. alive, claiming nothing ⇒ the janitor keeps everything (the #111 fix).
    f.write_text(_json.dumps({"ts": _time.time(), "pid": 1, "capabilities": []}),
                 encoding="utf-8")
    assert hb.server_is_alive() is True
    assert hb.server_runs_chores() is True
    assert daemon._yielded_task_names(tasks, hb.server_runs_chores(), hb.claimed_chores()) == set()

    # 2. alive, claiming family-a ⇒ exactly those five yield.
    f.write_text(_json.dumps({"ts": _time.time(), "pid": 1, "capabilities": ["family-a"]}),
                 encoding="utf-8")
    assert daemon._yielded_task_names(
        tasks, hb.server_runs_chores(), hb.claimed_chores()
    ) == hb.SERVER_ABSORBED_TASKS

    # 3. stale ⇒ it exited; everything resumes here.
    stale = _time.time() - (hb.LIVENESS_STALE_AFTER_S + 5)
    f.write_text(_json.dumps({"ts": stale, "pid": 1, "capabilities": ["family-a"]}),
                 encoding="utf-8")
    assert hb.server_is_alive() is False
    assert hb.server_runs_chores() is False
    assert daemon._yielded_task_names(tasks, hb.server_runs_chores(), hb.claimed_chores()) == set()


# Section 3 (the per-session watchdog going silent while the server owns a chore) was
# retired here with `_run_watchdog`/`_seed_stale_task_and_dead_daemon` — see the module
# docstring's note on property 5.


# ---------- 4. the transition log carries ts/age/reason (TRDD-HXZ8B0IS) ----------


def test_transition_message_carries_reason_and_age_when_yielding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A yield transition names the yielded chores AND why the probe read alive —
    ts, age, and reason must all be present in the one log line."""
    _claim(monkeypatch, tmp_path, ["family-a"], age_s=1.0)
    probe = hb.server_liveness_probe()
    msg = daemon._chore_coordination_message(hb.SERVER_ABSORBED_TASKS, probe)
    assert "yielding to active ai-maestro server" in msg
    assert "reason=alive" in msg
    assert f"ts={probe.ts:.1f}" in msg
    assert f"age={probe.age:.1f}s" in msg


def test_transition_message_carries_reason_and_age_when_resuming(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A resume transition (empty yielded set) still carries ts/age/reason — here the
    probe read STALE, which is the exact case TRDD-HXZ8B0IS exists to make legible."""
    _claim(monkeypatch, tmp_path, ["family-a"], age_s=hb.LIVENESS_STALE_AFTER_S + 5)
    probe = hb.server_liveness_probe()
    msg = daemon._chore_coordination_message(set(), probe)
    assert "resuming singleton chores" in msg
    assert "reason=stale(age=" in msg
    assert f"ts={probe.ts:.1f}" in msg
    assert f"age={probe.age:.1f}s" in msg


@pytest.mark.parametrize("age_s,expected_reason", [(89.0, "alive"), (91.0, "stale")])
def test_transition_message_at_the_89_91_second_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, age_s: float, expected_reason: str
) -> None:
    """The exact boundary from the incident report: 89 s reads alive, 91 s reads stale —
    both must surface their reason and age in the transition line."""
    ts = _claim(monkeypatch, tmp_path, ["family-a"], age_s=age_s)
    # Pin `now` to the written stamp: against wall-clock, one second of scheduler stall
    # under load (this host has run at loadavg 30+) turns the 89 s case into 90+ s and the
    # test flakes on the very boundary it exists to pin (four-commit review, 2026-09-06).
    probe = hb.server_liveness_probe(now=ts + age_s)
    assert probe.reason == expected_reason
    msg = daemon._chore_coordination_message(
        hb.SERVER_ABSORBED_TASKS if expected_reason == "alive" else set(), probe
    )
    assert f"age={probe.age:.1f}s" in msg
    assert expected_reason in msg


def test_transition_message_reports_absent_with_no_ts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No liveness file at all ⇒ no ts/age to print, but the reason still appears."""
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(tmp_path / "absent-liveness.json"))
    probe = hb.server_liveness_probe()
    msg = daemon._chore_coordination_message(set(), probe)
    assert "reason=absent" in msg
    assert "ts=" not in msg


