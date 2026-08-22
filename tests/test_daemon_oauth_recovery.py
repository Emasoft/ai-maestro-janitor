#!/usr/bin/env python3
"""`task_oauth_recovery` — the durable half of 429 recovery (TRDD-6054NY8H).

The session hook spawns a DETACHED `rotator.py auto` with both streams on DEVNULL, so a
child that never lands is invisible: nothing waits on it, nothing reads it, and the session
that would have noticed is the one that just died of the rate limit. The daemon services the
leftover request because it is a plain background process — not a Claude turn, so the 429
cannot reach it, and still alive minutes later when the hook is long gone.

These pin the four decisions in that task, each of which is a way to get it wrong:
grace (do not duplicate a healthy hook), opt-in (never act on a withdrawn consent),
clear-on-failure (never thrash), and no-marker (cost nothing on the overwhelmingly common
fire where no rate limit happened).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from test_daemon import _import_daemon_module  # type: ignore[import-not-found]


def _arm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, age_s: int, opt_in: bool):
    """Point the daemon's global-state dir at tmp and write a recovery request `age_s` old."""
    daemon = _import_daemon_module()
    rot = tmp_path / "oauth-rotator"
    rot.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(daemon.gs, "global_state_dir", lambda: tmp_path / "global-state")
    marker = rot / "recovery-requested.ts"
    marker.write_text(str(int(time.time()) - age_s), encoding="utf-8")
    if opt_in:
        (rot / "opt-in.flag").write_text("1", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        daemon.state, "run_subprocess",
        lambda cmd, **kw: calls.append(list(cmd)) or None,  # None = the timeout/missing path
    )
    return daemon, marker, calls


def test_no_marker_costs_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The common fire — no rate limit ever happened — must not spawn anything."""
    daemon = _import_daemon_module()
    monkeypatch.setattr(daemon.gs, "global_state_dir", lambda: tmp_path / "global-state")
    calls: list[list[str]] = []
    monkeypatch.setattr(daemon.state, "run_subprocess", lambda cmd, **kw: calls.append(cmd))
    daemon.task_oauth_recovery()
    assert calls == [], "no request marker → the task must be a pure stat and return"


def test_within_grace_lets_the_hooks_own_child_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh request means the hook's detached child is probably still working.

    Acting immediately would duplicate the healthy path on every single 429, which is the
    reason for a grace window rather than servicing the marker the moment it appears.
    """
    daemon, marker, calls = _arm(tmp_path, monkeypatch, age_s=5, opt_in=True)
    daemon.task_oauth_recovery()
    assert calls == [], "inside the grace window the daemon must defer to the hook's child"
    assert marker.exists(), "and must NOT consume the request it declined to service"


def test_past_grace_services_the_abandoned_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This is the whole point: the hook's child died, so the daemon finishes the job."""
    daemon, marker, calls = _arm(tmp_path, monkeypatch, age_s=999, opt_in=True)
    daemon.task_oauth_recovery()
    assert len(calls) == 1, "past the grace window the daemon must run the rotator itself"
    assert calls[0][-1] == "auto", f"must use the self-guarding verb, got {calls[0][-1]!r}"
    assert not marker.exists(), (
        "the request must be consumed even though run_subprocess returned None (timeout / no "
        "uv) — leaving it would re-run `auto` every 120s against an account that is plainly "
        "not recoverable, which is the thrash the rotator's own dwell exists to prevent"
    )


def test_withdrawn_opt_in_drops_the_request_without_acting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Consent removed between the request and the fire must not be honoured retroactively.

    `auto` reads the live credential, and on macOS that can raise a keychain prompt — a user
    who turned rotation off must not get one because of a 429 recorded earlier.
    """
    daemon, marker, calls = _arm(tmp_path, monkeypatch, age_s=999, opt_in=False)
    daemon.task_oauth_recovery()
    assert calls == [], "no opt-in flag → the rotator must never be invoked"
    assert not marker.exists(), "and the stale request must be dropped, not left to re-fire"
