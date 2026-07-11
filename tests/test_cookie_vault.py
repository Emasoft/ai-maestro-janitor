"""Tests for cookie_vault — the Chrome-cookies sqlite⇄jar⇄json mechanics (Phase 2b).

Real sqlite, no mocks. The load-bearing test is the FULL round-trip with BINARY
encrypted_value bytes (incl. NUL and high bytes): extract → json → back → inject into a
FRESH db → re-extract must equal the original, because Chrome's encrypted_value blob is
exactly what must survive verbatim for a re-injected cookie to decrypt.
"""

from __future__ import annotations

import os
import platform
import sqlite3
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scripts" / "oauth_rotator"))

import cookie_vault as cv  # noqa: E402
import safe_storage as ss  # noqa: E402

_TEST_COOKIE_SERVICE = "ai-maestro-janitor-cookies-TEST-%d" % os.getpid()


def _real_macos_keychain() -> bool:
    if platform.system() != "Darwin":
        return False
    from shutil import which
    return which("security") is not None

# A realistic claude.ai cookie row with BINARY encrypted_value (NUL + high bytes — the
# bytes Chrome's OSCrypt actually produces). Full 21-column tuple in COOKIE_COLUMNS order.
_ENC_SESSION = bytes([0x76, 0x31, 0x30, 0x00, 0xFF, 0xA9, 0x01, 0x7F, 0x80, 0x00, 0xDE, 0xAD])
_ENC_CF = bytes(range(256))  # every byte value 0..255 — the harshest round-trip fixture


def _row(host, name, enc, *, path="/", persistent=1, expires=13_400_000_000_000_000):
    """Build a full-column cookie row dict (COOKIE_COLUMNS order) for the fixture."""
    vals: dict[str, object] = {c: 0 for c in cv.COOKIE_COLUMNS}
    vals.update(
        creation_utc=13_300_000_000_000_000, host_key=host, top_frame_site_key="",
        name=name, value="", encrypted_value=enc, path=path, expires_utc=expires,
        is_secure=1, is_httponly=1, last_access_utc=13_350_000_000_000_000,
        has_expires=1, is_persistent=persistent, priority=1, samesite=0,
        source_scheme=2, source_port=443, last_update_utc=13_350_000_000_000_000,
        source_type=0, has_cross_site_ancestor=0,
    )
    return vals


def _make_db(path: Path, rows: list[dict]) -> None:
    """Create a Chrome-schema Cookies sqlite at `path` with `rows` (uses cookie_vault's
    own DDL so the fixture matches the real schema exactly)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        cv._ensure_cookies_table(con)
        cols = ", ".join(cv.COOKIE_COLUMNS)
        ph = ", ".join("?" for _ in cv.COOKIE_COLUMNS)
        for r in rows:
            con.execute(f"INSERT INTO cookies ({cols}) VALUES ({ph})",
                        tuple(r[c] for c in cv.COOKIE_COLUMNS))
        con.commit()
    finally:
        con.close()


def test_extract_filters_to_claude_ai(tmp_path: Path) -> None:
    """extract_jar returns only host_key LIKE '%claude.ai' rows, sorted by name."""
    db = tmp_path / "Cookies"
    _make_db(db, [
        _row(".claude.ai", "sessionKey", _ENC_SESSION),
        _row("claude.ai", "cf_clearance", _ENC_CF),
        _row(".google.com", "OTHER", b"nope"),   # must be EXCLUDED
    ])
    jar = cv.extract_jar(db)
    assert jar.names() == ("cf_clearance", "sessionKey")  # sorted, google excluded
    assert len(jar) == 2


def test_extract_preserves_binary_encrypted_value(tmp_path: Path) -> None:
    """The encrypted_value BLOB is returned as exact bytes (incl. NUL / high bytes)."""
    db = tmp_path / "Cookies"
    _make_db(db, [_row(".claude.ai", "sessionKey", _ENC_SESSION)])
    jar = cv.extract_jar(db)
    assert jar.rows[0]["encrypted_value"] == _ENC_SESSION
    assert isinstance(jar.rows[0]["encrypted_value"], bytes)


def test_json_roundtrip_preserves_all_columns_and_blob(tmp_path: Path) -> None:
    """jar_to_json → jar_from_json is loss-less, including the binary blob (every byte 0..255)."""
    db = tmp_path / "Cookies"
    _make_db(db, [_row(".claude.ai", "cf_clearance", _ENC_CF),
                  _row(".claude.ai", "sessionKey", _ENC_SESSION)])
    jar = cv.extract_jar(db)
    back = cv.jar_from_json(cv.jar_to_json(jar))
    assert back.rows == jar.rows
    assert back.host_filter == jar.host_filter


def test_full_extract_inject_reextract_roundtrip(tmp_path: Path) -> None:
    """THE load-bearing test: extract → json → back → inject into a FRESH db → re-extract
    must equal the original jar (every column + the OSCrypt blob byte-for-byte)."""
    src = tmp_path / "src" / "Cookies"
    _make_db(src, [_row(".claude.ai", "cf_clearance", _ENC_CF),
                   _row("claude.ai", "sessionKey", _ENC_SESSION)])
    original = cv.extract_jar(src)

    transported = cv.jar_from_json(cv.jar_to_json(original))  # the keychain transport shape
    dst = tmp_path / "dst" / "Default" / "Cookies"           # a fresh profile (no DB yet)
    written = cv.inject_jar(dst, transported)
    assert written == 2
    assert dst.is_file()

    reextracted = cv.extract_jar(dst)
    assert reextracted.rows == original.rows  # full fidelity through the whole pipeline


def test_inject_is_idempotent(tmp_path: Path) -> None:
    """Injecting the same jar twice REPLACES (unique index) — no duplicate rows."""
    db = tmp_path / "Cookies"
    jar = cv.CookieJar(rows=(_row(".claude.ai", "sessionKey", _ENC_SESSION),), host_filter="%claude.ai")
    cv.inject_jar(db, jar)
    cv.inject_jar(db, jar)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        n = con.execute("SELECT COUNT(*) FROM cookies WHERE name='sessionKey'").fetchone()[0]
    finally:
        con.close()
    assert n == 1


def test_extract_missing_db_raises(tmp_path: Path) -> None:
    """extract_jar on an absent profile DB fails fast (FileNotFoundError)."""
    with pytest.raises(FileNotFoundError):
        cv.extract_jar(tmp_path / "nope" / "Cookies")


def test_jar_from_json_rejects_bad_version() -> None:
    """A version mismatch is a hard error — never a silent empty jar."""
    with pytest.raises(ValueError, match="version"):
        cv.jar_from_json('{"version": 999, "rows": []}')


def test_jar_from_json_rejects_missing_columns() -> None:
    """A row missing required columns is rejected (a partial inject would break Chrome)."""
    bad = '{"version": 1, "host_filter": "%claude.ai", "rows": [{"name": "x"}]}'
    with pytest.raises(ValueError, match="missing columns"):
        cv.jar_from_json(bad)


def test_jar_from_json_rejects_garbage() -> None:
    """Non-JSON input fails fast rather than yielding an empty jar."""
    with pytest.raises(ValueError):
        cv.jar_from_json("this is not json")


def test_empty_jar_roundtrips(tmp_path: Path) -> None:
    """A profile with no claude.ai cookies yields an empty jar that still round-trips."""
    db = tmp_path / "Cookies"
    _make_db(db, [_row(".google.com", "x", b"y")])
    jar = cv.extract_jar(db)
    assert len(jar) == 0
    assert len(cv.jar_from_json(cv.jar_to_json(jar))) == 0


# ---------------------------------------------------------------------------
# Keychain orchestration — snapshot / materialize / forget.
# ---------------------------------------------------------------------------
def test_materialize_returns_none_when_nothing_stored(monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    """materialize_from_keychain returns None (nothing to inject) when no jar is stored —
    no real keychain needed: force safe_storage to the 'none' backend."""
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "none")
    assert cv.materialize_from_keychain("ghost@x.com", tmp_path / "Cookies") is None


def test_snapshot_failed_propagates_failclosed(monkeypatch: pytest.MonkeyPatch,
                                                tmp_path: Path) -> None:
    """A keychain that REFUSES the write surfaces FAILED so the caller fails closed."""
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "macos")
    db = tmp_path / "Cookies"
    _make_db(db, [_row(".claude.ai", "sessionKey", _ENC_SESSION)])

    class _R:
        returncode = 1  # security write refused (locked/declined)
        stdout = ""
        stderr = ""  # run_security reads proc.stdout + proc.stderr (Safe Keychain Protocol, TRDD-K3WQ7XM9)
    monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: _R())
    assert cv.snapshot_to_keychain("a@x.com", db) is ss.StoreResult.FAILED


@pytest.mark.skipif(not _real_macos_keychain(), reason="needs a real macOS `security` keychain")
def test_snapshot_then_materialize_switches_profile(isolated_keychain,  # isolated temp keychain — NEVER login (TRDD-K3WQ7XM9 FIX B)
                                                     monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
    """THE Phase-2 profile switch, end-to-end through the REAL keychain: snapshot account
    A's cookies from its profile → store encrypted in the keychain → materialize into a
    DIFFERENT (empty) profile → re-extract must equal the original jar (every byte). Uses a
    throwaway PID-scoped cookie service; forgets it after."""
    monkeypatch.delenv("CLAUDE_SAFE_STORAGE_BACKEND", raising=False)  # real macOS backend
    monkeypatch.setattr(cv, "COOKIE_KEYCHAIN_SERVICE", _TEST_COOKIE_SERVICE)
    email = "switch@x.com"
    src = tmp_path / "profileA" / "Default" / "Cookies"
    _make_db(src, [_row(".claude.ai", "cf_clearance", _ENC_CF),
                   _row("claude.ai", "sessionKey", _ENC_SESSION)])
    original = cv.extract_jar(src)
    try:
        res = cv.snapshot_to_keychain(email, src)
        assert res is ss.StoreResult.OK, f"snapshot failed: {res}"

        dst = tmp_path / "profileB" / "Default" / "Cookies"   # a fresh, empty profile
        written = cv.materialize_from_keychain(email, dst)
        assert written == 2
        assert cv.extract_jar(dst).rows == original.rows       # full fidelity via the keychain
    finally:
        cv.forget_in_keychain(email)
    # After forget, materialize finds nothing.
    assert cv.materialize_from_keychain(email, tmp_path / "profileC" / "Cookies") is None


# ---------------------------------------------------------------------------
# The SCRUB (TRDD-dfc0959a Phase 3) — the one DESTRUCTIVE op in the vault.
#
# Scrubbing destroys the only credential that can mint a session without a human, so
# every test here is about the guard REFUSING. The verdict string is the contract:
# "skipped:" (opt-in off), "refused:" (proof failed, nothing touched), "scrubbed:".
# No mocks — the "keychain copy is incomplete" case is produced FOR REAL by adding a
# cookie to the profile after the snapshot, which is exactly how it happens in life.
# ---------------------------------------------------------------------------
def _claude_rows_on_disk(db: Path) -> int:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(
            "SELECT COUNT(*) FROM cookies WHERE host_key LIKE '%claude.ai'").fetchone()[0]
    finally:
        con.close()


def test_scrub_is_skipped_when_its_opt_in_is_absent(monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path) -> None:
    """DEFAULT OFF: destruction is never implicit, even with a perfect keychain copy."""
    monkeypatch.delenv(cv.SCRUB_ENV, raising=False)
    db = tmp_path / "Cookies"
    _make_db(db, [_row(".claude.ai", "sessionKey", _ENC_SESSION)])

    verdict = cv.scrub_profile_cookies("a@x.com", db)

    assert verdict.startswith("skipped:")
    assert _claude_rows_on_disk(db) == 1  # untouched


def test_scrub_refuses_when_no_jar_is_stored(monkeypatch: pytest.MonkeyPatch,
                                             tmp_path: Path) -> None:
    """Opted in, but nothing is in the keychain: deleting now would brick the account."""
    monkeypatch.setenv(cv.SCRUB_ENV, "1")
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "none")
    db = tmp_path / "Cookies"
    _make_db(db, [_row(".claude.ai", "sessionKey", _ENC_SESSION)])

    verdict = cv.scrub_profile_cookies("a@x.com", db)

    assert verdict.startswith("refused:")
    assert _claude_rows_on_disk(db) == 1  # untouched


def test_scrub_refuses_when_there_is_nothing_on_disk(monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
    """An empty cookie set proves nothing — "0 == 0" must not read as a good verify."""
    monkeypatch.setenv(cv.SCRUB_ENV, "1")
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "none")
    db = tmp_path / "Cookies"
    _make_db(db, [])

    ok, why = cv.verify_restorable("a@x.com", db)

    assert ok is False
    assert "nothing to verify" in why


def test_scrub_refuses_when_the_profile_db_is_absent(monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
    """A missing Cookies DB must be a refusal verdict, never an exception out of a
    best-effort capture step."""
    monkeypatch.setenv(cv.SCRUB_ENV, "1")
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "none")

    verdict = cv.scrub_profile_cookies("a@x.com", tmp_path / "gone" / "Cookies")

    assert verdict.startswith("refused:")


@pytest.mark.skipif(not _real_macos_keychain(), reason="needs a real macOS `security` keychain")
def test_scrub_refuses_when_the_keychain_copy_is_stale(isolated_keychain,
                                                        monkeypatch: pytest.MonkeyPatch,
                                                        tmp_path: Path) -> None:
    """THE brick scenario, reproduced for real: the profile gained a cookie AFTER the
    snapshot, so the keychain copy can no longer restore the profile. The guard must
    refuse and leave every cookie on disk — a stale jar that restores only some cookies
    is indistinguishable from a good one until you have already destroyed the original.
    """
    monkeypatch.setenv(cv.SCRUB_ENV, "1")
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "macos")
    monkeypatch.setattr(cv, "COOKIE_KEYCHAIN_SERVICE", _TEST_COOKIE_SERVICE)
    email = "stale@x.com"
    db = tmp_path / "profile" / "Cookies"
    _make_db(db, [_row(".claude.ai", "sessionKey", _ENC_SESSION)])
    try:
        assert cv.snapshot_to_keychain(email, db) is ss.StoreResult.OK
        # The profile moves on: a second claude.ai cookie appears after the snapshot.
        con = sqlite3.connect(db)
        try:
            cols = ", ".join(cv.COOKIE_COLUMNS)
            ph = ", ".join("?" for _ in cv.COOKIE_COLUMNS)
            r = _row(".claude.ai", "cf_clearance", _ENC_CF)
            con.execute(f"INSERT INTO cookies ({cols}) VALUES ({ph})",
                        tuple(r[c] for c in cv.COOKIE_COLUMNS))
            con.commit()
        finally:
            con.close()

        ok, why = cv.verify_restorable(email, db)
        assert ok is False
        assert "did not reproduce" in why

        verdict = cv.scrub_profile_cookies(email, db)
        assert verdict.startswith("refused:")
        assert _claude_rows_on_disk(db) == 2  # BOTH cookies survive
    finally:
        cv.forget_in_keychain(email)


@pytest.mark.skipif(not _real_macos_keychain(), reason="needs a real macOS `security` keychain")
def test_scrub_refuses_when_the_stored_jar_is_corrupt(isolated_keychain,
                                                       monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    """A jar that cannot be parsed cannot restore anything — refuse, keep the originals."""
    monkeypatch.setenv(cv.SCRUB_ENV, "1")
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "macos")
    monkeypatch.setattr(cv, "COOKIE_KEYCHAIN_SERVICE", _TEST_COOKIE_SERVICE)
    email = "corrupt@x.com"
    db = tmp_path / "profile" / "Cookies"
    _make_db(db, [_row(".claude.ai", "sessionKey", _ENC_SESSION)])
    try:
        assert ss.store(_TEST_COOKIE_SERVICE, email, "}{ not a jar") is ss.StoreResult.OK

        verdict = cv.scrub_profile_cookies(email, db)

        assert verdict.startswith("refused:")
        assert "unreadable" in verdict
        assert _claude_rows_on_disk(db) == 1  # untouched
    finally:
        cv.forget_in_keychain(email)


@pytest.mark.skipif(not _real_macos_keychain(), reason="needs a real macOS `security` keychain")
def test_scrub_removes_only_proven_rows_and_the_profile_still_restores(
        isolated_keychain, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The happy path, end-to-end and reversible: with a verified keychain copy, scrub
    deletes exactly the claude.ai rows (an unrelated cookie the jar never held survives),
    and materialize_from_keychain puts the scrubbed cookies back byte-for-byte — which is
    the whole justification for destroying them in the first place."""
    monkeypatch.setenv(cv.SCRUB_ENV, "1")
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "macos")
    monkeypatch.setattr(cv, "COOKIE_KEYCHAIN_SERVICE", _TEST_COOKIE_SERVICE)
    email = "good@x.com"
    db = tmp_path / "profile" / "Cookies"
    _make_db(db, [
        _row(".claude.ai", "sessionKey", _ENC_SESSION),
        _row(".claude.ai", "cf_clearance", _ENC_CF),
        _row(".other.example", "tracker", b"\x01\x02"),   # NOT in the jar's host_filter
    ])
    try:
        original = cv.extract_jar(db)
        assert cv.snapshot_to_keychain(email, db) is ss.StoreResult.OK

        verdict = cv.scrub_profile_cookies(email, db)

        assert verdict.startswith("scrubbed:"), verdict
        assert _claude_rows_on_disk(db) == 0            # the proven rows are gone
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            # The unrelated cookie is untouched: we never snapshotted it, so we could not
            # restore it, so we must not delete it.
            assert con.execute(
                "SELECT COUNT(*) FROM cookies WHERE host_key = '.other.example'"
            ).fetchone()[0] == 1
        finally:
            con.close()

        # And the destruction is undoable — the point of the guard.
        assert cv.materialize_from_keychain(email, db) == 2
        assert cv.extract_jar(db).rows == original.rows
    finally:
        cv.forget_in_keychain(email)
