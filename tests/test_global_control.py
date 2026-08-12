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
import re
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


# ---------- MAINTENANCE: the verbs are REJECTED, never no-ops (INVERTED 2026-07-31) ----------


@pytest.mark.parametrize("verb", ["maintenance", "maintenance-off", "pause", "unpause"])
def test_retired_verbs_are_rejected_not_silently_accepted(verb, tmp_path, monkeypatch, capsys) -> None:
    """Every retired control verb EXITS NON-ZERO and says why.

    Rejecting is the whole point, and it is why these tests were inverted rather than deleted: a
    retired verb that exits 0 lets the caller walk away believing the fleet is quiesced — the
    exact illusion the mode itself created, now reproduced by its own removal. `maintenance-off`
    and `unpause` are refused too, because there is nothing left to lift; any flag still on disk
    is inert and is swept by the next arm."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    # Mint a fresh user-intent token for the verb FIRST: even a caller with the strongest
    # authority the CLI recognises cannot resurrect a retired switch. Authorization decides
    # WHO may act, never WHAT exists.
    _user_asked(monkeypatch, tmp_path, f"/janitor-global-{verb}")
    monkeypatch.setattr(cli.sys, "argv", ["x", verb])
    assert cli.main() == 1, f"`{verb}` must FAIL, not no-op"
    out = capsys.readouterr().out
    assert "REFUSED" in out
    assert "disarm" in out, "the refusal must name the one stop that still exists"
    assert not (tmp_path / "maintenance-mode.flag").exists(), "a refused verb writes nothing"
    assert gs.kill_switch_present() is False, "and must never fall through to a real stop"


def test_status_has_exactly_two_states(tmp_path, monkeypatch, capsys) -> None:
    """RUNNING or DISARMED — nothing in between.

    Status used to have a MAINTENANCE branch that OUTRANKED a stop, plus a combined
    "MAINTENANCE + DISARMED" line, because the two flags could disagree about whether the daemon
    was stopped or merely idling. With one switch left there is one question to answer, and a
    reader can no longer be told the fleet is fine while it does nothing."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    monkeypatch.setattr(cli.sys, "argv", ["x", "status"])
    cli.main()
    assert "RUNNING" in capsys.readouterr().out

    gs.set_kill_switch()
    cli.main()
    out = capsys.readouterr().out
    assert "DISARMED" in out
    assert "MAINTENANCE" not in out, "no mode may soften a stop"


def test_arm_sweeps_the_retired_flags_but_not_a_real_stop(tmp_path, monkeypatch, capsys) -> None:
    """`arm` is the MIGRATION path for both retired flags — the only one a host in maintenance
    will ever reach, since the mode's own lever is gone. It sweeps them and clears the
    kill-switch it was actually asked to clear, and it creates no cron anywhere."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path))
    for name in ("maintenance-mode.flag", "global-pause.flag"):
        (tmp_path / name).write_text("left by an older janitor", encoding="utf-8")
    gs.set_kill_switch("stopped by hand")

    monkeypatch.setattr(cli.sys, "argv", ["x", "arm"])
    assert cli.main() == 0
    capsys.readouterr()
    for name in ("maintenance-mode.flag", "global-pause.flag"):
        assert not (tmp_path / name).exists(), f"arm must sweep the retired {name}"
    assert gs.kill_switch_present() is False


def test_global_arm_skill_doc_is_explicit_it_is_flag_only() -> None:
    """janitor#77: the CLI's own printed output already says this arms no per-project cron —
    the skill doc that surfaces to a reader/agent BEFORE the CLI ever runs must say the same
    thing, prominently, not just in a buried Scope section. Also: the doc must not still
    instruct a reader to run the RETIRED global-pause/unpause verbs as if they still work
    (drift from the 2026-07-31 removal) — every mention of `/janitor-global-unpause` must sit
    in a sentence that says it no longer exists."""
    skill = (_PROJECT_ROOT / "skills" / "janitor-global-arm" / "SKILL.md").read_text(encoding="utf-8")
    lowered = skill.lower()
    assert "flag-only" in lowered, "the doc must say plainly this is a FLAG-only revive"
    assert "arms nothing" in lowered, "the strongest, least-misreadable phrasing must be present"
    assert "does not fan out" in lowered or "does not arm any per-project" in lowered, (
        "the doc must state, unambiguously, that it does not touch per-project crons"
    )
    for m in re.finditer(r".{0,80}/janitor-global-unpause.{0,120}", skill, flags=re.DOTALL):
        assert "no longer exist" in m.group(0), (
            f"every mention of the retired unpause verb must say it no longer exists: {m.group(0)!r}"
        )
