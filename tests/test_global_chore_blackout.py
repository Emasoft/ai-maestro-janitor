"""The global-chore blackout: chores that a live server displaces but never absorbs.

Regression suite for ai-maestro#111. A live ai-maestro server does not make the janitor
daemon YIELD its five absorbed chores — `ensure_daemon_running` refuses to spawn the daemon
AT ALL, and the daemon owns eleven. The other six then run NOWHERE, and the only staleness
watchdog suppressed its own alarm on the very signal that caused the outage. Measured cost:
eleven chores dark for 10-14 days on the owner's host, in total silence.

Two properties are pinned here (a third, `emit_if_daemon_stale` suppressing ONLY absorbed
chores while a server runs, was pinned until that function's sole caller — the
marketplace refresh detector — was retired; the function itself has zero callers left and
was deleted with it, so the property no longer has a subject to test):

  1. `GLOBAL_CHORES` matches daemon.py's Task registry name-for-name and default-for-default
     (parsed from source — no daemon import). The roster is a hand-maintained copy of the
     registry, so without this test it silently rots the first time a chore is added and the
     blackout detector goes blind to exactly the newest chore.
  2. The detector reports unabsorbed staleness, ignores absorbed chores, and stays silent on
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

import harness_backend as hb  # noqa: E402

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


def test_unabsorbed_chores_are_pinned_by_name() -> None:
    """The exact gap ai-maestro#111 is about, pinned by name so a silent re-classification fails.

    WHAT THIS SET MEASURES, so every entry below is read correctly: the assertion is
    `set(harness_backend.unabsorbed_chores()) == {...}`, and `unabsorbed_chores()` is
    GLOBAL_CHORES minus `SERVER_ABSORBED_TASKS` — the janitor's own STATIC absorption
    boundary. It is NOT the server's live CLAIM set, which is dynamic (read from the
    liveness file's `capabilities` on every probe) and already contains names that appear
    in this very set.

    `fleet-plugins-update` joined the roster on 2026-08-11 (TRDD-G4BCRUP7 R3) and is the
    SEVENTH member. It is listed here deliberately, not to make the assertion pass: the
    tripwire fired correctly and the fact it exposed is that the janitor's absorbed table
    does not carry it, so the janitor yields the chore to the server instead of running
    it. At the time of writing (2026-10-20) the server DID advertise it as a capability
    and the daemon's own yield line named it — so the server owns it now, and whether the
    server actually executes it is a server-side question this repo cannot answer from
    here.

    `cold-cache-clear` joined on 2026-08-13 as the EIGHTH, and it is added here by the same
    discipline: the tripwire fired, and the honest answer is that ai-maestro's server does
    not advertise it either. That matters more than the others, because this chore is the
    ONLY actor that can shrink a cold-cache session before its next cron fire pays full
    price — so if the server ever takes it over, the exact expense the chore exists to
    prevent goes unprevented. The SessionStart half still fires there (it is a hook, not a
    daemon task), so the blackout costs the running-session window, not the whole feature.

    So R3 ("keep every project's plugins updated") is satisfied on a standalone host, and
    on a server host it is the server's to run, not the janitor's. That is a cross-repo
    ask, not something this repo can close alone, and it is the same shape as ai-maestro#111
    and TRDD-6CRC9SQQ's open contract item. Note what the `global-chore-blackout` detector
    does NOT do for these names: it reports ORPHANED chores — a claimed chore whose server
    is gone, or an unclaimed chore with no daemon. A chore the server has simply never
    claimed, while the daemon is alive, satisfies neither arm, so this pin is the ONLY
    thing naming it — which is exactly why this set is pinned by name.

    `runaway-guard` joined 2026-10-20 as the ELEVENTH (TRDD-5G66S0HK), and unlike most of
    the others here its absence from the janitor's ABSORBED TABLE costs the mechanism that
    RELIEVES HOST PRESSURE. The others cost an improvement this repo would have liked;
    this one costs the pressure relief, so it is not benign: if the server ever claims it,
    the janitor stops running it and the server must run it in exchange.

    WHAT THIS PIN DOES NOT SAY, because the rule it used to state was wrong (TRDD-5G66S0HK,
    "## CORRECTION to the blackout claim above", 2026-10-20 20:50): an unclaimed chore is
    NOT suppressed. The yield predicate is PER-CHORE (`daemon._task_yielded_to_server` =
    `server_runs_chores and task_name in claimed`), and `claimed_chores()` FAILS TOWARD
    COVERAGE — an unrecognised or absent claim keeps the chore with the janitor. At the time
    of writing (2026-10-20) the live server advertised six capabilities and this was not one
    of them, so the daemon KEEPS it with the server alive. The spawn gate agrees,
    for claim-set reasons: the standalone daemon is refused only when the server claims EVERY
    chore (`server_owns_every_chore`), which is false while this chore is unclaimed. (The
    gate has other, orthogonal refusals — harness-agent thin mode, the kill switch, the
    daemon-enabled knob — none of which are about the claim set.) So the honest statement is:
    the pin names the CROSS-REPO ASK (the server must CLAIM the chore AND implement the
    beat), and until it does, the janitor keeps the chore — the safe direction. Adding it to
    SERVER_ABSORBED_TASKS would be a false statement AND would put a chore the server does
    not implement inside the `family-a` capability set.
    """
    assert set(hb.unabsorbed_chores()) == {
        "memory-guard", "cache-prune", "rules-cleanup",
        # github-config-audit moved to SERVER_ABSORBED_TASKS 2026-08-18
        # (janitor#274, ratified rev 8) — the server executes and stamps it.
        "session-liveness", "fleet-stop",
        "fleet-plugins-update", "cold-cache-clear",
        # `gh-notify-inbox` joined 2026-08-20 as the NINTH (TRDD-079778RM), by the same
        # discipline: the tripwire fired and the honest answer is that the server does not
        # claim it — it is a brand-new lane the server has never heard of. Unlike the others
        # this blackout is BENIGN: every reader checks the inbox's age and falls back to the
        # pre-existing machine-wide gated poll when nobody is fetching, so a server host gets
        # exactly the behaviour it had before this chore existed. The blackout costs the
        # IMPROVEMENT, not the feature — which is why it is listed rather than absorbed.
        "gh-notify-inbox",
        # `integrity-repin` joined 2026-08-22 as the TENTH (TRDD-ZM5LZ24Y, USER decision #8)
        # — and unlike every other name here it is unabsorbed BY DESIGN, not by omission.
        # The C3 last-good certification used to live inside `task_version_update`, which IS
        # absorbed; the month the server owned `version-update`, the self-heal's only caller
        # went with it and the trust anchor sat frozen at 0.59.0 while 3.3.x ran, with the
        # daemon healthy and on cadence. So this one must NEVER be moved into
        # SERVER_ABSORBED_TASKS to "tidy" the roster: being unclaimable is the fix. If the
        # server ever does claim it, that is a REGRESSION of ZM5LZ24Y, not an improvement.
        "integrity-repin",
        # `oauth-recovery` joined 2026-08-22 (TRDD-6054NY8H, USER decision #2) — also
        # unabsorbed by design. It finishes a 429 recovery the session hook started and the
        # server has no equivalent, so absorbing it would hand the chore to something that
        # does not run it: the ai-maestro#111 hole, on the one path whose failure costs a
        # spent 7-day window. Absorb it if and when the server implements reactive recovery.
        "oauth-recovery",
        # `runaway-guard` joined 2026-10-20 (TRDD-5G66S0HK) as the ELEVENTH — and unlike
        # most of the others above this blackout is NOT BENIGN. The others cost an
        # IMPROVEMENT (a sweep, an update, a notification); this one costs the MECHANISM
        # THAT RELIEVES HOST PRESSURE. The janitor's ABSORBED TABLE does not include it, so
        # the pin names it. It must NEVER be moved into SERVER_ABSORBED_TASKS to "tidy" the
        # roster: that would drop the name from this tripwire AND put a chore the server
        # does not implement inside the `family-a` capability set, which a server
        # advertising that coarse token would then claim. WHAT AN UNCLAIMED CHORE MEANS
        # HERE: the yield is PER-CHORE (`server_runs_chores and task_name in claimed`) and
        # `claimed_chores()` fails toward coverage, so a chore the server has not CLAIMED
        # is never suppressed — at the time of writing (2026-10-20) the server advertised
        # six capabilities and this was not one of them, so the janitor KEEPS it.
        # IT DOES NOT RUN IT, though, and that is a SEPARATE fact from the claim set: the
        # chore's own body returns immediately unless CLAUDE_PLUGIN_OPTION_RUNAWAY_GUARD_ENABLED
        # is truthy (scripts/daemon.py:1171), and that variable is set NOWHERE on this host
        # (measured 2026-10-20: not in the environment, not in any settings file, not in the
        # installed plugin data dir). So today the janitor neither yields this chore to the
        # server nor executes it at all — the kill daemon is DEFAULT-OFF, awaiting the
        # owner's opt-in. The claim set decides WHO would own it; the opt-in decides
        # WHETHER it runs. Conflating the two made the blackout look like a live failure
        # when the feature is in fact not switched on.
        # The cross-repo ask is therefore a TAKEOVER ask: the server must claim the chore
        # AND implement the beat, or the pressure relief stops. This is the ai-maestro#111
        # hole and TRDD-6CRC9SQQ's open contract item, and the `global-chore-blackout`
        # detector does NOT cover it — that detector reports ORPHANED chores (claimed and
        # gone, or unclaimed with no daemon), and this chore satisfies neither arm, so the
        # pin is the only thing making the gap visible.
        "runaway-guard",
        # user-plugins-update briefly returned here 2026-08-19 (TRDD-TIZHEPNC) and was
        # then RETIRED from GLOBAL_CHORES entirely 2026-08-20 (TRDD-E39YT9G6): the
        # harness self-updates installed plugins, so no sweep exists to be absorbed OR
        # unabsorbed — it left this pin by leaving the chore roster, not by a claim.
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
    stamps["version-update"] = now - 10 * 86400        # claimed + stale ⇒ the server's problem
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
    stamps["version-update"] = now - 10 * 86400
    monkeypatch.setattr(mod.gs, "read_last_run", lambda t: stamps.get(t, 0))

    assert [chore for chore, _age in mod._blackout(now)] == ["version-update"]


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
