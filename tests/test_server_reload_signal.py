"""TRDD-BEXY5KIP — the server-published plugins-updated signal feeds the reload generation.

The hub's absorbed fleet-plugins-update lane never writes our reload-needed.flag (the
publish/consume boundary), so its atomic ~/.aimaestro/state/plugins-updated.json is one
more READ-ONLY source in reload_generation()'s max. The per-project reload-acked.ts that
_phase_plugin_reload already advances is the consumption record — no new stamp exists.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import global_state as gs  # noqa: E402


@pytest.fixture(autouse=True)
def _iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "gs"))
    sig = tmp_path / "plugins-updated.json"
    monkeypatch.setenv(gs.SERVER_PLUGINS_UPDATED_ENV, str(sig))
    return sig


def _write(sig: Path, payload: object) -> None:
    sig.write_text(json.dumps(payload), encoding="utf-8")


def test_a_valid_server_signal_feeds_the_generation(_iso: Path) -> None:
    epoch = int(time.time()) - 30
    _write(_iso, {"updated_at_epoch": epoch, "updated": ["x@mp"], "by": "fleet-plugins-update", "count": 1})
    assert gs.reload_generation() == epoch


def test_the_newer_source_wins_either_way(_iso: Path) -> None:
    now = int(time.time())
    _write(_iso, {"updated_at_epoch": now - 500, "updated": [], "by": "t", "count": 0})
    gs.set_reload_flag("some-plugin@mp")  # stamps ~now, newer than the server signal
    assert gs.reload_generation() >= now - 2
    # And the server side wins when IT is newer: clear our flag, keep only the signal.
    gs.clear_reload_flag()
    assert gs.reload_generation() == now - 500


@pytest.mark.parametrize("payload", [
    "not json {",
    [1, 2, 3],
    {},
    {"updated_at_epoch": "soon"},
    {"updated_at_epoch": 0},
    {"updated_at_epoch": -5},
])
def test_every_defective_signal_is_a_silent_zero(_iso: Path, payload: object) -> None:
    """Fail-open: a broken producer must never invent a reload."""
    if isinstance(payload, str):
        _iso.write_text(payload, encoding="utf-8")
    else:
        _write(_iso, payload)
    assert gs.reload_generation() == 0


def test_an_absent_signal_is_a_silent_zero(_iso: Path) -> None:
    assert not _iso.exists()
    assert gs.reload_generation() == 0


def test_a_far_future_epoch_is_rejected_to_protect_the_ack_ratchet(_iso: Path) -> None:
    """The phase's per-project ack advances TO the generation, so a bogus huge epoch
    would ratchet every ack past all future real generations — disabled forever,
    silently. Clamped at now + 1 day (clock-skew tolerance)."""
    _write(_iso, {"updated_at_epoch": int(time.time()) + 90000, "updated": [], "by": "t", "count": 0})
    assert gs.reload_generation() == 0
    near_skew = int(time.time()) + 3600
    _write(_iso, {"updated_at_epoch": near_skew, "updated": [], "by": "t", "count": 0})
    assert gs.reload_generation() == near_skew


def test_the_consumer_never_writes_the_producers_file(_iso: Path) -> None:
    """The publish/consume boundary, pinned from our side: reading the generation N
    times leaves the signal byte-identical (mtime may be read, content never written)."""
    _write(_iso, {"updated_at_epoch": int(time.time()) - 10, "updated": ["x@mp"], "by": "t", "count": 1})
    before = _iso.read_bytes()
    for _ in range(3):
        gs.reload_generation()
    assert _iso.read_bytes() == before
