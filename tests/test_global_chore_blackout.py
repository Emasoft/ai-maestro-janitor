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


def test_unabsorbed_chores_names_the_six_the_server_never_claimed() -> None:
    """The exact gap ai-maestro#111 is about, pinned by name so a silent re-classification fails."""
    assert set(hb.unabsorbed_chores()) == {
        "memory-guard", "cache-prune", "rules-cleanup",
        "github-config-audit", "session-liveness", "fleet-stop",
    }


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


def test_detector_reports_only_the_unabsorbed_chores_that_are_stale(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stale unabsorbed chores are reported; absorbed and fresh ones are not."""
    mod = _load_detector()
    now = int(time.time())
    stamps = {c: now for c in hb.GLOBAL_CHORES}
    stamps["marketplace-refresh"] = now - 10 * 86400   # absorbed + stale ⇒ not our finding
    stamps["session-liveness"] = now - 10 * 86400      # unabsorbed + stale ⇒ reported
    stamps["fleet-stop"] = now - 5 * 86400             # unabsorbed + stale ⇒ reported
    monkeypatch.setattr(mod.gs, "read_last_run", lambda t: stamps.get(t, 0))

    found = mod._blackout(now)
    assert [chore for chore, _age in found] == ["session-liveness", "fleet-stop"], \
        "must report unabsorbed staleness only, worst first"


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
