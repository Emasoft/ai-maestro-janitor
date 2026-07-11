"""Cookie-jar mechanics for the rotator (TRDD-dfc0959a Phase 2): EXTRACT a Chrome
profile's claude.ai cookies into a portable JSON jar, and INJECT a jar back into a
profile's Cookies sqlite. These are the sqlite⇄jar⇄json primitives the keychain
cookie storage is built on (the safe_storage glue + capture-flow integration is 2c).

Design — we NEVER decrypt a cookie value ourselves. Chrome stores each cookie's bytes
in the ``encrypted_value`` BLOB, encrypted with the per-USER OSCrypt key (the "Chrome
Safe Storage" keychain entry on macOS, the login keyring on Linux, DPAPI on Windows).
That key is stable across every Chrome profile of the same OS user, so a row's
``encrypted_value`` copied verbatim into ANOTHER of this user's profiles still decrypts.
So the jar carries Chrome's already-encrypted blobs (base64'd for JSON transport) and
re-injection is a faithful row copy — the plaintext cookie never passes through us, and
when the jar is stored via ``safe_storage`` it is encrypted AGAIN at rest (defense in
depth). Cross-user / cross-machine transport is therefore intentionally NOT supported
(the OSCrypt key differs) — this is for switching profiles on one user's machine.

Read paths open the sqlite ``mode=ro``; the inject path writes a fresh/served profile DB.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

import safe_storage

# Keychain service the per-account claude.ai cookie jar is stored under (overridable for
# tests). The jar (Chrome's already-encrypted blobs, JSON, base64) is encrypted AGAIN at
# rest by safe_storage's backend — this is the "cookies stored encrypted in the OS
# safe-storage, used to switch profiles" half of USER directive #2.
COOKIE_KEYCHAIN_SERVICE = os.environ.get(
    "CLAUDE_ROTATOR_COOKIE_KEYCHAIN_SERVICE", "Claude Code-rotator-cookies")

# The full Chrome `cookies` table column set (schema verified against Chrome 13x on
# macOS, 2026-06). ALL are NOT NULL, so a faithful round-trip must carry every one —
# a partial INSERT would violate the NOT NULL constraints and Chrome would reject the DB.
# Ordered exactly as the table declares them.
COOKIE_COLUMNS: tuple[str, ...] = (
    "creation_utc", "host_key", "top_frame_site_key", "name", "value", "encrypted_value",
    "path", "expires_utc", "is_secure", "is_httponly", "last_access_utc", "has_expires",
    "is_persistent", "priority", "samesite", "source_scheme", "source_port",
    "last_update_utc", "source_type", "has_cross_site_ancestor",
)

# The column that holds Chrome's OSCrypt-encrypted bytes (a BLOB → base64 in JSON).
_BLOB_COLUMN = "encrypted_value"

JAR_VERSION = 1


@dataclass(frozen=True)
class CookieJar:
    """A portable snapshot of one account's claude.ai cookies.

    ``rows`` is the list of full-column cookie records (each a dict keyed by
    ``COOKIE_COLUMNS``); ``encrypted_value`` is held as raw ``bytes`` in-memory and
    base64-encoded only at JSON serialization. ``host_filter`` records the SQL LIKE
    pattern the jar was extracted with so a reader knows its scope."""

    rows: tuple[dict, ...]
    host_filter: str

    def __len__(self) -> int:
        return len(self.rows)

    def names(self) -> tuple[str, ...]:
        """The cookie names in the jar (for logging / assertions — never the values)."""
        return tuple(r["name"] for r in self.rows)


def extract_jar(cookies_db: Path | str, *, host_filter: str = "%claude.ai") -> CookieJar:
    """Read every cookie whose ``host_key`` matches ``host_filter`` from a Chrome Cookies
    sqlite (opened read-only) into a CookieJar. Raises FileNotFoundError if the DB is
    absent (fail-fast — the caller decides whether an absent profile is expected)."""
    db = Path(cookies_db)
    if not db.is_file():
        raise FileNotFoundError(f"Chrome Cookies DB not found: {db}")
    cols = ", ".join(COOKIE_COLUMNS)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cur = con.execute(
            f"SELECT {cols} FROM cookies WHERE host_key LIKE ? ORDER BY name, path",
            (host_filter,),
        )
        rows: list[dict] = []
        for record in cur.fetchall():
            row = dict(zip(COOKIE_COLUMNS, record))
            # encrypted_value comes back as bytes (BLOB) or possibly memoryview — normalise.
            ev = row[_BLOB_COLUMN]
            row[_BLOB_COLUMN] = bytes(ev) if ev is not None else b""
            rows.append(row)
    finally:
        con.close()
    return CookieJar(rows=tuple(rows), host_filter=host_filter)


def jar_to_json(jar: CookieJar) -> str:
    """Serialise a CookieJar to a compact JSON string (the form stored in safe_storage).
    The ``encrypted_value`` BLOB is base64-encoded; everything else is JSON-native."""
    out_rows = []
    for row in jar.rows:
        r = dict(row)
        r[_BLOB_COLUMN] = base64.b64encode(row[_BLOB_COLUMN]).decode("ascii")
        out_rows.append(r)
    return json.dumps(
        {"version": JAR_VERSION, "host_filter": jar.host_filter, "rows": out_rows},
        separators=(",", ":"),
    )


def jar_from_json(payload: str) -> CookieJar:
    """Parse a jar previously produced by ``jar_to_json``. Raises ValueError on a version
    mismatch or a malformed payload (fail-fast — a corrupt jar must not silently yield an
    empty one that would look like 'no cookies')."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"cookie jar is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != JAR_VERSION:
        raise ValueError(f"unsupported cookie-jar version: {data.get('version') if isinstance(data, dict) else 'n/a'}")
    rows: list[dict] = []
    for r in data.get("rows", []):
        row = dict(r)
        missing = [c for c in COOKIE_COLUMNS if c not in row]
        if missing:
            raise ValueError(f"cookie jar row missing columns: {missing}")
        row[_BLOB_COLUMN] = base64.b64decode(row[_BLOB_COLUMN].encode("ascii"))
        rows.append(row)
    return CookieJar(rows=tuple(rows), host_filter=str(data.get("host_filter", "%claude.ai")))


def _ensure_cookies_table(con: sqlite3.Connection) -> None:
    """Create the Chrome ``cookies`` table + its unique index if absent, so a jar can be
    injected into a fresh/empty profile DB. The DDL matches Chrome's schema verbatim."""
    con.execute(
        "CREATE TABLE IF NOT EXISTS cookies("
        "creation_utc INTEGER NOT NULL,host_key TEXT NOT NULL,top_frame_site_key TEXT NOT NULL,"
        "name TEXT NOT NULL,value TEXT NOT NULL,encrypted_value BLOB NOT NULL,path TEXT NOT NULL,"
        "expires_utc INTEGER NOT NULL,is_secure INTEGER NOT NULL,is_httponly INTEGER NOT NULL,"
        "last_access_utc INTEGER NOT NULL,has_expires INTEGER NOT NULL,is_persistent INTEGER NOT NULL,"
        "priority INTEGER NOT NULL,samesite INTEGER NOT NULL,source_scheme INTEGER NOT NULL,"
        "source_port INTEGER NOT NULL,last_update_utc INTEGER NOT NULL,source_type INTEGER NOT NULL,"
        "has_cross_site_ancestor INTEGER NOT NULL)"
    )
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS cookies_unique_index ON cookies("
        "host_key, top_frame_site_key, has_cross_site_ancestor, name, path, source_scheme, source_port)"
    )


def inject_jar(cookies_db: Path | str, jar: CookieJar) -> int:
    """Write every row of ``jar`` into the Cookies sqlite at ``cookies_db`` (created with
    the Chrome schema if absent), REPLACING any existing row with the same unique key.
    Returns the number of rows written. Chrome must NOT be running on this profile during
    the write (it holds a sqlite lock); the caller serialises that.

    Uses INSERT OR REPLACE keyed on the table's unique index so re-injecting an updated
    jar is idempotent and never duplicates a cookie."""
    db = Path(cookies_db)
    db.parent.mkdir(parents=True, exist_ok=True)
    placeholders = ", ".join("?" for _ in COOKIE_COLUMNS)
    cols = ", ".join(COOKIE_COLUMNS)
    con = sqlite3.connect(db)
    try:
        _ensure_cookies_table(con)
        written = 0
        for row in jar.rows:
            con.execute(
                f"INSERT OR REPLACE INTO cookies ({cols}) VALUES ({placeholders})",
                tuple(row[c] for c in COOKIE_COLUMNS),
            )
            written += 1
        con.commit()
    finally:
        con.close()
    return written


# --------------------------------------------------------------------------
# Keychain orchestration — store a profile's cookies in the OS safe-storage and
# materialize them back (the "switch profiles via keychain-stored cookies" of
# USER directive #2). These tie cookie_vault (sqlite⇄jar) to safe_storage (encrypted
# at rest). The live capture-flow wiring (snapshot before / scrub after a capture in
# slot_capture_browser) is the validation-gated Phase 3 step; these primitives are it.
# --------------------------------------------------------------------------
def snapshot_to_keychain(email: str, cookies_db: Path | str,
                         *, host_filter: str = "%claude.ai") -> safe_storage.StoreResult:
    """Extract ``email``'s claude.ai cookies from its Chrome profile and store the jar
    ENCRYPTED in the OS safe-storage under (COOKIE_KEYCHAIN_SERVICE, email).

    Returns the safe_storage three-valued result so the caller fails closed: a
    ``FAILED`` (present-but-locked keychain) must NOT be treated as "snapshotted". An
    absent profile DB raises FileNotFoundError (the caller decides if that's expected)."""
    jar = extract_jar(cookies_db, host_filter=host_filter)
    return safe_storage.store(COOKIE_KEYCHAIN_SERVICE, email, jar_to_json(jar))


def materialize_from_keychain(email: str, cookies_db: Path | str) -> int | None:
    """Load ``email``'s stored cookie jar from safe-storage and INJECT it into the Chrome
    profile Cookies DB at ``cookies_db`` (created if absent). Returns the number of rows
    written, or ``None`` if no jar is stored for ``email`` (nothing to materialize).

    This is the profile SWITCH: before a capture for ``email`` the daemon materializes
    that account's keychain-stored cookies into its profile so the seeded session is
    present without a plaintext jar ever living on disk between runs."""
    payload = safe_storage.retrieve(COOKIE_KEYCHAIN_SERVICE, email)
    if payload is None:
        return None
    jar = jar_from_json(payload)   # raises ValueError on a corrupt jar — fail fast
    return inject_jar(cookies_db, jar)


def forget_in_keychain(email: str) -> None:
    """Best-effort removal of ``email``'s stored cookie jar from safe-storage (retiring
    an account / scrubbing). Never raises."""
    safe_storage.delete(COOKIE_KEYCHAIN_SERVICE, email)


# --------------------------------------------------------------------------
# The on-disk SCRUB (TRDD-dfc0959a Phase 3) — directive #2's "scrub after".
#
# This is the one DESTRUCTIVE operation in the vault, and it destroys the ONLY
# credential that can mint a new session without a human: if the keychain copy is
# silently incomplete, scrubbing the profile's cookies BRICKS that account's capture
# (a fresh human login is the only recovery). So it is gated twice:
#
#   1. Its OWN opt-in, separate from the parent CLAUDE_ROTATOR_KEYCHAIN_COOKIES flag.
#      Default OFF — an operator must ask for destruction explicitly.
#   2. A verify-before-destroy PROOF that fails CLOSED. The proof is not "the bytes
#      reached the keychain" but a full RESTORE REHEARSAL: retrieve the jar → parse it
#      → inject it into a throwaway DB → re-extract → compare to what is on disk. That
#      exercises the exact path a future `materialize_from_keychain` will take, so a
#      bug anywhere in retrieve/parse/inject would be caught BEFORE the original is
#      gone — which a plain byte-compare of the stored blob would not catch.
#
# It also scrubs ONLY the rows matching `host_filter` — the exact rows the jar holds.
# Deleting the whole Cookies DB would take cookies we never snapshotted and therefore
# cannot restore.
# --------------------------------------------------------------------------
SCRUB_ENV = "CLAUDE_ROTATOR_KEYCHAIN_COOKIES_SCRUB"


def scrub_enabled() -> bool:
    """The scrub's OWN opt-in. DEFAULT OFF (destruction is never implicit)."""
    return os.environ.get(SCRUB_ENV, "").strip().lower() in ("1", "true", "on", "yes")


def verify_restorable(email: str, cookies_db: Path | str,
                      *, host_filter: str = "%claude.ai") -> tuple[bool, str]:
    """Prove the keychain jar can RESTORE this profile's cookies exactly. ``(ok, why)``.

    The rehearsal runs the real restore path (safe_storage.retrieve → jar_from_json →
    inject_jar → extract_jar) against a throwaway DB and compares the result to the
    live on-disk cookies. Only an exact match returns True — so a truncated jar, a
    locked keychain, a corrupt payload, or an inject that silently drops a row all
    yield False, and the caller must NOT destroy anything.

    An empty on-disk cookie set also returns False: there is nothing to prove and
    nothing worth destroying, and treating "0 == 0" as proof would let a profile whose
    cookies already vanished mark itself safely scrubbed.
    """
    disk = extract_jar(cookies_db, host_filter=host_filter)  # FileNotFoundError → caller
    if len(disk) == 0:
        return (False, "no matching cookies on disk — nothing to verify or scrub")

    payload = safe_storage.retrieve(COOKIE_KEYCHAIN_SERVICE, email)
    if payload is None:
        return (False, "no cookie jar stored in the keychain for this account")
    try:
        stored = jar_from_json(payload)
    except ValueError as exc:
        return (False, f"stored cookie jar is unreadable: {exc}")

    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "Cookies"
        try:
            inject_jar(probe, stored)
            restored = extract_jar(probe, host_filter=host_filter)
        except (sqlite3.Error, OSError) as exc:
            return (False, f"restore rehearsal failed: {exc}")

    if restored != disk:
        return (
            False,
            f"restore rehearsal did not reproduce the on-disk cookies "
            f"({len(restored)} restored vs {len(disk)} on disk)",
        )
    return (True, f"{len(disk)} cookie(s) proven restorable from the keychain")


def _delete_matching_rows(cookies_db: Path | str, host_filter: str) -> int:
    """Delete exactly the rows a jar with this ``host_filter`` would carry. Returns the
    number removed. Chrome must not be running on the profile (it holds a sqlite lock)."""
    con = sqlite3.connect(Path(cookies_db))
    try:
        cur = con.execute("DELETE FROM cookies WHERE host_key LIKE ?", (host_filter,))
        con.commit()
        return cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
    finally:
        con.close()


def scrub_profile_cookies(email: str, cookies_db: Path | str,
                          *, host_filter: str = "%claude.ai") -> str:
    """Remove this profile's on-disk claude.ai cookies — but ONLY after proving the
    keychain copy can restore them. Returns a one-line verdict; NEVER raises.

    Verdicts: ``skipped: …`` (opt-in off), ``refused: …`` (the proof failed — nothing
    was touched), or ``scrubbed: …``. "Refused" is the safe outcome and is expected
    whenever anything is off; the on-disk cookies are already Chrome-OSCrypt encrypted,
    so keeping them costs little, while destroying an unrestorable session costs a
    human login.
    """
    if not scrub_enabled():
        return f"skipped: scrub is opt-in and {SCRUB_ENV} is not set"
    try:
        ok, why = verify_restorable(email, cookies_db, host_filter=host_filter)
    except (FileNotFoundError, ValueError, sqlite3.Error, OSError) as exc:
        return f"refused: verification could not run ({exc})"
    if not ok:
        return f"refused: {why}"
    try:
        removed = _delete_matching_rows(cookies_db, host_filter)
    except (sqlite3.Error, OSError) as exc:
        return f"refused: delete failed after a good verify ({exc})"
    return f"scrubbed: {removed} on-disk cookie row(s) removed — {why}"
