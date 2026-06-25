"""Tests for the C3 pin-last-GOOD-version + quarantine-bad-version primitives
(TRDD-T198DT1W) that live in ``version_update_lib``.

C3 adds a DATA-dir trust anchor the cache-writer cannot forge: an HMAC of a
GOOD version's manifest, keyed by the DATA-dir ``.integrity-key`` (the key
``janitor_self_integrity.load_or_create_key`` mints). A malicious cache push
that rewrites a version's plaintext manifest STILL fails the HMAC (it lacks the
key), so the stub falls back; a quarantine list lets the stub skip a
proven-bad version fast.

The cardinal rule is FAIL-OPEN — these primitives degrade to "no opinion"
(``None`` / empty set) on every uncertainty (no key, no manifest, unreadable /
malformed state), so the stub's C2-only behavior is preserved whenever C3
cannot PROVE anything. Every leg below is a real on-disk round-trip — no
mocks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


@pytest.fixture
def vu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Import version_update_lib with the DATA dir redirected to a tmp tree so
    no test ever touches the real ~/.claude DATA dir."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    # Key lives at <data>/.integrity-key (janitor_self_integrity convention).
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    for mod in ("version_update_lib", "janitor_self_integrity", "janitor_integrity"):
        sys.modules.pop(mod, None)
    import version_update_lib as mod  # noqa: PLC0415

    return mod


# ── fixture builders ────────────────────────────────────────────────────────


def _make_manifest(version_dir: Path, files: dict[str, str]) -> Path:
    """Write the wrapped on-disk manifest shape (the real writer's shape)."""
    p = version_dir / ".integrity" / "manifest-sha256.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 1, "files": dict(sorted(files.items()))}))
    return p


def _data_dir(vu) -> Path:
    d = vu._data_dir()
    assert d is not None
    return d


# ── manifest_hmac ───────────────────────────────────────────────────────────


def test_manifest_hmac_none_without_key(vu, tmp_path, monkeypatch):
    """No DATA-dir key resolvable → manifest_hmac is None (fail-open: no anchor)."""
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    monkeypatch.delenv("JANITOR_DATA_DIR", raising=False)
    v = tmp_path / "0.20.1"
    _make_manifest(v, {"README.md": "deadbeef"})
    assert vu.manifest_hmac(v, key=None) is None


def test_manifest_hmac_none_without_manifest(vu, tmp_path):
    """No manifest on disk → None (a version that shipped none can't be pinned)."""
    v = tmp_path / "0.20.1"
    v.mkdir()
    assert vu.manifest_hmac(v, key=b"k" * 32) is not None or True  # no manifest:
    assert vu.manifest_hmac(v, key=b"k" * 32) is None


def test_manifest_hmac_matches_manual_hmac(vu, tmp_path):
    """manifest_hmac == HMAC-SHA256(raw manifest bytes, key), base64 — the exact
    value the stub recomputes independently."""
    key = b"x" * 32
    v = tmp_path / "0.20.1"
    mp = _make_manifest(v, {"README.md": "abc", "CLAUDE.md": "def"})
    raw = mp.read_bytes()
    import base64  # noqa: PLC0415

    expected = base64.b64encode(hmac.new(key, raw, hashlib.sha256).digest()).decode()
    assert vu.manifest_hmac(v, key=key) == expected


# ── last-good pin round-trip ────────────────────────────────────────────────


def test_pin_good_version_round_trips(vu, tmp_path):
    """pin_good_version writes the version + its manifest HMAC; read_last_good
    returns them; the HMAC is reproducible from the version + key."""
    key = vu._load_key()
    assert key is not None and len(key) == 32
    v = tmp_path / "0.20.1"
    _make_manifest(v, {"README.md": "abc"})
    ok = vu.pin_good_version(v, "0.20.1")
    assert ok
    pin = vu.read_last_good()
    assert pin is not None
    assert pin["version"] == "0.20.1"
    assert pin["manifest_hmac"] == vu.manifest_hmac(v, key=key)


def test_pin_good_version_noop_without_manifest(vu, tmp_path):
    """A version with NO manifest cannot be pinned (no anchor to compute) → the
    writer is a no-op and read_last_good stays None — never a partial pin."""
    v = tmp_path / "0.20.1"
    v.mkdir()
    assert vu.pin_good_version(v, "0.20.1") is False
    assert vu.read_last_good() is None


def test_read_last_good_none_on_missing(vu):
    """No pin file yet (fresh install) → None (fail-open: stub stays C2-only)."""
    assert vu.read_last_good() is None


def test_read_last_good_none_on_malformed(vu):
    """A corrupt/garbage pin file → None, never an exception (fail-open)."""
    data = _data_dir(vu)
    pin = data / "integrity" / "last-good.json"
    pin.parent.mkdir(parents=True, exist_ok=True)
    pin.write_text("{ not json")
    assert vu.read_last_good() is None


def test_pin_survives_primary_corruption(vu, tmp_path):
    """The pin is written through janitor_integrity.backup_and_write — corrupting
    the PRIMARY still recovers the value from the .bak mirror (crash-safety)."""
    v = tmp_path / "0.20.1"
    _make_manifest(v, {"README.md": "abc"})
    assert vu.pin_good_version(v, "0.20.1")
    data = _data_dir(vu)
    primary = data / "integrity" / "last-good.json"
    primary.write_text("CORRUPTED")  # clobber the primary; .bak + sidecar intact
    pin = vu.read_last_good()
    assert pin is not None and pin["version"] == "0.20.1"


# ── quarantine ──────────────────────────────────────────────────────────────


def test_quarantine_empty_on_missing(vu):
    """No quarantine file → empty set (fail-open: nothing is skipped)."""
    assert vu.read_quarantine() == set()


def test_add_quarantine_round_trips(vu):
    """add_quarantine records a version; read_quarantine returns it; adding a
    second version unions (never replaces)."""
    assert vu.add_quarantine("0.21.0", "crash-loop")
    assert vu.read_quarantine() == {"0.21.0"}
    assert vu.add_quarantine("0.22.0", "manifest-tamper")
    assert vu.read_quarantine() == {"0.21.0", "0.22.0"}
    # Idempotent: re-adding the same version doesn't duplicate.
    assert vu.add_quarantine("0.21.0", "again")
    assert vu.read_quarantine() == {"0.21.0", "0.22.0"}


def test_quarantine_empty_on_malformed(vu):
    """Garbage quarantine file → empty set, never an exception (fail-open: a
    corrupt quarantine must NEVER make the stub skip a good version)."""
    data = _data_dir(vu)
    q = data / "integrity" / "quarantine.json"
    q.parent.mkdir(parents=True, exist_ok=True)
    q.write_text("][ not json")
    assert vu.read_quarantine() == set()
