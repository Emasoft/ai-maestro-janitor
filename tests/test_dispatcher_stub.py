"""Tests for the dispatcher-stub's C2 verify-before-exec gate (TRDD-T198DT1W).

The stub is the boot-critical bootstrap of the whole janitor (cron → stub →
dispatch.py → daemon). Its one job — pick a cached plugin version and exec its
`dispatch.py` — must now:

  (a) prefer the NEWEST version that verifies clean against its shipped integrity
      manifest,
  (b) on an EXPLICIT corruption (a manifest-listed file whose live hash differs,
      or is gone), walk DOWN to the next-older clean version, and
  (c) FAIL-OPEN on every uncertainty — no/unreadable/malformed/empty manifest, a
      degenerate empty-hash entry, or NO clean version at all — so the heartbeat
      is never bricked by its own integrity gate.

These tests prove all three legs. We load the hyphenated stub file by spec and
stub `os.execv` so `main()` "execs" into a recorded path instead of replacing the
test process.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path

import pytest

_STUB_PATH = Path(__file__).resolve().parent.parent / "scripts" / "dispatcher-stub.py"


def _load_stub():
    """Import scripts/dispatcher-stub.py (hyphenated → not importable by name)."""
    spec = importlib.util.spec_from_file_location("dispatcher_stub", _STUB_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Execed(Exception):
    """Raised by the fake os.execv so main() stops at the 'exec' point, exactly as
    the real os.execv would replace the process (never returning)."""


@pytest.fixture
def stub():
    return _load_stub()


# ── fixture builders ────────────────────────────────────────────────────────


def _make_version(cache_root: Path, version: str, *, dispatch: bool = True) -> Path:
    """Create a cached `<version>/scripts/dispatch.py` (unless dispatch=False)."""
    vdir = cache_root / version
    (vdir / "scripts").mkdir(parents=True)
    if dispatch:
        (vdir / "scripts" / "dispatch.py").write_text(
            f"#!/usr/bin/env python3\nprint('dispatch {version}')\n"
        )
    return vdir


def _hash(vdir: Path, rel: str) -> str:
    return hashlib.sha256((vdir / rel).read_bytes()).hexdigest()


def _write_manifest(vdir: Path, files: dict) -> None:
    """Write the wrapped on-disk manifest shape the real writer produces."""
    (vdir / ".integrity").mkdir(parents=True, exist_ok=True)
    (vdir / ".integrity" / "manifest-sha256.json").write_text(
        json.dumps({"version": 1, "files": files})
    )


def _write_raw_manifest(vdir: Path, raw: str) -> None:
    """Write arbitrary bytes as the manifest (malformed-JSON / wrong-shape cases)."""
    (vdir / ".integrity").mkdir(parents=True, exist_ok=True)
    (vdir / ".integrity" / "manifest-sha256.json").write_text(raw)


def _clean_files(vdir: Path) -> dict:
    """Drop a README into the version and return a CORRECT manifest 'files' dict
    (≥2 entries: the dispatch.py + the README) hashed from the live files."""
    (vdir / "README.md").write_text(f"readme for {vdir.name}\n")
    return {
        "scripts/dispatch.py": _hash(vdir, "scripts/dispatch.py"),
        "README.md": _hash(vdir, "README.md"),
    }


def _run_main(monkeypatch, stub, cache_root: Path, data_root: Path | None = None) -> str:
    """Run stub.main() with PLUGIN_CACHE_ROOT (and, for C3, PLUGIN_DATA_ROOT)
    redirected and os.execv stubbed; return the path of the dispatch.py that
    would have been execed. When `data_root` is None it points at a guaranteed-
    empty tmp dir so the C3 reader finds no pin/quarantine (pure C2 behavior)."""
    monkeypatch.setattr(stub, "PLUGIN_CACHE_ROOT", cache_root)
    if data_root is None:
        data_root = cache_root.parent / "_empty_data"
        data_root.mkdir(exist_ok=True)
    monkeypatch.setattr(stub, "PLUGIN_DATA_ROOT", data_root)
    captured: dict[str, str] = {}

    def fake_execv(path, argv):
        captured["path"] = path
        captured["argv"] = argv
        raise _Execed

    monkeypatch.setattr(stub.os, "execv", fake_execv)
    with pytest.raises(_Execed):
        stub.main()
    return captured["path"]


# ── C3 fixture builders (TRDD-T198DT1W) ──────────────────────────────────────
#
# The stub's C3 reader is stdlib-only and reads three DATA-dir artifacts the
# DAEMON writes:  <data>/.integrity-key  (raw 32-byte HMAC key),
# <data>/integrity/last-good.json  ({version, manifest_hmac}),
# <data>/integrity/quarantine.json ({versions: [...]}).  These builders write
# the exact on-disk PRIMARY shapes (the bytes janitor_integrity.backup_and_write
# leaves as the primary) so the stub recomputes the same HMAC.


def _write_key(data_root: Path) -> bytes:
    key = b"k3-test-key-32-bytes-padding!!!!!"[:32]
    assert len(key) == 32
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / ".integrity-key").write_bytes(key)
    return key


def _manifest_bytes(vdir: Path) -> bytes:
    return (vdir / ".integrity" / "manifest-sha256.json").read_bytes()


def _manifest_hmac(vdir: Path, key: bytes) -> str:
    return base64.b64encode(
        hmac.new(key, _manifest_bytes(vdir), hashlib.sha256).digest()
    ).decode("ascii")


def _write_pin(data_root: Path, version: str, manifest_hmac: str) -> None:
    p = data_root / "integrity" / "last-good.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": version, "manifest_hmac": manifest_hmac}, sort_keys=True))


def _write_quarantine(data_root: Path, versions: list[str]) -> None:
    p = data_root / "integrity" / "quarantine.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"versions": versions}, sort_keys=True))


# ── the common path ─────────────────────────────────────────────────────────


def test_clean_latest_execs_latest(stub, tmp_path, monkeypatch):
    """Newest version verifies clean → exec ITS dispatch.py (the 99% case)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.18.0")
    _write_manifest(v0, _clean_files(v0))
    v1 = _make_version(cache, "0.18.1")
    _write_manifest(v1, _clean_files(v1))
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


def test_no_manifest_fail_open_execs_latest(stub, tmp_path, monkeypatch):
    """A version with NO manifest (old releases) is accepted — never blocked."""
    cache = tmp_path / "cache"
    cache.mkdir()
    _make_version(cache, "0.18.0")  # no manifest at all
    v1 = _make_version(cache, "0.18.1")  # no manifest at all
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


# ── corruption → fall back ──────────────────────────────────────────────────


def test_corrupt_latest_falls_back_to_clean_older(stub, tmp_path, monkeypatch):
    """Latest's manifest no longer matches a live file → walk DOWN to the clean
    older version."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.18.0")
    _write_manifest(v0, _clean_files(v0))
    v1 = _make_version(cache, "0.18.1")
    _write_manifest(v1, _clean_files(v1))
    # Corrupt v1's README AFTER the manifest was written → live hash ≠ manifest.
    (v1 / "README.md").write_text("TAMPERED\n")
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v0 / "scripts" / "dispatch.py")


def test_manifest_lists_missing_file_falls_back(stub, tmp_path, monkeypatch):
    """A manifest entry whose file is GONE (partial download) → corrupt → fall back."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.18.0")
    _write_manifest(v0, _clean_files(v0))
    v1 = _make_version(cache, "0.18.1")
    files = _clean_files(v1)
    files["skills/ghost/SKILL.md"] = "deadbeef" * 8  # never created on disk
    _write_manifest(v1, files)
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v0 / "scripts" / "dispatch.py")


# ── fail-open on uncertainty ────────────────────────────────────────────────


def test_malformed_manifest_fail_open(stub, tmp_path, monkeypatch):
    """Unparseable manifest JSON → cannot prove corruption → accept (fail-open)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    _make_version(cache, "0.18.0")
    v1 = _make_version(cache, "0.18.1")
    _write_raw_manifest(v1, "{ this is not json ")
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


def test_manifest_wrong_shape_fail_open(stub, tmp_path, monkeypatch):
    """Valid JSON but not the {files:{...}} shape → fail-open accept."""
    cache = tmp_path / "cache"
    cache.mkdir()
    _make_version(cache, "0.18.0")
    v1 = _make_version(cache, "0.18.1")
    _write_raw_manifest(v1, json.dumps([1, 2, 3]))  # a list, not a dict
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


def test_empty_expected_hash_is_fail_open(stub, tmp_path, monkeypatch):
    """An empty expected hash (compute_manifest records "" for a file that vanished
    at BUILD time) is manifest uncertainty, not tampering → that entry is skipped,
    the version still verifies on its real entries → exec latest."""
    cache = tmp_path / "cache"
    cache.mkdir()
    _make_version(cache, "0.18.0")
    v1 = _make_version(cache, "0.18.1")
    files = _clean_files(v1)
    files["README.md"] = ""  # degenerate build entry — must NOT fail the version
    _write_manifest(v1, files)
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


def test_all_corrupt_fail_open_execs_newest_runnable(stub, tmp_path, monkeypatch):
    """No version verifies clean → fail-open to the NEWEST runnable version (a
    possibly-corrupt heartbeat beats a dead one — the cardinal rule)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.18.0")
    _write_manifest(v0, _clean_files(v0))
    (v0 / "README.md").write_text("TAMPERED 0\n")
    v1 = _make_version(cache, "0.18.1")
    _write_manifest(v1, _clean_files(v1))
    (v1 / "README.md").write_text("TAMPERED 1\n")
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v1 / "scripts" / "dispatch.py")  # newest, even though dirty


# ── runnability / preserved behaviors ───────────────────────────────────────


def test_latest_missing_dispatch_skips_to_older(stub, tmp_path, monkeypatch):
    """Newest version has no dispatch.py (broken release) → skip it, run the older
    one (more immortal than the old `sys.exit`)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.18.0")
    _write_manifest(v0, _clean_files(v0))
    _make_version(cache, "0.18.1", dispatch=False)  # no dispatch.py
    chosen = _run_main(monkeypatch, stub, cache)
    assert chosen == str(v0 / "scripts" / "dispatch.py")


def test_no_versions_exits(stub, tmp_path, monkeypatch):
    """Empty cache root → SystemExit (preserved)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(stub, "PLUGIN_CACHE_ROOT", cache)
    with pytest.raises(SystemExit):
        stub.main()


def test_no_runnable_dispatch_exits(stub, tmp_path, monkeypatch):
    """Versions exist but none carry a dispatch.py → SystemExit (preserved)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    _make_version(cache, "0.18.0", dispatch=False)
    _make_version(cache, "0.18.1", dispatch=False)
    monkeypatch.setattr(stub, "PLUGIN_CACHE_ROOT", cache)
    with pytest.raises(SystemExit):
        stub.main()


# ── direct unit coverage of the verify primitive ────────────────────────────


def test_verify_version_clean_true(stub, tmp_path):
    v = _make_version(tmp_path, "0.18.1")
    _write_manifest(v, _clean_files(v))
    ok, reason = stub._verify_version(v)
    assert ok and reason == "verified"


def test_verify_version_mismatch_false(stub, tmp_path):
    v = _make_version(tmp_path, "0.18.1")
    _write_manifest(v, _clean_files(v))
    (v / "README.md").write_text("changed\n")
    ok, reason = stub._verify_version(v)
    assert not ok and reason.startswith("mismatch:")


def test_verify_version_no_manifest_true(stub, tmp_path):
    v = _make_version(tmp_path, "0.18.1")  # no manifest
    ok, reason = stub._verify_version(v)
    assert ok and reason == "no-manifest"


# ── C3 pin + quarantine (TRDD-T198DT1W) ──────────────────────────────────────
#
# C3 adds a DATA-dir trust anchor the cache-writer can't forge (an HMAC of a
# GOOD version's manifest, keyed by the DATA-dir key) plus a quarantine list.
# It can ONLY ADD ONE new rejection: a candidate whose pin names IT but whose
# manifest HMAC differs (proven tamper). Every other state is FAIL-OPEN —
# C3 has no opinion and the C2 verdict stands. These tests prove both the new
# rejection AND that C3 never blocks a version C2 would have run.


def test_c3_no_pin_no_quarantine_is_c2_only(stub, tmp_path, monkeypatch):
    """Fresh install: no key, no pin, no quarantine → C3 is a pure no-op; the
    newest clean version runs exactly as C2 alone (the ZERO-false-rejection
    invariant on every machine that never ran the daemon's pin-writer)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.20.0")
    _write_manifest(v0, _clean_files(v0))
    v1 = _make_version(cache, "0.20.1")
    _write_manifest(v1, _clean_files(v1))
    data = tmp_path / "data"  # empty → no key/pin/quarantine
    data.mkdir()
    chosen = _run_main(monkeypatch, stub, cache, data)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


def test_c3_pin_matches_accepts(stub, tmp_path, monkeypatch):
    """Pin names the newest version AND its manifest HMAC matches → strong
    accept (the certified-good happy path)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v1 = _make_version(cache, "0.20.1")
    _write_manifest(v1, _clean_files(v1))
    data = tmp_path / "data"
    key = _write_key(data)
    _write_pin(data, "0.20.1", _manifest_hmac(v1, key))
    chosen = _run_main(monkeypatch, stub, cache, data)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


def test_c3_pin_mismatch_falls_back(stub, tmp_path, monkeypatch):
    """Pin names the newest version but the manifest HMAC DIFFERS → proven
    tamper (the manifest was rewritten by someone without the DATA key) → fall
    back to the next version, even though the plaintext manifest self-verifies.
    This is the SOLE new rejection C3 introduces — the malicious-replacement
    case an unsigned C2 manifest cannot catch."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.20.0")
    _write_manifest(v0, _clean_files(v0))
    v1 = _make_version(cache, "0.20.1")
    _write_manifest(v1, _clean_files(v1))
    data = tmp_path / "data"
    _write_key(data)
    # Pin a WRONG hmac for 0.20.1 → its recomputed hmac won't match the pin.
    _write_pin(data, "0.20.1", "Zm9yZ2VkLWhtYWMtdmFsdWU=")  # base64("forged-hmac-value")
    chosen = _run_main(monkeypatch, stub, cache, data)
    assert chosen == str(v0 / "scripts" / "dispatch.py")


def test_c3_pin_for_older_version_does_not_block_newer(stub, tmp_path, monkeypatch):
    """The pin names an OLDER version than the newest clean one. C3 has no
    anchor for the newer version → no opinion → the newer clean version still
    runs (a self-update past the last pin must NOT be blocked)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.20.0")
    _write_manifest(v0, _clean_files(v0))
    v1 = _make_version(cache, "0.20.1")
    _write_manifest(v1, _clean_files(v1))
    data = tmp_path / "data"
    key = _write_key(data)
    _write_pin(data, "0.20.0", _manifest_hmac(v0, key))  # pin the OLDER one
    chosen = _run_main(monkeypatch, stub, cache, data)
    assert chosen == str(v1 / "scripts" / "dispatch.py")  # newest still wins


def test_c3_quarantined_version_is_skipped(stub, tmp_path, monkeypatch):
    """A quarantined version is skipped fast even if it verifies clean → run the
    next (older) clean version. This is the bad-self-update self-heal hook."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.20.0")
    _write_manifest(v0, _clean_files(v0))
    v1 = _make_version(cache, "0.20.1")
    _write_manifest(v1, _clean_files(v1))
    data = tmp_path / "data"
    _write_quarantine(data, ["0.20.1"])
    chosen = _run_main(monkeypatch, stub, cache, data)
    assert chosen == str(v0 / "scripts" / "dispatch.py")


def test_c3_all_quarantined_fail_open_runs_newest(stub, tmp_path, monkeypatch):
    """Every runnable version is quarantined → FAIL-OPEN: run the newest
    runnable version anyway (a possibly-bad heartbeat beats a dead one — the
    cardinal rule trumps the quarantine when nothing else is left)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v0 = _make_version(cache, "0.20.0")
    _write_manifest(v0, _clean_files(v0))
    v1 = _make_version(cache, "0.20.1")
    _write_manifest(v1, _clean_files(v1))
    data = tmp_path / "data"
    _write_quarantine(data, ["0.20.0", "0.20.1"])
    chosen = _run_main(monkeypatch, stub, cache, data)
    assert chosen == str(v1 / "scripts" / "dispatch.py")  # newest, despite quarantine


def test_c3_malformed_pin_is_fail_open(stub, tmp_path, monkeypatch):
    """A corrupt last-good.json → C3 has no opinion → newest clean version runs
    (a broken pin must NEVER divert the boot path)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v1 = _make_version(cache, "0.20.1")
    _write_manifest(v1, _clean_files(v1))
    data = tmp_path / "data"
    _write_key(data)
    (data / "integrity").mkdir(parents=True, exist_ok=True)
    (data / "integrity" / "last-good.json").write_text("{ not json")
    chosen = _run_main(monkeypatch, stub, cache, data)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


def test_c3_malformed_quarantine_is_fail_open(stub, tmp_path, monkeypatch):
    """A corrupt quarantine.json → empty set → nothing is skipped → newest clean
    version runs (a broken quarantine must NEVER skip a good version)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v1 = _make_version(cache, "0.20.1")
    _write_manifest(v1, _clean_files(v1))
    data = tmp_path / "data"
    (data / "integrity").mkdir(parents=True, exist_ok=True)
    (data / "integrity" / "quarantine.json").write_text("][ not json")
    chosen = _run_main(monkeypatch, stub, cache, data)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


def test_c3_pin_present_but_no_key_is_fail_open(stub, tmp_path, monkeypatch):
    """A pin exists but the DATA key is GONE → C3 cannot recompute the HMAC → no
    opinion → newest clean version runs (a lost key must not brick the boot)."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v1 = _make_version(cache, "0.20.1")
    _write_manifest(v1, _clean_files(v1))
    data = tmp_path / "data"
    data.mkdir()
    # Pin present, but NO .integrity-key written.
    _write_pin(data, "0.20.1", "Zm9yZ2VkLWhtYWMtdmFsdWU=")  # would mismatch IF a key existed
    chosen = _run_main(monkeypatch, stub, cache, data)
    assert chosen == str(v1 / "scripts" / "dispatch.py")


def test_c3_pin_mismatch_then_no_fallback_fail_open(stub, tmp_path, monkeypatch):
    """Pin names the ONLY version and its HMAC mismatches (proven tamper), with
    no older version to fall back to → FAIL-OPEN to that newest-runnable version
    anyway. Even a proven-bad single version beats a dead heartbeat — the
    cardinal rule is the final backstop."""
    cache = tmp_path / "cache"
    cache.mkdir()
    v1 = _make_version(cache, "0.20.1")
    _write_manifest(v1, _clean_files(v1))
    data = tmp_path / "data"
    _write_key(data)
    _write_pin(data, "0.20.1", "Zm9yZ2VkLWhtYWMtdmFsdWU=")  # mismatch
    chosen = _run_main(monkeypatch, stub, cache, data)
    assert chosen == str(v1 / "scripts" / "dispatch.py")  # fail-open backstop


# ── direct unit coverage of the C3 stub readers ──────────────────────────────


def test_read_pin_and_key_round_trip(stub, tmp_path):
    """_read_pin + _read_key recover what the daemon writes."""
    data = tmp_path / "data"
    key = _write_key(data)
    _write_pin(data, "0.20.1", "abc123")
    assert stub._read_key(data) == key
    assert stub._read_pin(data) == {"version": "0.20.1", "manifest_hmac": "abc123"}


def test_read_quarantine_set(stub, tmp_path):
    """_read_quarantine parses the versions list into a set; malformed → empty."""
    data = tmp_path / "data"
    _write_quarantine(data, ["0.20.0", "0.20.1"])
    assert stub._read_quarantine(data) == {"0.20.0", "0.20.1"}
    (data / "integrity" / "quarantine.json").write_text("nope")
    assert stub._read_quarantine(data) == set()


def test_pin_hmac_matches_helper(stub, tmp_path):
    """_pin_hmac recomputes base64(HMAC(manifest-bytes, key)) — identical to the
    daemon-side version_update_lib.manifest_hmac value."""
    data = tmp_path / "data"
    key = _write_key(data)
    v = _make_version(tmp_path, "0.20.1")
    _write_manifest(v, _clean_files(v))
    assert stub._pin_hmac(v, key) == _manifest_hmac(v, key)
