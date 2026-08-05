"""Consuming the ai-maestro server's hibernation answer (janitor#194).

The janitor cannot observe hibernation: the registry reads `offline` for a hibernated agent,
a crashed one, and one never woken alike. So it reported NEITHER rather than guess — the
state was unknown, not wrong. The server now answers it by WRITING a file into each janitor's
own project; the janitor calls nothing, needs no credential, and executes nothing.

Two properties carry the whole design, and both are easy to get subtly wrong:

  1. **No live answer is not good news.** Absent, malformed, wrong-version and stale all mean
     "no answer" — never "the fleet is fine" and never "the fleet is broken". A consumer that
     renders any of them as a verdict invents one.
  2. **`hibernated` and `never_woken` are HEALTHY.** A guardian that reports a deliberate
     sleep as an outage manufactures alarms nobody can act on. Only `crashed` is unhealthy.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_ROOT / "scripts"))

import fleet_status as fstat  # type: ignore[import-not-found]  # noqa: E402
import hibernation as hib  # type: ignore[import-not-found]  # noqa: E402


def _write(root: Path, payload: dict) -> None:
    p = hib.path_for(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def _payload(**over) -> dict:
    """A well-formed v1 answer, overridable per test."""
    base = {
        "v": 1,
        "ts": time.time(),
        "staleAfterS": 360,
        "producedBy": "ai-maestro-server-daemon",
        "data": {
            "agent": {"agentId": "a1", "name": "n", "state": "hibernated",
                      "persisted": False, "tmux": False},
            "counts": {"running": 0, "hibernated": 6, "crashed": 3,
                       "never_woken": 0, "orphaned": 14},
        },
    }
    base.update(over)
    return base


# ── 1. "no live answer" must never read as a verdict ──────────────────────────────────


def test_an_absent_file_is_no_answer(tmp_path: Path) -> None:
    assert hib.read(tmp_path) is None


def test_an_unrecognised_version_is_treated_as_ABSENT_not_as_data(tmp_path: Path) -> None:
    """Their contract, verbatim. A future schema must not be parsed with today's assumptions."""
    _write(tmp_path, _payload(v=2))
    assert hib.read(tmp_path) is None


def test_an_answer_older_than_the_producers_own_window_is_no_answer(tmp_path: Path) -> None:
    """Staleness uses the window the SERVER publishes, not one hard-coded here — so they can
    change cadence without the janitor silently declaring every answer stale."""
    _write(tmp_path, _payload(ts=time.time() - 400, staleAfterS=360))
    assert hib.read(tmp_path) is None

    _write(tmp_path, _payload(ts=time.time() - 400, staleAfterS=3600))
    assert hib.read(tmp_path) is not None, "a wider window from the producer must be honoured"


def test_malformed_json_is_no_answer(tmp_path: Path) -> None:
    p = hib.path_for(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert hib.read(tmp_path) is None


def test_a_boolean_timestamp_is_rejected(tmp_path: Path) -> None:
    """`bool` is an int subclass, so a naive isinstance check reads `true` as epoch 1 — an
    answer 56 years stale that would sail through as fresh if the sign were flipped."""
    _write(tmp_path, _payload(ts=True))
    assert hib.read(tmp_path) is None


def test_a_missing_staleness_window_is_no_answer(tmp_path: Path) -> None:
    """Without it we cannot judge freshness, and assuming a default would be inventing one."""
    payload = _payload()
    del payload["staleAfterS"]
    _write(tmp_path, payload)
    assert hib.read(tmp_path) is None


# ── 2. healthy vs unhealthy ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", ["running", "hibernated", "never_woken"])
def test_deliberate_and_running_states_are_healthy(tmp_path: Path, state: str) -> None:
    _write(tmp_path, _payload(data={"agent": {"state": state}, "counts": {}}))
    answer = hib.read(tmp_path)
    assert answer is not None and answer.is_healthy() is True


def test_only_crashed_is_unhealthy(tmp_path: Path) -> None:
    _write(tmp_path, _payload(data={"agent": {"state": "crashed"}, "counts": {}}))
    answer = hib.read(tmp_path)
    assert answer is not None and answer.is_healthy() is False


def test_an_answer_with_no_agent_record_judges_NOTHING(tmp_path: Path) -> None:
    """The install tree gets a roster and no per-agent record. `None` is not "healthy" — a
    caller that cannot tell must say so rather than reassure."""
    _write(tmp_path, _payload(data={"agents": [{"state": "crashed"}], "counts": {}}))
    answer = hib.read(tmp_path)
    assert answer is not None
    assert answer.state() == ""
    assert answer.is_healthy() is None


# ── 3. what the dashboard renders ─────────────────────────────────────────────────────


def test_counts_label_omits_running_to_avoid_two_disagreeing_numbers(tmp_path: Path) -> None:
    """The table already lists running sessions one per row, and the two are measured
    differently (registry vs process table) — printing both invites a contradiction."""
    _write(tmp_path, _payload())
    answer = hib.read(tmp_path)
    assert answer is not None
    label = answer.counts_label()
    assert label == "6 hibernated · 3 crashed · 14 orphaned"
    assert "running" not in label


def test_zero_counts_are_omitted_rather_than_printed_as_zeros(tmp_path: Path) -> None:
    _write(tmp_path, _payload(data={
        "agent": {"state": "running"},
        "counts": {"running": 3, "hibernated": 0, "crashed": 0, "never_woken": 0, "orphaned": 0},
    }))
    answer = hib.read(tmp_path)
    assert answer is not None and answer.counts_label() == ""


@dataclass
class _Inst:
    diagnosis: str = "healthy"
    active: bool = False
    terminal: dict | None = None


def test_the_session_column_reports_hibernated_as_deliberate_not_as_a_fault() -> None:
    out = fstat._run_state(_Inst(), server_up=True, agent_state="hibernated")
    assert "hibernated" in out
    assert "no auto-resume" in out, "the distinction from STOPPED is the whole point"
    assert "FROZEN" not in out and "CRASHED" not in out


def test_the_session_column_reports_crashed_as_the_servers_verdict() -> None:
    assert "CRASHED" in fstat._run_state(_Inst(), server_up=True, agent_state="crashed")


def test_never_woken_is_rendered_healthy() -> None:
    out = fstat._run_state(_Inst(), server_up=True, agent_state="never_woken")
    assert "healthy" in out and out.upper() != out, "not an alarm"


def test_no_live_answer_falls_through_to_what_we_can_OBSERVE(tmp_path: Path) -> None:
    """The absence of an answer is not permission to guess: with no agent_state the column
    reports the observable diagnosis, exactly as it did before #194 existed."""
    assert hib.read(tmp_path) is None
    agent = _Inst(terminal={"aimaestro_session": "x"})
    assert "STOPPED" in fstat._run_state(agent, server_up=False, agent_state="")
    assert fstat._run_state(_Inst(active=True), server_up=True, agent_state="") == "working"


def test_a_disarmed_project_stays_disarmed_whatever_the_server_says() -> None:
    """A user opt-out is sacrosanct and outranks a server verdict about the agent."""
    out = fstat._run_state(_Inst(diagnosis="unarmed"), server_up=True, agent_state="crashed")
    assert "disarmed" in out
