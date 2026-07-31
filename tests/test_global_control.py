"""Tests for the machine-wide janitor control flags (TRDD-a3fa4d5d).

One machine-wide stop, plus a keep-warm mode:
  * the kill-switch (DISARM) — daemon exits AND every heartbeat goes silent. The
    daemon + ensure_daemon_running + dispatch.py Phase 0 all honor it (TRDD-NJ22HNC3).
  * the maintenance flag — sessions keep firing, cache-refresh-only.

The global-pause flag (PAUSE) was a third mechanism until 2026-07-31. It is retired: a
stop that leaves the daemon resident and every heartbeat firing-but-idle is
indistinguishable from a healthy fleet, which is how a project sat silently disabled for
two weeks. Only `clear_global_pause` survives, as a migration sweep run by `arm`.

These cover the global_state primitives + the global_control_cli surface against an
isolated state dir (no real daemon, no real ~/.claude). The daemon-idle and
dispatch-no-op WIRING is covered by test_daemon.py / the dispatch tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import global_control_cli as cli  # type: ignore[import-not-found]  # noqa: E402
import global_state as gs  # type: ignore[import-not-found]  # noqa: E402
import pytest  # noqa: E402
import state as st  # type: ignore[import-not-found]  # noqa: E402
import user_intent  # type: ignore[import-not-found]  # noqa: E402

# ---------- DISARM (kill-switch) ----------

def test_disarm_set_and_clear(tmp_path, monkeypatch) -> None:
    """set creates the kill-switch (with the reason), clear removes it, clear is
    idempotent — the DISARM/revive primitives the daemon already obeys."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    # The six mode flags now live at the FIXED control_dir() (ARCHITECTURE.md §7.1,
    # TRDD-QK7M2B0X), not global_state_dir() — pin it to the SAME isolated tmp_path so
    # the raw-path assertions below (which read `tmp_path / "<flag>"` directly) still
    # find what set_*() wrote, and so no test here shares the real ~/.claude/janitor-control.
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    assert gs.kill_switch_present() is False
    gs.set_kill_switch("disarmed via test")
    assert gs.kill_switch_present() is True
    assert json.loads((tmp_path / "kill-switch.flag").read_text(encoding="utf-8"))["reason"] == "disarmed via test"
    gs.clear_kill_switch()
    assert gs.kill_switch_present() is False
    gs.clear_kill_switch()                       # idempotent


def test_set_kill_switch_default_reason(tmp_path, monkeypatch) -> None:
    """An empty reason still writes a non-empty marker so the flag file is never blank."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    # The six mode flags now live at the FIXED control_dir() (ARCHITECTURE.md §7.1,
    # TRDD-QK7M2B0X), not global_state_dir() — pin it to the SAME isolated tmp_path so
    # the raw-path assertions below (which read `tmp_path / "<flag>"` directly) still
    # find what set_*() wrote, and so no test here shares the real ~/.claude/janitor-control.
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    gs.set_kill_switch()
    assert json.loads((tmp_path / "kill-switch.flag").read_text(encoding="utf-8"))["reason"] == "stopped"


# ---------- the global_control_cli surface ----------


@pytest.fixture(autouse=True)
def _isolate_state_dir():
    """`state.state_dir()` is lru_cached — a per-process singleton, correct in production (one process,
    one project) and poison in a test process that hosts many. Clear it around every test so the intent
    token one test writes can never be read by another."""
    caches = (st.project_root, st.janitor_root, st.state_dir, st.log_dir)
    for c in caches:
        c.cache_clear()
    yield
    for c in caches:
        c.cache_clear()


def _user_asked(monkeypatch, tmp_path, prompt: str) -> None:
    """Simulate the USER typing `prompt` — the only thing that can authorize a machine-wide STOP.

    A stop (`disarm`/`pause`) is intent-gated (TRDD-RDFWQIFA): without it, an agent could set the
    machine-wide stop itself and every session would then dutifully self-disarm ON THAT STOP'S
    AUTHORITY — a trivial bypass of the `disarmed.flag` guard, which accepts a genuine global stop as
    authority. Gating the stop closes the chain, so no link in it is forgeable.

    In production the token is minted by the UserPromptSubmit hook from the user's RAW keystrokes — the
    one surface the model can never author. Here we mint it through that same function.
    """
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    for c in (st.project_root, st.janitor_root, st.state_dir, st.log_dir):
        c.cache_clear()
    st.init_state()
    user_intent.record_intent_from_prompt(prompt)


def test_a_stop_with_no_user_intent_is_REFUSED(tmp_path, monkeypatch, capsys) -> None:
    """THE security property. An agent that decides on its own to stop the fleet must fail.

    On 2026-07-14 an agent disarmed the heartbeat to save tokens during a rate limit and the session
    sat dead for HOURS — the exact stall the heartbeat exists to abolish. A machine-wide stop is worse
    still: it is the authority every session's self-disarm then relies on. So a stop with no user
    keystroke behind it does nothing at all.
    """
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    # The six mode flags now live at the FIXED control_dir() (ARCHITECTURE.md §7.1,
    # TRDD-QK7M2B0X), not global_state_dir() — pin it to the SAME isolated tmp_path so
    # the raw-path assertions below (which read `tmp_path / "<flag>"` directly) still
    # find what set_*() wrote, and so no test here shares the real ~/.claude/janitor-control.
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "no-intent"))
    monkeypatch.setattr(cli.sys, "argv", ["x", "disarm", "an agent decided this on its own"])
    assert cli.main() != 0, "an unauthorized machine-wide stop must FAIL, not silently succeed"
    assert gs.kill_switch_present() is False, "no flag may be raised without the user's say-so"


def test_cli_disarm_arm_roundtrip(tmp_path, monkeypatch, capsys) -> None:
    """DISARM is the TRUE STOP: the kill-switch makes the daemon EXIT and every heartbeat go
    silent (TRDD-NJ22HNC3). ARM revives it, and also SWEEPS the retired global-pause flag an
    older version could have left set — nothing reads it now, but a stale flag in the control
    plane makes a healthy machine look suspended to the next reader."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    # The six mode flags now live at the FIXED control_dir() (ARCHITECTURE.md §7.1,
    # TRDD-QK7M2B0X), not global_state_dir() — pin it to the SAME isolated tmp_path so
    # the raw-path assertions below (which read `tmp_path / "<flag>"` directly) still
    # find what set_*() wrote, and so no test here shares the real ~/.claude/janitor-control.
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    _user_asked(monkeypatch, tmp_path, "/janitor-global-disarm")
    monkeypatch.setattr(cli.sys, "argv", ["x", "disarm", "because"])
    assert cli.main() == 0
    assert gs.kill_switch_present() is True
    monkeypatch.setattr(cli.sys, "argv", ["x", "status"])
    cli.main()
    assert "DISARMED" in capsys.readouterr().out
    monkeypatch.setattr(cli.sys, "argv", ["x", "arm"])
    assert cli.main() == 0
    assert gs.kill_switch_present() is False


def test_the_pause_subcommands_no_longer_exist(tmp_path, monkeypatch) -> None:
    """`pause` / `unpause` must be REJECTED, not silently accepted as a no-op.

    A retired verb that exits 0 is worse than one that errors: a script (or an agent) keeps
    calling it, believes the fleet is suspended, and nothing says otherwise.
    """
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    for verb in ("pause", "unpause"):
        _user_asked(monkeypatch, tmp_path, f"/janitor-global-{verb}")
        monkeypatch.setattr(cli.sys, "argv", ["x", verb])
        with pytest.raises(SystemExit):
            cli.main()


def test_arm_sweeps_a_stale_pause_flag(tmp_path, monkeypatch) -> None:
    """The migration: a host paused under an older janitor must not keep a flag that makes it
    look suspended forever. `arm` is where the sweep runs."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    stale = tmp_path / "global-pause.flag"
    stale.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(cli.sys, "argv", ["x", "arm"])
    assert cli.main() == 0
    assert not stale.exists(), "arm must sweep the retired pause flag"


def test_cli_reload_skills_stamps_only_its_own_flag(tmp_path, monkeypatch, capsys) -> None:
    """`reload-skills` stamps ONLY the standalone-skills reload generation — NOT the
    kill-switch, NOT the pause flag. Status stays RUNNING (it is a one-time reload
    request, not a stop-state)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    # The six mode flags now live at the FIXED control_dir() (ARCHITECTURE.md §7.1,
    # TRDD-QK7M2B0X), not global_state_dir() — pin it to the SAME isolated tmp_path so
    # the raw-path assertions below (which read `tmp_path / "<flag>"` directly) still
    # find what set_*() wrote, and so no test here shares the real ~/.claude/janitor-control.
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    assert gs.skills_reload_flag_present() is False
    monkeypatch.setattr(cli.sys, "argv", ["x", "reload-skills", "installed skill-x"])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "reload-skills requested" in out
    assert gs.skills_reload_flag_present() is True
    body = (tmp_path / "skills-reload-needed.flag").read_text(encoding="utf-8")
    assert json.loads(body)["reason"] == "installed skill-x"
    # It is NOT a stop: neither the kill-switch nor the pause flag is raised.
    assert gs.kill_switch_present() is False
    monkeypatch.setattr(cli.sys, "argv", ["x", "status"])
    cli.main()
    assert "RUNNING" in capsys.readouterr().out


def test_cli_default_command_is_status(tmp_path, monkeypatch, capsys) -> None:
    """No argument → status (a safe read-only default, never an accidental disarm/pause)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    # The six mode flags now live at the FIXED control_dir() (ARCHITECTURE.md §7.1,
    # TRDD-QK7M2B0X), not global_state_dir() — pin it to the SAME isolated tmp_path so
    # the raw-path assertions below (which read `tmp_path / "<flag>"` directly) still
    # find what set_*() wrote, and so no test here shares the real ~/.claude/janitor-control.
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    monkeypatch.setattr(cli.sys, "argv", ["x"])
    assert cli.main() == 0
    assert "RUNNING" in capsys.readouterr().out
    assert gs.kill_switch_present() is False


# ---------- MAINTENANCE (maintenance flag, TRDD-FPL60EKV) ----------

def test_cli_maintenance_roundtrip(tmp_path, monkeypatch, capsys) -> None:
    """`maintenance` sets the maintenance flag and status reports MAINTENANCE;
    `maintenance-off` clears it and status returns to RUNNING."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    # The six mode flags now live at the FIXED control_dir() (ARCHITECTURE.md §7.1,
    # TRDD-QK7M2B0X), not global_state_dir() — pin it to the SAME isolated tmp_path so
    # the raw-path assertions below (which read `tmp_path / "<flag>"` directly) still
    # find what set_*() wrote, and so no test here shares the real ~/.claude/janitor-control.
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    monkeypatch.setattr(cli.sys, "argv", ["x", "maintenance", "keep caches warm"])
    assert cli.main() == 0
    assert gs.maintenance_mode_present() is True
    assert json.loads((tmp_path / "maintenance-mode.flag").read_text(encoding="utf-8"))["reason"] == "keep caches warm"
    monkeypatch.setattr(cli.sys, "argv", ["x", "status"])
    cli.main()
    assert "MAINTENANCE" in capsys.readouterr().out
    monkeypatch.setattr(cli.sys, "argv", ["x", "maintenance-off"])
    assert cli.main() == 0
    assert gs.maintenance_mode_present() is False


def test_cli_maintenance_does_not_disarm(tmp_path, monkeypatch) -> None:
    """MAINTENANCE raises ONLY its own flag — never the kill-switch or global-pause. It is
    the opposite intent (keep firing cheap, not stop), so it must not imply a stop."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    # The six mode flags now live at the FIXED control_dir() (ARCHITECTURE.md §7.1,
    # TRDD-QK7M2B0X), not global_state_dir() — pin it to the SAME isolated tmp_path so
    # the raw-path assertions below (which read `tmp_path / "<flag>"` directly) still
    # find what set_*() wrote, and so no test here shares the real ~/.claude/janitor-control.
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    monkeypatch.setattr(cli.sys, "argv", ["x", "maintenance"])
    assert cli.main() == 0
    assert gs.maintenance_mode_present() is True
    assert gs.kill_switch_present() is False, "maintenance must NOT disarm"


def test_cli_status_maintenance_wins_over_disarm(tmp_path, monkeypatch, capsys) -> None:
    """When maintenance AND a stop are both set, status reports MAINTENANCE — precedence
    mirrors dispatch's mode resolution (maintenance is the explicit keep-warm intent)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    # The six mode flags now live at the FIXED control_dir() (ARCHITECTURE.md §7.1,
    # TRDD-QK7M2B0X), not global_state_dir() — pin it to the SAME isolated tmp_path so
    # the raw-path assertions below (which read `tmp_path / "<flag>"` directly) still
    # find what set_*() wrote, and so no test here shares the real ~/.claude/janitor-control.
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    gs.set_kill_switch()
    gs.set_maintenance_mode()
    monkeypatch.setattr(cli.sys, "argv", ["x", "status"])
    cli.main()
    assert "MAINTENANCE" in capsys.readouterr().out


# ---------- Boundary: the self-budget path never writes GLOBAL flags (TRDD-ZCODD6YS) ----------


def _import_dispatch_gc():
    import importlib.util as _u

    spec = _u.spec_from_file_location("dispatch_gc_ut", str(_PROJECT_ROOT / "scripts" / "dispatch.py"))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_self_budget_never_calls_global_setters(tmp_path, monkeypatch) -> None:
    """The self-budget actuator must NEVER call set_maintenance_mode / set_kill_switch (the
    per-project channeling invariant, TRDD-X92VBFNF): a per-project budget can only ever set
    the LOCAL maintenance flag, never stop the fleet. Both global setters are patched to fail
    the test if they are ever reached while the phase drives an over-budget maintenance
    verdict."""
    import json
    import time as _time

    project = tmp_path / "project"
    (project / ".janitor" / "state").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "global"))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "control"))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_SELF_BUDGET", "1000")
    # Pop state/global_state so this test gets FRESH modules whose @lru_cache'd state_dir()
    # resolves under THIS env — a shared, already-populated cache from an earlier test file
    # would otherwise point the phase at the wrong project (the exact multi-file batch flake).
    for m in ("dispatch_gc_ut", "state", "global_state"):
        sys.modules.pop(m, None)

    dispatch = _import_dispatch_gc()
    _st = dispatch.state
    _gs = dispatch.gs
    _gs.init_global_state()
    _st.init_state()
    sd = _st.state_dir()
    (sd / "token-meter.jsonl").write_text(
        json.dumps({"ts": int(_time.time()), "heartbeat": True, "output": 5000}) + "\n", encoding="utf-8"
    )

    monkeypatch.setattr(_gs, "set_maintenance_mode", lambda *a, **k: pytest.fail("self-budget must NEVER set the GLOBAL maintenance flag"))
    monkeypatch.setattr(_gs, "set_kill_switch", lambda *a, **k: pytest.fail("self-budget must NEVER set the kill-switch"))

    assert dispatch._phase_self_budget() is True  # maintenance verdict
    assert (sd / _st.MAINTENANCE_FLAG).is_file(), "only the LOCAL flag is written"
    assert _gs.maintenance_mode_present() is False
    assert _gs.kill_switch_present() is False
