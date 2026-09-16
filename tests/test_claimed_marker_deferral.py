"""Tests for TRDD-7ZMQSXO6 (a): a heartbeat fire must not dispatch a memory chore that
already has an UNEXPIRED CLAIMED record — the scheduler re-emitting the same
`[janitor-memory-<chore>]` marker while a peer's earlier claim on that chore is still
in flight must defer instead of spawning a second agent onto the same work.

`dispatch._suppress_stale_memory_markers` is extended (never re-implemented) to check
`memory_dispatch_claim`'s CLAIMED pool with the EXACT age/threshold math
`memory_dispatch_claim.expire_stale_claims` applies (max_age_s=0) before it ever reaches
the pre-existing PENDING-pool "claimable" check these tests' siblings
(`tests/test_dispatch_defang.py`) already pin.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import dispatch  # noqa: E402
import memory_dispatch_claim as mdc  # noqa: E402
import memory_settings  # noqa: E402
import orphaned_memory_maint as omm  # noqa: E402
import state  # noqa: E402

CHORE = "split"


def _clear_state_cache() -> None:
    state.project_root.cache_clear()
    state.janitor_root.cache_clear()
    state.state_dir.cache_clear()


def _threshold_s(chore: str, scope: str) -> float:
    """The exact expiry threshold `expire_stale_claims` would apply — reused here so
    the fixtures below age a claim past/short of it without depending on the real
    per-day settings' concrete values (only their default in this untouched suite)."""
    cadence_s = memory_settings.interval_s_for(chore)
    factor = omm.factor_for_scope(scope)
    return max(0.0, cadence_s * factor, mdc._STALE_CLAIM_FLOOR_S)


def _write_claimed(state_dir: Path, dispatch_id: str, chore: str, *, stamped_at: int, scope: str = "PROJECT") -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    p = state_dir / f"{mdc.CLAIMED_PREFIX}{dispatch_id}.json"
    p.write_text(json.dumps({
        "marker": f"[janitor-memory-{chore}]", "intervention": chore,
        "scope": scope, "root": "/tmp/project/memory", "stamped_at": stamped_at,
        "dispatch_id": dispatch_id,
    }), encoding="utf-8")
    return p


def _write_pending(state_dir: Path, dispatch_id: str, chore: str, *, stamped_at: int = 100, scope: str = "PROJECT") -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    p = state_dir / f"{mdc.PENDING_PREFIX}{dispatch_id}.json"
    p.write_text(json.dumps({
        "marker": f"[janitor-memory-{chore}]", "intervention": chore,
        "scope": scope, "root": "/tmp/project/memory", "stamped_at": stamped_at,
        "dispatch_id": dispatch_id,
    }), encoding="utf-8")
    return p


def test_marker_deferred_when_unexpired_claim_exists(tmp_path, monkeypatch):
    """(1) An unexpired CLAIMED record for the chore drops the marker and prints the
    plain deferral line, even with no PENDING record at all."""
    import time

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(dispatch, "_decision_fired", False)
    _clear_state_cache()
    try:
        sd = state.state_dir()
        _write_claimed(sd, "100-abcd1234", CHORE, stamped_at=int(time.time()) - 100)
        out = dispatch._suppress_stale_memory_markers("[janitor-memory-split]\n")
        assert "[janitor-memory-split]\n" not in out
        assert "deferred" in out and "split claim is still in flight" in out
        assert dispatch._decision_fired is True
    finally:
        _clear_state_cache()


def test_marker_survives_when_only_matching_claim_is_expired(tmp_path, monkeypatch):
    """(2) A CLAIMED record older than its chore's own expiry threshold must not defer
    anything — the marker falls through to the pre-existing PENDING-pool check and
    survives unchanged because a matching pending record is also present."""
    import time

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(dispatch, "_decision_fired", False)
    _clear_state_cache()
    try:
        sd = state.state_dir()
        threshold = _threshold_s(CHORE, "PROJECT")
        stale_stamped_at = int(time.time()) - int(threshold) - 1000
        _write_claimed(sd, "50-expiredaaa", CHORE, stamped_at=stale_stamped_at)
        _write_pending(sd, "200-deadbeef", CHORE, stamped_at=100)
        out = dispatch._suppress_stale_memory_markers("[janitor-memory-split]\n")
        assert out == "[janitor-memory-split]\n"
        assert "deferred" not in out
        assert dispatch._decision_fired is False
    finally:
        _clear_state_cache()


def test_marker_unaffected_when_no_claimed_record_exists(tmp_path, monkeypatch):
    """(3) No CLAIMED record at all: behaviour is exactly the pre-existing pending-pool
    gate — unchanged."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(dispatch, "_decision_fired", False)
    _clear_state_cache()
    try:
        sd = state.state_dir()
        _write_pending(sd, "200-deadbeef", CHORE, stamped_at=100)
        out = dispatch._suppress_stale_memory_markers("[janitor-memory-split]\n")
        assert out == "[janitor-memory-split]\n"
        assert dispatch._decision_fired is False
    finally:
        _clear_state_cache()


def test_deferral_alone_suppresses_the_quiet_token(tmp_path, monkeypatch, capsys):
    """(4) A fire whose only action this cycle is the deferral must NOT also print
    `[janitor-quiet]` — a deferral is a decision (TRDD-7ZMQSXO6 (a))."""
    import time

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(dispatch, "_decision_fired", False)
    _clear_state_cache()
    try:
        sd = state.state_dir()
        _write_claimed(sd, "100-abcd1234", CHORE, stamped_at=int(time.time()) - 100)
        dispatch._suppress_stale_memory_markers("[janitor-memory-split]\n")
        capsys.readouterr()  # discard anything captured incidentally so far
        dispatch._emit_quiet_if_idle()
        assert capsys.readouterr().out == ""
    finally:
        _clear_state_cache()
