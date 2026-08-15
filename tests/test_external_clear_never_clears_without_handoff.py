"""`/clear` is never typed unless the handoff is already on disk (TRDD-UQW5IOAE).

THE INVARIANT, and why it is the one that matters most in this whole feature: the clear is
UNRECOVERABLE and nothing reviews it first, so the handoff is the only thing standing between an
unattended shrink and a session losing everything it was working on. If the chain can ever fire
while the handoff write failed, the feature stops being "shrink a session" and becomes "destroy
one".

It holds today by CONSTRUCTION — `state.atomic_write` raises rather than swallowing, and the write
is a plain statement before `_fire`, so an OSError skips the clear. That is exactly why it needs a
test: the invariant is currently protected by the ABSENCE of a try/except, and the most natural
future "improvement" to a write that can fail is to wrap it in one. That refactor would look like
hardening and would silently convert a failed handoff into a destructive clear, with every other
test in the suite still green.

END-TO-END ON PURPOSE, not a pure-function check. This card's advisor verdict (2026-08-14) is
explicit that a mutation of a pure gate cannot catch a wiring defect — TRDD-OO301H7D was an
argument computed and never passed, and 53 of 54 pure-layer tests stayed green through it. So
these drive the real `main()` and assert on the ORDER of real effects.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import external_clear as ec  # noqa: E402
import external_handoff_clear as ehc  # noqa: E402


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _firing_project(tmp_path, monkeypatch) -> tuple[Path, Path]:
    """A project the watcher will actually decide to clear, with a recorded pane.

    Every veto is satisfied with REAL inputs rather than by stubbing the gate: a long-idle
    transcript that does not end on an unanswered question, the feature switched on, and the
    agentlensPro probe disabled so no subprocess is spawned.
    """
    import memory_scopes  # noqa: PLC0415

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(ec.ENABLED_ENV, "true")
    monkeypatch.setenv(ec.CACHE_EXPIRED_COMMAND_ENV, "")  # no third-party probe
    monkeypatch.setenv(ec.MIN_CONTEXT_ENV, "0")  # size must not veto

    import cold_cache_compact  # noqa: PLC0415

    monkeypatch.setenv(cold_cache_compact.CLEAR_MIN_IDLE_ENV, "60")

    now = int(time.time())
    root = tmp_path / "proj"
    sd = root / ".janitor" / "state"
    sd.mkdir(parents=True)
    (root / "design" / "tasks").mkdir(parents=True)

    slug = memory_scopes.project_slug(os.path.realpath(str(root)))
    tdir = tmp_path / ".claude" / "projects" / slug
    tdir.mkdir(parents=True)
    (tdir / "s1.jsonl").write_text(
        json.dumps({"type": "assistant", "timestamp": _iso(now - 9000), "message": {}}) + "\n",
        encoding="utf-8",
    )
    # An old mtime is what makes the session look abandoned rather than merely quiet.
    os.utime(tdir / "s1.jsonl", (now - 9000, now - 9000))

    # A pane the chain could type into — without one the watcher declines before any of this.
    monkeypatch.setattr(
        ehc.ec, "terminal_from_record", lambda _rec: {"kind": "tmux", "pane": "%1"}
    )
    return root, sd


def _run_main(root: Path, monkeypatch) -> int:
    monkeypatch.setattr(sys, "argv", ["external_handoff_clear.py", "--project-root", str(root),
                                      "--force"])
    return ehc.main()


def test_the_handoff_is_on_disk_before_the_clear_chain_is_spawned(tmp_path, monkeypatch) -> None:
    """The ordering, asserted from INSIDE the fire: both happening is not the same as the right
    one happening first. A chain spawned before the write would still leave a handoff on disk by
    the time any after-the-fact assertion looked."""
    root, sd = _firing_project(tmp_path, monkeypatch)
    seen: dict = {}

    def _spy_fire(_root, _sd, _terminal, _now):
        handoff = sd / "agent-handoff.md"
        seen["existed_at_fire"] = handoff.is_file()
        seen["bytes_at_fire"] = handoff.stat().st_size if handoff.is_file() else 0

    monkeypatch.setattr(ehc, "_fire", _spy_fire)

    rc = _run_main(root, monkeypatch)

    assert rc == 0
    assert seen.get("existed_at_fire") is True, (
        "the clear chain was spawned while no handoff existed on disk — an unattended /clear "
        "with nothing to resume from is unrecoverable data loss."
    )
    assert seen["bytes_at_fire"] > 0, "the handoff existed but was empty at fire time"


def test_a_failed_handoff_write_never_reaches_the_clear(tmp_path, monkeypatch) -> None:
    """The guard this file exists for. `atomic_write` currently RAISES, so the clear is skipped —
    wrapping it in a try/except would look like hardening and would silently make a failed
    handoff clear the session anyway."""
    root, _sd = _firing_project(tmp_path, monkeypatch)
    fired: list[bool] = []

    def _boom(_target, _value):
        raise OSError("disk full")

    monkeypatch.setattr(ehc.state, "atomic_write", _boom)
    monkeypatch.setattr(ehc, "_fire", lambda *_a, **_k: fired.append(True))

    with pytest.raises(OSError):
        _run_main(root, monkeypatch)

    assert fired == [], (
        "the clear chain was spawned even though writing the handoff FAILED — the session would "
        "be cleared with no handoff to resume from."
    )
