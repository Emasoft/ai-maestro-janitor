"""The disarm guard: `disarmed.flag` may only be written on real human authority (TRDD-RDFWQIFA).

The flag is the OFF switch for BOTH of the heartbeat's survival paths — it makes the fleet guardian
treat the project as sacrosanct (never re-arm) and suppresses the SessionStart re-arm nudge. So the
question these tests ask is the security one: can an agent, acting alone, produce that flag?
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "scripts" / "disarm_guard.py"

sys.path.insert(0, str(REPO / "scripts" / "lib"))

import user_intent  # noqa: E402


def _run(project: Path, global_state: Path) -> str:
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(project),  # isolate the presence breadcrumb
        "CLAUDE_PROJECT_DIR": str(project),
        "JANITOR_GLOBAL_STATE_DIR": str(global_state),
    }
    out = subprocess.run([sys.executable, str(GUARD)], env=env, capture_output=True, text=True, check=False)
    return out.stdout.strip()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".janitor" / "state").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def gstate(tmp_path: Path) -> Path:
    d = tmp_path / "global"
    d.mkdir()
    return d


def _flag(project: Path) -> Path:
    return project / ".janitor" / "state" / "disarmed.flag"


def test_an_agent_alone_cannot_write_the_flag(project: Path, gstate: Path) -> None:
    """THE test. No user request, no global stop — an agent running /janitor-disarm on its own
    judgment must NOT be able to claim the user opted out.

    This is the 2026-07-14 incident: the agent disarmed to save tokens during a rate limit, the flag
    told the guardian "the human chose this", and the session stayed dead for hours. With no flag the
    guardian sees `cron_dead` and re-arms — the mistake becomes self-healing instead of permanent.
    """
    assert _run(project, gstate) == "DISARM_UNVERIFIED"
    assert not _flag(project).exists(), "an agent must not be able to forge the user's opt-out"


def test_a_user_request_records_the_flag(project: Path, gstate: Path) -> None:
    """A human who typed /janitor-disarm gets exactly what they asked for — the gate protects them,
    it does not obstruct them."""
    sdir = project / ".janitor" / "state"
    user_intent.record_intent_from_prompt("/janitor-disarm", state_dir=sdir)
    assert _run(project, gstate).startswith("DISARM_RECORDED:user-asked")
    assert _flag(project).exists()


def test_a_machine_wide_stop_authorizes_the_self_disarm(project: Path, gstate: Path) -> None:
    """The [janitor-self-disarm] path: the user already stopped the whole fleet, and each session
    deleting its own cron is how that stop is EXECUTED (a cron fire is a billed turn even when it
    does nothing). The authority is real global state, which an agent cannot fabricate — the flag that
    sets it is itself intent-gated in global_control_cli."""
    (gstate / "kill-switch.flag").write_text("stopped by the user")
    assert _run(project, gstate).startswith("DISARM_RECORDED:global-stop")
    assert _flag(project).exists()


def test_the_intent_is_spent_so_one_request_disarms_once(project: Path, gstate: Path) -> None:
    """One request authorizes one disarm — not a standing licence for the next ten minutes."""
    sdir = project / ".janitor" / "state"
    user_intent.record_intent_from_prompt("/janitor-disarm", state_dir=sdir)
    assert _run(project, gstate).startswith("DISARM_RECORDED")
    _flag(project).unlink()
    assert _run(project, gstate) == "DISARM_UNVERIFIED", "the token must be spent, not standing"
    assert not _flag(project).exists()
