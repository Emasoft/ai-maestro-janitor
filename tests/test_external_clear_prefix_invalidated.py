"""The prefix-invalidating triggers (TRDD-2F3I2P18): model/effort switch + plugin/skills reload.

Both kill the prompt-cache prefix OUTRIGHT, regardless of the clock, so the gate treats either
as an expired cache arriving by a different route. The property under test throughout is the
tri-state contract copied from `cache_certainly_expired`: an unreadable signal is `None` — never
a synthesized `False` — so a broken probe can only abstain, never overrule the other triggers.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "lib"))

import external_clear as ec  # noqa: E402


class _Proc:
    def __init__(self, rc: int, out: str = "") -> None:
        self.returncode, self.stdout, self.stderr = rc, out, ""


def _rows(*rows: str) -> str:
    return "\n".join(rows) + "\n"


def _arm_statusline(monkeypatch: pytest.MonkeyPatch, stdout: str, rc: int = 0) -> None:
    """Make the agentlens probe reachable and return a canned statusline table."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "08be725e-dead-beef")
    monkeypatch.delenv(ec.CACHE_EXPIRED_COMMAND_ENV, raising=False)
    monkeypatch.setattr(ec.shutil, "which", lambda _name: "/fake/bin/agentlenspro")
    monkeypatch.setattr(
        ec.state, "run_subprocess", lambda *_a, **_k: _Proc(rc, stdout)
    )


# --- model/effort switch (statusline series) ---------------------------------------


def test_a_model_switch_between_the_two_newest_turns_is_a_dead_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A different model on the newest row than the one before it reads True."""
    _arm_statusline(monkeypatch, _rows(
        "18:27:33  08be725e  Sonnet 5  high  69  686.9k  127.92",
        "18:20:10  08be725e  Opus 5    high  68  680.0k  127.10",
    ))
    assert ec.prefix_invalidated() is True


def test_an_effort_switch_alone_is_a_dead_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same model, different effort — the USER's 2026-09-01 addition — also reads True."""
    _arm_statusline(monkeypatch, _rows(
        "18:27:33  08be725e  Opus 5  max   69  686.9k  127.92",
        "18:20:10  08be725e  Opus 5  high  68  680.0k  127.10",
    ))
    assert ec.prefix_invalidated() is True


def test_a_stable_model_and_effort_reads_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two identical consecutive rows are a live prefix — a definite False, not an abstain."""
    _arm_statusline(monkeypatch, _rows(
        "18:27:33  08be725e  Opus 5  high  69  686.9k  127.92",
        "18:20:10  08be725e  Opus 5  high  68  680.0k  127.10",
    ))
    assert ec.prefix_invalidated() is False


def test_another_sessions_switch_says_nothing_about_this_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rows from other sessions are skipped; with fewer than two own rows the answer is None."""
    _arm_statusline(monkeypatch, _rows(
        "18:27:33  aaaa1111  Sonnet 5  high  69  686.9k  127.92",
        "18:20:10  aaaa1111  Opus 5    high  68  680.0k  127.10",
        "18:19:00  08be725e  Opus 5    high  68  679.0k  127.00",
    ))
    assert ec.prefix_invalidated() is None


def test_a_failed_probe_abstains_never_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-zero exit or empty table is 'no signal' (None) — the tri-state contract."""
    _arm_statusline(monkeypatch, "", rc=1)
    assert ec.prefix_invalidated() is None


def test_no_session_id_abstains(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a session id no row is ours, so there is nothing to compare."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    assert ec.prefix_invalidated() is None


def test_the_shared_disable_env_silences_this_probe_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The suite's agentlens kill-switch must disable BOTH probes, not just cache-expired."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "08be725e-dead-beef")
    monkeypatch.setenv(ec.CACHE_EXPIRED_COMMAND_ENV, "")
    assert ec.prefix_invalidated() is None


def test_a_multiword_model_name_does_not_shift_the_effort_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'Opus 5' vs 'Opus 5.1' must compare as models, not misread '5' as the effort."""
    _arm_statusline(monkeypatch, _rows(
        "18:27:33  08be725e  Opus 5.1  high  69  686.9k  127.92",
        "18:20:10  08be725e  Opus 5    high  68  680.0k  127.10",
    ))
    assert ec.prefix_invalidated() is True


# --- plugin/skills reload (the janitor's own ack stamps) ---------------------------


def _write_stamp(sd: Path, name: str, gen: int, *, age_s: int, now: int) -> None:
    p = sd / name
    p.write_text(str(gen), encoding="utf-8")
    os.utime(p, (now - age_s, now - age_s))


def test_a_fresh_plugin_reload_ack_fires_and_survives_a_non_firing_probe(tmp_path: Path) -> None:
    """A fresh reload-acked.ts reads True, and STAYS True until the fire path consumes it —
    a dry-run or a vetoed gate probing first must not eat the event (review-fork, 2026-09-01)."""
    now = 1_700_000_000
    _write_stamp(tmp_path, "reload-acked.ts", 3, age_s=30, now=now)
    assert ec.reload_invalidated(tmp_path, now=now) is True
    # A second probe (the dry-run / vetoed-gate shape) still sees the pending event.
    assert ec.reload_invalidated(tmp_path, now=now) is True
    # Only the fire path consumes: after it, the same stamp must not fire a second clear.
    ec.consume_reload_events(tmp_path)
    assert ec.reload_invalidated(tmp_path, now=now) is False


def test_a_fresh_skills_reload_ack_fires(tmp_path: Path) -> None:
    """/reload-skills is its own stamp and must trigger independently of the plugin one."""
    now = 1_700_000_000
    _write_stamp(tmp_path, "skills-reload-acked.ts", 7, age_s=10, now=now)
    assert ec.reload_invalidated(tmp_path, now=now) is True


def test_a_stale_ack_is_consumed_silently(tmp_path: Path) -> None:
    """An ack older than the freshness window is a rewrite already paid — never fired on."""
    now = 1_700_000_000
    _write_stamp(tmp_path, "reload-acked.ts", 3, age_s=ec._RELOAD_EVENT_FRESH_S + 60, now=now)
    assert ec.reload_invalidated(tmp_path, now=now) is False
    # ...and it was consumed: advancing time cannot resurrect it.
    assert ec.reload_invalidated(tmp_path, now=now + 5) is False


def test_no_stamps_at_all_is_a_definite_false(tmp_path: Path) -> None:
    """Absent stamps are a readable fact (no reload ever acked), not an unreadable signal."""
    assert ec.reload_invalidated(tmp_path, now=1_700_000_000) is False


def test_a_corrupt_stamp_abstains_never_false(tmp_path: Path) -> None:
    """A stamp that exists but does not parse is a broken signal — None, per the contract."""
    (tmp_path / "reload-acked.ts").write_text("not-a-number", encoding="utf-8")
    assert ec.reload_invalidated(tmp_path, now=1_700_000_000) is None


def test_a_corrupt_cursor_self_heals_instead_of_dying(tmp_path: Path) -> None:
    """Garbage in the cursor must not permanently disable the trigger."""
    now = 1_700_000_000
    (tmp_path / ec._RELOAD_SEEN_FILE).write_text("{broken", encoding="utf-8")
    _write_stamp(tmp_path, "reload-acked.ts", 3, age_s=30, now=now)
    assert ec.reload_invalidated(tmp_path, now=now) is True
    # The fire-path consume heals the cursor: it now parses and carries the generation.
    ec.consume_reload_events(tmp_path)
    healed = json.loads((tmp_path / ec._RELOAD_SEEN_FILE).read_text(encoding="utf-8"))
    assert healed["plugins"] == 3
    assert ec.reload_invalidated(tmp_path, now=now) is False


def test_a_second_reload_after_consumption_fires_again(tmp_path: Path) -> None:
    """Each ack advance is one event: gen 3 consumed by the fire path, gen 4 fires anew."""
    now = 1_700_000_000
    _write_stamp(tmp_path, "reload-acked.ts", 3, age_s=30, now=now)
    assert ec.reload_invalidated(tmp_path, now=now) is True
    ec.consume_reload_events(tmp_path)
    _write_stamp(tmp_path, "reload-acked.ts", 4, age_s=5, now=now + 60)
    assert ec.reload_invalidated(tmp_path, now=now + 60) is True


def test_a_stale_event_pending_beside_a_fresh_one_is_not_consumed_early(tmp_path: Path) -> None:
    """One name stale, the other fresh: the probe must fire AND leave the cursor alone — a
    partial consume would need one write covering both names and would eat the fresh event."""
    now = 1_700_000_000
    _write_stamp(tmp_path, "reload-acked.ts", 2, age_s=ec._RELOAD_EVENT_FRESH_S + 60, now=now)
    _write_stamp(tmp_path, "skills-reload-acked.ts", 5, age_s=10, now=now)
    assert ec.reload_invalidated(tmp_path, now=now) is True
    # No cursor write happened, so the fresh event is still pending on the next probe.
    assert not (tmp_path / ec._RELOAD_SEEN_FILE).exists()
    assert ec.reload_invalidated(tmp_path, now=now) is True
