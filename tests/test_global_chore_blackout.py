"""The global-chore blackout: chores that a live server displaces but never absorbs.

Regression suite for ai-maestro#111. A live ai-maestro server does not make the janitor
daemon YIELD its five absorbed chores — `ensure_daemon_running` refuses to spawn the daemon
AT ALL, and the daemon owns eleven. The other six then run NOWHERE, and the only staleness
watchdog suppressed its own alarm on the very signal that caused the outage. Measured cost:
eleven chores dark for 10-14 days on the owner's host, in total silence.

Three properties are pinned here, because each one alone was insufficient:

  1. `GLOBAL_CHORES` matches daemon.py's Task registry name-for-name and default-for-default
     (parsed from source — no daemon import). The roster is a hand-maintained copy of the
     registry, so without this test it silently rots the first time a chore is added and the
     blackout detector goes blind to exactly the newest chore.
  2. `emit_if_daemon_stale` suppresses ONLY absorbed chores while a server runs. The missing
     membership test is the whole bug.
  3. The detector reports unabsorbed staleness, ignores absorbed chores, and stays silent on
     a host where the daemon has never run (a fresh install must never be alarmed about a
     feature it has not had yet).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import daemon_watchdog  # noqa: E402
import global_state as gs  # noqa: E402
import harness_backend as hb  # noqa: E402
import state  # noqa: E402

_DAEMON_SRC = _ROOT / "scripts" / "daemon.py"
_DETECTOR = _ROOT / "scripts" / "detectors" / "global-chore-blackout.py"


def _load_detector():
    """Import the hyphenated detector module by path."""
    spec = importlib.util.spec_from_file_location("global_chore_blackout", _DETECTOR)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _registry_from_daemon_source() -> dict[str, tuple[str, int]]:
    """`{chore: (env_var, default_cadence_s)}` parsed out of daemon.py's own source.

    Parsed rather than imported: importing daemon.py pulls its whole dependency tree into a
    unit test, and the thing under test is the TEXT of the registry, not its runtime.
    """
    src = _DAEMON_SRC.read_text(encoding="utf-8")
    consts = {
        name: (env, int(default))
        for name, env, default in re.findall(
            r"(_INTERVAL_[A-Z_]+)\s*=\s*_env_interval\(\s*\"([A-Z_]+)\",\s*(\d+)", src
        )
    }
    registry: dict[str, tuple[str, int]] = {}
    for chore, const in re.findall(r"Task\(\"([a-z0-9-]+)\",\s*(_INTERVAL_[A-Z_]+)", src):
        assert const in consts, f"{chore} references unknown interval constant {const}"
        registry[chore] = consts[const]
    return registry


def test_global_chores_roster_matches_the_daemon_task_registry() -> None:
    """Every daemon Task appears in GLOBAL_CHORES with the same env var and default."""
    assert hb.GLOBAL_CHORES == _registry_from_daemon_source()


def test_absorbed_and_unabsorbed_partition_the_roster_without_overlap() -> None:
    """The two sets are disjoint and together cover every chore — no chore is unclassified."""
    absorbed = set(hb.SERVER_ABSORBED_TASKS)
    unabsorbed = set(hb.unabsorbed_chores())
    assert absorbed & unabsorbed == set()
    assert absorbed | unabsorbed == set(hb.GLOBAL_CHORES)
    assert absorbed <= set(hb.GLOBAL_CHORES), "an absorbed chore that is not a real chore"


def test_unabsorbed_chores_names_the_eight_the_server_never_claimed() -> None:
    """The exact gap ai-maestro#111 is about, pinned by name so a silent re-classification fails.

    `fleet-plugins-update` joined the roster on 2026-08-11 (TRDD-G4BCRUP7 R3) and is the
    SEVENTH member. It is listed here deliberately, not to make the assertion pass: the
    tripwire fired correctly and the fact it exposed is that on a host running a live
    ai-maestro server — which suppresses the daemon — fleet-wide plugin updates do not run
    at ALL, because the server does not claim that chore and the daemon has yielded.

    `cold-cache-clear` joined on 2026-08-13 as the EIGHTH, and it is added here by the same
    discipline: the tripwire fired, and the honest answer is that ai-maestro's server does not
    claim it either. That matters more than the others, because this chore is the ONLY actor
    that can shrink a cold-cache session before its next cron fire pays full price — so on a
    server host, the exact expense the chore exists to prevent goes unprevented. The
    SessionStart half still fires there (it is a hook, not a daemon task), so the blackout costs
    the running-session window, not the whole feature.

    So R3 ("keep every project's plugins updated") is satisfied on a standalone host and
    BLACKED OUT on a server host until ai-maestro claims it. That is a cross-repo ask, not
    something this repo can close alone, and it is the same shape as ai-maestro#111 and
    TRDD-6CRC9SQQ's open contract item. The `global-chore-blackout` detector is what makes
    the blackout visible meanwhile — which is exactly why this set is pinned by name.
    """
    assert set(hb.unabsorbed_chores()) == {
        "memory-guard", "cache-prune", "rules-cleanup",
        # github-config-audit moved to SERVER_ABSORBED_TASKS 2026-08-18
        # (janitor#274, ratified rev 8) — the server executes and stamps it.
        "session-liveness", "fleet-stop",
        "fleet-plugins-update", "cold-cache-clear",
        # user-plugins-update LEFT the absorbed set 2026-08-19 (TRDD-TIZHEPNC /
        # ai-maestro PE54D95Q AC6: the harness self-updates installed plugins, so
        # the server's absorbed loop duplicated it and stopped claiming it) —
        # daemon-owned again, hence back in the unabsorbed pin.
        "user-plugins-update",
    }


def _publish(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tokens: list[str],
             *, age_s: float = 0.0) -> None:
    """Publish a server-liveness probe advertising `tokens`, `age_s` seconds old."""
    f = tmp_path / "liveness.json"
    f.write_text(
        json.dumps({"ts": time.time() - age_s, "pid": 1, "capabilities": tokens}),
        encoding="utf-8",
    )
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, str(f))


def test_a_claimed_chore_with_NO_live_server_is_orphaned_even_when_the_daemon_is_alive(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hole a live daemon HIDES, and the reason the detector's old early-return was wrong.

    The operator override asserts "the server runs chores" with no probe to corroborate it,
    so the daemon dutifully yields all five absorbed chores — to a server that is not there.
    The daemon being alive is irrelevant: it is alive and NOT running them."""
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, "/nonexistent-liveness.json")
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "up")

    assert hb.server_is_alive() is False
    assert hb.claimed_chores() == hb.SERVER_ABSORBED_TASKS
    assert hb.orphaned_chores(daemon_alive=True) == hb.SERVER_ABSORBED_TASKS


def test_an_unclaimed_chore_with_no_daemon_is_orphaned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The ai-maestro#111 shape: the server claims five, the daemon is gone, six fall through."""
    _publish(monkeypatch, tmp_path, ["family-a"])
    orphans = hb.orphaned_chores(daemon_alive=False)
    assert orphans == frozenset(hb.unabsorbed_chores())
    assert "session-liveness" in orphans


def test_nothing_is_orphaned_when_a_live_server_claims_everything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The target state the owner named — every chore passed to an ai-maestro equivalent.
    The daemon may be absent; that is the POINT of a complete handover."""
    _publish(monkeypatch, tmp_path, sorted(hb.GLOBAL_CHORES))
    assert hb.orphaned_chores(daemon_alive=False) == frozenset()


def test_nothing_is_orphaned_when_the_daemon_runs_and_nothing_is_claimed(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordinary standalone host: no server, a live daemon, every chore covered."""
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, "/nonexistent-liveness.json")
    assert hb.orphaned_chores(daemon_alive=True) == frozenset()


def test_a_stale_probe_orphans_the_chores_it_used_to_claim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A server that died is not a server. Its claim expires with its probe, so the chores
    revert to the daemon — and are orphaned only if the daemon is gone too."""
    _publish(monkeypatch, tmp_path, ["family-a"], age_s=hb.LIVENESS_STALE_AFTER_S + 5)
    assert hb.claimed_chores() == frozenset()
    assert hb.orphaned_chores(daemon_alive=True) == frozenset()
    assert hb.orphaned_chores(daemon_alive=False) == frozenset(hb.GLOBAL_CHORES)


@pytest.fixture
def _server_up_daemon_dead(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """The blackout condition: a server claims the chores and the daemon is not running.

    CLAUDE_PROJECT_DIR is redirected to a tmp tree because `emit_if_daemon_stale` dedupes
    through a seen-file under `state.state_dir()`, which follows CLAUDE_PROJECT_DIR rather
    than the session-isolated HOME. Without this the test writes its dedupe stamp into the
    REAL project's `.janitor/state/` and then passes exactly ONCE PER HOUR — every later run
    reads back its own stamp and sees the silence it is supposed to catch. It cost a green
    run followed by an inexplicable red one on the very next invocation.
    """
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    state.init_state()
    monkeypatch.setattr(hb, "server_runs_chores", lambda: True)
    monkeypatch.setattr(gs, "daemon_is_alive", lambda *a, **k: False)
    monkeypatch.setattr(gs, "daemon_pid", lambda: None)
    monkeypatch.setattr(gs, "read_heartbeat", lambda: 0)


def test_watchdog_still_alarms_for_an_UNABSORBED_chore_while_a_server_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], _server_up_daemon_dead
) -> None:
    """THE bug. The old gate returned for every chore whenever a server was alive."""
    assert "session-liveness" not in hb.SERVER_ABSORBED_TASKS
    monkeypatch.setattr(gs, "read_last_run", lambda _t: int(time.time()) - 10 * 86400)

    daemon_watchdog.emit_if_daemon_stale(
        task_name="session-liveness",
        last_run_filename="session-liveness.last-run.ts",
        cadence_env="CLAUDE_PLUGIN_OPTION_DAEMON_SESSION_LIVENESS_INTERVAL",
        default_cadence_s=120,
        subject="the fleet guardian last ran",
    )
    out = capsys.readouterr().out
    assert "session-liveness" in out, "an unowned chore must alarm even while a server runs"


def test_watchdog_stays_silent_for_an_ABSORBED_chore_while_a_server_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], _server_up_daemon_dead
) -> None:
    """The suppression that IS correct: a CLAIMED chore goes stale by design.

    Updated 2026-08-05 for the owner ruling on janitor#134 ("alive or claimed?" → "both").
    Membership in SERVER_ABSORBED_TASKS is no longer sufficient — the server must have
    published a claim — so the test now states the claim explicitly. That is the whole
    point of the change: "the server absorbs this in principle" and "the server is running
    this right now" were the same condition, and six chores fell through the gap."""
    assert "marketplace-refresh" in hb.SERVER_ABSORBED_TASKS
    monkeypatch.setattr(hb, "claimed_chores", lambda **_kw: frozenset({"marketplace-refresh"}))
    monkeypatch.setattr(gs, "read_last_run", lambda _t: int(time.time()) - 10 * 86400)

    daemon_watchdog.emit_if_daemon_stale(
        task_name="marketplace-refresh",
        last_run_filename="marketplace-refresh.last-run.ts",
        cadence_env="CLAUDE_PLUGIN_OPTION_DAEMON_MARKETPLACE_REFRESH_INTERVAL",
        default_cadence_s=3600,
        subject="global marketplaces last refreshed",
    )
    assert capsys.readouterr().out == ""


def test_detector_reports_the_stale_chores_NOBODY_will_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A CLAIMED chore is the server's, however stale its stamp; an UNCLAIMED one with no
    daemon is nobody's and is reported, worst first.

    Rewritten 2026-08-05: this used to assert "absorbed chores are never reported", which is
    not the same statement and is false. Absorbed describes what the server takes IN
    PRINCIPLE; a chore is only safe when something is actually running it. The two were
    conflated once already and six chores fell through the gap."""
    mod = _load_detector()
    now = int(time.time())
    _publish(monkeypatch, tmp_path, ["family-a"])       # a live server owns the absorbed 5
    monkeypatch.setattr(mod.gs, "daemon_is_alive", lambda *a, **k: False)

    stamps = {c: now for c in hb.GLOBAL_CHORES}
    stamps["marketplace-refresh"] = now - 10 * 86400   # claimed + stale ⇒ the server's problem
    stamps["session-liveness"] = now - 10 * 86400      # unclaimed + no daemon ⇒ reported
    stamps["fleet-stop"] = now - 5 * 86400             # unclaimed + no daemon ⇒ reported
    monkeypatch.setattr(mod.gs, "read_last_run", lambda t: stamps.get(t, 0))

    found = mod._blackout(now)
    assert [chore for chore, _age in found] == ["session-liveness", "fleet-stop"], \
        "must report only what nothing will run, worst first"


def test_detector_reports_a_CLAIMED_chore_when_the_server_claiming_it_is_gone(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mirror case the old assertion would have forbidden outright: an absorbed chore
    yielded on an operator override, with no live server to receive it."""
    mod = _load_detector()
    now = int(time.time())
    monkeypatch.setenv(hb.LIVENESS_FILE_ENV, "/nonexistent-liveness.json")
    monkeypatch.setenv(hb.SERVER_CHORES_ENV, "up")
    monkeypatch.setattr(mod.gs, "daemon_is_alive", lambda *a, **k: True)

    stamps = {c: now for c in hb.GLOBAL_CHORES}
    stamps["marketplace-refresh"] = now - 10 * 86400
    monkeypatch.setattr(mod.gs, "read_last_run", lambda t: stamps.get(t, 0))

    assert [chore for chore, _age in mod._blackout(now)] == ["marketplace-refresh"]


def test_detector_is_silent_when_every_chore_is_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    now = int(time.time())
    mod = _load_detector()
    monkeypatch.setattr(mod.gs, "read_last_run", lambda _t: now)
    assert mod._blackout(now) == []


def test_detector_is_silent_on_a_host_where_the_daemon_has_never_run(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh install has no stamps at all — alarming there reports the absence of history,
    not an outage, and would fire on every new machine."""
    mod = _load_detector()
    monkeypatch.setattr(mod.gs, "read_last_run", lambda _t: 0)
    assert mod._blackout(int(time.time())) == []


def test_detector_treats_a_never_stamped_chore_as_stale_once_the_daemon_HAS_run(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strongest form of the finding: the daemon demonstrably ran here, yet this chore has
    never completed once. Skipping it would hide precisely the chore that never worked."""
    mod = _load_detector()
    now = int(time.time())
    stamps = {c: now for c in hb.GLOBAL_CHORES}
    stamps["memory-guard"] = 0
    stamps["cache-prune"] = now - 30 * 86400  # the oldest evidence the daemon ran here
    monkeypatch.setattr(mod.gs, "read_last_run", lambda t: stamps.get(t, 0))

    found = dict(mod._blackout(now))
    assert "memory-guard" in found
    assert found["memory-guard"] == pytest.approx(30 * 86400, abs=5), \
        "age is measured from the oldest evidence, never invented from the epoch"
