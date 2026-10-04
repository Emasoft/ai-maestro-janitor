"""capture() and the refusal marker (TRDD-0SU2C2IM): the marker carries the observed account as
data and a successful capture for the account clears it. The only fakes are the network/keychain/
browser edges of capture(); the marker I/O is real, in a temp dir."""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

_SLOT_PY = Path(__file__).resolve().parent.parent / "scripts" / "oauth_rotator" / "slot_capture_browser.py"
_spec = importlib.util.spec_from_file_location("slot_capture_refusal_under_test", _SLOT_PY)
assert _spec and _spec.loader
scb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scb)

_TARGET = "spare.person@users.noreply.github.com"
_OTHER = "other.person@users.noreply.github.com"


def _edges(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scb.rotator, "ROOT", tmp_path)
    monkeypatch.setattr(scb, "_materialize_cookies", lambda e: None)
    monkeypatch.setattr(scb, "_snapshot_cookies", lambda e: None)


def test_refusal_marker_takes_the_account_from_the_exception_not_the_wording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reworded refusal message still records the observed account."""
    _edges(monkeypatch, tmp_path)

    def refuse(*_a: object, **_k: object) -> str:
        raise scb._ConsentRefused(scb._Refusal("totally different wording", _OTHER))

    monkeypatch.setattr(scb, "_drive_browser", refuse)
    assert scb.capture(_TARGET, headless=True) == scb.EXIT_CONSENT_REFUSED
    marker = scb.rotator_alert.fresh_refusal(tmp_path, _TARGET, time.time())
    assert marker is not None and marker["actual"] == _OTHER


def test_unconfirmed_account_is_recorded_as_none() -> None:
    """The real refusal builder carries None when the account could not be read."""
    assert scb._consent_refusal(None, _TARGET).actual is None
    assert scb._consent_refusal(_OTHER, _TARGET).actual == _OTHER
    assert scb._consent_refusal(_TARGET, _TARGET) is None


def test_successful_capture_clears_the_refusal_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Filing the slot ends the signed-in-as-another-account condition at once."""
    _edges(monkeypatch, tmp_path)
    scb.rotator_alert.record_capture_refused(tmp_path, _TARGET, _OTHER, time.time())
    assert scb.rotator_alert._refusal_path(tmp_path, _TARGET).exists()
    monkeypatch.setattr(scb, "_drive_browser", lambda *a, **k: "the-code")
    monkeypatch.setattr(scb, "_exchange", lambda *a, **k: {"access_token": "a", "refresh_token": "r", "expires_in": 3600})
    monkeypatch.setattr(scb.rotator, "account_email", lambda blob: _TARGET)
    monkeypatch.setattr(scb.rotator, "file_slot", lambda *a, **k: True)
    assert scb.capture(_TARGET, headless=True) == 0
    assert not scb.rotator_alert._refusal_path(tmp_path, _TARGET).exists()
